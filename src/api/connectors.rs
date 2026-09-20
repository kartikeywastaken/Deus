use crate::connectors::build_all_connectors;
use axum::Json;
use serde_json::json;

pub async fn list_connectors() -> Json<serde_json::Value> {
    let connectors = build_all_connectors(None);
    let items: Vec<_> = connectors.iter().map(|c| c.healthcheck()).collect();

    Json(json!({
        "mode": "LIVE",
        "items": items,
    }))
}
