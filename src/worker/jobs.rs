use crate::connectors::build_all_connectors;
use crate::db::models::InvestigationJobRecord;
use crate::db::repository::Repository;
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

            for seed in seeds {
                let seed_type = seed.seed_type.to_uppercase();
                let seed_val = seed.normalized_value.unwrap_or_default();
                if seed_val.is_empty() {
                    continue;
                }

                if seed_type == "EMAIL" {
                    // For EMAIL seeds, run only connectors whose supported_seeds contains "email"
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

                        for prof in output.profiles {
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

                            created_profile_ids.insert(db_prof.id);

                            self.repo
                                .add_observation(
                                    search_run_id,
                                    db_prof.id,
                                    conn_run.id,
                                    conn.name(),
                                    Some(&prof.canonical_url),
                                    json!({"platform": prof.platform, "username": prof.username}),
                                    prof.raw_json,
                                )
                                .await
                                .map_err(|e| e.to_string())?;
                        }

                        self.repo
                            .complete_connector_run(conn_run.id, output.status, output.error.as_deref())
                            .await
                            .map_err(|e| e.to_string())?;
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

                                    for mut prof in output.profiles {
                                        prof.bio = Some(format!("[Derived weak lead from email local-part '{}'] {}", local_part, prof.bio.unwrap_or_default()));
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

                                        created_profile_ids.insert(db_prof.id);

                                        self.repo
                                            .add_observation(
                                                search_run_id,
                                                db_prof.id,
                                                conn_run.id,
                                                conn.name(),
                                                Some(&prof.canonical_url),
                                                json!({"platform": prof.platform, "username": prof.username, "derived_lead": true}),
                                                prof.raw_json,
                                            )
                                            .await
                                            .map_err(|e| e.to_string())?;
                                    }

                                    self.repo
                                        .complete_connector_run(conn_run.id, output.status, output.error.as_deref())
                                        .await
                                        .map_err(|e| e.to_string())?;
                                }
                            }
                        }
                    }
                } else {
                    for conn in &connectors {
                        let conn_run = self
                            .repo
                            .create_connector_run(search_run_id, conn.name(), json!({"seed": seed_val}))
                            .await
                            .map_err(|e| e.to_string())?;

                        let output = conn.search_username(&seed_val).await;

                        for prof in output.profiles {
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

                            created_profile_ids.insert(db_prof.id);

                            self.repo
                                .add_observation(
                                    search_run_id,
                                    db_prof.id,
                                    conn_run.id,
                                    conn.name(),
                                    Some(&prof.canonical_url),
                                    json!({"platform": prof.platform, "username": prof.username}),
                                    prof.raw_json,
                                )
                                .await
                                .map_err(|e| e.to_string())?;
                        }

                        self.repo
                            .complete_connector_run(conn_run.id, output.status, output.error.as_deref())
                            .await
                            .map_err(|e| e.to_string())?;
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
