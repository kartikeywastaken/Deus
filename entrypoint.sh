#!/usr/bin/env bash
set -e

echo "==> Running Alembic Database Migrations..."
if [ -n "$DATABASE_URL" ]; then
    success=0
    for i in 1 2 3 4 5; do
        echo "Attempt $i: running alembic upgrade head..."
        if python3 -m alembic upgrade head; then
            success=1
            echo "==> Database migrations completed successfully."
            break
        else
            echo "Migration attempt $i failed, waiting 5 seconds..."
            sleep 5
        fi
    done
    if [ $success -ne 1 ]; then
        echo "==> WARNING: Migrations did not complete successfully after retries."
    fi
else
    echo "==> WARNING: DATABASE_URL is not set. Skipping migrations."
fi

echo "==> Starting Deus Rust Backend..."
exec ./deus
