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
        tracing::info!("Connecting to PostgreSQL database at {}:{}{}...", host, port, path);
        if host == "localhost" || host == "127.0.0.1" {
            tracing::warn!("DATABASE_URL host is '{}'. On Render or cloud platforms, ensure you set the DATABASE_URL environment variable in your dashboard to your managed database connection string.", host);
        }
    }

    let mut attempts = 0;
    let max_attempts = 10;
    loop {
        attempts += 1;
        match PgPoolOptions::new()
            .max_connections(50)
            .min_connections(2)
            .acquire_timeout(Duration::from_secs(30))
            .idle_timeout(Duration::from_secs(600))
            .max_lifetime(Duration::from_secs(1800))
            .connect(database_url)
            .await
        {
            Ok(pool) => {
                tracing::info!("Successfully connected to PostgreSQL database.");
                return Ok(pool);
            }
            Err(e) if attempts < max_attempts => {
                tracing::warn!(
                    "Database connection attempt {}/{} failed ({}); retrying in 3 seconds...",
                    attempts,
                    max_attempts,
                    e
                );
                tokio::time::sleep(Duration::from_secs(3)).await;
            }
            Err(e) => {
                tracing::error!(
                    "Failed to connect to database after {} attempts: {}",
                    attempts,
                    e
                );
                return Err(e);
            }
        }
    }
}
