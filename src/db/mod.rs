pub mod models;
pub mod repository;

use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use std::time::Duration;

pub async fn init_db(database_url: &str) -> Result<PgPool, sqlx::Error> {
    if let Ok(parsed) = url::Url::parse(database_url) {
        let host = parsed.host_str().unwrap_or("unknown");
        let port = parsed.port().unwrap_or(5432);
        let path = parsed.path();
        tracing::info!("Configuring PostgreSQL pool for {}:{}{}...", host, port, path);
        if host == "localhost" || host == "127.0.0.1" {
            tracing::warn!("DATABASE_URL host is '{}'. In cloud environments, set the DATABASE_URL environment variable to your remote database.", host);
        }
    }

    let pool = PgPoolOptions::new()
        .max_connections(50)
        .min_connections(1)
        .acquire_timeout(Duration::from_secs(30))
        .idle_timeout(Duration::from_secs(600))
        .max_lifetime(Duration::from_secs(1800))
        .connect_lazy(database_url)?;

    Ok(pool)
}
