use crate::db::repository::Repository;
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::{Deserialize, Serialize};
use serde_json::json;
use uuid::Uuid;

#[derive(Debug, Deserialize)]
pub struct CreateSeedRequest {
    pub seed_type: String,
    pub value: String,
}

#[derive(Debug, Deserialize)]
pub struct CreateSearchRequest {
    pub scope: Option<String>,
    pub seed_type: Option<String>,
    pub value: Option<String>,
    pub seeds: Option<Vec<CreateSeedRequest>>,
    pub max_pivot_depth: Option<i32>,
    pub max_questions: Option<i32>,
    pub max_connector_runs: Option<i32>,
    pub max_candidates: Option<i32>,
    pub max_search_duration_seconds: Option<i32>,
}

#[derive(Debug, Serialize)]
pub struct SearchResponse {
    pub id: Uuid,
    pub status: String,
    pub scope: String,
    pub created_at: String,
    pub pivot_depth: i32,
    pub questions_asked: i32,
    pub connector_runs_count: i32,
}

pub async fn create_search(
    State(repo): State<Repository>,
    Json(payload): Json<CreateSearchRequest>,
) -> Result<(StatusCode, Json<serde_json::Value>), (StatusCode, Json<serde_json::Value>)> {
    let scope = payload.scope.as_deref().unwrap_or("self_audit");
    let search = repo
        .create_search_run(
            scope,
            payload.max_pivot_depth.unwrap_or(3),
            payload.max_questions.unwrap_or(3),
            payload.max_connector_runs.unwrap_or(30),
            payload.max_candidates.unwrap_or(100),
            payload.max_search_duration_seconds.unwrap_or(600),
        )
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))))?;

    let mut seeds_added = 0;

    if let (Some(ref stype), Some(ref sval)) = (payload.seed_type, payload.value) {
        let norm_val = sval.trim().to_lowercase();
        if !norm_val.is_empty() {
            repo.add_seed(search.id, stype, sval, &norm_val, None)
                .await
                .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))))?;
            seeds_added += 1;
        }
    }

    if let Some(ref seed_list) = payload.seeds {
        for seed in seed_list {
            let norm_val = seed.value.trim().to_lowercase();
            if !norm_val.is_empty() {
                repo.add_seed(search.id, &seed.seed_type, &seed.value, &norm_val, None)
                    .await
                    .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))))?;
                seeds_added += 1;
            }
        }
    }

    if seeds_added == 0 {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"error": "No valid search seeds provided"})),
        ));
    }

    repo.create_investigation_job(search.id, json!({"action": "start"}))
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))))?;

    Ok((
        StatusCode::CREATED,
        Json(json!({
            "id": search.id,
            "status": search.status,
            "scope": search.scope,
            "created_at": search.created_at,
        })),
    ))
}

pub async fn get_search(
    State(repo): State<Repository>,
    Path(id): Path<Uuid>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let search = repo
        .get_search_run(id)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))))?
        .ok_or_else(|| (StatusCode::NOT_FOUND, Json(json!({"detail": "Search run not found"}))))?;

    let seeds = repo.get_seeds(id).await.unwrap_or_default();

    Ok(Json(json!({
        "id": search.id,
        "status": search.status,
        "scope": search.scope,
        "created_at": search.created_at,
        "pivot_depth": search.pivot_depth,
        "questions_asked": search.questions_asked,
        "connector_runs_count": search.connector_runs_count,
        "error_summary": search.error_summary,
        "seeds": seeds,
    })))
}

pub async fn continue_search(
    State(repo): State<Repository>,
    Path(id): Path<Uuid>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    repo.update_search_status(id, "DISCOVERING", None)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))))?;

    repo.create_investigation_job(id, json!({"action": "continue"}))
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))))?;

    Ok(Json(json!({"status": "DISCOVERING", "message": "Search run resumed"})))
}

pub async fn stop_search(
    State(repo): State<Repository>,
    Path(id): Path<Uuid>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    repo.update_search_status(id, "STOPPED", Some("User requested search cancellation"))
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))))?;

    Ok(Json(json!({"status": "STOPPED", "message": "Search run cancelled"})))
}

pub async fn get_evidence(
    State(repo): State<Repository>,
    Path(id): Path<Uuid>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let evidence = repo
        .get_evidence(id)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))))?;

    Ok(Json(json!({"items": evidence, "evidence": evidence})))
}

pub async fn get_connector_runs(
    State(repo): State<Repository>,
    Path(id): Path<Uuid>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let connector_runs = repo
        .get_connector_runs(id)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))))?;

    Ok(Json(json!({"items": connector_runs})))
}

pub async fn get_identifiers(
    State(_repo): State<Repository>,
    Path(_id): Path<Uuid>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    Ok(Json(json!({"items": []})))
}

pub async fn get_observations(
    State(_repo): State<Repository>,
    Path(_id): Path<Uuid>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    Ok(Json(json!({"items": []})))
}
