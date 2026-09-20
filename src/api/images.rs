use crate::image::phash::compute_image_fingerprint;
use axum::{
    extract::{Multipart, Path},
    http::StatusCode,
    Json,
};
use serde_json::json;
use uuid::Uuid;

pub async fn upload_image(
    Path(id): Path<Uuid>,
    mut multipart: Multipart,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    while let Ok(Some(field)) = multipart.next_field().await {
        if let Ok(bytes) = field.bytes().await {
            if let Ok(fp) = compute_image_fingerprint(bytes.as_ref()) {
                return Ok(Json(json!({
                    "search_run_id": id,
                    "sha256": fp.sha256,
                    "perceptual_hash": fp.phash,
                    "width": fp.width,
                    "height": fp.height,
                    "status": "FINGERPRINTED",
                    "raw_bytes_retained": false,
                })));
            }
        }
    }

    Err((
        StatusCode::BAD_REQUEST,
        Json(json!({"error": "No valid image data provided"})),
    ))
}
