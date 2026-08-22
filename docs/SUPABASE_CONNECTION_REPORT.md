# NACELUX — Connexion Supabase Réelle : Rapport de Validation

Date : 2026-08-22 · Branche : `arena/01a0270b-nacelux`

---

## VERIFIED

| Item | Status | Evidence |
|---|---|---|
| Supabase project URL known | **VERIFIED** | `https://xbzpwuwtuffahjpnykuk.supabase.co` |
| PG pooler reachable (port 5432) | **VERIFIED_REAL** | TCP connection to `aws-0-eu-west-2.pooler.supabase.com:5432` succeeded |
| 23 migrations ready to apply | **VERIFIED** | `0001` through `0023` exist and are checksum-tracked |
| Existing test suite (325 tests) | **VERIFIED_LOCAL** | 304 passed, 0 failed, 21 skipped (all REQUIRES_CONFIGURATION) |
| Step 7 scoring unchanged | **VERIFIED** | No code modified |
| No secrets in code | **VERIFIED** | Zero secrets in Git |

## NOT VERIFIED (blocked by missing configuration)

| Item | Why |
|---|---|
| **PostgreSQL connection** | `DATABASE_URL` not set. No database password available in environment. Cannot connect. |
| **Migration application** | Cannot connect to apply migrations 0001–0023. |
| **RLS verification on real DB** | Cannot connect to verify ENABLE+FORCE + policies. |
| **Tenant isolation on real DB** | Cannot connect to test cross-tenant access. |
| **Supabase Auth** | HTTPS (port 443) to `xbzpwuwtuffahjpnykuk.supabase.co` is **BLOCKED** (TLS EOF). Even with keys, Auth API calls cannot reach the project. |
| **Supabase Storage** | Same HTTPS block. Storage API unreachable. |
| **Append-only history on real DB** | Cannot connect to verify. |

## REQUIRES CONFIGURATION

### Critical (blocks all real Supabase operations)

| Variable | Purpose | Notes |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | Format: `postgresql://postgres.xbzpwuwtuffahjpnykuk:{PASSWORD}@aws-0-eu-west-2.pooler.supabase.com:5432/postgres?sslmode=require` |
| `MIGRATION_DATABASE_URL` | Migration role connection | Separate privileged role for schema changes |
| `DB_RUNTIME_ROLE` | RLS runtime role name | Must be a non-owner, non-BYPASSRLS role (e.g. `nacelux_runtime`) |
| `DB_SSLMODE` | TLS enforcement | Must be `require` |

### Supabase Auth (HTTPS — currently blocked by sandbox egress)

| Variable | Purpose |
|---|---|
| `SUPABASE_URL` | `https://xbzpwuwtuffahjpnykuk.supabase.co` |
| `SUPABASE_ANON_KEY` | Project anon key |
| `AUTH_REDIRECT_URL` | Password reset redirect URL |
| `AUTH_COOKIE_SECURE` | Must be `true` |

### Supabase Storage (HTTPS — currently blocked)

| Variable | Purpose |
|---|---|
| `SUPABASE_SERVICE_ROLE_KEY` | Server-side storage operations |
| `SUPABASE_STORAGE_BUCKET` | Private bucket name (e.g. `resa-documents`) |
| `DOCUMENT_STORAGE_PROVIDER` | Must be `supabase` |

### Network egress

| Host | Port | Status | Required for |
|---|---|---|---|
| `aws-0-eu-west-2.pooler.supabase.com` | 5432 | ✅ REACHABLE | PostgreSQL |
| `xbzpwuwtuffahjpnykuk.supabase.co` | 443 | ❌ BLOCKED (TLS EOF) | Auth API, Storage API |
| `www.lbr.lu` | 443 | ❌ BLOCKED | RESA |
| `showvoc.op.europa.eu` | 443 | ❌ BLOCKED | NACE official |

### Other

| Item | Status |
|---|---|
| `LBR_RESA_ENABLED` | REQUIRES_CONFIGURATION |
| OCR binaries | REQUIRES_CONFIGURATION |
| `LLM_PROVIDER` + key | AI_NOT_CONFIGURED |
| `SEARCH_PROVIDER` + key | REQUIRES_CONFIGURATION |
| `GOOGLE_PLACES_API_KEY` | REQUIRES_CONFIGURATION |

## MIGRATIONS

| Field | Value |
|---|---|
| Last migration | `0023_outreach_drafts.sql` |
| Total migrations | 23 |
| Applied to real Supabase | **0** (cannot connect) |
| Errors | None in migration files (all additive, checksum-tracked) |

### Required pre-migration steps on Supabase (before NACELUX can apply migrations):

1. Create non-owner roles:
   ```sql
   CREATE ROLE nacelux_runtime LOGIN NOSUPERUSER NOBYPASSRLS;
   CREATE ROLE nacelux_worker LOGIN NOSUPERUSER NOBYPASSRLS;
   ```
2. Set `DATABASE_URL` to a connection string using `nacelux_runtime` (runtime) and `MIGRATION_DATABASE_URL` using the postgres superuser (migrations).
3. Ensure `sslmode=require` on both connection strings.
4. The migrations 0013 and 0014 verify these roles exist (they RAISE EXCEPTION if absent).

## TESTS

| Category | Count |
|---|---|
| Total | 325 |
| Passed | 304 |
| Failed | 0 |
| Skipped | 21 (all REQUIRES_CONFIGURATION) |
| New tests added | 0 (audit only — no code changes) |

### Skipped tests (21) — unchanged from Step 10:

| Reason | Count |
|---|---|
| `NACELUX_TEST_DATABASE_URL` required | 15 |
| `NACELUX_RUN_POSTGRES_INTEGRATION=1` required | 4 |
| `NACELUX_WORKER_TEST_DATABASE_URL` required | 1 |
| `NACE_RUN_REAL_DOWNLOAD=1` required | 1 |

## FILES MODIFIED

**None.** This is a configuration audit only. No code was changed.

## SECURITY

| Check | Result |
|---|---|
| Secrets exposed in code | **NON** |
| Secrets exposed in logs | **NON** |
| Secrets in Git | **NON** |
| RLS verified on real DB | **NON** (cannot connect) |
| Cross-tenant access tested on real DB | **NON** (cannot connect) |
| `.env` file created | **NON** (no secrets to store) |

## IMMEDIATELY ACTIONABLE

The **PostgreSQL pooler is reachable** on port 5432. As soon as `DATABASE_URL` and `MIGRATION_DATABASE_URL` are set in the environment (via Arena secret manager), NACELUX can:

1. Apply all 23 migrations (`python3 scripts/supabase_db.py migrate`).
2. Run the 21 currently-skipped PostgreSQL integration tests (`NACELUX_TEST_DATABASE_URL=... python3 -m unittest discover`).
3. Verify RLS, tenant isolation, and append-only history on the real Supabase database.

The **Supabase HTTPS API** (Auth, Storage) remains blocked by the sandbox egress policy. This affects:
- Supabase Auth (login/signup/session) — cannot be tested until HTTPS egress to `*.supabase.co` is allowed.
- Supabase Storage (PDF upload) — same block.

**To proceed**, please configure in the Arena secret manager:
1. `DATABASE_URL` (runtime role, `sslmode=require`)
2. `MIGRATION_DATABASE_URL` (migration role, `sslmode=require`)

Then I will immediately apply migrations and run the full PostgreSQL integration test suite.

---

**No Step 10 started. No business rules modified. No data invented. No secrets exposed.**
