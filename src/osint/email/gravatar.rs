use crate::osint::email::types::{EmailCtx, SiteResult, Status};
use md5::{Digest as Md5Digest, Md5};
use serde_json::Value;
use sha2::Sha256;

pub async fn check(ctx: &EmailCtx) -> Vec<SiteResult> {
    let normalized = &ctx.normalized_email;

    // SHA256 hash
    let mut hasher_sha = Sha256::new();
    hasher_sha.update(normalized.as_bytes());
    let sha256_hash = hex::encode(hasher_sha.finalize());

    // MD5 hash fallback
    let mut hasher_md5 = Md5::new();
    hasher_md5.update(normalized.as_bytes());
    let md5_hash = hex::encode(hasher_md5.finalize());

    let profile_url = format!("{}/{}.json", ctx.endpoints.gravatar_url, sha256_hash);
    let mut resp = ctx.client.get(&profile_url).send().await;

    if let Ok(ref r) = resp {
        if r.status() == reqwest::StatusCode::NOT_FOUND {
            let md5_url = format!("{}/{}.json", ctx.endpoints.gravatar_url, md5_hash);
            resp = ctx.client.get(&md5_url).send().await;
        }
    }

    match resp {
        Ok(r) => {
            let status_code = r.status();
            if status_code == reqwest::StatusCode::NOT_FOUND {
                return vec![SiteResult {
                    id: "gravatar".to_string(),
                    label: "Gravatar".to_string(),
                    status: Status::NotRegistered,
                    via: "gravatar".to_string(),
                    reason: None,
                    username: None,
                    profile_url: None,
                    detail: None,
                }];
            }

            if status_code == reqwest::StatusCode::TOO_MANY_REQUESTS || status_code == reqwest::StatusCode::FORBIDDEN {
                return vec![SiteResult {
                    id: "gravatar".to_string(),
                    label: "Gravatar".to_string(),
                    status: Status::CantCheck,
                    via: "gravatar".to_string(),
                    reason: Some("rate limited by Gravatar".to_string()),
                    username: None,
                    profile_url: None,
                    detail: None,
                }];
            }

            if !status_code.is_success() {
                return vec![SiteResult {
                    id: "gravatar".to_string(),
                    label: "Gravatar".to_string(),
                    status: Status::CantCheck,
                    via: "gravatar".to_string(),
                    reason: Some(format!("HTTP {}", status_code)),
                    username: None,
                    profile_url: None,
                    detail: None,
                }];
            }

            if let Ok(json) = r.json::<Value>().await {
                if let Some(entry) = json.get("entry").and_then(|v| v.as_array()).and_then(|arr| arr.first()) {
                    let preferred_username = entry.get("preferredUsername").and_then(|v| v.as_str()).map(String::from);
                    let canonical_url = entry.get("profileUrl").and_then(|v| v.as_str()).map(String::from)
                        .unwrap_or_else(|| format!("https://gravatar.com/{}", preferred_username.as_deref().unwrap_or(&sha256_hash)));

                    return vec![SiteResult {
                        id: "gravatar".to_string(),
                        label: "Gravatar".to_string(),
                        status: Status::Registered,
                        via: "gravatar".to_string(),
                        reason: None,
                        username: preferred_username,
                        profile_url: Some(canonical_url),
                        detail: Some("public Gravatar profile".to_string()),
                    }];
                }
            }

            vec![SiteResult {
                id: "gravatar".to_string(),
                label: "Gravatar".to_string(),
                status: Status::NotRegistered,
                via: "gravatar".to_string(),
                reason: None,
                username: None,
                profile_url: None,
                detail: None,
            }]
        }
        Err(e) => {
            let reason = if e.is_timeout() {
                "request timed out".to_string()
            } else {
                format!("connection error: {}", e)
            };
            vec![SiteResult {
                id: "gravatar".to_string(),
                label: "Gravatar".to_string(),
                status: Status::CantCheck,
                via: "gravatar".to_string(),
                reason: Some(reason),
                username: None,
                profile_url: None,
                detail: None,
            }]
        }
    }
}
