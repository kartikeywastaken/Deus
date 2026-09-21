use serde::Deserialize;
use std::env;

#[derive(Debug, Clone, Deserialize)]
pub struct Config {
    pub database_url: String,
    pub api_port: u16,
    pub github_token: Option<String>,
    pub ai_adviser_enabled: bool,
    pub openai_api_key: Option<String>,
    pub connector_timeout_seconds: u64,
    pub max_pivot_depth: i32,
    pub max_connector_runs: i32,
    pub max_candidates: i32,
    pub max_questions: i32,
    pub max_search_duration_seconds: i32,
}

impl Config {
    pub fn from_env() -> Self {
        dotenvy::dotenv().ok();

        Self {
            database_url: env::var("DATABASE_URL")
                .unwrap_or_else(|_| "postgresql://osint:osint-dev@localhost:5432/osint".to_string()),
            api_port: env::var("PORT")
            .or_else(|_| env::var("API_PORT"))
            .ok()
            .and_then(|p| p.parse().ok())
            .unwrap_or(8765),
            github_token: env::var("GITHUB_TOKEN").ok().filter(|s| !s.is_empty()),
            ai_adviser_enabled: env::var("AI_ADVISER_ENABLED")
                .map(|v| v.eq_ignore_ascii_case("true") || v == "1")
                .unwrap_or(false),
            openai_api_key: env::var("OPENAI_API_KEY").ok().filter(|s| !s.is_empty()),
            connector_timeout_seconds: env::var("CONNECTOR_TIMEOUT_SECONDS")
                .ok()
                .and_then(|p| p.parse().ok())
                .unwrap_or(30),
            max_pivot_depth: env::var("MAX_PIVOT_DEPTH")
                .ok()
                .and_then(|p| p.parse().ok())
                .unwrap_or(3),
            max_connector_runs: env::var("MAX_CONNECTOR_RUNS")
                .ok()
                .and_then(|p| p.parse().ok())
                .unwrap_or(30),
            max_candidates: env::var("MAX_CANDIDATES")
                .ok()
                .and_then(|p| p.parse().ok())
                .unwrap_or(100),
            max_questions: env::var("MAX_QUESTIONS")
                .ok()
                .and_then(|p| p.parse().ok())
                .unwrap_or(3),
            max_search_duration_seconds: env::var("MAX_SEARCH_DURATION_SECONDS")
                .ok()
                .and_then(|p| p.parse().ok())
                .unwrap_or(600),
        }
    }
}
