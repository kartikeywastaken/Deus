use crate::db::repository::Repository;
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde_json::json;
use uuid::Uuid;

pub async fn get_report(
    State(repo): State<Repository>,
    Path(id): Path<Uuid>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let reports = repo
        .get_reports(id)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))))?;

    match reports.first() {
        Some(r) => Ok(Json(json!({
            "report_data": r.report_data.clone(),
            "report": r.report_data.clone()
        }))),
        None => Ok(Json(json!({
            "report_data": null,
            "search_run_id": id,
            "status": "PENDING",
            "message": "Report generation in progress"
        }))),
    }
}
