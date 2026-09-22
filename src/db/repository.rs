use crate::db::models::*;
use chrono::Utc;
use serde_json::Value as JsonValue;
use sqlx::PgPool;
use uuid::Uuid;

#[derive(Clone)]
pub struct Repository {
    pub pool: PgPool,
}

impl Repository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn create_search_run(
        &self,
        scope: &str,
        max_pivot_depth: i32,
        max_questions: i32,
        max_connector_runs: i32,
        max_candidates: i32,
        max_search_duration_seconds: i32,
    ) -> Result<SearchRun, sqlx::Error> {
        let id = Uuid::new_v4();
        let now = Utc::now();
        let record = sqlx::query_as::<_, SearchRun>(
            r#"
            INSERT INTO search_runs (
                id, status, scope, created_at, pivot_depth, questions_asked, connector_runs_count,
                max_pivot_depth, max_questions, max_connector_runs, max_candidates, max_search_duration_seconds
            )
            VALUES ($1, 'CREATED', $2, $3, 0, 0, 0, $4, $5, $6, $7, $8)
            RETURNING *
            "#,
        )
        .bind(id)
        .bind(scope)
        .bind(now)
        .bind(max_pivot_depth)
        .bind(max_questions)
        .bind(max_connector_runs)
        .bind(max_candidates)
        .bind(max_search_duration_seconds)
        .fetch_one(&self.pool)
        .await?;

        Ok(record)
    }

    pub async fn add_seed(
        &self,
        search_run_id: Uuid,
        seed_type: &str,
        original_value: &str,
        normalized_value: &str,
        artifact_id: Option<Uuid>,
    ) -> Result<SearchSeed, sqlx::Error> {
        let id = Uuid::new_v4();
        let now = Utc::now();
        let record = sqlx::query_as::<_, SearchSeed>(
            r#"
            INSERT INTO search_seeds (id, search_run_id, seed_type, original_value, normalized_value, artifact_id, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING *
            "#,
        )
        .bind(id)
        .bind(search_run_id)
        .bind(seed_type)
        .bind(original_value)
        .bind(normalized_value)
        .bind(artifact_id)
        .bind(now)
        .fetch_one(&self.pool)
        .await?;

        Ok(record)
    }

    pub async fn create_investigation_job(
        &self,
        search_run_id: Uuid,
        payload: JsonValue,
    ) -> Result<InvestigationJobRecord, sqlx::Error> {
        let id = Uuid::new_v4();
        let now = Utc::now();
        let record = sqlx::query_as::<_, InvestigationJobRecord>(
            r#"
            INSERT INTO investigation_jobs (id, search_run_id, job_type, payload, status, attempt_count, available_at, created_at, updated_at, runtime_seconds)
            VALUES ($1, $2, 'INVESTIGATE', $3, 'PENDING', 0, $4, $4, $4, 0.0)
            RETURNING *
            "#,
        )
        .bind(id)
        .bind(search_run_id)
        .bind(payload)
        .bind(now)
        .fetch_one(&self.pool)
        .await?;

        Ok(record)
    }

    pub async fn get_search_run(&self, id: Uuid) -> Result<Option<SearchRun>, sqlx::Error> {
        sqlx::query_as::<_, SearchRun>("SELECT * FROM search_runs WHERE id = $1")
            .bind(id)
            .fetch_optional(&self.pool)
            .await
    }

    pub async fn get_seeds(&self, search_run_id: Uuid) -> Result<Vec<SearchSeed>, sqlx::Error> {
        sqlx::query_as::<_, SearchSeed>("SELECT * FROM search_seeds WHERE search_run_id = $1 ORDER BY created_at ASC")
            .bind(search_run_id)
            .fetch_all(&self.pool)
            .await
    }

    pub async fn get_profiles(&self, search_run_id: Uuid) -> Result<Vec<ProfileRecord>, sqlx::Error> {
        sqlx::query_as::<_, ProfileRecord>(
            r#"
            SELECT DISTINCT p.* FROM profiles p
            JOIN profile_observations o ON p.id = o.profile_id
            WHERE o.search_run_id = $1
            ORDER BY p.first_seen_at ASC
            "#
        )
        .bind(search_run_id)
        .fetch_all(&self.pool)
        .await
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn upsert_profile(
        &self,
        platform: &str,
        username: Option<&str>,
        normalized_username: Option<&str>,
        display_name: Option<&str>,
        canonical_url: &str,
        avatar_url: Option<&str>,
        current_bio: Option<&str>,
        current_location: Option<&str>,
        current_organization: Option<&str>,
    ) -> Result<ProfileRecord, sqlx::Error> {
        let norm_platform = platform.trim().to_lowercase();
        let norm_url = {
            let mut s = canonical_url.trim().to_string();
            if s.starts_with("http://") {
                s = format!("https://{}", &s[7..]);
            }
            if s.ends_with('/') && s.len() > 8 {
                s.pop();
            }
            s
        };

        let id = Uuid::new_v4();
        let now = Utc::now();
        let record = sqlx::query_as::<_, ProfileRecord>(
            r#"
            INSERT INTO profiles (
                id, platform, username, normalized_username, display_name, canonical_url,
                avatar_url, current_bio, current_location, current_organization,
                first_seen_at, last_seen_at, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $11, $11)
            ON CONFLICT (platform, canonical_url) DO UPDATE SET
                display_name = COALESCE(EXCLUDED.display_name, profiles.display_name),
                avatar_url = COALESCE(EXCLUDED.avatar_url, profiles.avatar_url),
                current_bio = COALESCE(EXCLUDED.current_bio, profiles.current_bio),
                current_location = COALESCE(EXCLUDED.current_location, profiles.current_location),
                current_organization = COALESCE(EXCLUDED.current_organization, profiles.current_organization),
                last_seen_at = EXCLUDED.last_seen_at
            RETURNING *
            "#,
        )
        .bind(id)
        .bind(&norm_platform)
        .bind(username)
        .bind(normalized_username)
        .bind(display_name)
        .bind(&norm_url)
        .bind(avatar_url)
        .bind(current_bio)
        .bind(current_location)
        .bind(current_organization)
        .bind(now)
        .fetch_one(&self.pool)
        .await?;

        Ok(record)
    }

    pub async fn create_connector_run(
        &self,
        search_run_id: Uuid,
        connector: &str,
        input_data: JsonValue,
    ) -> Result<ConnectorRunRecord, sqlx::Error> {
        let id = Uuid::new_v4();
        let now = Utc::now();
        let record = sqlx::query_as::<_, ConnectorRunRecord>(
            r#"
            INSERT INTO connector_runs (id, search_run_id, connector, status, started_at, request_count, input_data, metadata)
            VALUES ($1, $2, $3, $4, $5, 1, $6, '{}')
            RETURNING *
            "#,
        )
        .bind(id)
        .bind(search_run_id)
        .bind(connector)
        .bind(ConnectorStatus::Running.as_str())
        .bind(now)
        .bind(input_data)
        .fetch_one(&self.pool)
        .await?;

        Ok(record)
    }

    pub async fn complete_connector_run(
        &self,
        id: Uuid,
        status: ConnectorStatus,
        error: Option<&str>,
    ) -> Result<(), sqlx::Error> {
        let now = Utc::now();
        sqlx::query(
            r#"
            UPDATE connector_runs
            SET status = $1, completed_at = $2, error = $3
            WHERE id = $4
            "#
        )
        .bind(status.as_str())
        .bind(now)
        .bind(error)
        .bind(id)
        .execute(&self.pool)
        .await?;

        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn add_observation(
        &self,
        search_run_id: Uuid,
        profile_id: Uuid,
        connector_run_id: Uuid,
        connector: &str,
        source_url: Option<&str>,
        normalized_data: JsonValue,
        raw_data: JsonValue,
    ) -> Result<ProfileObservationRecord, sqlx::Error> {
        let id = Uuid::new_v4();
        let now = Utc::now();
        let record = sqlx::query_as::<_, ProfileObservationRecord>(
            r#"
            INSERT INTO profile_observations (
                id, search_run_id, profile_id, connector_run_id, connector, source_url, observed_at, normalized_data, raw_data
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING *
            "#,
        )
        .bind(id)
        .bind(search_run_id)
        .bind(profile_id)
        .bind(connector_run_id)
        .bind(connector)
        .bind(source_url)
        .bind(now)
        .bind(normalized_data)
        .bind(raw_data)
        .fetch_one(&self.pool)
        .await?;

        Ok(record)
    }

    pub async fn get_hypotheses(&self, search_run_id: Uuid) -> Result<Vec<IdentityHypothesisRecord>, sqlx::Error> {
        sqlx::query_as::<_, IdentityHypothesisRecord>(
            "SELECT * FROM identity_hypotheses WHERE search_run_id = $1 ORDER BY rank ASC"
        )
        .bind(search_run_id)
        .fetch_all(&self.pool)
        .await
    }

    pub async fn get_memberships(&self, hypothesis_id: Uuid) -> Result<Vec<HypothesisMembershipRecord>, sqlx::Error> {
        sqlx::query_as::<_, HypothesisMembershipRecord>(
            "SELECT * FROM hypothesis_memberships WHERE hypothesis_id = $1"
        )
        .bind(hypothesis_id)
        .fetch_all(&self.pool)
        .await
    }

    pub async fn get_evidence(&self, search_run_id: Uuid) -> Result<Vec<EvidenceSignalRecord>, sqlx::Error> {
        sqlx::query_as::<_, EvidenceSignalRecord>(
            "SELECT * FROM evidence_signals WHERE search_run_id = $1 ORDER BY created_at ASC"
        )
        .bind(search_run_id)
        .fetch_all(&self.pool)
        .await
    }

    pub async fn get_pending_question(&self, search_run_id: Uuid) -> Result<Option<InvestigationQuestionRecord>, sqlx::Error> {
        sqlx::query_as::<_, InvestigationQuestionRecord>(
            "SELECT * FROM investigation_questions WHERE search_run_id = $1 AND status = 'PENDING' ORDER BY created_at DESC LIMIT 1"
        )
        .bind(search_run_id)
        .fetch_optional(&self.pool)
        .await
    }

    pub async fn get_reports(&self, search_run_id: Uuid) -> Result<Vec<ReportRecord>, sqlx::Error> {
        sqlx::query_as::<_, ReportRecord>(
            "SELECT * FROM reports WHERE search_run_id = $1 ORDER BY generated_at DESC"
        )
        .bind(search_run_id)
        .fetch_all(&self.pool)
        .await
    }

    pub async fn get_connector_runs(&self, search_run_id: Uuid) -> Result<Vec<ConnectorRunRecord>, sqlx::Error> {
        sqlx::query_as::<_, ConnectorRunRecord>(
            "SELECT * FROM connector_runs WHERE search_run_id = $1 ORDER BY started_at ASC"
        )
        .bind(search_run_id)
        .fetch_all(&self.pool)
        .await
    }

    pub async fn get_observations(&self, search_run_id: Uuid) -> Result<Vec<ProfileObservationRecord>, sqlx::Error> {
        sqlx::query_as::<_, ProfileObservationRecord>(
            "SELECT * FROM profile_observations WHERE search_run_id = $1 ORDER BY observed_at ASC"
        )
        .bind(search_run_id)
        .fetch_all(&self.pool)
        .await
    }


    pub async fn update_search_status(&self, id: Uuid, status: &str, error_summary: Option<&str>) -> Result<(), sqlx::Error> {
        let now = Utc::now();
        sqlx::query(
            r#"
            UPDATE search_runs
            SET status = $1, error_summary = COALESCE($2, error_summary), completed_at = CASE WHEN $1 IN ('COMPLETED', 'FAILED', 'STOPPED') THEN $3 ELSE completed_at END
            WHERE id = $4
            "#
        )
        .bind(status)
        .bind(error_summary)
        .bind(now)
        .bind(id)
        .execute(&self.pool)
        .await?;

        Ok(())
    }
}
