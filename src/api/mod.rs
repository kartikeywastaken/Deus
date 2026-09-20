pub mod candidates;
pub mod connectors;
pub mod events;
pub mod graph;
pub mod health;
pub mod hypotheses;
pub mod images;
pub mod questions;
pub mod reports;
pub mod searches;

use crate::db::repository::Repository;
use axum::{
    routing::{get, post},
    Json, Router,
};
use serde_json::json;
use std::path::Path;
use tower_http::cors::{Any, CorsLayer};
use tower_http::services::ServeDir;

pub fn build_router(repo: Repository) -> Router {
    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    let api_routes = Router::new()
        .route("/health", get(health::health_check))
        .route("/api/config.js", get(health::config_js))
        .route("/api/connectors", get(connectors::list_connectors))
        .route("/api/searches", post(searches::create_search))
        .route("/api/searches/:id", get(searches::get_search))
        .route("/api/searches/:id/continue", post(searches::continue_search))
        .route("/api/searches/:id/stop", post(searches::stop_search))
        .route("/api/searches/:id/evidence", get(searches::get_evidence))
        .route("/api/searches/:id/connector-runs", get(searches::get_connector_runs))
        .route("/api/searches/:id/identifiers", get(searches::get_identifiers))
        .route("/api/searches/:id/observations", get(searches::get_observations))
        .route("/api/searches/:id/candidates", get(candidates::get_candidates))
        .route("/api/searches/:id/hypotheses", get(hypotheses::get_hypotheses))
        .route("/api/searches/:id/question", get(questions::get_pending_question))
        .route("/api/searches/:id/question-answer", post(questions::answer_question))
        .route("/api/searches/:id/report", get(reports::get_report))
        .route("/api/searches/:id/graph", get(graph::get_graph))
        .route("/api/searches/:id/events", get(events::sse_events))
        .route("/api/searches/:id/images", post(images::upload_image))
        .route("/api/searches/:id/image-matches", post(images::upload_image))
        .route(
            "/api/osint/email",
            get(|| async { Json(json!({"status": "available", "data": {}})) }),
        )
        .layer(cors)
        .with_state(repo);

    let frontend_dir = Path::new("./frontend");
    if frontend_dir.exists() {
        api_routes.fallback_service(ServeDir::new(frontend_dir))
    } else {
        api_routes
    }
}
