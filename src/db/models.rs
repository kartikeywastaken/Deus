use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;
use uuid::Uuid;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default, sqlx::Type)]
#[sqlx(type_name = "search_status", rename_all = "SCREAMING_SNAKE_CASE")]
pub enum SearchStatus {
    #[default]
    Created,
    Discovering,
    Normalizing,
    Expanding,
    Enriching,
    Correlating,
    AwaitingUser,
    Continuing,
    Reporting,
    Completed,
    Failed,
    Cancelled,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default, sqlx::Type)]
#[sqlx(type_name = "search_scope", rename_all = "snake_case")]
pub enum SearchScope {
    #[default]
    SelfAudit,
    Authorized,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, sqlx::Type)]
#[sqlx(type_name = "seed_type", rename_all = "snake_case")]
pub enum SeedType {
    Username,
    Email,
    Domain,
    Url,
    Image,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ConnectorStatus {
    Pending,
    Running,
    Success,
    Partial,
    NoResults,
    RateLimited,
    AuthRequired,
    Unavailable,
    Disabled,
    Failed,
    Manual,
}

impl ConnectorStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "PENDING",
            Self::Running => "RUNNING",
            Self::Success => "SUCCESS",
            Self::Partial => "PARTIAL",
            Self::NoResults => "NO_RESULTS",
            Self::RateLimited => "RATE_LIMITED",
            Self::AuthRequired => "AUTH_REQUIRED",
            Self::Unavailable => "UNAVAILABLE",
            Self::Disabled => "DISABLED",
            Self::Failed => "FAILED",
            Self::Manual => "MANUAL",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, sqlx::Type)]
#[sqlx(type_name = "evidence_direction", rename_all = "SCREAMING_SNAKE_CASE")]
pub enum EvidenceDirection {
    Support,
    Contradict,
    Neutral,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, sqlx::Type)]
#[sqlx(type_name = "classification", rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Classification {
    Strong,
    Likely,
    Ambiguous,
    Weak,
    Contradictory,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, sqlx::Type)]
#[sqlx(type_name = "hypothesis_status", rename_all = "SCREAMING_SNAKE_CASE")]
pub enum HypothesisStatus {
    Active,
    Pruned,
    Merged,
}

#[derive(Clone, Copy, PartialEq, Eq, Serialize, Deserialize, sqlx::Type)]
#[sqlx(type_name = "question_type", rename_all = "SCREAMING_SNAKE_CASE")]
pub enum QuestionType {
    YesNo,
    SingleSelect,
    MultiSelect,
}

impl std::fmt::Debug for QuestionType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::YesNo => write!(f, "YES_NO"),
            Self::SingleSelect => write!(f, "SINGLE_SELECT"),
            Self::MultiSelect => write!(f, "MULTI_SELECT"),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, sqlx::Type)]
#[sqlx(type_name = "question_status", rename_all = "SCREAMING_SNAKE_CASE")]
pub enum QuestionStatus {
    Pending,
    Answered,
    Skipped,
    Expired,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, sqlx::Type)]
#[sqlx(type_name = "sensitivity_level", rename_all = "SCREAMING_SNAKE_CASE")]
pub enum SensitivityLevel {
    Low,
    Moderate,
    High,
}

