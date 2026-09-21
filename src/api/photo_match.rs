use crate::db::repository::Repository;
use crate::enrich::{AvatarFetcher, DefaultAvatarFetcher};
use crate::photo_match::{
    avatars::extract_candidate_avatar_specs, get_photo_store, match_avatar, prepare_photo,
    MatchMethod, PhotoMatchResult, Verdict,
};
use axum::{
    extract::{ConnectInfo, Multipart, Path, Query, State},
    http::{header, HeaderMap, StatusCode},
    Json,
};
use futures::stream::{self, StreamExt};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::net::{IpAddr, SocketAddr};
use std::sync::Arc;
use std::time::Duration;
use tokio::time::timeout;
use uuid::Uuid;

#[derive(Debug, Deserialize)]
pub struct PhotoMatchQuery {
    pub token: String,
}

#[derive(Debug, Serialize)]
pub struct PhotoMatchCounts {
    pub same_photo: usize,
    pub possible_match: usize,
    pub no_match: usize,
    pub no_avatar: usize,
    pub unavailable: usize,
    pub too_small: usize,
}

#[derive(Debug, Serialize)]
pub struct CandidateMatchItem {
    pub profile_id: String,
    pub platform: String,
    pub username: String,
    pub profile_url: String,
    pub avatar_url: String,
    pub verdict: Verdict,
    pub strength: f32,
    pub method: MatchMethod,
}

#[derive(Debug, Serialize)]
pub struct PhotoMatchesResponse {
    pub status: String,
    pub total: usize,
    pub checked: usize,
    pub pending: usize,
    pub counts: PhotoMatchCounts,
    pub matches: Vec<CandidateMatchItem>,
}

pub async fn upload_photo_handler(
    State(_repo): State<Repository>,
    Path(id): Path<Uuid>,
    connect_info: Option<ConnectInfo<SocketAddr>>,
    headers: HeaderMap,
    mut multipart: Multipart,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let client_ip: IpAddr = headers
        .get("x-forwarded-for")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.split(',').next())
        .and_then(|s| s.trim().parse().ok())
        .or_else(|| {
            headers
                .get("x-real-ip")
                .and_then(|v| v.to_str().ok())
                .and_then(|s| s.trim().parse().ok())
        })
        .unwrap_or_else(|| {
            connect_info
                .map(|ci| ci.0.ip())
                .unwrap_or_else(|| IpAddr::from([127, 0, 0, 1]))
        });

    let store = get_photo_store();
    {
        let mut guard = store.lock().unwrap();
        if !guard.check_rate_limit(client_ip) {
            return Err((
                StatusCode::TOO_MANY_REQUESTS,
                Json(json!({"detail": "Rate limit exceeded for photo matching uploads"})),
            ));
        }
    }

    let mut photo_bytes: Option<Vec<u8>> = None;

    while let Ok(Some(field)) = multipart.next_field().await {
        if field.name() == Some("photo") {
            let bytes = field
                .bytes()
                .await
                .map_err(|e| (StatusCode::BAD_REQUEST, Json(json!({"detail": format!("Failed to read field: {e}")}))))?;
            photo_bytes = Some(bytes.to_vec());
            break;
        }
    }

    let bytes = photo_bytes.ok_or_else(|| {
        (
            StatusCode::BAD_REQUEST,
            Json(json!({"detail": "Missing 'photo' multipart field"})),
        )
    })?;

    let prepared = prepare_photo(&bytes).map_err(|e| {
        (
            StatusCode::BAD_REQUEST,
            Json(json!({"detail": e})),
        )
    })?;

    let width = prepared.original_width;
    let height = prepared.original_height;

    let token = {
        let mut guard = store.lock().unwrap();
        guard.insert(id, prepared)
    };

    Ok(Json(json!({
        "token": token,
        "width": width,
        "height": height
    })))
}

pub async fn get_photo_matches_handler(
    State(repo): State<Repository>,
    Path(id): Path<Uuid>,
    Query(query): Query<PhotoMatchQuery>,
) -> Result<(HeaderMap, Json<PhotoMatchesResponse>), (StatusCode, Json<Value>)> {
    let fetcher = DefaultAvatarFetcher;
    get_photo_matches_internal(repo, id, query.token, Arc::new(fetcher)).await
}

