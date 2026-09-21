pub mod candidates;
pub mod connectors;
pub mod events;
pub mod graph;
pub mod health;
pub mod photo_match;
pub mod reports;
pub mod searches;

use crate::db::repository::Repository;
use axum::{
    extract::DefaultBodyLimit,
    routing::{get, post},
    Router,
};
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
        .route("/api/searches/:id/report", get(reports::get_report))
        .route("/api/searches/:id/graph", get(graph::get_graph))
        .route("/api/searches/:id/events", get(events::sse_events))
        .route(
            "/api/searches/:id/photo",
            post(photo_match::upload_photo_handler).delete(photo_match::clear_photo_handler),
        )
        .route(
            "/api/searches/:id/photo-matches",
            get(photo_match::get_photo_matches_handler),
        )
        .route("/api/osint/email", post(crate::osint::email::scan).get(crate::osint::email::email_info_handler))
        .layer(DefaultBodyLimit::max(15 * 1024 * 1024))
        .layer(cors)
        .with_state(repo);

    let frontend_dir = Path::new("./frontend");
    if frontend_dir.exists() {
        api_routes.fallback_service(ServeDir::new(frontend_dir))
    } else {
        api_routes
    }
}