#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct SearchRun {
    pub id: Uuid,
    pub status: String,
    pub scope: String,
    pub created_at: DateTime<Utc>,
    pub started_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
    pub retention_expires_at: Option<DateTime<Utc>>,
    pub pivot_depth: i32,
    pub questions_asked: i32,
    pub connector_runs_count: i32,
    pub max_pivot_depth: i32,
    pub max_questions: i32,
    pub max_connector_runs: i32,
    pub max_candidates: i32,
    pub max_search_duration_seconds: i32,
    pub error_summary: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct SearchSeed {
    pub id: Uuid,
    pub search_run_id: Uuid,
    pub seed_type: String,
    pub original_value: Option<String>,
    pub normalized_value: Option<String>,
    pub artifact_id: Option<Uuid>,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct ProfileRecord {
    pub id: Uuid,
    pub platform: String,
    pub platform_account_id: Option<String>,
    pub username: Option<String>,
    pub normalized_username: Option<String>,
    pub display_name: Option<String>,
    pub normalized_display_name: Option<String>,
    pub canonical_url: String,
    pub avatar_url: Option<String>,
    pub current_bio: Option<String>,
    pub current_location: Option<String>,
    pub current_organization: Option<String>,
    pub first_seen_at: DateTime<Utc>,
    pub last_seen_at: DateTime<Utc>,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct ConnectorRunRecord {
    pub id: Uuid,
    pub search_run_id: Uuid,
    pub connector: String,
    pub connector_version: Option<String>,
    pub status: String,
    pub started_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
    pub request_count: i32,
    pub error: Option<String>,
    pub input_data: serde_json::Value,
    pub metadata: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct ProfileObservationRecord {
    pub id: Uuid,
    pub search_run_id: Uuid,
    pub profile_id: Uuid,
    pub connector_run_id: Uuid,
    pub connector: String,
    pub source_url: Option<String>,
    pub observed_at: DateTime<Utc>,
    pub normalized_data: serde_json::Value,
    pub raw_data: serde_json::Value,
    pub content_hash: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct EvidenceSignalRecord {
    pub id: Uuid,
    pub search_run_id: Uuid,
    pub left_profile_id: Uuid,
    pub right_profile_id: Uuid,
    pub signal_type: String,
    pub direction: String,
    pub raw_value: serde_json::Value,
    pub normalized_score: f64,
    pub reliability: f64,
    pub model_contribution: Option<f64>,
    pub evidence_family: String,
    pub source_observation_ids: Vec<Uuid>,
    pub extractor_version: String,
    pub explanation: String,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct IdentityHypothesisRecord {
    pub id: Uuid,
    pub search_run_id: Uuid,
    pub label: Option<String>,
    pub rank: i32,
    pub overall_score: f64,
    pub classification: String,
    pub status: String,
    pub model_version: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct HypothesisMembershipRecord {
    pub id: Uuid,
    pub hypothesis_id: Uuid,
    pub profile_id: Uuid,
    pub score: f64,
    pub classification: String,
    pub support_count: i32,
    pub contradiction_count: i32,
    pub computed_at: DateTime<Utc>,
    pub model_version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct InvestigationQuestionRecord {
    pub id: Uuid,
    pub search_run_id: Uuid,
    pub question_type: String,
    pub question_text: String,
    pub options: serde_json::Value,
    pub context: serde_json::Value,
    pub reason: String,
    pub affected_profile_ids: Vec<Uuid>,
    pub affected_hypothesis_ids: Vec<Uuid>,
    pub expected_information_gain: Option<f64>,
    pub sensitivity_level: String,
    pub status: String,
    pub created_at: DateTime<Utc>,
    pub answered_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct InvestigationJobRecord {
    pub id: Uuid,
    pub search_run_id: Uuid,
    pub job_type: String,
    pub payload: serde_json::Value,
    pub status: String,
    pub attempt_count: i32,
    pub available_at: DateTime<Utc>,
    pub lease_until: Option<DateTime<Utc>>,
    pub worker_id: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub last_error: Option<String>,
    pub runtime_seconds: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct ReportRecord {
    pub id: Uuid,
    pub search_run_id: Uuid,
    pub report_data: serde_json::Value,
    pub generated_at: DateTime<Utc>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_connector_status_as_str_allowed_values() {
        let allowed = [
            "PENDING",
            "RUNNING",
            "SUCCESS",
            "PARTIAL",
            "NO_RESULTS",
            "RATE_LIMITED",
            "AUTH_REQUIRED",
            "UNAVAILABLE",
            "DISABLED",
            "FAILED",
            "MANUAL",
        ];
        assert_eq!(allowed.len(), 11, "Allowed list must have 11 entries");

        let statuses = [
            ConnectorStatus::Pending,
            ConnectorStatus::Running,
            ConnectorStatus::Success,
            ConnectorStatus::Partial,
            ConnectorStatus::NoResults,
            ConnectorStatus::RateLimited,
            ConnectorStatus::AuthRequired,
            ConnectorStatus::Unavailable,
            ConnectorStatus::Disabled,
            ConnectorStatus::Failed,
            ConnectorStatus::Manual,
        ];

        assert_eq!(statuses.len(), 11, "ConnectorStatus variants count must be 11");
        for status in &statuses {
            assert!(
                allowed.contains(&status.as_str()),
                "ConnectorStatus::as_str() '{}' not in allowed list",
                status.as_str()
            );
        }
    }
}