pub async fn get_photo_matches_internal<F: AvatarFetcher + 'static>(
    repo: Repository,
    id: Uuid,
    token: String,
    fetcher: Arc<F>,
) -> Result<(HeaderMap, Json<PhotoMatchesResponse>), (StatusCode, Json<Value>)> {
    let mut response_headers = HeaderMap::new();
    response_headers.insert(header::CACHE_CONTROL, "no-store".parse().unwrap());

    let store = get_photo_store();
    let prepared_entry = {
        let mut guard = store.lock().unwrap();
        guard.get(&token, id)
    };

    let prepared_entry = prepared_entry.ok_or_else(|| {
        (
            StatusCode::NOT_FOUND,
            Json(json!({"detail": "photo session expired"})),
        )
    })?;

    let search_run = repo
        .get_search_run(id)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"detail": e.to_string()}))))?
        .ok_or_else(|| (StatusCode::NOT_FOUND, Json(json!({"detail": "Search not found"}))))?;

    let profiles = repo
        .get_profiles(id)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"detail": e.to_string()}))))?;

    let observations = repo
        .get_observations(id)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"detail": e.to_string()}))))?;

    let candidate_specs = extract_candidate_avatar_specs(&profiles, &observations);
    let total_candidates = candidate_specs.len();

    let mut same_photo_count = 0;
    let mut possible_match_count = 0;
    let mut no_match_count = 0;
    let mut no_avatar_count = 0;
    let mut unavailable_count = 0;
    let mut too_small_count = 0;
    let mut checked_count = 0;

    let mut matches_list = Vec::new();

    // 15 seconds overall budget per call
    let per_call_budget = Duration::from_secs(15);
    let start_time = tokio::time::Instant::now();

    // Max 4 concurrent avatar fetches
    let stream_specs = stream::iter(candidate_specs);

    let mut results_stream = stream_specs.map(|spec| {
        let token_clone = token.clone();
        let store_clone = store.clone();
        let prepared_clone = prepared_entry.prepared.clone();
        let fetcher_clone = fetcher.clone();

        async move {
            let elapsed = start_time.elapsed();
            if elapsed >= per_call_budget {
                return (spec, None);
            }

            let avatar_url = match spec.avatar_url.clone() {
                Some(url) if !url.trim().is_empty() => url,
                _ => return (spec, Some(PhotoMatchResult { verdict: Verdict::NoMatch, strength: 0.0, method: MatchMethod::CropMatch })),
            };

            // Check cache
            let cached = {
                let guard = store_clone.lock().unwrap();
                guard.get_cached_result(&token_clone, &avatar_url)
            };

            if let Some(res) = cached {
                return (spec, Some(res));
            }

            // Fetch avatar with 8s timeout
            let fetch_res = timeout(Duration::from_secs(8), fetcher_clone.fetch_avatar(&avatar_url)).await;
            let avatar_bytes = match fetch_res {
                Ok(Ok(bytes)) => bytes,
                _ => {
                    let res = PhotoMatchResult {
                        verdict: Verdict::Unavailable,
                        strength: 0.0,
                        method: MatchMethod::CropMatch,
                    };
                    let mut guard = store_clone.lock().unwrap();
                    guard.cache_result(&token_clone, avatar_url, res.clone());
                    return (spec, Some(res));
                }
            };

            // Run match in blocking task
            let match_res = tokio::task::spawn_blocking(move || {
                match_avatar(&prepared_clone, &avatar_bytes)
            })
            .await
            .unwrap_or(PhotoMatchResult {
                verdict: Verdict::Unavailable,
                strength: 0.0,
                method: MatchMethod::CropMatch,
            });

            {
                let mut guard = store_clone.lock().unwrap();
                guard.cache_result(&token_clone, avatar_url, match_res.clone());
            }

            (spec, Some(match_res))
        }
    }).buffer_unordered(4);

    while let Some((spec, res_opt)) = results_stream.next().await {
        let avatar_url_opt = spec.avatar_url.clone();
        if avatar_url_opt.is_none() {
            no_avatar_count += 1;
            checked_count += 1;
            continue;
        }

        let res = match res_opt {
            Some(r) => r,
            None => continue,
        };

        checked_count += 1;

        match res.verdict {
            Verdict::SamePhoto => {
                same_photo_count += 1;
                matches_list.push(CandidateMatchItem {
                    profile_id: spec.profile_id,
                    platform: spec.platform,
                    username: spec.username,
                    profile_url: spec.profile_url,
                    avatar_url: avatar_url_opt.unwrap_or_default(),
                    verdict: Verdict::SamePhoto,
                    strength: res.strength,
                    method: res.method,
                });
            }
            Verdict::PossibleMatch => {
                possible_match_count += 1;
                matches_list.push(CandidateMatchItem {
                    profile_id: spec.profile_id,
                    platform: spec.platform,
                    username: spec.username,
                    profile_url: spec.profile_url,
                    avatar_url: avatar_url_opt.unwrap_or_default(),
                    verdict: Verdict::PossibleMatch,
                    strength: res.strength,
                    method: res.method,
                });
            }
            Verdict::NoMatch => no_match_count += 1,
            Verdict::TooSmall => too_small_count += 1,
            Verdict::Unavailable => unavailable_count += 1,
        }
    }

    let pending_count = total_candidates.saturating_sub(checked_count);

    let search_status_str = search_run.status.to_uppercase();
    let is_terminal = matches!(
        search_status_str.as_str(),
        "COMPLETED" | "FAILED" | "CANCELLED" | "STOPPED"
    );

    let status = if is_terminal && pending_count == 0 {
        "done"
    } else {
        "pending"
    };

    // Sort matches: SAME_PHOTO first, then POSSIBLE_MATCH, then by strength desc
    matches_list.sort_by(|a, b| {
        let a_rank = if a.verdict == Verdict::SamePhoto { 0 } else { 1 };
        let b_rank = if b.verdict == Verdict::SamePhoto { 0 } else { 1 };
        a_rank.cmp(&b_rank).then_with(|| b.strength.partial_cmp(&a.strength).unwrap_or(std::cmp::Ordering::Equal))
    });

    let resp = PhotoMatchesResponse {
        status: status.to_string(),
        total: total_candidates,
        checked: checked_count,
        pending: pending_count,
        counts: PhotoMatchCounts {
            same_photo: same_photo_count,
            possible_match: possible_match_count,
            no_match: no_match_count,
            no_avatar: no_avatar_count,
            unavailable: unavailable_count,
            too_small: too_small_count,
        },
        matches: matches_list,
    };

    Ok((response_headers, Json(resp)))
}

pub async fn clear_photo_handler(
    State(_repo): State<Repository>,
    Path(id): Path<Uuid>,
    Query(query): Query<PhotoMatchQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let store = get_photo_store();
    let mut guard = store.lock().unwrap();
    if guard.delete(&query.token, id) {
        Ok(Json(json!({"detail": "photo session cleared"})))
    } else {
        Err((
            StatusCode::NOT_FOUND,
            Json(json!({"detail": "photo session expired"})),
        ))
    }
}
