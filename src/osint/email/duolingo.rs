// src/osint/email/duolingo.rs
// Direct, permissionless email lookup for Duolingo profiles.

use crate::osint::email::types::{EmailCtx, SiteResult, Status};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct DuolingoUser {
    username: Option<String>,
    name: Option<String>,
}

#[derive(Debug, Deserialize)]
struct DuolingoResponse {
    users: Option<Vec<DuolingoUser>>,
}

pub async fn check(ctx: &EmailCtx) -> Vec<SiteResult> {
    let mut results = Vec::new();

    let req = ctx
        .client
        .get("https://www.duolingo.com/2017-06-30/users")
        .query(&[("email", &ctx.normalized_email)])
        .header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)");

    match req.send().await {
        Ok(resp) if resp.status().is_success() => {
            if let Ok(data) = resp.json::<DuolingoResponse>().await {
                if let Some(users) = data.users {
                    if !users.is_empty() {
                        let user = &users[0];
                        let username = user.username.clone();
                        let profile_url = username
                            .as_ref()
                            .map(|u| format!("https://www.duolingo.com/profile/{}", u));

                        results.push(SiteResult {
                            id: "duolingo".to_string(),
                            label: "Duolingo".to_string(),
                            status: Status::Registered,
                            via: "duolingo_api".to_string(),
                            reason: None,
                            username,
                            profile_url,
                            detail: user.name.clone(),
                        });
                        return results;
                    }
                }
            }
            results.push(SiteResult {
                id: "duolingo".to_string(),
                label: "Duolingo".to_string(),
                status: Status::NotRegistered,
                via: "duolingo_api".to_string(),
                reason: None,
                username: None,
                profile_url: None,
                detail: None,
            });
        }
        Ok(resp) => {
            results.push(SiteResult {
                id: "duolingo".to_string(),
                label: "Duolingo".to_string(),
                status: Status::CantCheck,
                via: "duolingo_api".to_string(),
                reason: Some(format!("HTTP status {}", resp.status())),
                username: None,
                profile_url: None,
                detail: None,
            });
        }
        Err(e) => {
            results.push(SiteResult {
                id: "duolingo".to_string(),
                label: "Duolingo".to_string(),
                status: Status::CantCheck,
                via: "duolingo_api".to_string(),
                reason: Some(e.to_string()),
                username: None,
                profile_url: None,
                detail: None,
            });
        }
    }

    results
}
