use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BreachExposure {
    pub name: String,
    pub domain: String,
}

#[derive(Debug, Clone)]
pub struct Endpoints {
    pub gravatar_url: String,
    pub github_api_url: String,
    pub pgp_key_url: String,
    pub hibp_api_url: String,
}

impl Default for Endpoints {
    fn default() -> Self {
        Self {
            gravatar_url: "https://en.gravatar.com".to_string(),
            github_api_url: "https://api.github.com".to_string(),
            pgp_key_url: "https://keys.openpgp.org/vks/v1/by-email".to_string(),
            hibp_api_url: "https://haveibeenpwned.com/api/v3/breachedaccount".to_string(),
        }
    }
}

#[derive(Debug, Clone)]
pub struct EmailCtx {
    pub raw_email: String,
    pub normalized_email: String,
    pub base_email: String,
    pub domain: String,
    pub local_part: String,
    pub client: reqwest::Client,
    pub self_audit_confirmed: bool,
    pub github_token: Option<String>,
    pub hibp_api_key: Option<String>,
    pub endpoints: Endpoints,
}

#[derive(Debug, Clone, Deserialize)]
pub struct EmailScanRequest {
    pub email: String,
    pub self_audit_confirmed: Option<bool>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Status {
    Registered,
    NotRegistered,
    CantCheck,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SiteResult {
    pub id: String,
    pub label: String,
    pub status: Status,
    pub via: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub username: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub profile_url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Summary {
    pub registered: usize,
    pub not_registered: usize,
    pub cant_check: usize,
    pub scan_ms: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EmailScanResponse {
    pub email: String,
    pub provider: String,
    pub summary: Summary,
    pub sites: Vec<SiteResult>,
    pub breaches: Vec<BreachExposure>,
}