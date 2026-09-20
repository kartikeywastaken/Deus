pub mod adler;
pub mod engine;
pub mod fallback;
pub mod github;
pub mod raven;
pub mod website;

use async_trait::async_trait;
use serde::{Deserialize, Serialize};

pub use crate::db::models::ConnectorStatus;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DiscoveredProfile {
    pub platform: String,
    pub username: String,
    pub canonical_url: String,
    pub display_name: Option<String>,
    pub avatar_url: Option<String>,
    pub bio: Option<String>,
    pub location: Option<String>,
    pub organization: Option<String>,
    pub raw_json: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConnectorHealth {
    pub connector: String,
    pub availability: String,
    pub auth_required: bool,
    pub supported_seeds: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConnectorOutput {
    pub profiles: Vec<DiscoveredProfile>,
    pub status: ConnectorStatus,
    pub error: Option<String>,
    pub sites_checked: usize,
    pub sites_errored: usize,
    pub sites_rate_limited: usize,
}

impl ConnectorOutput {
    pub fn success(profiles: Vec<DiscoveredProfile>, sites_checked: usize) -> Self {
        let status = if profiles.is_empty() {
            ConnectorStatus::NoResults
        } else {
            ConnectorStatus::Success
        };
        Self {
            profiles,
            status,
            error: None,
            sites_checked,
            sites_errored: 0,
            sites_rate_limited: 0,
        }
    }

    pub fn unavailable(reason: impl Into<String>) -> Self {
        Self {
            profiles: vec![],
            status: ConnectorStatus::Unavailable,
            error: Some(reason.into()),
            sites_checked: 0,
            sites_errored: 0,
            sites_rate_limited: 0,
        }
    }
}

#[async_trait]
pub trait OsintConnector: Send + Sync {
    fn name(&self) -> &'static str;
    fn availability(&self) -> &'static str;
    fn healthcheck(&self) -> ConnectorHealth;
    async fn search_username(&self, username: &str) -> ConnectorOutput;
}

pub fn build_all_connectors(github_token: Option<String>) -> Vec<Box<dyn OsintConnector>> {
    vec![
        Box::new(raven::RavenConnector::new()),
        Box::new(adler::AdlerConnector::new()),
        Box::new(github::GitHubConnector::new(github_token)),
        Box::new(website::WebsiteConnector::new()),
        Box::new(fallback::SubprocessConnector::new("maigret")),
        Box::new(fallback::SubprocessConnector::new("sherlock")),
    ]
}
