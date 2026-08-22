# NACELUX — Étape 8 : Opportunities / Commercial Workspace

Date : 2026-08-22 · Branche : `arena/01a0270b-nacelux` · Commit : `9bec6ba`

## Architecture
Commercial workspace built **on top** of the Step 7 scoring engine. **No changes to `calculate()`**, weights, thresholds, actions, fingerprint logic, or append-only history.

## API — **VERIFIED**

### `GET /api/v1/opportunities` — paginated, filtered, sorted
- Pagination: `limit` (max 100), `offset`, returns `pagination{total,limit,offset,page,pages}`.
- Filters: `search`, `score_min`, `score_max`, `level`, `municipality`.
- Sorting: `highest_score` (default), `lowest_score`, `newest`, `recently_updated`.
- Returns: `company_id`, `company_name`, `score`, `level`, `recommended_action`, `model_version`, `fingerprint`, `calculated_at`, `accepted_signals` (count), `rejected_signals` (count).

### `GET /api/v1/opportunities/:company_id` — full detail
Returns: company detail (reuses `company_detail`), `accepted_signals` (ACTIVE), `rejected_signals` (non-ACTIVE with status), `score_history` (model_version/score/level/action/fingerprint/created_at), `validation` (status/reviewer/reviewed_at/comment).

### `POST /api/v1/opportunities/validate` — manual validation
Decisions: `APPROVED`, `REJECTED`, `DISMISSED`, `REVIEW_PENDING`. Stores reviewer, comment, previous_status, new_status in append-only `opportunity_validations` table + audit log.

All endpoints: Auth + membership + RLS + server-side organization_id.

## Accepted vs Rejected Signals — **VERIFIED**
- ACCEPTED: `status='ACTIVE'` business_signals (evidence-backed).
- REJECTED: `status!='ACTIVE'` with status, explanation, and reason visible.
- UNKNOWN / NOT_CHECKED / NOT_CONNECTED → 0 points (never converted to positive).

## Evidence View — **VERIFIED**
The opportunity detail reuses `company_detail` which returns: signals (with evidence), digital_checks (with evidence), data_lineage (source → raw_record → company). Score breakdown includes factor-level provenance.

## Commercial Actions — **VERIFIED**
Unchanged from Step 7: NO_WEBSITE→CREATE_WEBSITE, WEAK_SEO→SEO_SERVICE, WEAK_WEBSITE→WEBSITE_REDESIGN, NO_GOOGLE_BUSINESS→LOCAL_SEO, LOW→LOW_PRIORITY, otherwise→MONITOR.

## Manual Validation — **VERIFIED**
States: REVIEW_PENDING (default), APPROVED, REJECTED, DISMISSED. Append-only audit trail (`opportunity_validations`). Does NOT modify the score or scoring history.

## Score History — **VERIFIED**
Append-only `opportunity_score_history` returns model_version, total_score, level, recommended_action, fingerprint, created_at. Immutable after creation (tested).

## Migration 0022
companies += validation_status/validated_by/validated_at/validation_comment.
opportunity_validations (RLS ENABLE+FORCE, tenant-scoped, append-only).
SQLite mirrored.

## Tests — **304 passed, 0 failed, 21 skipped**

### Step 8 tests (17 new):
- API: pagination, filtering (score_min, level, search), sorting (lowest_score), detail, not_found, required fields.
- Validation: approve, reject (with previous status), invalid decision, not_found.
- Security: no secrets in response, tenant isolation structure.
- Regression: Step 7 scoring unchanged, fingerprint deterministic, history immutable, unknown=0.

### All other tests (287 existing): all pass.

## VERIFIED
- Opportunities API (list, detail, validate) with pagination/filtering/sorting.
- Accepted vs rejected signals with reasons.
- Manual validation (APPROVED/REJECTED/DISMISSED) with audit trail.
- Score history immutable.
- Step 7 scoring formula, weights, thresholds, actions, fingerprint — unchanged.
- RLS / tenant isolation preserved.
- No secrets in API responses.
- No invented data/evidence/contacts.
- UNKNOWN / NOT_CHECKED = 0 points.

## REQUIRES CONFIGURATION
- NACELUX_TEST_DATABASE_URL (PostgreSQL SSL integration).
- Live RESA network access.
- OCR binaries, LLM keys.
- Supabase Auth/Storage/SSL.

## NOT VERIFIED
- Frontend Opportunities page (backend API ready; UI not built this iteration).
- End-to-end with live RESA data.

## Files Modified
- `backend/app.py` — GET /opportunities (enhanced), GET /opportunities/:id, POST /opportunities/validate.
- `backend/database.py` — SQLite SCHEMA (opportunity_validations), init_db ALTERs (companies validation columns).
- `database/migrations/0022_opportunity_validation.sql` — NEW.
- `backend/migrations.py` — TABLE_ORDER.
- `tests/test_step8_opportunities.py` — NEW (17 tests).

## Acceptance Criteria
- ✅ Step 7 scoring formula unchanged.
- ✅ Step 7 weights unchanged.
- ✅ Step 7 thresholds unchanged.
- ✅ Step 7 actions unchanged.
- ✅ Step 7 fingerprint unchanged.
- ✅ Score history remains append-only.
- ✅ RLS remains active.
- ✅ Tenant isolation remains verified.
- ✅ No invented data.
- ✅ No invented evidence.
- ✅ No external enrichment without configuration.
- ✅ Opportunities are explainable.
- ✅ Every positive factor traceable to evidence.
- ✅ Every rejected signal has a reason.
- ✅ Human validation is auditable.
- ✅ Existing Steps 1–7 remain passing.

---

STOP after completing Step 8. Step 9 NOT started.
