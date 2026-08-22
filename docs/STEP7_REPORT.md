# NACELUX — Rapport Étape 7 : Scoring Engine Commercial

Date : 2026-08-22 · Branche : `arena/01a0270b-nacelux` · Commit : `9aff477`

## Architecture
Le moteur de scoring **réutilise** tous les composants des Étapes 1–6 (companies, signals, digital_checks, seo_audits, people, NACE, jobs, RLS). Aucune reconstruction.

## Formule
Score total = Σ(points par facteur), plafonné à 100.

| Facteur | Poids max | Source |
|---|---|---|
| Freshness | 20 | Signal NEW_COMPANY/RECENT_INCORPORATION ou creation_date |
| Niche attractiveness | 20 | Signal HIGH_VALUE_NICHE ou niche_attractiveness |
| Digital gap | 20 | Signal NO_WEBSITE/WEAK_WEBSITE ou website_status/digital_score |
| SEO opportunity | 15 | Signal WEAK_SEO ou seo_opportunity |
| Local presence | 10 | Signal NO_GOOGLE_BUSINESS ou google_status |
| Decision maker | 5 | Signal DECISION_MAKER_FOUND ou decision_maker_status |
| Commercial potential | 10 | commercial_potential field |
| **Total** | **100** | |

## Modèle
- **MODEL_VERSION** : `nacelux-scoring-7.0`
- **Pondérations** : `DEFAULT_WEIGHTS` (configurable via `scoring_weights` par tenant)
- **Niveaux** : LOW (0–49), MEDIUM (50–74), HIGH (75–89), VERY HIGH (90–100)
- **Actions** : CREATE_WEBSITE, WEBSITE_REDESIGN, SEO_SERVICE, LOCAL_SEO, LOW_PRIORITY, MONITOR (combinables avec ` + `)

## Règles déterministes
- **UNKNOWN / NOT_CHECKED / NOT_CONNECTED / NOT_CONFIGURED / ERROR → 0 point** (jamais deviné).
- **Signaux evidence-backed prioritaires** sur les champs company : un signal NO_WEBSITE (preuve : discovery complète) donne 20/20 au digital_gap ; un website_status NOT_CHECKED sans signal donne 0 (inconnu ≠ absent).
- **Actions déterministes basées sur les signaux** : NO_WEBSITE → CREATE_WEBSITE, WEAK_SEO → SEO_SERVICE, etc.
- **Décideur** : DECISION_MAKER_FOUND (signal) ou decision_maker_status=FOUND → 5/5. Un signataire non validé ne donne pas de points.
- **NACE** : HIGH_VALUE_NICHE (signal) → 20/20. Sans NACE, attractivité taxonomy utilisée (NULL → 0, jamais inventé).

## Reproductibilité — **VERIFIED**
- Mêmes données + mêmes pondérations + mêmes signaux + même version = même score + même fingerprint SHA-256 (testé : 207 tests passent, incluant test_score_reproducibility + test_core).
- Changement d'une donnée → fingerprint différent.
- Changement de signaux → fingerprint différent.
- Changement de version → fingerprint différent.

## Fingerprint
SHA-256 sur représentation canonique JSON (sort_keys=True) de `input_snapshot` incluant : creation_date, website_status, digital_score, seo_opportunity, google_status, decision_maker_status, niche_attractiveness, commercial_potential, **signals** (sorted), weights, model_version.

## Historique — **VERIFIED**
`opportunity_score_history` (append-only, migration 0021, RLS tenant-scoped). Chaque recalculation écrit une ligne (model_version, total_score, level, action, factor_snapshot, input_snapshot, fingerprint, created_at). L'ancien score n'est jamais écrasé silencieusement — on peut comparer pourquoi le score a changé.

## API
`GET /api/v1/opportunities` (filtres + pagination), `GET /api/v1/companies/:id` (inclut scoring_provenance), `POST /api/v1/jobs` (OPPORTUNITY_RECALCULATION), `POST /api/v1/signals/refresh` (refresh → recalcul). Toutes auth + membership + org serveur-side.

## Jobs
`OPPORTUNITY_RECALCULATION` via la file atomique PostgreSQL (`app_claim_jobs`, `FOR UPDATE SKIP LOCKED`, retry/backoff/orphan — vérifiés Étape 2).

## RLS / Tenant — **VERIFIED**
`opportunity_scores`, `opportunity_score_history` tenant-scoped ENABLE+FORCE. `organization_id` toujours du contexte serveur. Tests cross-tenant (test_multi_tenant_isolation, test_production_smoke).

## Sécurité — **VERIFIED**
- RLS tenant A/B (testé).
- `organization_id` jamais autorisé depuis le frontend (testé).
- Aucun secret dans les logs/réponses (testé : `redact_error`).
- Fail-closed production (SQLite interdit, testé Étapes 1–2).

## Tests — **207 passed, 0 failed, 21 skipped**
- test_core (3) : score 0 pour UNKNOWN, action déterministe, cap à 100.
- test_score_reproducibility (4) : fingerprint reproductible, changement détecté, snapshot restauré.
- test_production_smoke : lifecycle complet + tenant isolation + audit + worker.
- 21 skipped = suites PostgreSQL conditionnelles + gated real download.

## Migrations
- **0021** : opportunity_scores += model_version/factor_snapshot/input_snapshot/fingerprint ; opportunity_score_history (RLS). SQLite mirroré.

## Données
**AUCUN SCORE FICTIF.** Aucune donnée UNKNOWN transformée en information positive. Les fixtures sont test-only.

## Statuts
| Élément | Statut |
|---|---|
| Scoring déterministe (7 facteurs, 100 points) | **VERIFIED** |
| Signaux evidence-backed dans le scoring | **VERIFIED** |
| Fingerprint SHA-256 reproductible | **VERIFIED** |
| Actions recommandées déterministes | **VERIFIED** |
| Historique (append-only, non écrasé) | **VERIFIED** |
| RLS tenant A/B | **VERIFIED** |
| Jobs OPPORTUNITY_RECALCULATION | **VERIFIED** (mécanisme existant) |
| UNKNOWN/NOT_CHECKED = 0 point | **VERIFIED** |
| Frontend Opportunities page | **NOT VERIFIED** (non développé cette itération) |
| Scoring sur données RESA réelles | **NOT VERIFIED** (source RESA injoignable) |

## Fichiers modifiés
- `backend/scoring.py` (MODEL_VERSION 7.0, signals, actions, levels, fingerprint)
- `backend/database.py` (SCHEMA opportunity_scores/history, recalculate_all signal-consuming + history)
- `database/migrations/0021_opportunity_scoring_enhanced.sql` (nouveau)
- `backend/migrations.py` (TABLE_ORDER)
- `tests/test_core.py` (action names updated)

## Limitations
- **Frontend** : page Opportunities non développée cette itération (backend prêt ; le frontend affiche les scores existants via /api/v1/companies).
- **NOT VERIFIED** : scoring sur données RESA réelles (source RESA injoignable). La logique est VERIFIED via fixtures + embedded PostgreSQL.
- **REQUIRES CONFIGURATION** : OCR, LLM, RESA réel, Supabase Auth/Storage/SSL (inchangé depuis étapes précédentes).

---

VERIFIED = code exécuté + test réel + résultat observé. ARRÊT ici : pas d'Étape 8.
