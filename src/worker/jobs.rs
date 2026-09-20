use crate::connectors::build_all_connectors;
use crate::correlation::akinator::select_best_question;
use crate::correlation::clustering::build_hypotheses;
use crate::correlation::features::{Direction, EvidenceFamily, EvidenceSignal, SignalType};
use crate::correlation::scorer::score_evidence;
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

            for seed in seeds {
                let seed_val = seed.normalized_value.unwrap_or_default();
                if seed_val.is_empty() {
                    continue;
                }

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

        let all_profiles = self
            .repo
            .get_profiles(search_run_id)
            .await
            .map_err(|e| e.to_string())?;

        let profile_ids: Vec<Uuid> = all_profiles.iter().map(|p| p.id).collect();
        let mut pairwise_scores = Vec::new();
        let mut all_signals = Vec::new();

        // Performance guard: if profile count is large (> 60), perform fast exact matching only
        let max_pairwise = 60;
        let compare_limit = all_profiles.len().min(max_pairwise);

        for i in 0..compare_limit {
            for j in (i + 1)..compare_limit {
                let p1 = &all_profiles[i];
                let p2 = &all_profiles[j];

                let mut signals = Vec::new();

                if let (Some(u1), Some(u2)) = (&p1.normalized_username, &p2.normalized_username) {
                    if u1 == u2 {
                        signals.push(EvidenceSignal {
                            signal_type: SignalType::UsernameExact,
                            evidence_family: EvidenceFamily::Username,
                            direction: Direction::Support,
                            normalized_score: 1.0,
                            reliability: 1.0,
                            explanation: format!("Exact matching username '{}'", u1),
                        });
                    } else if compare_limit <= 30 {
                        let sim = strsim::jaro_winkler(u1, u2);
                        if sim >= 0.85 {
                            signals.push(EvidenceSignal {
                                signal_type: SignalType::UsernameSimilarity,
                                evidence_family: EvidenceFamily::Username,
                                direction: Direction::Support,
                                normalized_score: sim,
                                reliability: 0.8,
                                explanation: format!("High username Jaro-Winkler similarity: {:.2}", sim),
                            });
                        }
                    }
                }

                let assessment = score_evidence(&signals);
                pairwise_scores.push((p1.id, p2.id, assessment.raw_score, assessment.classification));
                all_signals.extend(signals);
            }
        }

        let clusters = build_hypotheses(&profile_ids, &pairwise_scores);

        for cluster in &clusters {
            let hyp_id = Uuid::new_v4();
            let hyp_res = sqlx::query(
                r#"
                INSERT INTO identity_hypotheses (id, search_run_id, rank, overall_score, classification, status, model_version, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, 'ACTIVE', 'deterministic-v0.1-rust', NOW(), NOW())
                ON CONFLICT (search_run_id, rank) DO UPDATE SET
                    overall_score = EXCLUDED.overall_score,
                    classification = EXCLUDED.classification,
                    updated_at = NOW()
                "#
            )
            .bind(hyp_id)
            .bind(search_run_id)
            .bind(cluster.rank)
            .bind(cluster.overall_score)
            .bind(format!("{:?}", cluster.classification).to_uppercase())
            .execute(&self.repo.pool)
            .await;

            if let Err(e) = hyp_res {
                error!("Failed to insert identity_hypothesis: {}", e);
            }

            for pid in &cluster.profile_ids {
                let mem_id = Uuid::new_v4();
                let mem_res = sqlx::query(
                    r#"
                    INSERT INTO hypothesis_memberships (id, hypothesis_id, profile_id, score, classification, support_count, contradiction_count, computed_at, model_version)
                    VALUES ($1, $2, $3, $4, $5, 1, 0, NOW(), 'deterministic-v0.1-rust')
                    ON CONFLICT (hypothesis_id, profile_id) DO NOTHING
                    "#
                )
                .bind(mem_id)
                .bind(hyp_id)
                .bind(pid)
                .bind(cluster.overall_score)
                .bind(format!("{:?}", cluster.classification).to_uppercase())
                .execute(&self.repo.pool)
                .await;

                if let Err(e) = mem_res {
                    error!("Failed to insert hypothesis_membership: {}", e);
                }
            }
        }

        let top_score = clusters.first().map(|c| c.overall_score).unwrap_or(0.0);
        let action = job.payload.get("action").and_then(|v| v.as_str()).unwrap_or("start");

        let mut has_pending_question = false;
        if action == "start" {
            if let Some(question) = select_best_question(&profile_ids, top_score) {
                let q_id = Uuid::new_v4();
                let q_res = sqlx::query(
                    r#"
                    INSERT INTO investigation_questions (
                        id, search_run_id, question_type, question_text, options, context, reason,
                        affected_profile_ids, affected_hypothesis_ids, expected_information_gain, sensitivity_level, status, created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, '{}', $6, $7, '{}', $8, $9, 'PENDING', NOW())
                    "#
                )
                .bind(q_id)
                .bind(search_run_id)
                .bind(format!("{:?}", question.question_type).to_uppercase())
                .bind(&question.question_text)
                .bind(&question.options)
                .bind(&question.reason)
                .bind(&question.affected_profile_ids)
                .bind(question.expected_information_gain)
                .bind(format!("{:?}", question.sensitivity_level).to_uppercase())
                .execute(&self.repo.pool)
                .await;

                if let Err(e) = q_res {
                    error!("Failed to insert investigation_question: {}", e);
                } else {
                    has_pending_question = true;
                }
            }
        }

        let final_status = if has_pending_question { "AWAITING_USER" } else { "COMPLETED" };
        let conn_runs = self.repo.get_connector_runs(search_run_id).await.unwrap_or_default();
        let first_url = all_profiles.first().map(|p| p.canonical_url.clone()).unwrap_or_default();
        let top_classif = clusters.first().map(|c| c.classification).unwrap_or(crate::db::models::Classification::Ambiguous);

        let executive_finding = format!(
            "{} candidate profiles found across {} connectors; top hypothesis classified as {:?} with a {:.1} match confidence.",
            all_profiles.len(),
            conn_runs.len(),
            top_classif,
            top_score
        );

        let lead_candidates: Vec<serde_json::Value> = all_profiles.iter().map(|p| {
            json!({
                "platform": p.platform,
                "username": p.normalized_username.as_deref().unwrap_or(p.username.as_deref().unwrap_or("")),
                "display_name": p.display_name.as_deref().unwrap_or(""),
                "canonical_url": p.canonical_url,
                "reason": format!("Matched via {:?} evidence cluster", top_classif)
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

        let supporting_evidence: Vec<serde_json::Value> = all_signals.iter().filter(|s| s.direction == Direction::Support).map(|s| {
            json!({
                "explanation": s.explanation,
                "source_urls": Vec::<String>::new()
            })
        }).collect();

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
            "hypotheses": clusters.len(),
            "top_score": top_score,
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
