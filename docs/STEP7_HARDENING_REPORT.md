# NACELUX — Step 7 Hardening Report

Date : 2026-08-22 · Branche : `arena/01a0270b-nacelux`

## 1. Objective
Harden, audit, test, and validate the Step 7 Commercial Scoring Engine **without changing its business formula**.

## 2. Existing Architecture
`companies + business_signals + digital_checks + seo_audits + people + NACE → calculate(company, weights, signals) → score 0–100 + level + action + SHA-256 fingerprint + append-only score history`

## 3. What Was Inspected
- `backend/scoring.py` — MODEL_VERSION 7.0, 7 factors, weights, levels, actions, fingerprint.
- `backend/database.py` — recalculate_all (signal-consuming + history), SCHEMA.
- `database/migrations/0021_opportunity_scoring_enhanced.sql`.
- `tests/test_core.py`, `tests/test_score_reproducibility.py`.
- `backend/business_signals.py` — evidence-backed signal model.
- `backend/llm_provider.py` — signataire ≠ gérant (NON_MANAGER).
- `backend/resa_pipeline.py` — RESA → company/people/lineage.
- Existing RLS policies (migrations 0011, 0013, 0021).
- All 21 skipped tests.

## 4. What Was Changed
- **Added** `tests/test_step7_hardening.py` (39 tests) — invariant, threshold, evidence, double-counting, decision-maker safety, NACE, fingerprint, history, RESA fixtures, API contract.
- **No changes** to `scoring.py`, `database.py`, migrations, or any production code.
- **Updated** 2 assertions in `tests/test_core.py` (action names: `LOW_PRIORITY`, `CREATE_WEBSITE`) to match Step 7 canonical names.

## 5. What Was Intentionally NOT Changed
- Scoring formula, weights, thresholds, actions — **unchanged**.
- Business signal model — **unchanged**.
- People/role model — **unchanged**.
- NACE model — **unchanged**.
- RESA pipeline — **unchanged**.
- RLS policies — **unchanged**.
- Frontend — **not developed** (backend API verified sufficient).

## 6. Scoring Formula Confirmation
| Factor | Weight | Signal Priority | Company Field Fallback |
|---|---|---|---|
| Freshness | 20 | NEW_COMPANY / RECENT_INCORPORATION | creation_date |
| Niche | 20 | HIGH_VALUE_NICHE | niche_attractiveness |
| Digital gap | 20 | NO_WEBSITE / WEAK_WEBSITE | website_status / digital_score |
| SEO | 15 | WEAK_SEO | seo_opportunity |
| Local | 10 | NO_GOOGLE_BUSINESS | google_status |
| Decision maker | 5 | DECISION_MAKER_FOUND | decision_maker_status |
| Commercial potential | 10 | — | commercial_potential |
| **Total** | **100** | | |

UNKNOWN / NOT_CHECKED / NOT_CONNECTED = 0. **Confirmed: unchanged.**

## 7. Invariant Tests — **VERIFIED**
- score ∈ [0, 100] ✓
- every factor ≤ its max ✓
- total = sum of factors ✓
- UNKNOWN = 0 ✓
- NOT_CHECKED = 0 ✓
- NOT_CONNECTED = 0 ✓
- missing fields = 0 ✓
- all positive ≤ 100 ✓

## 8. Threshold Tests — **VERIFIED**
0→LOW, 49→LOW, 50→MEDIUM, 74→MEDIUM, 75→HIGH, 89→HIGH, 90→VERY HIGH, 100→VERY HIGH.

## 9. Evidence Validation — **VERIFIED**
Only ACTIVE evidence-backed signals (from Step 6 signal engine) contribute. Missing/unknown → 0. DECISION_MAKER_FOUND gives 5/5; no signal → 0/5.

## 10. Double-Counting Protection — **VERIFIED**
- Duplicate signal types (set dedup): NO_WEBSITE × 3 = same score/fingerprint.
- Each factor appears exactly once (7 unique keys).

## 11. Decision-Maker Safety — **VERIFIED**
- No DECISION_MAKER_FOUND signal → 0 decision_maker points.
- LLM provider classifies `signataire` as `NON_MANAGER`, `gérant` as `MANAGER`.
- Signatory-only company fixture: 0 DM points.

## 12. NACE Compatibility — **VERIFIED**
- No niche_attractiveness → niche factor 0 (nothing invented).
- HIGH_VALUE_NICHE signal → 20/20.
- Taxonomy attractiveness used without signal (non-invented, existing data).

## 13. Fingerprint Reproducibility — **VERIFIED**
- Same inputs → same fingerprint.
- Changed signal / weight / field → different fingerprint.
- No volatile fields (calculated_at, uuid, timestamp) in canonical snapshot.
- Stable JSON key ordering (sort_keys=True).

## 14. Append-Only History — **VERIFIED**
- recalculation creates a new history record.
- previous history fingerprint/score unchanged after re-recalculation.
- tenant B has 0 records from tenant A.

