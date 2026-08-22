# NACELUX — Rapport Étape 6 (Business Signals)

Date : 2026-08-22 · Branche : `arena/01a0270b-nacelux` · Commit : `5ada17f`

**Aucun signal sans preuve. Aucune donnée inconnue ne produit un signal positif/négatif.** UNKNOWN ≠ NOT_CHECKED ≠ NOT_CONNECTED ; NOT_CONFIGURED ≠ NOT_FOUND. Aucun score commercial global (Étape 7).

## Business Signals — **VERIFIED**
Moteur versionné, evidence-backed, idempotent (upsert + fingerprint SHA-256), historique conservé (ACTIVE→INACTIVE), rafraîchissement via job atomique.

## Signals implémentés (8)
NEW_COMPANY, RECENT_INCORPORATION, NO_WEBSITE, WEAK_WEBSITE, WEAK_SEO, NO_GOOGLE_BUSINESS, DECISION_MAKER_FOUND, HIGH_VALUE_NICHE — tous testés.

## Rules
Versionnée (`SIGNAL_RULE_VERSION`, défaut 1.0) ; seuils configurables (new_days, recent_days, weak_seo, weak_website, weak_website_min_factors, high_value_niche). Les anciennes versions restent reproductibles (fingerprint inclut rule_version).

## Evidence
Chaque signal porte : signal_type, value, confidence, source, explanation, severity, rule_version, data_quality, detected_at/last_seen_at, status, evidence (json : source, source_url, check_id/run, observed value, **fingerprint SHA-256**). Un utilisateur comprend POURQUOI le signal existe.

## Confidence — **VERIFIED** (déterministe)
Dépend de la qualité de source/fraîcheur/preuve/complétude/méthode (1.0 officielle, 0.8–0.95 selon preuve, 0.6–0.75 inférée). Pas de confiance subjective.

## Data Quality — **VERIFIED**
VERIFIED / OBSERVED / INFERRED (+ DEMO dev-only). INFERRED ne devient jamais VERIFIED.

## NO_WEBSITE — conditions exactes : **VERIFIED**
Généré **uniquement** si un `website_discovery_runs` existe avec status=SUCCESS, pas de selected_candidate_id, pas d'error_code (discovery complète = recherche exécutée, aucun candidat evidence-backed). Les 5 cas testés :
- Cas A (discovery non exécutée) → aucun NO_WEBSITE ✅
- Cas B (NOT_CONFIGURED) → aucun ✅ (NOT_CONFIGURED ≠ NOT_FOUND)
- Cas C (ERROR/FAILED) → aucun ✅
- Cas D (BLOCKED) → aucun ✅
- Cas E (discovery complète, aucun site) → NO_WEBSITE ✅
Un verify-404 (page manquante) ne produit plus NO_WEBSITE (corrigé : avant, la digital_checks status NOT_FOUND était ambigüe).

## NO_GOOGLE_BUSINESS — conditions exactes : **VERIFIED**
Uniquement si check Google Business status=NOT_FOUND **et** source_provider=google_places (vraie recherche Places). NOT_CONNECTED/NOT_CHECKED/inconnu → aucun signal.

## People — conditions : **VERIFIED**
DECISION_MAKER_FOUND uniquement : dirigeant officiel (source_type=OFFICIAL, confidence≥0.8, privacy ACTIVE) ou profil public haute-confiance (≥0.82). Interdit : déduction (confidence<0.8), source INFERRED, nom généré. Testé.

## NACE — conditions : **VERIFIED**
HIGH_VALUE_NICHE depuis l'attractivité de la taxonomy existante (NULL/unknown → aucun signal ; jamais inventé). Se renforce automatiquement quand NACE officiel est ACTIVE (confidence + élevée). NACE NOT_IMPORTED → pas de classification inventée.

## Jobs — **VERIFIED**
`BUSINESS_SIGNAL_REFRESH` via la file atomique PostgreSQL (`app_claim_jobs`, `FOR UPDATE SKIP LOCKED`) ; retry/backoff/max-attempts/orphan-recovery (vérifiés étape 2). Vérifié en live (refresh → 8 companies, 10 signaux actifs).

## API — **VERIFIED**
`POST /api/v1/signals/refresh` (auth, org serveur-side), `GET /api/v1/signals` (filtres company_id/type/severity/status/confidence/date/pagination), `GET /api/v1/companies/:id` (inclut `signals`), dashboard (compteurs active_signals/high_priority_signals). Toutes auth + membership, jamais `organization_id` client.

## Frontend — **VERIFIED**
Drawer : section « Business signals » (signaux actifs uniquement, severity, confidence, quality, « Why: » explication). Dashboard : cartes Active signals / High priority signals. Un signal UNKNOWN/NOT_CHECKED/NOT_CONNECTED n'est jamais affiché comme actif.

## RLS — **VERIFIED**
`business_signals`, `business_signal_definitions`, `business_signal_runs` tenant-scoped (ENABLE+FORCE, `app_user_has_org_access`). Tenant isolation vérifiée (tests step6 + suite PG étape 2/3). A ne voit pas les signaux de B.

## Tests — **167 passed, 0 failed, 21 skipped**
Step 6 : 22 OK (8 signaux + guardrails négatifs + 5 cas NO_WEBSITE + Google/People/NACE + fingerprint/idempotence/activation/désactivation/historique/tenant/secrets). Skipped = suites PostgreSQL conditionnelles.

## Données
**AUCUNE DONNÉE FICTIVE EN PRODUCTION.** Les fixtures NACE/signaux sont test-only (SQLite isolé), jamais chargées en runtime. Le dashboard affiche 0 si aucun signal réel.

## Limitations
- **VERIFIED** : 8 signaux, guardrails (UNKNOWN/NOT_CHECKED/NOT_CONNECTED → rien), 5 cas NO_WEBSITE, Google/People/NACE, fingerprint/idempotence, historique, tenant isolation, RLS, jobs, API, frontend, dashboard.
- **REQUIRES CONFIGURATION** : NO_WEBSITE/NO_GOOGLE_BUSINESS réels dépendent d'une discovery/search Google Places configurée (clés API) — sans clé, le moteur ne produit pas ces signaux (par conception, pas de faux négatif).
- **NOT VERIFIED ici (déjà connu)** : Supabase Auth/Storage/SSL réels (projet requis) ; import NACE officiel (source ShowVoc injoignable).
- Pas de score commercial 0–100 (Étape 7).

---

VERIFIED = code exécuté + test réel + résultat observé. Je m'arrête à la fin de l'Étape 6 (pas d'Étape 7 automatique).
