use crate::connectors::{ConnectorHealth, ConnectorOutput, ConnectorStatus, DiscoveredProfile, OsintConnector};
use async_trait::async_trait;
use serde_json::json;
use std::env;
use std::process::Stdio;
use std::time::Duration;
use tokio::process::Command;
use tokio::time::timeout;

pub struct SubprocessConnector {
    name: &'static str,
}

impl SubprocessConnector {
    pub fn new(name: &'static str) -> Self {
        Self { name }
    }

    async fn is_binary_available(&self) -> bool {
        let bin_name = match self.name {
            "sherlock" => env::var("SHERLOCK_BINARY").unwrap_or_else(|_| "sherlock".to_string()),
            "maigret" => env::var("MAIGRET_BINARY").unwrap_or_else(|_| "maigret".to_string()),
            other => other.to_string(),
        };

        Command::new(&bin_name)
            .arg("--version")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .await
            .map(|s| s.success())
            .unwrap_or(false)
    }
}

fn is_binary_installed_sync(name: &str) -> bool {
    let bin_name = match name {
        "sherlock" => env::var("SHERLOCK_BINARY").unwrap_or_else(|_| "sherlock".to_string()),
        "maigret" => env::var("MAIGRET_BINARY").unwrap_or_else(|_| "maigret".to_string()),
        other => other.to_string(),
    };
    std::process::Command::new(&bin_name)
        .arg("--version")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

#[async_trait]
impl OsintConnector for SubprocessConnector {
    fn name(&self) -> &'static str {
        self.name
    }

    fn availability(&self) -> &'static str {
        if is_binary_installed_sync(self.name) {
            "CLI_SUBPROCESS"
        } else {
            "NOT_INSTALLED"
        }
    }

    fn healthcheck(&self) -> ConnectorHealth {
        ConnectorHealth {
            connector: self.name.to_string(),
            availability: self.availability().to_string(),
            auth_required: false,
            supported_seeds: vec!["username".to_string()],
        }
    }

    async fn search_username(&self, username: &str) -> ConnectorOutput {
        if !self.is_binary_available().await {
            return ConnectorOutput::unavailable(format!("Binary '{}' is not installed or not available on PATH", self.name));
        }

        let bin_name = match self.name {
            "sherlock" => env::var("SHERLOCK_BINARY").unwrap_or_else(|_| "sherlock".to_string()),
            "maigret" => env::var("MAIGRET_BINARY").unwrap_or_else(|_| "maigret".to_string()),
            other => other.to_string(),
        };

        let timeout_secs: u64 = env::var("CONNECTOR_TIMEOUT_SECONDS")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(30);

        let mut cmd = Command::new(&bin_name);

        if self.name == "sherlock" {
            cmd.arg(username).arg("--json").arg("--timeout").arg("10");
        } else if self.name == "maigret" {
            cmd.arg(username).arg("--json").arg("simple").arg("--timeout").arg("10");
        } else {
            cmd.arg(username);
        }

        let child = cmd
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output();

        match timeout(Duration::from_secs(timeout_secs), child).await {
            Ok(Ok(output)) => {
                let stdout_str = String::from_utf8_lossy(&output.stdout);
                let mut profiles = Vec::new();

                if let Ok(json_val) = serde_json::from_str::<serde_json::Value>(&stdout_str) {
                    if let Some(map) = json_val.as_object() {
                        for (site, data) in map {
                            let url = data.get("url_user").or_else(|| data.get("url")).and_then(|v| v.as_str());
                            if let Some(canonical_url) = url {
                                profiles.push(DiscoveredProfile {
                                    platform: site.clone(),
                                    username: username.to_string(),
                                    canonical_url: canonical_url.to_string(),
                                    display_name: None,
                                    avatar_url: None,
                                    bio: None,
                                    location: None,
                                    organization: None,
                                    raw_json: json!({
                                        "source": self.name,
                                        "site_name": site,
                                        "canonical_url": canonical_url,
                                        "verified": true,
                                    }),
                                });
                            }
                        }
                    }
                }

                let status = if profiles.is_empty() {
                    ConnectorStatus::NoResults
                } else {
                    ConnectorStatus::Success
                };

                ConnectorOutput {
                    profiles,
                    status,
                    error: None,
                    sites_checked: 0,
                    sites_errored: 0,
                    sites_rate_limited: 0,
                }
            }
            Ok(Err(e)) => ConnectorOutput {
                profiles: vec![],
                status: ConnectorStatus::Failed,
                error: Some(format!("Failed to execute process '{}': {}", self.name, e)),
                sites_checked: 0,
                sites_errored: 1,
                sites_rate_limited: 0,
            },
            Err(_) => ConnectorOutput {
                profiles: vec![],
                status: ConnectorStatus::Partial,
                error: Some(format!("Subprocess '{}' timed out after {}s", self.name, timeout_secs)),
                sites_checked: 0,
                sites_errored: 1,
                sites_rate_limited: 0,
            },
        }
    }
}
