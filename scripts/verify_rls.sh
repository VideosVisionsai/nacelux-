#!/usr/bin/env bash
# =============================================================================
# NACELUX — Real PostgreSQL / RLS verification runner (ÉTAPE 2.11).
#
# Runs the PostgreSQL integration + RLS tenant-isolation suites against a REAL
# PostgreSQL database supplied by the operator. It NEVER uses SQLite, NEVER
# fabricates data, and NEVER prints the database password or connection URL.
#
# Required environment:
#   NACELUX_TEST_DATABASE_URL      non-owner runtime role (NO BYPASSRLS, not superuser)
# Optional environment:
#   NACELUX_WORKER_TEST_DATABASE_URL  non-owner worker role (enables the atomic
#                                     job-claim test)
#
# The database must already have the roles (nacelux_runtime / nacelux_worker)
# created and all migrations applied (e.g. via `python3 scripts/supabase_db.py migrate`).
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -z "${NACELUX_TEST_DATABASE_URL:-}" ]; then
  echo "ERROR: NACELUX_TEST_DATABASE_URL is not set." >&2
  echo "Provide a non-owner runtime PostgreSQL connection string (SSL-capable for Supabase)." >&2
  echo "No SQLite fallback is permitted. Refusing to run." >&2
  exit 2
fi

export NACELUX_RUN_POSTGRES_INTEGRATION=1
# Inform the adapter-level SSL posture without revealing any value.
export DB_SSLMODE="${DB_SSLMODE:-require}"

echo "=== NACELUX PostgreSQL / RLS verification ==="
echo "Runtime role connection : <redacted>"
echo "Worker role connection  : ${NACELUX_WORKER_TEST_DATABASE_URL:+<redacted>}${NACELUX_WORKER_TEST_DATABASE_URL:-<not provided; job test will skip>}"

# --- 1. Real connectivity pre-flight (no password/URL ever printed) ----------
python3 - "$@" <<'PY'
import os, re, sys
try:
    import psycopg
except ImportError:
    print("FAIL: psycopg is not installed (pip install \"psycopg[binary]>=3.2,<4\")", file=sys.stderr)
    sys.exit(3)
url = os.environ["NACELUX_TEST_DATABASE_URL"]
def redact(msg):
    msg = re.sub(r"(?i)(postgres(?:ql)?://[^:]+:)[^@]+@", r"\1<redacted>@", str(msg))
    msg = re.sub(r"(?i)password=[^\s&]+", "password=<redacted>", msg)
    return msg
try:
    with psycopg.connect(url) as conn:
        role = conn.execute("SELECT rolname, rolbypassrls, rolsuper FROM pg_roles WHERE rolname=current_user").fetchone()
        if role[1]:
            print("FAIL: the test role has BYPASSRLS — RLS cannot be verified with a privileged role.", file=sys.stderr); sys.exit(4)
        if role[2]:
            print("FAIL: the test role is SUPERUSER — RLS cannot be verified.", file=sys.stderr); sys.exit(4)
    print("OK: connected as non-owner role '%s' (not bypassrls, not superuser)." % role[0])
except SystemExit:
    raise
except Exception as exc:
    print("FAIL: could not connect to the test database: %s" % redact(exc), file=sys.stderr)
    sys.exit(5)
PY

echo
echo "=== Running PostgreSQL suites ==="
# Exit status reflects the test result. No SQLite fallback is involved anywhere.
python3 -m unittest \
  tests.test_step2_rls_isolation \
  tests.test_postgres_integration \
  -v
