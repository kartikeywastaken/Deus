pub mod github;
pub mod gravatar;
pub mod hibp;
pub mod holehe;
pub mod normalize;
pub mod pgp;
pub mod types;

use std::collections::HashMap;
use std::env;
use std::sync::Arc;
use std::time::{Duration, Instant};

use axum::{extract::Json, http::StatusCode, response::IntoResponse};
use serde_json::json;
use tokio::sync::Mutex;
use tokio::time::timeout;

use crate::osint::email::normalize::normalize_email;
use crate::osint::email::types::{
    EmailCtx, EmailScanRequest, EmailScanResponse, Endpoints, SiteResult, Status, Summary,
};

type CacheMap = Arc<Mutex<HashMap<String, (Instant, EmailScanResponse)>>>;

static EMAIL_CACHE: std::sync::OnceLock<CacheMap> = std::sync::OnceLock::new();

fn get_cache() -> &'static CacheMap {
    EMAIL_CACHE.get_or_init(|| Arc::new(Mutex::new(HashMap::new())))
}

fn get_provider_label(domain: &str) -> String {
    let d = domain.to_lowercase();
    if d.contains("gmail") || d.contains("googlemail") {
        "Gmail".to_string()
    } else if d.contains("outlook")
        || d.contains("hotmail")
        || d.contains("live.com")
        || d.contains("msn.com")
    {
        "Outlook".to_string()
    } else if d.contains("yahoo") || d.contains("ymail") || d.contains("rocketmail") {
        "Yahoo".to_string()
    } else if d.contains("proton") || d.contains("pm.me") {
        "ProtonMail".to_string()
    } else if d.contains("icloud") || d.contains("me.com") || d.contains("mac.com") {
        "iCloud".to_string()
    } else if d.contains("zoho") {
        "Zoho".to_string()
    } else if d.contains("aol") {
        "AOL".to_string()
    } else if d.contains("gmx") {
        "GMX".to_string()
    } else if d.contains("tutanota") || d.contains("tuta.io") {
        "Tuta".to_string()
    } else if d.contains("mail.ru") {
        "Mail.ru".to_string()
    } else if d.contains("yandex") {
        "Yandex".to_string()
    } else {
        domain.to_string()
    }
}

pub async fn email_info_handler() -> impl IntoResponse {
    (
        StatusCode::OK,
        Json(json!({
            "service": "Email OSINT Holehe Audit API",
            "method_required": "POST",
            "payload_format": { "email": "user@example.com", "self_audit_confirmed": true }
        })),
    )
}

