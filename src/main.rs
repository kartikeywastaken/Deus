use deus::api;
use deus::config::Config;
use deus::db;
use deus::db::repository::Repository;
use deus::worker::jobs::Worker;
use std::net::SocketAddr;
use std::sync::Arc;
use tracing::info;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .init();

    let cfg = Config::from_env();
    info!("Starting Deus Rust Backend server on port {}", cfg.api_port);

    let pool = db::init_db(&cfg.database_url).await?;
    let repo = Repository::new(pool);

    // Spawn background worker loop
    let worker = Arc::new(Worker::new(repo.clone(), cfg.github_token.clone()));
    tokio::spawn(async move {
        worker.run_loop().await;
    });

    let app = api::build_router(repo);
    let mut port = cfg.api_port;
    let mut addr = SocketAddr::from(([0, 0, 0, 0], port));

    let listener = match tokio::net::TcpListener::bind(&addr).await {
        Ok(l) => l,
        Err(e) if e.kind() == std::io::ErrorKind::AddrInUse => {
            port += 1;
            addr = SocketAddr::from(([0, 0, 0, 0], port));
            tracing::warn!("Port {} was in use (AddrInUse); bound to fallback port http://{}", cfg.api_port, addr);
            tokio::net::TcpListener::bind(&addr).await?
        }
        Err(e) => return Err(e.into()),
    };

    info!("Deus Rust API listening on http://{}", addr);
    axum::serve(listener, app).await?;

    Ok(())
}
