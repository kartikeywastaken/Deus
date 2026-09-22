#!/usr/bin/env bash
set -e

echo "==> Running Alembic Database Migrations..."
if [ -n "$DATABASE_URL" ]; then
    python3 -m alembic upgrade head || {
        echo "Alembic migration failed, retrying in 3 seconds..."
        sleep 3
        python3 -m alembic upgrade head
    }
    echo "==> Database migrations completed successfully."
else
    echo "==> WARNING: DATABASE_URL is not set. Skipping migrations."
fi

echo "==> Starting Deus Rust Backend..."
exec ./deus
