use crate::db::repository::Repository;
use axum::{
    extract::{Path, State},
    http::StatusCode,
    Json,
};
use serde::Deserialize;
use serde_json::json;
use uuid::Uuid;

#[derive(Debug, Deserialize)]
pub struct AnswerQuestionRequest {
    pub answer: Option<serde_json::Value>,
    pub value: Option<serde_json::Value>,
}

pub async fn get_pending_question(
    State(repo): State<Repository>,
    Path(id): Path<Uuid>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let question = repo
        .get_pending_question(id)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))))?;

    match question {
        Some(q) => Ok(Json(json!({"item": q, "question": q}))),
        None => Ok(Json(json!({"item": null, "question": null, "message": "No pending questions"}))),
    }
}

pub async fn answer_question(
    State(repo): State<Repository>,
    Path(id): Path<Uuid>,
    Json(payload): Json<AnswerQuestionRequest>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let question = repo
        .get_pending_question(id)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))))?
        .ok_or_else(|| (StatusCode::NOT_FOUND, Json(json!({"detail": "No pending question to answer"}))))?;

    let ans_val = payload.answer.or(payload.value).unwrap_or(json!({"answer": "submitted"}));
    let ans_id = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO investigation_answers (id, question_id, answer, created_at) VALUES ($1, $2, $3, NOW())"
    )
    .bind(ans_id)
    .bind(question.id)
    .bind(&ans_val)
    .execute(&repo.pool)
    .await
    .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))))?;

    sqlx::query(
        "UPDATE investigation_questions SET status = 'ANSWERED', answered_at = NOW() WHERE id = $1"
    )
    .bind(question.id)
    .execute(&repo.pool)
    .await
    .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))))?;

    repo.update_search_status(id, "DISCOVERING", None)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))))?;

    repo.create_investigation_job(id, json!({"action": "resume_with_hint", "answer": ans_val}))
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))))?;

    Ok(Json(json!({"status": "SUCCESS", "message": "Answer recorded; search resumed"})))
}
