use crate::osint::email::types::{EmailCtx, SiteResult, Status};
use serde_json::Value;
use url::form_urlencoded;

pub async fn check(ctx: &EmailCtx) -> Vec<SiteResult> {
    let email = &ctx.normalized_email;
    let encoded_email = form_urlencoded::byte_serialize(email.as_bytes()).collect::<String>();

    let user_search_url = format!("{}/search/users?q={}+in:email", ctx.endpoints.github_api_url, encoded_email);
    let commit_search_url = format!("{}/search/commits?q=author-email:{}", ctx.endpoints.github_api_url, encoded_email);

    let mut req_user = ctx.client.get(&user_search_url)
        .header("User-Agent", "Deus-OSINT-Engine/1.0")
        .header("Accept", "application/vnd.github.v3+json");

    let mut req_commit = ctx.client.get(&commit_search_url)
        .header("User-Agent", "Deus-OSINT-Engine/1.0")
        .header("Accept", "application/vnd.github.cloak-preview+json");

    if let Some(ref token) = ctx.github_token {
        if !token.trim().is_empty() {
            let auth_val = format!("Bearer {}", token.trim());
            req_user = req_user.header("Authorization", &auth_val);
            req_commit = req_commit.header("Authorization", &auth_val);
        }
    }

    let user_res = req_user.send().await;
    let commit_res = req_commit.send().await;

    let mut login = None;
    let mut profile_url = None;
    let mut detail = None;

    let mut user_rate_limited = false;
    let mut user_error = None;

    if let Ok(r) = user_res {
        let sc = r.status();
        if sc == reqwest::StatusCode::FORBIDDEN || sc == reqwest::StatusCode::TOO_MANY_REQUESTS {
            user_rate_limited = true;
        } else if !sc.is_success() {
            user_error = Some(format!("HTTP {}", sc));
        } else if let Ok(json) = r.json::<Value>().await {
            if let Some(items) = json.get("items").and_then(|v| v.as_array()) {
                if let Some(first_user) = items.first() {
                    login = first_user.get("login").and_then(|v| v.as_str()).map(String::from);
                    profile_url = first_user.get("html_url").and_then(|v| v.as_str()).map(String::from);
                    detail = Some("public email on GitHub profile".to_string());
                }
            }
        }
    } else if let Err(e) = user_res {
        user_error = Some(e.to_string());
    }

    if login.is_none() {
        if let Ok(r) = commit_res {
            if r.status().is_success() {
                if let Ok(json) = r.json::<Value>().await {
                    if let Some(items) = json.get("items").and_then(|v| v.as_array()) {
                        if let Some(first_commit) = items.first() {
                            let repo_name = first_commit.get("repository").and_then(|v| v.get("full_name")).and_then(|v| v.as_str());
                            let author_login = first_commit.get("author").and_then(|v| v.get("login")).and_then(|v| v.as_str());
                            
                            if login.is_none() {
                                login = author_login.map(String::from);
                            }
                            if profile_url.is_none() {
                                profile_url = login.as_ref().map(|u| format!("https://github.com/{}", u));
                            }
                            detail = Some(format!("commit author in {}", repo_name.unwrap_or("public repository")));
                        }
                    }
                }
            }
        }
    }

    if login.is_some() || profile_url.is_some() {
        return vec![SiteResult {
            id: "github".to_string(),
            label: "GitHub".to_string(),
            status: Status::Registered,
            via: "github".to_string(),
            reason: None,
            username: login,
            profile_url,
            detail,
        }];
    }

    if user_rate_limited {
        return vec![SiteResult {
            id: "github".to_string(),
            label: "GitHub".to_string(),
            status: Status::CantCheck,
            via: "github".to_string(),
            reason: Some("rate limited by GitHub API".to_string()),
            username: None,
            profile_url: None,
            detail: None,
        }];
    }

    if let Some(err) = user_error {
        return vec![SiteResult {
            id: "github".to_string(),
            label: "GitHub".to_string(),
            status: Status::CantCheck,
            via: "github".to_string(),
            reason: Some(err),
            username: None,
            profile_url: None,
            detail: None,
        }];
    }

    vec![SiteResult {
        id: "github".to_string(),
        label: "GitHub".to_string(),
        status: Status::NotRegistered,
        via: "github".to_string(),
        reason: None,
        username: None,
        profile_url: None,
        detail: None,
    }]
}
