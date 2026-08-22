# NACELUX — Étape 3 : Rapport (cœur de la donnée : entreprises, sources, raw records, provenance, déduplication, import)

Date : 2026-08-22 · Branche : `arena/01a0270b-nacelux` · Commit : `14e2401`

Aucune donnée fictive. Aucune source officielle simulée. Aucun score/opportunité inventé (laissés NULL — développés plus tard).

### Companies — schéma final
Table existante (0001) + colonnes additives (0016) : `id, organization_id, company_name(=legal_name), trade_name, legal_form, rcs_number, vat_number, creation_date(=incorporation_date), status, capital, business_object(=business_purpose), description, primary_nace_code, secondary_nace_codes(jsonb), category, niche, subniche, website, email, phone, country, canton, municipality, locality, postal_code, street, street_number, latitude, longitude, website_status, digital_score, seo_score, seo_opportunity, google_status(=google_business_status), decision_maker_status, niche_attractiveness, commercial_potential, source_status, source_name, **source_id**, source_url, is_demo, **retrieved_at, provenance, checksum**, created_at, updated_at`. Index tenant/geo/nace/created + `idx_company_checksum`. RLS ENABLE+FORCE. Tous les champs requis ÉTAPE 3.1 couverts (noms adaptés au schéma existant).

### Sources — schéma final
`data_sources` : `id, organization_id, name, source_type, provider, base_url, status, source_version, source_checksum, configuration(jsonb), retrieved_at, records_count, note/description, last_run_at, created_at, updated_at`. Statuts autorisés (appliqués dans le code) : **ACTIVE, INACTIVE, REQUIRES_CONFIRMATION, FAILED**. Une source n'est **jamais** marquée VERIFIED sans vérification explicite (`ensure_source` force `VERIFIED → REQUIRES_CONFIRMATION`).

### Raw records — schéma final
`raw_records` : `id, organization_id, source_id(FK data_sources), external_id, payload, checksum(SHA-256), retrieved_at, stage, source_url, raw_content, content_format, status, metadata(jsonb)`. Index `(org,source_id,external_id)` et `(org,checksum)`. Contenu brut conservé intégralement pour audit/reproduction ; jamais modifié silencieusement.

### Data lineage — schéma final
`data_lineage` : `id, organization_id, entity_type, entity_id, field_name, source_id, source_url, document_id, retrieved_at, confidence, method, **raw_record_id(FK raw_records), checksum, transformation**`. Index `(org,entity_type,entity_id)`. Chaîne : SOURCE → raw_record → NORMALISATION → company.field (avec checksum + source_url + retrieved_at).