pub async fn scan(Json(payload): Json<EmailScanRequest>) -> impl IntoResponse {
    let start = Instant::now();
    let norm = match normalize_email(&payload.email) {
        Ok(n) => n,
        Err(e) => {
            return (
                StatusCode::BAD_REQUEST,
                Json(json!({ "detail": e.to_string() })),
            )
                .into_response()
        }
    };

    let self_audit_confirmed = payload.self_audit_confirmed.unwrap_or(false);
    let cache_key = format!("{}:{}", norm.normalized, self_audit_confirmed);

    // Cache lookup (10 minute TTL)
    {
        let cache = get_cache().lock().await;
        if let Some((inserted_at, cached_resp)) = cache.get(&cache_key) {
            if inserted_at.elapsed() < Duration::from_secs(600) {
                return (StatusCode::OK, Json(cached_resp.clone())).into_response();
            }
        }
    }

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(8))
        .build()
        .unwrap_or_default();

    let ctx = EmailCtx {
        raw_email: norm.raw.clone(),
        normalized_email: norm.normalized.clone(),
        base_email: norm.base_email.clone(),
        domain: norm.domain.clone(),
        local_part: norm.local_part.clone(),
        client,
        self_audit_confirmed,
        github_token: env::var("GITHUB_TOKEN").ok(),
        hibp_api_key: env::var("HIBP_API_KEY").ok(),
        endpoints: Endpoints::default(),
    };

    // Run sources concurrently
    let (holehe_results, gravatar_results, github_results, pgp_results, breaches) = tokio::join!(
        async {
            if self_audit_confirmed {
                holehe::check(&norm.normalized).await
            } else {
                vec![holehe::consent_required()]
            }
        },
        async {
            match timeout(Duration::from_secs(8), gravatar::check(&ctx)).await {
                Ok(res) => res,
                Err(_) => vec![SiteResult {
                    id: "gravatar".to_string(),
                    label: "Gravatar".to_string(),
                    status: Status::CantCheck,
                    via: "gravatar".to_string(),
                    reason: Some("request timed out".to_string()),
                    username: None,
                    profile_url: None,
                    detail: None,
                }],
            }
        },
        async {
            match timeout(Duration::from_secs(8), github::check(&ctx)).await {
                Ok(res) => res,
                Err(_) => vec![SiteResult {
                    id: "github".to_string(),
                    label: "GitHub".to_string(),
                    status: Status::CantCheck,
                    via: "github".to_string(),
                    reason: Some("request timed out".to_string()),
                    username: None,
                    profile_url: None,
                    detail: None,
                }],
            }
        },
        async {
            match timeout(Duration::from_secs(8), pgp::check(&ctx)).await {
                Ok(res) => res,
                Err(_) => vec![SiteResult {
                    id: "openpgp".to_string(),
                    label: "OpenPGP Key Server".to_string(),
                    status: Status::CantCheck,
                    via: "pgp".to_string(),
                    reason: Some("request timed out".to_string()),
                    username: None,
                    profile_url: None,
                    detail: None,
                }],
            }
        },
        async {
            timeout(Duration::from_secs(8), hibp::check(&ctx))
                .await
                .unwrap_or_default()
        }
    );

    let mut all_sites = Vec::new();
    all_sites.extend(holehe_results);
    all_sites.extend(gravatar_results);
    all_sites.extend(github_results);
    all_sites.extend(pgp_results);

    let sites = dedupe_and_sort_sites(all_sites);

    let registered_count = sites.iter().filter(|s| s.status == Status::Registered).count();
    let not_registered_count = sites.iter().filter(|s| s.status == Status::NotRegistered).count();
    let cant_check_count = sites.iter().filter(|s| s.status == Status::CantCheck).count();
    let scan_ms = start.elapsed().as_millis() as u64;

    let response = EmailScanResponse {
        email: norm.normalized.clone(),
        provider: get_provider_label(&norm.domain),
        summary: Summary {
            registered: registered_count,
            not_registered: not_registered_count,
            cant_check: cant_check_count,
            scan_ms,
        },
        sites,
        breaches,
    };

    // Cache response
    {
        let mut cache = get_cache().lock().await;
        cache.insert(cache_key, (Instant::now(), response.clone()));
    }

    (StatusCode::OK, Json(response)).into_response()
}

pub fn dedupe_and_sort_sites(sites: Vec<SiteResult>) -> Vec<SiteResult> {
    let mut map: HashMap<String, SiteResult> = HashMap::new();

    for site in sites {
        let key = site.label.to_lowercase();
        match map.get(&key) {
            None => {
                map.insert(key, site);
            }
            Some(existing) => {
                let replace = match (existing.status, site.status) {
                    (Status::Registered, _) => false,
                    (_, Status::Registered) => true,
                    (Status::CantCheck, Status::NotRegistered) => false,
                    (Status::NotRegistered, Status::CantCheck) => true,
                    _ => false,
                };
                if replace {
                    map.insert(key, site);
                }
            }
        }
    }

    let mut result: Vec<SiteResult> = map.into_values().collect();

    result.sort_by(|a, b| {
        let rank = |s: Status| match s {
            Status::Registered => 0,
            Status::NotRegistered => 1,
            Status::CantCheck => 2,
        };
        rank(a.status).cmp(&rank(b.status)).then_with(|| a.label.cmp(&b.label))
    });

    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_dedupe_and_sort() {
        let input = vec![
            SiteResult {
                id: "1".into(),
                label: "GitHub".into(),
                status: Status::CantCheck,
                via: "holehe".into(),
                reason: Some("rate limited".into()),
                username: None,
                profile_url: None,
                detail: None,
            },
            SiteResult {
                id: "2".into(),
                label: "GitHub".into(),
                status: Status::Registered,
                via: "github".into(),
                reason: None,
                username: Some("octocat".into()),
                profile_url: Some("https://github.com/octocat".into()),
                detail: None,
            },
            SiteResult {
                id: "3".into(),
                label: "Spotify".into(),
                status: Status::NotRegistered,
                via: "holehe".into(),
                reason: None,
                username: None,
                profile_url: None,
                detail: None,
            },
        ];

        let res = dedupe_and_sort_sites(input);
        assert_eq!(res.len(), 2);
        assert_eq!(res[0].label, "GitHub");
        assert_eq!(res[0].status, Status::Registered);
        assert_eq!(res[1].label, "Spotify");
        assert_eq!(res[1].status, Status::NotRegistered);
    }
}
