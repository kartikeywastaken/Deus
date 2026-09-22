use crate::connectors::engine::SiteEngine;
use crate::connectors::{ConnectorHealth, ConnectorOutput, OsintConnector};
use async_trait::async_trait;

pub struct AdlerConnector {
    engine: SiteEngine,
}

impl AdlerConnector {
    pub fn new() -> Self {
        Self {
            engine: SiteEngine::load_from_dataset(
                "adler-core",
                "adler_sites.json",
                include_str!("../../data/sites/adler_sites.json"),
            ),
        }
    }
}

impl Default for AdlerConnector {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl OsintConnector for AdlerConnector {
    fn name(&self) -> &'static str {
        "adler-core"
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
    fn test_adler_connector_rules_loaded() {
        let conn = AdlerConnector::new();
        assert!(conn.engine.load_error().is_none());
        assert!(conn.engine.rules_count() > 100);
    }
}
