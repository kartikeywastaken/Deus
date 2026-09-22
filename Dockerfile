# Multi-stage Dockerfile for Deus Rust Backend + Alembic Migrations

# ------------------------------------------------------------------------------
# Stage 1: Build Rust binary
# ------------------------------------------------------------------------------
FROM rust:bookworm AS builder

WORKDIR /usr/src/deus

# Pre-copy dependency files and site data for compile-time include_str!
COPY Cargo.toml Cargo.lock ./
COPY data ./data
COPY src ./src

# Build release binary
RUN cargo build --release

# ------------------------------------------------------------------------------
# Stage 2: Runtime image with Python + Alembic
# ------------------------------------------------------------------------------
FROM debian:bookworm-slim AS runner

# Install runtime packages: SSL, CA certificates, Python 3
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libssl3 \
    openssl \
    curl \
    python3 \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Set up Python virtual environment for Alembic migrations
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install migration dependencies
RUN pip install --no-cache-dir alembic sqlalchemy asyncpg pgvector

WORKDIR /app

# Copy compiled Rust executable from builder
COPY --from=builder /usr/src/deus/target/release/deus ./deus

# Copy migration files, configuration, data files, frontend, and entrypoint
COPY alembic.ini ./
COPY migrations ./migrations
COPY data ./data
COPY frontend ./frontend
COPY entrypoint.sh ./

RUN chmod +x ./entrypoint.sh ./deus

EXPOSE 8765

ENTRYPOINT ["./entrypoint.sh"]
