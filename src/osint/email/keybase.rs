// src/osint/email/keybase.rs
// Direct, permissionless Keybase email & identity proof lookup.

use crate::osint::email::types::{EmailCtx, SiteResult, Status};
use serde_json::Value;
use url::form_urlencoded;

pub async fn check(ctx: &EmailCtx) -> Vec<SiteResult> {
    let mut results = Vec::new();
    let email = &ctx.normalized_email;

    let encoded_email = form_urlencoded::byte_serialize(email.as_bytes()).collect::<String>();
    let url = format!(
        "https://keybase.io/_/api/1.0/user/lookup.json?email_or_username={}",
        encoded_email
    );

    let req = ctx
        .client
        .get(&url)
        .header("User-Agent", "Deus-OSINT-Engine/1.0 (Mozilla/5.0)");

    match req.send().await {
        Ok(resp) if resp.status().is_success() => {
            if let Ok(json) = resp.json::<Value>().await {
                if let Some(them) = json.get("them").and_then(|v| v.as_array()) {
                    if let Some(user) = them.first() {
                        let username = user
                            .get("basename")
                            .and_then(|v| v.as_str())
                            .map(String::from);
                        let full_name = user
                            .get("profile")
                            .and_then(|v| v.get("full_name"))
                            .and_then(|v| v.as_str())
                            .map(String::from);

                        let profile_url = username
                            .as_ref()
                            .map(|u| format!("https://keybase.io/{}", u));

                        results.push(SiteResult {
                            id: "keybase".to_string(),
                            label: "Keybase".to_string(),
                            status: Status::Registered,
                            via: "keybase_api".to_string(),
                            reason: None,
                            username,
                            profile_url,
                            detail: full_name
                                .or_else(|| Some("Verified Keybase profile".to_string())),
                        });
                        return results;
                    }
                }
            }
            results.push(SiteResult {
                id: "keybase".to_string(),
                label: "Keybase".to_string(),
                status: Status::NotRegistered,
                via: "keybase_api".to_string(),
                reason: None,
                username: None,
                profile_url: None,
                detail: None,
            });
        }
        Ok(resp) => {
            results.push(SiteResult {
                id: "keybase".to_string(),
                label: "Keybase".to_string(),
                status: Status::CantCheck,
                via: "keybase_api".to_string(),
                reason: Some(format!("HTTP status {}", resp.status())),
                username: None,
                profile_url: None,
                detail: None,
            });
        }
        Err(e) => {
            results.push(SiteResult {
                id: "keybase".to_string(),
                label: "Keybase".to_string(),
                status: Status::CantCheck,
                via: "keybase_api".to_string(),
                reason: Some(e.to_string()),
                username: None,
                profile_url: None,
                detail: None,
            });
        }
    }

    results
}