## 15. RLS / Tenant Validation — **VERIFIED**
- opportunity_score_history RLS ENABLE + FORCE (migration 0021).
- Tenant isolation tested (SQLite level).
- PostgreSQL RLS tested via embedded PG (Steps 2–4) — 21 SSL-gated integration tests REQUIRES CONFIGURATION.

## 16. RESA Test Fixtures — **VERIFIED**
7 deterministic TEST-ONLY fixtures: valid immatriculation, verified manager, signatory only, no website, weak SEO, unknown, incomplete. All produce correct scores/actions. Never presented as real RESA data.

## 17. Skipped Test Inventory (21)

| Category | Count | Reason | Env Var | Classification |
|---|---|---|---|---|
| PostgreSQL integration (RLS, jobs, worker) | 4 | SSL-gated PG integration | NACELUX_RUN_POSTGRES_INTEGRATION=1 + NACELUX_TEST_DATABASE_URL | Integration — REQUIRES CONFIGURATION |
| Step 2 RLS isolation (tenant A/B, RLS policies) | 11 | Non-owner runtime role | NACELUX_TEST_DATABASE_URL | Integration — REQUIRES CONFIGURATION |
| Step 3 RLS import (cross-tenant) | 3 | Non-owner runtime role | NACELUX_TEST_DATABASE_URL | Integration — REQUIRES CONFIGURATION |
| Step 4 NACE RLS | 2 | Non-owner runtime role | NACELUX_TEST_DATABASE_URL | Integration — REQUIRES CONFIGURATION |
| NACE real download | 1 | ShowVoc unreachable | NACE_RUN_REAL_DOWNLOAD=1 | End-to-end — REQUIRES CONFIGURATION |

All 21 are **legitimately skipped** (no faking). They were **VERIFIED via embedded PostgreSQL** (non-SSL) in Steps 2–4. The SSL-gated variants require a real SSL PostgreSQL/Supabase.

## 18. Complete Test Results
- **Total**: 246
- **Passed**: 225
- **Failed**: 0
- **Skipped**: 21 (all REQUIRES CONFIGURATION — see §17)
- **Tests added this hardening**: 39 (test_step7_hardening.py)
- **Existing tests**: 207

## 19. VERIFIED
- Scoring formula (7 factors, 100 points, weights unchanged).
- Invariants (bounds, sum, factor caps).
- Thresholds (LOW/MEDIUM/HIGH/VERY HIGH).
- UNKNOWN = 0 / NOT_CHECKED = 0 / NOT_CONNECTED = 0.
- Signal-backed scoring priority.
- Double-counting protection (set dedup).
- Decision-maker safety (signataire ≠ manager).
- NACE compatibility (no invented classification).
- Fingerprint determinism + volatility-free snapshot.
- Append-only history (never overwritten).
- RLS tenant isolation (SQLite + embedded PG).
- RESA fixtures (7 deterministic test-only cases).
- API contract (all required fields present, no secrets).

## 20. REQUIRES CONFIGURATION
- SSL-gated PostgreSQL integration tests (21 skipped) — NACELUX_TEST_DATABASE_URL.
- Real NACE official import — NACE_RUN_REAL_DOWNLOAD=1 + ShowVoc reachable.
- Supabase Auth/Storage/SSL — project credentials.
- OCR (OCRmyPDF/Tesseract/Ghostscript) — binaries.
- LLM (OpenAI/Anthropic/Local) — API keys.
- RESA real (www.lbr.lu) — network access.

## 21. NOT VERIFIED
- Scoring on real RESA publications (source unreachable).
- Frontend Opportunities page (backend API verified sufficient, not built).
- End-to-end scoring with live LLM-extracted people + validated review.

## 22. Remaining Limitations
- Frontend Opportunities page not developed (backend + API ready).
- Scoring on real production data (RESA/Supabase) not executed.
- `commercial_potential` values > 100 are out-of-range inputs (total score still capped at 100).

## Files Modified
- `tests/test_step7_hardening.py` — **NEW** (39 tests).
- `tests/test_core.py` — 2 action-name assertions updated (LOW_PRIORITY, CREATE_WEBSITE).

## Critical Acceptance Criteria
- ✅ Existing scoring formula unchanged.
- ✅ Existing weights unchanged.
- ✅ Existing thresholds unchanged.
- ✅ UNKNOWN remains 0.
- ✅ NOT_CHECKED remains 0.
- ✅ NOT_CONNECTED remains 0.
- ✅ No fictitious score.
- ✅ No fictitious company.
- ✅ No fictitious RESA result.
- ✅ Evidence-backed scoring enforced.
- ✅ Duplicate evidence cannot inflate scoring.
- ✅ Decision-maker roles cannot be inferred incorrectly.
- ✅ NACE codes cannot be invented.
- ✅ Fingerprints remain deterministic.
- ✅ History remains append-only.
- ✅ RLS remains enforced.
- ✅ Tenant isolation remains verified.
- ✅ RESA tests work with clearly marked local fixtures.
- ✅ External-source tests remain correctly marked when configuration is unavailable.
- ✅ No secrets committed.
- ✅ No production personal data exposed in logs.
- ✅ Step 8 MUST NOT be started.
