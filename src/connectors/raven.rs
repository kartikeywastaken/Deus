use crate::connectors::engine::SiteEngine;
use crate::connectors::{ConnectorHealth, ConnectorOutput, OsintConnector};
use async_trait::async_trait;

pub struct RavenConnector {
    engine: SiteEngine,
}

impl RavenConnector {
    pub fn new() -> Self {
        Self {
            engine: SiteEngine::load_from_dataset(
                "raven-osint",
                "raven_sites.json",
                include_str!("../../data/sites/raven_sites.json"),
            ),
        }
    }
}

impl Default for RavenConnector {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl OsintConnector for RavenConnector {
    fn name(&self) -> &'static str {
        "raven-osint"
    }

    fn availability(&self) -> &'static str {
        "AVAILABLE"
    }

    fn healthcheck(&self) -> ConnectorHealth {
        ConnectorHealth {
            connector: self.name().to_string(),
            availability: self.availability().to_string(),
            auth_required: false,
            supported_seeds: vec!["username".to_string()],
        }
    }

    async fn search_username(&self, username: &str) -> ConnectorOutput {
        self.engine.run_search(username).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_raven_connector_rules_loaded() {
        let conn = RavenConnector::new();
        assert!(conn.engine.load_error().is_none());
        assert!(conn.engine.rules_count() > 100);
    }
}
