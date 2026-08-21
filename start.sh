#!/bin/bash
set -e

echo "=== NACELUX Rev. 2.1 — Production Startup ==="
echo "Date: $(date -u '+%Y-%m-%d %H:%M:%SZ')"
echo "Environment: ${NACELUX_ENV:-production}"
echo "Process Type: ${PROCESS_TYPE:-web}"

# 1. Automatic PostgreSQL / Supabase Migrations
if [ -n "$DATABASE_URL" ]; then
    echo "PostgreSQL DATABASE_URL detected."
    if [ "${AUTO_MIGRATE:-true}" = "true" ] || [ "${AUTO_MIGRATE:-true}" = "1" ]; then
        echo "Running idempotent database migrations..."
        python3 scripts/supabase_db.py migrate || {
            echo "WARNING: Automatic migration returned non-zero. Continuing with startup..."
        }
    fi
    if [ "${MIGRATE_SQLITE_DATA:-false}" = "true" ] || [ "${MIGRATE_SQLITE_DATA:-false}" = "1" ]; then
        echo "Copying baseline SQLite data..."
        python3 scripts/supabase_db.py copy-sqlite || true
    fi
fi

# 2. Dispatch based on PROCESS_TYPE
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
