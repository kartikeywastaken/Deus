use crate::db::repository::Repository;
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde_json::json;
use uuid::Uuid;

pub async fn get_graph(
    State(repo): State<Repository>,
    Path(id): Path<Uuid>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let profiles = repo
        .get_profiles(id)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))))?;

    let evidence = repo
        .get_evidence(id)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))))?;

    let nodes: Vec<_> = profiles
        .iter()
        .map(|p| {
            json!({
                "id": p.id,
                "label": p.username.as_deref().unwrap_or(&p.platform),
                "platform": p.platform,
                "url": p.canonical_url,
            })
        })
        .collect();

    let edges: Vec<_> = evidence
        .iter()
        .map(|e| {
            json!({
                "id": e.id,
                "source": e.left_profile_id,
                "target": e.right_profile_id,
                "signal_type": e.signal_type,
                "score": e.normalized_score,
                "direction": e.direction,
            })
        })
        .collect();

    Ok(Json(json!({
        "nodes": nodes,
        "edges": edges,
    })))
}
