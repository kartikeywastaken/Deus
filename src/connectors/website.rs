use crate::connectors::{ConnectorHealth, ConnectorOutput, OsintConnector};
use async_trait::async_trait;

pub struct WebsiteConnector;

impl WebsiteConnector {
    pub fn new() -> Self {
        Self
    }
}

impl Default for WebsiteConnector {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl OsintConnector for WebsiteConnector {
    fn name(&self) -> &'static str {
        "website"
    }

    fn availability(&self) -> &'static str {
        "AVAILABLE"
    }

    fn healthcheck(&self) -> ConnectorHealth {
        ConnectorHealth {
            connector: self.name().to_string(),
            availability: self.availability().to_string(),
            auth_required: false,
            supported_seeds: vec!["url".to_string(), "domain".to_string()],
        }
    }

    async fn search_username(&self, _username: &str) -> ConnectorOutput {
        ConnectorOutput::success(vec![], 0)
    }
}
