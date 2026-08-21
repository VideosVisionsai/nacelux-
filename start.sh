#!/bin/bash
set -euo pipefail

echo "=== NACELUX Rev. 2.1 — Production Startup ==="
echo "Date: $(date -u '+%Y-%m-%d %H:%M:%SZ')"
echo "Environment: ${NACELUX_ENV:-production}"
echo "Process Type: ${PROCESS_TYPE:-web}"

# Production never falls back to SQLite. DATABASE_URL is mandatory.
if [ -z "${DATABASE_URL:-}" ]; then
    echo "ERROR: DATABASE_URL is not set. Silent SQLite fallback is forbidden in production."
    echo "Set DATABASE_URL to a PostgreSQL/Supabase connection string and DB_PROVIDER=postgresql."
    exit 1
fi

if [ "${DB_PROVIDER:-postgresql}" != "postgresql" ] && [ "${DB_PROVIDER:-}" != "postgres" ] && [ "${DB_PROVIDER:-}" != "supabase" ]; then
    echo "ERROR: DB_PROVIDER=${DB_PROVIDER} is not PostgreSQL. SQLite fallback is forbidden."
    exit 1
fi

echo "PostgreSQL DATABASE_URL detected (provider=${DB_PROVIDER:-postgresql})."

if [ "${AUTO_MIGRATE:-true}" = "true" ] || [ "${AUTO_MIGRATE:-true}" = "1" ]; then
    echo "Running idempotent database migrations..."
    if ! python3 scripts/supabase_db.py migrate; then
        echo "ERROR: Database migration failed. Refusing to start. No SQLite fallback."
        exit 1
    fi
    echo "Migrations completed successfully."
else
    echo "AUTO_MIGRATE is disabled; skipping schema migrations."
fi

if [ "${MIGRATE_SQLITE_DATA:-false}" = "true" ] || [ "${MIGRATE_SQLITE_DATA:-false}" = "1" ]; then
    echo "Copying baseline SQLite data into PostgreSQL..."
    if ! python3 scripts/supabase_db.py copy-sqlite; then
        echo "ERROR: SQLite copy into PostgreSQL failed. Refusing to start."
        exit 1
    fi
fi

case "${PROCESS_TYPE:-web}" in
    worker)
        echo "Starting NACELUX background worker..."
        exec python3 backend/worker.py
        ;;
    all|both|full)
        echo "Starting background worker in sub-process..."
        python3 backend/worker.py &
        WORKER_PID=$!
        trap "kill $WORKER_PID 2>/dev/null || true" EXIT
        echo "Starting HTTP Web API on port ${PORT:-8000}..."
        exec python3 backend/app.py
        ;;
    web|*)
        echo "Starting HTTP Web API on port ${PORT:-8000}..."
        exec python3 backend/app.py
        ;;
esac
