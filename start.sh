#!/bin/bash
set -euo pipefail

ENVIRONMENT="${NACELUX_ENV:-production}"
PROCESS="${PROCESS_TYPE:-web}"
WEB_PID=""
WORKER_PID=""

echo "=== NACELUX Rev. 2.1 — Startup ==="
echo "Date: $(date -u '+%Y-%m-%d %H:%M:%SZ')"
echo "Environment: ${ENVIRONMENT}"
echo "Process Type: ${PROCESS}"

if [ "${ENVIRONMENT}" = "production" ] || [ "${ENVIRONMENT}" = "prod" ]; then
    # Production is fail-closed. No alias, demo seed or SQLite path is accepted.
    if [ "${DB_PROVIDER:-}" != "postgresql" ]; then
        echo "ERROR: DB_PROVIDER=postgresql is mandatory in production. SQLite fallback is forbidden."
        exit 1
    fi
    if [ -z "${DATABASE_URL:-}" ]; then
        echo "ERROR: DATABASE_URL is mandatory in production."
        exit 1
    fi
    if [ -z "${MIGRATION_DATABASE_URL:-}" ]; then
        echo "ERROR: MIGRATION_DATABASE_URL is mandatory for privileged migrations in production."
        exit 1
    fi
    if [ "${MIGRATION_DATABASE_URL}" = "${DATABASE_URL}" ]; then
        echo "ERROR: MIGRATION_DATABASE_URL must be separate from the non-owner runtime DATABASE_URL."
        exit 1
    fi
    if [ -z "${DB_RUNTIME_ROLE:-}" ]; then
        echo "ERROR: DB_RUNTIME_ROLE is mandatory for RLS runtime validation."
        exit 1
    fi
    if [ "${DB_SSLMODE:-}" != "require" ]; then
        echo "ERROR: DB_SSLMODE=require is mandatory in production."
        exit 1
    fi
    if [ "${AUTO_MIGRATE:-}" != "true" ] && [ "${AUTO_MIGRATE:-}" != "1" ]; then
        echo "ERROR: AUTO_MIGRATE=true is mandatory in production."
        exit 1
    fi
    if [ "${MIGRATE_SQLITE_DATA:-false}" = "true" ] || [ "${MIGRATE_SQLITE_DATA:-false}" = "1" ]; then
        echo "ERROR: SQLite data migration is forbidden in production."
        exit 1
    fi
    if [ "${AUTH_COOKIE_SECURE:-}" != "true" ] && [ "${AUTH_COOKIE_SECURE:-}" != "1" ]; then
        echo "ERROR: AUTH_COOKIE_SECURE=true is mandatory in production."
        exit 1
    fi
    if [ -z "${SUPABASE_URL:-}" ] || [ -z "${SUPABASE_ANON_KEY:-}" ] || [ -z "${AUTH_REDIRECT_URL:-}" ]; then
        echo "ERROR: Supabase Auth configuration is incomplete. Refusing production startup."
        exit 1
    fi
    if [ "${DOCUMENT_STORAGE_PROVIDER:-}" != "supabase" ]; then
        echo "ERROR: DOCUMENT_STORAGE_PROVIDER=supabase is mandatory in production."
        exit 1
    fi
    if [ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ] || [ -z "${SUPABASE_STORAGE_BUCKET:-}" ]; then
        echo "ERROR: Supabase private storage configuration is incomplete."
        exit 1
    fi
    if [ -z "${LBR_RESA_ENABLED+x}" ] || [ -z "${PDF_OCR_ENABLED+x}" ]; then
        echo "ERROR: LBR_RESA_ENABLED and PDF_OCR_ENABLED must be explicitly configured."
        exit 1
    fi
    # Validate configuration without printing any credential or connection URI.
    python3 - <<'PY'
import os
import sys
sys.path.insert(0, 'backend')
from db_adapter import validate_production_database_config, validate_database_url
import auth
auth.validate_production_auth()
validate_production_database_config()
validate_database_url(os.environ.get('MIGRATION_DATABASE_URL', ''), require_ssl=True)
print('Production configuration validated: PostgreSQL, TLS, Supabase Auth and private storage.')
PY
else
    if [ "${DB_PROVIDER:-auto}" = "sqlite" ]; then
        echo "Development SQLite mode enabled explicitly."
    fi
fi

if [ -n "${DATABASE_URL:-}" ]; then
    echo "PostgreSQL configuration accepted without exposing credentials."
fi

run_migrations() {
    if [ "${AUTO_MIGRATE:-true}" = "true" ] || [ "${AUTO_MIGRATE:-true}" = "1" ]; then
        if [ -n "${DATABASE_URL:-}" ]; then
            echo "Running idempotent database migrations..."
            if ! python3 scripts/supabase_db.py migrate; then
                echo "ERROR: Database migration failed. Refusing to start. No SQLite fallback."
                return 1
            fi
            echo "Migrations completed successfully."
        elif [ "${ENVIRONMENT}" = "production" ] || [ "${ENVIRONMENT}" = "prod" ]; then
            echo "ERROR: DATABASE_URL is mandatory before migrations in production."
            return 1
        else
            echo "Development SQLite schema will be initialized by the application."
        fi
    else
        echo "AUTO_MIGRATE is disabled; skipping schema migrations."
    fi
}

stop_children() {
    if [ -n "${WORKER_PID}" ] && kill -0 "${WORKER_PID}" 2>/dev/null; then
        kill "${WORKER_PID}" 2>/dev/null || true
    fi
    if [ -n "${WEB_PID}" ] && kill -0 "${WEB_PID}" 2>/dev/null; then
        kill "${WEB_PID}" 2>/dev/null || true
    fi
}

start_web_for_production() {
    echo "Starting HTTP Web API on port ${PORT:-8000} before database readiness checks..."
    # /health is a liveness endpoint. Database initialization is performed by
    # this parent process while the web process can answer liveness immediately.
    NACELUX_SKIP_DB_INIT=true python3 backend/app.py &
    WEB_PID=$!
    trap 'stop_children' EXIT INT TERM
}

case "${PROCESS}" in
    worker)
        run_migrations
        echo "Starting NACELUX background worker..."
        exec python3 backend/worker.py
        ;;
    all|both|full)
        if [ "${ENVIRONMENT}" = "production" ] || [ "${ENVIRONMENT}" = "prod" ]; then
            start_web_for_production
            if ! run_migrations; then
                stop_children
                wait "${WEB_PID}" 2>/dev/null || true
                exit 1
            fi
            echo "Starting background worker after migrations completed..."
            python3 backend/worker.py &
            WORKER_PID=$!
            wait "${WEB_PID}"
        else
            run_migrations
            echo "Starting background worker..."
            python3 backend/worker.py &
            WORKER_PID=$!
            echo "Starting HTTP Web API on port ${PORT:-8000}..."
            exec python3 backend/app.py
        fi
        ;;
    web|*)
        if [ "${ENVIRONMENT}" = "production" ] || [ "${ENVIRONMENT}" = "prod" ]; then
            start_web_for_production
            if ! run_migrations; then
                stop_children
                wait "${WEB_PID}" 2>/dev/null || true
                exit 1
            fi
            wait "${WEB_PID}"
        else
            run_migrations
            echo "Starting HTTP Web API on port ${PORT:-8000}..."
            exec python3 backend/app.py
        fi
        ;;
esac
