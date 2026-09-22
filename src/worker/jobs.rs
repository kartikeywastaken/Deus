use crate::connectors::build_all_connectors;
use crate::db::models::InvestigationJobRecord;
use crate::db::repository::Repository;
use crate::worker::seed::{extract_handle, normalize_canonical_url};
use futures::stream::{self, StreamExt};
use serde_json::json;
use std::collections::HashSet;
use std::sync::Arc;
use std::time::Duration;
use tracing::{error, info};
use uuid::Uuid;

pub struct Worker {
    repo: Repository,
    github_token: Option<String>,
}

impl Worker {
    pub fn new(repo: Repository, github_token: Option<String>) -> Self {
        Self { repo, github_token }
    }

    pub async fn run_loop(self: Arc<Self>) {
        info!("Rust background worker started successfully");
        loop {
            if let Err(e) = self.process_next_job().await {
                error!("Worker job loop error: {}", e);
            }
            tokio::time::sleep(Duration::from_secs(2)).await;
        }
    }

    async fn process_next_job(&self) -> Result<(), String> {
        let job = sqlx::query_as::<_, InvestigationJobRecord>(
            r#"
            UPDATE investigation_jobs
            SET status = 'RUNNING', updated_at = NOW()
            WHERE id = (
                SELECT id FROM investigation_jobs
                WHERE status = 'PENDING' AND available_at <= NOW()
                ORDER BY created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING *
            "#
        )
        .fetch_optional(&self.repo.pool)
        .await
        .map_err(|e| e.to_string())?;

        let Some(job) = job else {
            return Ok(());
        };

        let job_id = job.id;
        let search_run_id = job.search_run_id;

        if let Err(err) = self.execute_job(&job).await {
            error!("Investigation job {} failed for search {}: {}", job_id, search_run_id, err);

            let _ = sqlx::query(
                "UPDATE investigation_jobs SET status = 'FAILED', last_error = $1, updated_at = NOW() WHERE id = $2"
            )
            .bind(&err)
            .bind(job_id)
            .execute(&self.repo.pool)
            .await;

            let _ = self
                .repo
                .update_search_status(search_run_id, "FAILED", Some(&err))
                .await;
        }

        Ok(())
    }

    async fn persist_connector_output(
        &self,
        search_run_id: Uuid,
        conn_run_id: Uuid,
        connector_name: &str,
        output: crate::connectors::ConnectorOutput,
        derived_note: Option<&str>,
    ) -> Result<Vec<Uuid>, String> {
        let mut created_ids = Vec::new();

        for mut prof in output.profiles {
            prof.canonical_url = normalize_canonical_url(&prof.canonical_url);

            if let Some(note) = derived_note {
                let bio = prof.bio.unwrap_or_default();
                prof.bio = Some(format!("[{}] {}", note, bio));
            }

            let db_prof = self
                .repo
                .upsert_profile(
                    &prof.platform,
                    Some(&prof.username),
                    Some(&prof.username.to_lowercase()),
                    prof.display_name.as_deref(),
                    &prof.canonical_url,
                    prof.avatar_url.as_deref(),
                    prof.bio.as_deref(),
                    prof.location.as_deref(),
                    prof.organization.as_deref(),
                )
                .await
                .map_err(|e| e.to_string())?;

            created_ids.push(db_prof.id);

            self.repo
                .add_observation(
                    search_run_id,
                    db_prof.id,
                    conn_run_id,
                    connector_name,
                    Some(&prof.canonical_url),
                    json!({
                        "platform": prof.platform,
                        "username": prof.username,
                        "derived": derived_note.is_some()
                    }),
                    prof.raw_json,
                )
                .await
                .map_err(|e| e.to_string())?;
        }

        self.repo
            .complete_connector_run(conn_run_id, output.status, output.error.as_deref())
            .await
            .map_err(|e| e.to_string())?;

        Ok(created_ids)
    }

    async fn fetch_github_profile_links(&self, handle: &str) -> Vec<(String, String, String)> {
        let client = reqwest::Client::new();
        let mut results = Vec::new();

        let user_url = format!("https://api.github.com/users/{}", handle);
        let mut req = client.get(&user_url).header("User-Agent", "Deus/1.0");

        if let Some(token) = &self.github_token {
            req = req.header("Authorization", format!("Bearer {}", token));
        }

        if let Ok(resp) = req.send().await {
            if resp.status().is_success() {
                if let Ok(user) = resp.json::<serde_json::Value>().await {
                    if let Some(tw) = user.get("twitter_username").and_then(|v| v.as_str()) {
                        if !tw.trim().is_empty() {
                            results.push(("twitter".to_string(), tw.to_string(), format!("https://x.com/{}", tw)));
                        }
                    }

                    if let Some(blog) = user.get("blog").and_then(|v| v.as_str()) {
                        let blog_trimmed = blog.trim();
                        if !blog_trimmed.is_empty() {
                            let blog_url = if blog_trimmed.starts_with("http://") || blog_trimmed.starts_with("https://") {
                                blog_trimmed.to_string()
                            } else {
                                format!("https://{}", blog_trimmed)
                            };
                            if let Some((plat, h)) = extract_handle(&blog_url) {
                                results.push((plat, h, blog_url));
                            }
                        }
                    }
                }
            }
        }

        let social_url = format!("https://api.github.com/users/{}/social_accounts", handle);
        let mut req_social = client.get(&social_url).header("User-Agent", "Deus/1.0");

        if let Some(token) = &self.github_token {
            req_social = req_social.header("Authorization", format!("Bearer {}", token));
        }

        if let Ok(resp) = req_social.send().await {
            if resp.status().is_success() {
                if let Ok(accounts) = resp.json::<Vec<serde_json::Value>>().await {
                    for acc in accounts {
                        if let Some(url_str) = acc.get("url").and_then(|v| v.as_str()) {
                            if let Some((plat, h)) = extract_handle(url_str) {
                                results.push((plat, h, url_str.to_string()));
                            }
                        }
                    }
                }
            }
        }

        results
    }

    async fn execute_job(&self, job: &InvestigationJobRecord) -> Result<(), String> {
        let search_run_id = job.search_run_id;
        info!("Executing investigation job for search_run_id: {}", search_run_id);

        self.repo
            .update_search_status(search_run_id, "DISCOVERING", None)
            .await
            .map_err(|e| e.to_string())?;

        let existing_profiles = self
            .repo
            .get_profiles(search_run_id)
            .await
            .unwrap_or_default();

        let mut created_profile_ids = HashSet::new();

        if existing_profiles.is_empty() {
            let seeds = self
                .repo
                .get_seeds(search_run_id)
                .await
                .map_err(|e| e.to_string())?;

            let connectors = build_all_connectors(self.github_token.clone());
            let pivot_email_localpart = std::env::var("EMAIL_LOCALPART_PIVOT")
                .map(|v| v.eq_ignore_ascii_case("true"))
                .unwrap_or(false);

            let parallelism: usize = std::env::var("CONNECTOR_PARALLELISM")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(10);

            for seed in seeds {
                let seed_type = seed.seed_type.to_uppercase();
                let seed_val = seed.original_value.unwrap_or_else(|| seed.normalized_value.clone().unwrap_or_default());
                if seed_val.trim().is_empty() {
                    continue;
                }

                if seed_type == "EMAIL" {
                    for conn in &connectors {
                        if !conn.healthcheck().supported_seeds.iter().any(|s| s.eq_ignore_ascii_case("email")) {
                            continue;
                        }

                        let conn_run = self
                            .repo
                            .create_connector_run(search_run_id, conn.name(), json!({"seed": seed_val}))
                            .await
                            .map_err(|e| e.to_string())?;

                        let output = conn.search_username(&seed_val).await;
                        let ids = self.persist_connector_output(search_run_id, conn_run.id, conn.name(), output, None).await?;
                        created_profile_ids.extend(ids);
                    }

                    if pivot_email_localpart {
                        if let Some(at_idx) = seed_val.find('@') {
                            let local_part = &seed_val[..at_idx];
                            if !local_part.is_empty() {
                                for conn in &connectors {
                                    if !conn.healthcheck().supported_seeds.iter().any(|s| s.eq_ignore_ascii_case("username")) {
                                        continue;
                                    }

                                    let conn_run = self
                                        .repo
                                        .create_connector_run(search_run_id, conn.name(), json!({"seed": local_part, "pivot_from": seed_val}))
                                        .await
                                        .map_err(|e| e.to_string())?;

                                    let output = conn.search_username(local_part).await;
                                    let note = format!("Derived weak lead from email local-part '{}'", local_part);
                                    let ids = self.persist_connector_output(search_run_id, conn_run.id, conn.name(), output, Some(&note)).await?;
                                    created_profile_ids.extend(ids);
                                }
                            }
                        }
                    }
                } else if seed_type == "NAME" {
                    for conn in &connectors {
                        if !conn.healthcheck().supported_seeds.iter().any(|s| s.eq_ignore_ascii_case("name")) {
                            continue;
                        }

                        let conn_run = self
                            .repo
                            .create_connector_run(search_run_id, conn.name(), json!({"seed": seed_val}))
                            .await
                            .map_err(|e| e.to_string())?;

                        let output = conn.search_username(&seed_val).await;
                        let ids = self.persist_connector_output(search_run_id, conn_run.id, conn.name(), output, Some("Discovered via name search")).await?;
                        created_profile_ids.extend(ids);
                    }
                } else if seed_type == "PHONE" {
                    for conn in &connectors {
                        if !conn.healthcheck().supported_seeds.iter().any(|s| s.eq_ignore_ascii_case("phone")) {
                            continue;
                        }

                        let conn_run = self
                            .repo
                            .create_connector_run(search_run_id, conn.name(), json!({"seed": seed_val}))
                            .await
                            .map_err(|e| e.to_string())?;

                        let output = conn.search_username(&seed_val).await;
                        let ids = self.persist_connector_output(search_run_id, conn_run.id, conn.name(), output, Some("Phone structural metadata")).await?;
                        created_profile_ids.extend(ids);
                    }
                } else {
                    // USERNAME or PROFILE_URL seed
                    let (platform, extracted_handle) = match extract_handle(&seed_val) {
                        Some((p, h)) => (p, h),
                        None => {
                            let err_msg = format!("Could not extract valid profile handle from seed '{}'", seed_val);
                            return Err(err_msg);
                        }
                    };

                    // Insert direct seed target profile if the seed was a full profile URL or explicit path
                    if seed_val.starts_with("http://") || seed_val.starts_with("https://") || seed_val.contains('/') {
                        let raw_canonical = if seed_val.starts_with("http://") || seed_val.starts_with("https://") {
                            seed_val.clone()
                        } else {
                            format!("https://{}", seed_val)
                        };
                        let canonical = normalize_canonical_url(&raw_canonical);

                        let db_p1 = self
                            .repo
                            .upsert_profile(
                                &platform,
                                Some(&extracted_handle),
                                Some(&extracted_handle.to_lowercase()),
                                None,
                                &canonical,
                                None,
                                Some("Direct seed target profile"),
                                None,
                                None,
                            )
                            .await
                            .map_err(|e| e.to_string())?;
                        created_profile_ids.insert(db_p1.id);
                    }

                    // For github.com URLs, fetch GitHub public API for linked profiles
                    if platform == "github" || seed_val.contains("github.com") {
                        let linked = self.fetch_github_profile_links(&extracted_handle).await;
                        for (l_plat, l_handle, l_url) in linked {
                            let norm_l_url = normalize_canonical_url(&l_url);
                            let l_db = self
                                .repo
                                .upsert_profile(
                                    &l_plat,
                                    Some(&l_handle),
                                    Some(&l_handle.to_lowercase()),
                                    None,
                                    &norm_l_url,
                                    None,
                                    Some("Linked from profile"),
                                    None,
                                    None,
                                )
                                .await;
                            if let Ok(prof) = l_db {
                                created_profile_ids.insert(prof.id);
                            }
                        }
                    }

                    let connectors = build_all_connectors(self.github_token.clone());
                    let mut futures = Vec::new();

                    for conn in connectors {
                        let repo = self.repo.clone();
                        let handle = extracted_handle.clone();
                        futures.push(async move {
                            let conn_name = conn.name();
                            let conn_run_res = repo
                                .create_connector_run(search_run_id, conn_name, json!({"seed": handle}))
                                .await;
                            let output = conn.search_username(&handle).await;
                            (conn_name, conn_run_res, output)
                        });
                    }

                    let mut stream = stream::iter(futures).buffer_unordered(parallelism);

                    while let Some((conn_name, conn_run_res, output)) = stream.next().await {
                        if let Ok(conn_run) = conn_run_res {
                            if let Ok(ids) = self.persist_connector_output(search_run_id, conn_run.id, conn_name, output, None).await {
                                created_profile_ids.extend(ids);
                            }
                        }
                    }
                }
            }
        }

        let all_profiles = self
            .repo
            .get_profiles(search_run_id)
            .await
            .unwrap_or_default();

        let final_status = "COMPLETED";
        let conn_runs = self.repo.get_connector_runs(search_run_id).await.unwrap_or_default();
        let first_url = all_profiles.first().map(|p| p.canonical_url.clone()).unwrap_or_default();

        let executive_finding = format!(
            "Executive OSINT Identity Report: {} candidate profiles found across {} connectors.",
            all_profiles.len(),
            conn_runs.len()
        );

        let lead_candidates: Vec<serde_json::Value> = all_profiles.iter().map(|p| {
            json!({
                "platform": p.platform,
                "username": p.normalized_username.as_deref().unwrap_or(p.username.as_deref().unwrap_or("")),
                "display_name": p.display_name.as_deref().unwrap_or(""),
                "canonical_url": p.canonical_url,
                "reason": format!("Candidate profile discovered on {}", p.platform)
            })
        }).collect();

        let repository_references: Vec<serde_json::Value> = all_profiles.iter().filter(|p| {
            matches!(p.platform.to_lowercase().as_str(), "github" | "gitlab" | "pypi" | "crates_io" | "npm" | "dockerhub")
        }).map(|p| {
            json!({
                "url": p.canonical_url,
                "source_url": p.canonical_url
            })
        }).collect();

        let supporting_evidence: Vec<serde_json::Value> = Vec::new();

        let source_provenance: Vec<serde_json::Value> = conn_runs.iter().map(|r| {
            json!({
                "connector": r.connector,
                "source_url": first_url.clone()
            })
        }).collect();

        let report_id = Uuid::new_v4();
        let report_json = json!({
            "executive_finding": executive_finding,
            "lead_candidates": lead_candidates,
            "repository_references": repository_references,
            "supporting_evidence": supporting_evidence,
            "moderate_evidence": Vec::<serde_json::Value>::new(),
            "source_provenance": source_provenance,
            "search_run_id": search_run_id,
            "profiles_found": all_profiles.len(),
            "status": final_status,
            "engine": "Deus Rust Backend (raven-osint + adler-core)",
        });

        let rep_res = sqlx::query(
            "INSERT INTO reports (id, search_run_id, report_data, generated_at) VALUES ($1, $2, $3, NOW())"
        )
        .bind(report_id)
        .bind(search_run_id)
        .bind(report_json)
        .execute(&self.repo.pool)
        .await;

        if let Err(e) = rep_res {
            error!("Failed to insert report: {}", e);
        }

        self.repo
            .update_search_status(search_run_id, final_status, None)
            .await
            .map_err(|e| e.to_string())?;

        let job_res = sqlx::query("UPDATE investigation_jobs SET status = 'COMPLETED', updated_at = NOW() WHERE id = $1")
            .bind(job.id)
            .execute(&self.repo.pool)
            .await;

        if let Err(e) = job_res {
            error!("Failed to update investigation_job status: {}", e);
        }

        Ok(())
    }
}
