use crate::connectors::{ConnectorHealth, ConnectorOutput, DiscoveredProfile, OsintConnector};
use async_trait::async_trait;

pub struct GitHubConnector {
    token: Option<String>,
}

impl GitHubConnector {
    pub fn new(token: Option<String>) -> Self {
        Self { token }
    }
}

#[async_trait]
impl OsintConnector for GitHubConnector {
    fn name(&self) -> &'static str {
        "github"
    }

    fn availability(&self) -> &'static str {
        "AVAILABLE"
    }

    fn healthcheck(&self) -> ConnectorHealth {
        ConnectorHealth {
            connector: self.name().to_string(),
            availability: self.availability().to_string(),
            auth_required: false,
            supported_seeds: vec!["username".to_string(), "email".to_string()],
        }
    }

    async fn search_username(&self, username: &str) -> ConnectorOutput {
        let url = format!("https://api.github.com/users/{}", username);
        let client = reqwest::Client::new();
        let mut req = client.get(&url).header("User-Agent", "Deus-OSINT-Rust/1.0");

        if let Some(ref tok) = self.token {
            req = req.header("Authorization", format!("token {}", tok));
        }

        if let Ok(resp) = req.send().await {
            if resp.status().is_success() {
                if let Ok(json) = resp.json::<serde_json::Value>().await {
                    let avatar_url = json["avatar_url"].as_str().map(String::from);
                    let bio = json["bio"].as_str().map(String::from);
                    let display_name = json["name"].as_str().map(String::from);
                    let location = json["location"].as_str().map(String::from);
                    let company = json["company"].as_str().map(String::from);
                    let html_url = json["html_url"]
                        .as_str()
                        .unwrap_or(&format!("https://github.com/{}", username))
                        .to_string();

                    let profiles = vec![DiscoveredProfile {
                        platform: "github".to_string(),
                        username: username.to_string(),
                        canonical_url: html_url,
                        display_name,
                        avatar_url,
                        bio,
                        location,
                        organization: company,
                        raw_json: json,
                    }];

                    return ConnectorOutput::success(profiles, 1);
                }
            }
        }

        ConnectorOutput::success(vec![], 1)
    }
}