### Import — pipeline et statut : **VERIFIED**
`backend/import_pipeline.py`, source-agnostic, séparé des routes HTTP :
`SOURCE → raw_record → VALIDATION → NORMALISATION → DÉDUP → COMPANY → LINEAGE`.
- `preview()` : analyse sans écrire (records_received/valid/invalid, doublons, nouveaux, changements détectés, erreurs). **VERIFIED** (preview n'écrit rien : vérifié sur la preview live).
- `run()` : transactionnel (une transaction ; rollback total sur échec) ; enregistre `imports` (received/valid/created/updated/skipped/failed/status/error_summary) + `audit_logs`. **VERIFIED** (live + tests).
- `ensure_source()` : enregistre la source si absente (jamais VERIFIED).

### Deduplication — règles utilisées : **VERIFIED**
- Priorité aux identifiants officiels : **RCS puis TVA** (match → UPDATE la même entreprise, jamais de doublon).
- **Jamais** de fusion par similarité de nom. Un nom similaire (même nom normalisé, même org, sans id officiel) est enregistré dans `dedup_candidates` (status PENDING) et la nouvelle entreprise est **créée séparément** (non fusionnée). Contrainte `CHECK (match_basis NOT IN ('RCS','VAT','EXTERNAL_ID'))` : un id officiel ne peut pas être un « candidat » (il résout directement).
- Incertitude → on ne fusionne pas.

### API — routes créées/modifiées
- `GET /api/v1/companies` — **modifiée** : pagination (`limit`/`offset`, défaut 25, max 100) + métadonnées `pagination{total,limit,offset,page,pages}` ; filtres recherche/commune/canton/NACE/catégorie/niche/website/min_score/jours/niveau ; LEFT JOIN (entreprises sans score affichées, score NULL).
- `GET /api/v1/companies/:id` — LEFT JOIN (entreprise sans score consultable).
- `POST /api/v1/import/preview` — **modifiée** : utilise le pipeline (dry-run riche).
- `POST /api/v1/import` — **nouvelle** : import transactionnel (retourne import_id + compteurs ; échec → 500 + imports FAILED).
- `GET /api/v1/imports` — **nouvelle** : historique des imports du tenant.

### Frontend — vues connectées aux données réelles : **VERIFIED**
Page Companies connectée à `/api/v1/companies` (données réelles) : recherche, filtres, **pagination (Précédent/Suivant + page x/y)**, état vide (« No companies match these filters. »), affichage UNKNOWN/NOT_CHECKED via badges. Correction d'un bug : la recherche globale n'éffaçait plus la requête. `node --check` : JS valide. Aucune fixture affichée.

### Tests — passed / failed / skipped
- `unittest discover` : **109 passed, 0 failed, 18 skipped** (suites PostgreSQL conditionnelles).
- PostgreSQL réel embarqué : **step2 11/11** (RLS/tenant/jobs), **step3 3/3** (import tenant-scoped, import cross-tenant rejeté par RLS, artifacts isolés).
- data-core SQLite isolé : **17/17** (création/modif/lecture/pagination/recherche/filtres/raw/checksum/provenance/dédupe/preview/import/partiel/audit/secrets/pas-de-fictif).

### Sécurité — RLS / tenant isolation : **VERIFIED**
- Toutes les tables tenant (companies, raw_records, data_lineage, imports, dedup_candidates, sources…) RLS ENABLE+FORCE ; policy `app_user_has_org_access` (membership requis, jamais `organization_id` seul).
- L'`organization_id` provient toujours de la session/membership serveur (`self.org`) ; aucune route ne lit `organization_id` depuis le client.
- **Test réel PG** : utilisateur A ne peut ni lire, ni modifier, ni supprimer les données de B (et inversement) ; un utilisateur tentant d'importer dans l'org d'un autre tenant est **rejeté par RLS** (rien n'est écrit) ; artifacts (raw_records/imports) héritent de l'isolation.
- Rôle applicatif non-owner, non-BYPASSRLS, ne possède aucune table.

### Données — aucune donnée fictive en production : **confirmé**
- Aucune entreprise fictive créée par le pipeline (test : `provenance != 'DEMO'`, pas de `DEMO_COMPANIES`/`fixture` dans `import_pipeline.py`).
- Le seed démo reste **confiné au mode dev SQLite** (`database.init_db`, org `org_demo_lux`), inaccessible en production (fail-closed étapes 1–2).
- Unknown stays unknown : email/téléphone/site/NACE absents → NULL ; statuts → UNKNOWN/NOT_CHECKED ; email mal formé → sanitisé NULL. Aucun score/opportunité inventé (NULL jusqu'à l'étape scoring).

### Fichiers modifiés
- `database/migrations/0016_company_data_core.sql` (nouveau) · `backend/import_pipeline.py` (nouveau)
- `backend/database.py` (schéma SQLite miroir, `_companies_where`/`list_companies`/`count_companies`/`company_detail` LEFT JOIN)
- `backend/app.py` (pagination, import/preview, import commit, /imports, import du pipeline)
- `backend/migrations.py` (TABLE_ORDER) · `frontend/app.js` (pagination + fix recherche)
- `tests/test_step3_data_core.py`, `tests/test_step3_rls.py`, `tests/run_step3_embedded.py` (nouveaux) · `tests/_pg_embedded.py` (`set_app_database_url`)

### Points non vérifiés (REQUIRES CONFIGURATION)
- **Supabase Auth réel** (round-trips signup/login/etc.), **Supabase Storage réel**, **handshake SSL réel** : nécessitent un projet Supabase (inchangé depuis l'étape 2). `scripts/verify_rls.sh` reste prêt.
- Import depuis une **source officielle réelle** (ex. RESA, NACE officiel) : pas développé ici (hors périmètre Étape 3). Le pipeline est générique et prêt à recevoir ces sources.
- NACE officiel : non importé (Étape 3.17) — seules les relations sont préparées.

---

**Conclusion** : le cœur de la donnée NACELUX (entreprises, sources, raw records, provenance, déduplication déterministe, import transactionnel) est **implémenté et vérifié réellement** (109 tests + PostgreSQL réel). Aucune donnée fictive en production, aucune information inventée, isolation tenant validée par RLS. Je m'arrête à l'Étape 3 (pas d'Étape 4 automatique).
