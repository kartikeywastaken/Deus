use crate::osint::email::types::{EmailCtx, SiteResult, Status};
use url::form_urlencoded;

pub async fn check(ctx: &EmailCtx) -> Vec<SiteResult> {
    let email = &ctx.normalized_email;
    let encoded_email = form_urlencoded::byte_serialize(email.as_bytes()).collect::<String>();

    let url = format!("{}/{}", ctx.endpoints.pgp_key_url, encoded_email);
    let resp = ctx.client.get(&url).send().await;

    match resp {
        Ok(r) => {
            let status_code = r.status();
            if status_code == reqwest::StatusCode::NOT_FOUND {
                return vec![SiteResult {
                    id: "openpgp".to_string(),
                    label: "OpenPGP Key Server".to_string(),
                    status: Status::NotRegistered,
                    via: "pgp".to_string(),
                    reason: None,
                    username: None,
                    profile_url: None,
                    detail: None,
                }];
            }

            if status_code.is_success() {
                let canonical_url = format!("https://keys.openpgp.org/search?q={}", encoded_email);
                return vec![SiteResult {
                    id: "openpgp".to_string(),
                    label: "OpenPGP Key Server".to_string(),
                    status: Status::Registered,
                    via: "pgp".to_string(),
                    reason: None,
                    username: None,
                    profile_url: Some(canonical_url),
                    detail: Some("public PGP key published on keys.openpgp.org".to_string()),
                }];
            }

            vec![SiteResult {
                id: "openpgp".to_string(),
                label: "OpenPGP Key Server".to_string(),
                status: Status::CantCheck,
                via: "pgp".to_string(),
                reason: Some(format!("HTTP {}", status_code)),
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
                id: "openpgp".to_string(),
                label: "OpenPGP Key Server".to_string(),
                status: Status::CantCheck,
                via: "pgp".to_string(),
                reason: Some(reason),
                username: None,
                profile_url: None,
                detail: None,
            }]
        }
    }
}
