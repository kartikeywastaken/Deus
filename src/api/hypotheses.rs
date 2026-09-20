use crate::db::repository::Repository;
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde_json::json;
use uuid::Uuid;

pub async fn get_hypotheses(
    State(repo): State<Repository>,
    Path(id): Path<Uuid>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let hypotheses = repo
        .get_hypotheses(id)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))))?;

    let mut result = Vec::new();

    for hyp in hypotheses {
        let memberships = repo.get_memberships(hyp.id).await.unwrap_or_default();
        result.push(json!({
            "hypothesis": hyp,
            "members": memberships,
        }));
    }

    Ok(Json(json!({
        "items": result,
        "hypotheses": result,
    })))
}
