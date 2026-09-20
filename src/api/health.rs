use axum::{
    response::{IntoResponse, Response},
    Json,
};
use serde_json::json;

pub async fn health_check() -> Json<serde_json::Value> {
    Json(json!({
        "status": "ok",
        "database": "postgresql+pgvector",
        "collection_mode": "LIVE",
        "engine": "Rust (raven-osint + adler-core)",
    }))
}

pub async fn config_js() -> Response {
    let script = "window.OSINT_API_BASE = window.location.origin;\n";
    axum::response::Response::builder()
        .header("Content-Type", "application/javascript")
        .body(axum::body::Body::from(script))
        .unwrap_or_else(|_| Json(json!({"error": "Failed to serve config.js"})).into_response())
}
