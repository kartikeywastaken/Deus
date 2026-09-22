// src/osint/email/npm.rs
// Direct NPM Registry maintainer & package author lookup by email.

use crate::osint::email::types::{EmailCtx, SiteResult, Status};
use serde_json::Value;
use url::form_urlencoded;

pub async fn check(ctx: &EmailCtx) -> Vec<SiteResult> {
    let mut results = Vec::new();
    let email = &ctx.normalized_email;

    let encoded_email = form_urlencoded::byte_serialize(email.as_bytes()).collect::<String>();
    let url = format!(
        "https://registry.npmjs.org/-/v1/search?text=author:{}",
        encoded_email
    );

    let req = ctx
        .client
        .get(&url)
        .header("User-Agent", "Deus-OSINT-Engine/1.0");

    match req.send().await {
        Ok(resp) if resp.status().is_success() => {
            if let Ok(json) = resp.json::<Value>().await {
                if let Some(objects) = json.get("objects").and_then(|v| v.as_array()) {
                    if !objects.is_empty() {
                        let pkg_name = objects[0]
                            .get("package")
                            .and_then(|v| v.get("name"))
                            .and_then(|v| v.as_str());

                        let author_username = objects[0]
                            .get("package")
                            .and_then(|v| v.get("author"))
                            .and_then(|v| v.get("name"))
                            .and_then(|v| v.as_str());

                        let username = author_username.map(String::from);
                        let profile_url = username
                            .as_ref()
                            .map(|u| format!("https://www.npmjs.com/~{}", u));

                        let detail = pkg_name.map(|p| format!("Published package: {}", p));

                        results.push(SiteResult {
                            id: "npm".to_string(),
                            label: "NPM Registry".to_string(),
                            status: Status::Registered,
                            via: "npm_api".to_string(),
                            reason: None,
                            username,
                            profile_url,
                            detail,
                        });
                        return results;
                    }
                }
            }
            results.push(SiteResult {
                id: "npm".to_string(),
                label: "NPM Registry".to_string(),
                status: Status::NotRegistered,
                via: "npm_api".to_string(),
                reason: None,
                username: None,
                profile_url: None,
                detail: None,
            });
        }
        Ok(resp) => {
            results.push(SiteResult {
                id: "npm".to_string(),
                label: "NPM Registry".to_string(),
                status: Status::CantCheck,
                via: "npm_api".to_string(),
                reason: Some(format!("HTTP status {}", resp.status())),
                username: None,
                profile_url: None,
                detail: None,
            });
        }
        Err(e) => {
            results.push(SiteResult {
                id: "npm".to_string(),
                label: "NPM Registry".to_string(),
                status: Status::CantCheck,
                via: "npm_api".to_string(),
                reason: Some(e.to_string()),
                username: None,
                profile_url: None,
                detail: None,
            });
        }
    }

    results
}
