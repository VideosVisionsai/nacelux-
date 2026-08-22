# NACELUX — Rapport : Intégration RESA → Intelligence commerciale

Date : 2026-08-22 · Branche : `arena/01a0270b-nacelux` · Commit : `33cb263`

**Réutilisation des composants des Étapes 1–6 (aucune reconstruction).** RESA (www.lbr.lu) étant **inaccessible** depuis cet environnement, le connecteur réel reste **REQUIRES_CONFIGURATION** — **rien n'est simulé**. L'intégration est le pont entre les tables `resa_*` (connecteur/extraction existants) et le data-core (`raw_records`, `documents`, `companies`, `people`, `data_lineage`).

## Chaîne cible
`Publication RESA → raw_record → document/extraction → evidence → company matching → people/rôles → website → digital → SEO → NACE → business signals → ready for scoring`

## Statut RESA
- **Connecteur réel (www.lbr.lu)** : **REQUIRES_CONFIGURATION** (TLS bloqué dans le sandbox). Statut API : `connector: DISABLED`, `pipeline: REQUIRES_CONFIGURATION`, `storage: READY`. `data_source` enregistrée `REQUIRES_CONFIRMATION` (jamais VERIFIED sans accès réel confirmé).
- **Aucune publication/PDF/personne/rôle/URL/NACE inventé.**

## Composants réutilisés (pas recréés)
`resa_connector` (LBRResaConnector), `document_storage` (Supabase/local), `pdf_extraction` (text/OCR/page), `import_pipeline` (matching RCS/VAT, dédup, lineage, raw_record), `website_intelligence` (verify + SSRF), `seo_engine`, `business_signals`, jobs PostgreSQL atomiques, RLS/FORCE RLS, SHA-256, audit.

## Nouveau : `backend/resa_pipeline.py` (couche d'orchestration)
- `ensure_source` — enregistre RESA comme `data_source` tenant-scoped, statut **REQUIRES_CONFIRMATION**.
- `extract_company_facts` / `extract_people_facts` — extraction **à étiquette explicite uniquement** (dénomination, RCS, NACE, gérant/administrateur/…). Texte sans étiquette → rien (pas d'invention).
- `ingest()` — transactionnel : `raw_record` (SHA-256, provenance) → matching/création company (RCS puis VAT, déterministe, via `import_pipeline`) → `data_lineage` (champ + raw_record + source + checksum) → `people` + `people_evidence` officiels (`OFFICIAL_ROLE`, confidence 1.0, `RESA_EXTRACTION`). Audit-loggé. Marque l'entreprise `signals_ready` (les moteurs existants font website/digital/SEO/signals).
- `provenance()` — chaîne complète : publication → raw_record → evidence → company → person → website → digital → SEO → NACE → signals.

`import_pipeline.persist_raw_record` est désormais **idempotent** (réutilise le raw_record existant pour même org/source/external_id/checksum) → ré-ingester une publication est sûr (pas de doublon).

## API
- `GET /api/v1/resa` — expose `pipeline.status` (**REQUIRES_CONFIGURATION** quand le connecteur n'est pas prêt), connector/storage/extraction, journaux/entrées/documents/runs.
- `GET /api/v1/resa/provenance/:company_id` — chaîne de provenance complète (404 si absente).
- Toutes auth + organisation déterminée côté serveur (jamais `organization_id` client). **VERIFIED** en live (statuts corrects, 404).

## Frontend
La page RESA existante affiche les statuts réels (connector DISABLED, captcha, robots, storage). Le statut pipeline **REQUIRES_CONFIGURATION** est exposé via l'API. Aucun VERIFIED affiché sans exécution réelle.

## Jobs
`RESA_SYNC` via la file atomique PostgreSQL (`FOR UPDATE SKIP LOCKED`, retry/backoff/orphan — vérifiés Étape 2). Le pipeline `ingest` est appelable par le worker après extraction. **VERIFIED** (mécanisme existant).

## RLS / Tenant isolation
Toutes tables tenant-scoped ENABLE+FORCE (`app_user_has_org_access`). `resa_pipeline.ingest` écrit avec l'org serveur ; `provenance` est filtré par org. **VERIFIED** : test cross-tenant (org A n'apparaît pas chez B ; provenance B = null pour une company de A).

## Tests — **175 passed, 0 failed, 21 skipped**
Suite RESA (8) : extraction explicite, création company/people/lineage, idempotence, matching RCS, no-company (pas d'invention), tenant isolation, absence de secrets, source REQUIRES_CONFIRMATION. Skipped = suites PostgreSQL conditionnelles + gated.

## Données
**AUCUNE DONNÉE FICTIVE EN PRODUCTION.** Les fixtures RESA sont **test-only** (SQLite isolé), jamais chargées en runtime. Extraction uniquement à partir de texte réel étiqueté.

## Statuts par élément
| Élément | Statut |
|---|---|
| Connecteur RESA réel (fetch PDF) | **REQUIRES_CONFIGURATION** (source injoignable) |
| Stockage PDF privé (Supabase/local) | code **VERIFIED** · live Supabase **REQUIRES CONFIGURATION** |
| Extraction TEXT/OCR/page | code **VERIFIED** · moteur **REQUIRES_CONFIGURATION** (Tesseract non installé ici) |
| Intégration RESA→company/people/lineage | **VERIFIED** (logique, fixtures) |
| Matching/dédup RCS/VAT | **VERIFIED** |
| People evidence officielle | **VERIFIED** |
| Provenance chain + API | **VERIFIED** |
| Jobs / RLS / tenant isolation / SHA-256 / audit | **VERIFIED** |
| **End-to-end RESA réel → prospect** | **NOT VERIFIED** (connecteur injoignable) |

## Limitations / Points non vérifiés
- **REQUIRES_CONFIGURATION** : accès RESA réel (www.lbr.lu), stockage Supabase réel, OCR Tesseract réel. Sans cela, le pipeline ne tourne pas sur de vraies publications — par conception, aucune donnée n'est fabriquée.
- **NOT VERIFIED** : chaîne end-to-end réelle (publication réelle → PDF → extraction → company → signals). Le logique d'intégration est VERIFIED via fixtures ; l'intégration réelle attend un environnement avec accès RESA.
- Scoring commercial : **non développé** (Étape 7, pas commencé).

---

VERIFIED = code exécuté + test réel + résultat observé. ARRÊT ici : pas d'Étape 7, pas de scoring, pas de Google Business, pas d'envoi d'emails. J'attends la validation de l'intégration RESA → intelligence commerciale.
