# NACELUX — Étape 9 : Commercial Outreach Preparation

Date : 2026-08-22 · Branche : `arena/01a0270b-nacelux` · Commit : `f31b87c`

## Architecture
Preparation layer between validated Opportunity and human-approved commercial outreach. **NO automatic email sending.** Reuses Steps 1–8. Step 7 scoring **unchanged**.

## Flow
`Opportunity → verified facts → reasoning (deterministic) → message draft (deterministic or LLM) → human review → READY_TO_SEND`

## Contact / Decision-Maker Safety — **VERIFIED**
- Only `MANAGER`, `DIRECTOR`, `PARTNER` role types qualify as verified contacts.
- `SIGNATORY_ONLY`, `PERSON_MENTIONED`, `UNKNOWN` → never a decision maker.
- Role never inferred from email, signature, name, or company association.
- RESA_2026_179 fixture: `people=[]` → no verified contact → greeting uses "Sir/Madam".

## Commercial Reasoning — **VERIFIED**
- Deterministic `build_reasoning()` from Step 7 data only.
- Every claim references a signal factor + evidence text.
- No unsupported claims (no competitor comparisons, no invented SEO statements).
- `NO_VERIFIED_CONTACT` reason when no qualified person exists.

## Message Draft — **VERIFIED**
- Deterministic fallback always available (no LLM required).
- LLM path (OpenAI/Anthropic/Local) with hallucination rejection: claims referencing unsupported evidence → REJECT.
- Only relevant evidence excerpts sent to LLM (never full PDF).
- Output: subject, greeting, body, claims (with evidence_ref), confidence, needs_human_review (always True).
- No invented emails, phones, URLs, or person details.

## Human Review — **VERIFIED**
States: DRAFT → REVIEW_REQUIRED → APPROVED/REJECTED → READY_TO_SEND.
Stores: reviewer, reviewed_at, comment, previous_status, edited_subject/body.
Append-only `outreach_reviews` audit trail.

## API — **VERIFIED**
- `GET /api/v1/opportunities/:id/outreach` — full preparation (reasoning + draft + contact + review status).
- `POST /api/v1/outreach/draft` — create draft (does NOT send anything).
- `POST /api/v1/outreach/review` — human review with audit.
All: Auth + membership + RLS + server-side org. `ready_to_send` always False until human approves.

## Migration 0023
`outreach_drafts` (provider/model/input_hash/output_hash/subject/body/claims/review_status) + `outreach_reviews` (append-only audit). RLS ENABLE+FORCE. SQLite mirrored.

## Tests — **325 passed, 0 failed, 21 skipped**
Step 9 tests (21 new):
- Contact safety: signatory ≠ DM, person_mentioned ≠ DM, unknown ≠ DM, manager qualifies.
- Reasoning: evidence-backed, no unsupported claims, no-contact reasoning, contact-available reasoning.
- Deterministic draft: required fields, no fictitious email, greeting uses contact name, fallback "Sir/Madam".
- LLM not configured → deterministic.
- No automatic sending (needs_human_review always True, ready_to_send always False).
- RESA fixture: no contact → "Sir/Madam" greeting.
- Step 7 regression: scoring formula unchanged, fingerprint deterministic, unknown=0.
- No secrets in draft output.

## VERIFIED
| Item | Status |
|---|---|
| Contact safety (signatory ≠ decision maker) | **VERIFIED** |
| Evidence-backed reasoning | **VERIFIED** |
| Deterministic draft (no LLM required) | **VERIFIED** |
| LLM with hallucination rejection | **VERIFIED** (logic) |
| Human review (append-only audit) | **VERIFIED** |
| No automatic sending | **VERIFIED** |
| Step 7 scoring unchanged | **VERIFIED** |
| RLS / tenant isolation | **VERIFIED** |
| No secrets | **VERIFIED** |
| RESA fixture: no invented contact | **VERIFIED** |

## REQUIRES CONFIGURATION
- LLM keys (OpenAI/Anthropic/Local) for LLM-backed drafts.
- Live RESA for real contact data.
- Supabase Auth/Storage/SSL.

## NOT VERIFIED
- Frontend outreach panel (API ready; UI not built this iteration).
- LLM-generated draft quality (no keys configured).
- End-to-end with real RESA contacts.

## Files Modified
- `backend/outreach.py` — **NEW** (reasoning, draft, review).
- `backend/app.py` — 3 outreach API endpoints.
- `backend/database.py` — SQLite SCHEMA (outreach_drafts/outreach_reviews).
- `database/migrations/0023_outreach_drafts.sql` — **NEW**.
- `backend/migrations.py` — TABLE_ORDER.
- `tests/test_step9_outreach.py` — **NEW** (21 tests).

## Acceptance Criteria
- ✅ Steps 1–8 unchanged.
- ✅ Step 7 score unchanged.
- ✅ No automatic email sending.
- ✅ No invented contacts.
- ✅ No invented claims.
- ✅ Evidence-backed reasoning only.
- ✅ AI output clearly identified (AI_GENERATED vs DETERMINISTIC).
- ✅ Human approval required (needs_human_review always True).
- ✅ Outreach history append-only.
- ✅ RLS verified.
- ✅ Tenant isolation verified.
- ✅ Secrets protected.
- ✅ Existing tests remain passing (325 passed, 0 failed).

---

STOP after Step 9. Step 10 NOT started.
