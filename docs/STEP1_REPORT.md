# NACELUX — Étape 1 : Rapport (PostgreSQL / Supabase / Multi-tenant / RLS / Health / Port / Démo)

Date : 2026-08-22 · Branche : `arena/01a0270b-nacelux` · Commit : `b7a0de5`

Statuts utilisés : **VERIFIED** (réellement exécuté et réussi) · **NOT VERIFIED** (non exécutable dans cet environnement) · **REQUIRES CONFIGURATION** (code prêt, nécessite des secrets/infra externes).

---

## Architecture actuelle (constatée par analyse du code)

- **Frontend** : SPA statique (`frontend/index.html` + `app.js` + `styles.css`, fichiers minifiés long-lignes), servie par le backend Python via `API.static()`. Aucune logique d'autorisation côté navigateur ; l'`organization_id` n'est jamais lu depuis le client pour autoriser.
- **Backend** : API HTTP en bibliothèque standard Python (`backend/app.py`, `ThreadingHTTPServer`). Toutes les routes sont préfixées `/api/v1`. Les requêtes dérivent l'organisation **côté serveur** via `self.auth_context` → `auth.ensure_workspace()` (issu de l'appartenance de l'utilisateur authentifié), jamais depuis le frontend.
- **Base de données** : `backend/db_adapter.py` sélectionne SQLite (dev) ou PostgreSQL (prod) **à l'import** selon `NACELUX_ENV` / `DB_PROVIDER` / `DATABASE_URL`. En dev → SQLite (`backend/database.py`, `SCHEMA` + seed démo dans `init_db()`). En prod → PostgreSQL obligatoire (`IS_POSTGRES` forcé à `True`).
- **Migrations PostgreSQL** : runner idempotent checksum-tracked dans `backend/migrations.py` (`database/migrations/00xx_*.sql`, 15 fichiers après cette étape).
- **Auth** : passerelle Supabase Auth côté serveur (`backend/auth.py`) : signup/login/logout/recover/update-password/session + CSRF + cookies HttpOnly/Secure/SameSite=Lax.
- **Jobs** : worker (`backend/worker.py`) + file PostgreSQL atomique (`app_claim_jobs` / `app_reap_orphan_jobs`, `SECURITY DEFINER`).
- **Sécurité prod** : `start.sh`, `db_adapter.validate_production_database_config()`, `auth.validate_production_auth()`, `document_storage.validate_production_storage_config()` = **fail-closed**.
- **Déploiement** : `Dockerfile` (multi-stage, non-root, healthcheck `/health`), `railway.json` (healthcheck `/health`), `docker-compose.yml` (web + worker + postgres), `Procfile`.

> Important : la preview actuelle tourne en **mode dev (SQLite/Démo)** uniquement parce qu'aucun Supabase n'est configuré dans ce sandbox. L'architecture **production** existe déjà dans le code ; ce rapport documente ce qui est vérifié et ce qui reste à brancher.

## Architecture cible (préparée)

```
Frontend (SPA) → API Python (/api/v1) → PostgreSQL Supabase (RLS FORCÉ)
Utilisateur → Supabase Auth → cookie de session → API → organization_members → PostgreSQL RLS
```
- L'`organization_id` provient **toujours** du membership serveur ; une valeur fournie par le navigateur n'est jamais une preuve d'autorisation (vérifié : aucune route ne lit `organization_id` dans le body/query pour autoriser).
- RLS `FORCE ROW LEVEL SECURITY` sur toutes les tables tenant → même le propriétaire des tables est soumis à l'isolation.

## Fichiers modifiés (cette étape)

| Fichier | Changement |
|---|---|
| `database/migrations/0015_raw_records_documents.sql` | **Nouveau** — tables `raw_records` + `documents` (manquantes de la liste ÉTAPE 5), tenant-scoped, RLS ENABLE+FORCE, grants non-owner. |
| `backend/migrations.py` | `raw_records`/`documents` ajoutés à `TABLE_ORDER` ; `raw_records.payload` à `JSON_COLUMNS`. |
| `tests/test_step1_hardening.py` | **Nouveau** — tests réels PORT dynamique, écoute 0.0.0.0, 5432 jamais HTTP, + garanties RLS statiques sur 0015. |

Aucune logique métier ajoutée (pas de LBR/RESA, OCR, People Engine, scoring avancé, enrichment). Aucun secret committé.

## Migrations PostgreSQL (15 fichiers, `database/migrations/`)

`0001` organizations/users/organization_members/companies/opportunity_scores/prospects/data_sources/jobs/data_lineage/audit_logs/nace_codes/taxonomy_nodes/people/digital_checks/seo_audits/resa_publications/reports/territories/scoring_weights · `0002` liaison auth Supabase · `0003` RESA · `0004` stockage PDF RESA · `0005` extraction/OCR · `0006` NACE officiel (versions/items/labels/notes/correspondences/import_runs) · `0007` website/digital · `0008` SEO/signals · `0009` people engine (evidence/profiles_public/privacy_requests) · `0010` business signals (definitions/runs) · `0011` RLS policies · `0012` job retry/backoff · `0013` durcissement RLS + `app_provision_workspace` + grants runtime · `0014` file worker RLS (`app_claim_jobs`/`app_reap_orphan_jobs`) · **`0015` raw_records + documents (RLS)** — couvre désormais toute la liste requise ÉTAPE 5.

Toutes additives/idempotentes, aucune commande destructive (`DROP TABLE`/`TRUNCATE` interdit, vérifié par test). **Statut migrations : VERIFIED** (intégrité + non-destructivité, 71 tests). **Application réelle sur PostgreSQL : NOT VERIFIED** (aucun serveur PG provisionnable dans ce sandbox — voir RLS).

## Auth (Supabase)

Code-complet : signup, login, logout, recover, update-password, session, utilisateur authentifié, création auto d'organisation au premier login (`ensure_workspace` → `app_provision_workspace`), rôles OWNER/ADMIN/MEMBER, gestion des rôles. Cookies `HttpOnly; Secure; SameSite=Lax` + CSRF double-submit cookie. Le Development User/Demo Workspace n'existent qu'en dev (jamais en prod — triple garde). **Statut : REQUIRES CONFIGURATION** (`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `AUTH_REDIRECT_URL`, `AUTH_COOKIE_SECURE=true`). Round-trips Supabase réels : NOT VERIFIED (pas de projet Supabase fourni).

## RLS (PostgreSQL Row Level Security)

- `app_user_has_org_access()` exige **à la fois** `app.user_id` (positionné par le backend après vérification Supabase Auth) **et** l'appartenance à `organization_members`. `app.organization_id` seul ne suffit **jamais** (durci dans `0013`).
- `ENABLE` + `FORCE ROW LEVEL SECURITY` sur organizations/users/organization_members + toutes les tables tenant (liste dans `0013` + `0015`).
- Le rôle applicatif `nacelux_runtime` (et `nacelux_worker`) : non-superuser, sans `BYPASSRLS`, ne possède pas les tables ; vérifié à chaque connexion dans `db_adapter.connect()`.
- Tables protégées (RLS tenant) : companies, business_signals(+runs), opportunity_scores, prospects, data_sources, jobs, data_lineage, audit_logs, taxonomy_nodes, people(+evidence, profiles_public, privacy_requests, engine_runs), digital_checks, website_discovery_runs, website_candidates, google_business_profiles, seo_audits, resa_publications, reports, territories, scoring_weights, resa_journals, resa_entries, resa_documents, resa_sync_runs, storage_objects, document_extractions, document_page_extractions, **raw_records, documents**. Tables de référence en lecture seule (nace_*, business_signal_definitions).
- **Tests RLS réels (PostgreSQL)** : `tests/test_postgres_integration.py` (isolation cross-tenant A↔B, écritures bloquées, `app_claim_jobs` disjoint, rôle non-BYPASSRLS/non-superuser). **Statut : NOT VERIFIED dans ce sandbox** — ils sont **skipped** car aucun serveur PostgreSQL n'est provisionnable ici (mirrors Debian injoignables 80+443 ; pas de binaire PG ; PyPI seul joignable). Le harnais de test est correct et prêt à exécuter contre toute base PG de test (`NACELUX_RUN_POSTGRES_INTEGRATION=1` + `NACELUX_TEST_DATABASE_URL`). Isolation au niveau Python/repository : **VERIFIED** (`test_multi_tenant_isolation`, `test_production_smoke`).

## SQLite

- Existe **uniquement** hors production (`db_adapter.connect()` branche SQLite + `database.init_db()` branche `else` de `if IS_POSTGRES:`). En production `IS_POSTGRES` est toujours `True` → la branche SQLite est morte ; `connect()` lève `ProductionConfigurationError` si jamais atteinte en prod.
- Aucun fallback automatique PostgreSQL→SQLite (vérifié : `test_production_*` + démonstration fail-closed sans `DATABASE_URL`, 0 fuite de secret).
- **Statut : VERIFIED** (SQLite interdit en prod, fallback absent). Conservé pour la preview dev (explicitement autorisé par le cahier des charges).

## Mode Démo

Occurrences analysées (`Demo/DEMO/Development User/Development Workspace/fixture/mock/seed_demo`) :
- `backend/database.py` (`ORG_ID="org_demo_lux"`, `DEMO_COMPANIES`, seed démo) → branche SQLite de `init_db()`, **inaccessible en prod**.
- `backend/app.py` contexte démo → `if not AUTH_ACTIVE:` précédé de `if _PRODUCTION: raise` ; garde module `if _PRODUCTION and not AUTH_ACTIVE: raise`.
- `/api/v1/session` renvoie `"mode":"DEMO"` uniquement si `ctx.get('demo')` (dev only).
Aucune activation accidentelle en production possible. **Statut : VERIFIED** (démo confinée au dev). Non supprimé : conservé isolé pour la preview (autorisé).

## Tests exécutés (résultats réels)

`python3 -m unittest discover -s tests` → **71 passés, 4 skipped** (intégration PostgreSQL). Couverture ÉTAPE 12 :
1. `/health` 200 — **VERIFIED** · 2. `/health` sans PG — **VERIFIED** · 3. `/api/v1/health` 200 avec PG — NOT VERIFIED (pas de PG) · 4. `/api/v1/health` 503 sans PG + 0 secret — **VERIFIED** · 5. prod sans `DATABASE_URL` refuse — **VERIFIED** · 6. prod PG indispo refuse — **VERIFIED** (init_db fail-closed) · 7. jamais de fallback SQLite prod — **VERIFIED** · 8. PORT réellement utilisé — **VERIFIED** (binding réel) · 9. écoute 0.0.0.0 — **VERIFIED** · 10. 5432 jamais HTTP — **VERIFIED** · 11/12/13. pas d'utilisateur/workspace/label Démo en prod — **VERIFIED** · 14. pas de secret en logs — **VERIFIED** (`redact_error`) · 15. pas de secret en API — **VERIFIED** · 16/17. tenant A↔B isolation (couche Python) — **VERIFIED** · 18. RLS réellement actif — **NOT VERIFIED** (pas de PG) · 19. rôle sans BYPASSRLS — **VERIFIED** (check connexion + test PG skip).

## Production — prêt vs. à faire

**Prêt (VERIFIED)** : fail-closed SQLite/PG/Auth/Storage, health liveness/readiness, port dynamique 0.0.0.0, migrations additives complètes, RLS policies + FORCE + rôles non-owner, isolation tenant (Python), CSRF/cookies, redaction secrets, mode démo confiné, Dockerfile/Railway/worker.

**REQUIRES CONFIGURATION** : projet Supabase réel (`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_STORAGE_BUCKET`), `DATABASE_URL`/`MIGRATION_DATABASE_URL` réels, création des rôles `nacelux_runtime`/`nacelux_worker` (non-owner, non-BYPASSRLS), `AUTH_REDIRECT_URL`, `AUTH_COOKIE_SECURE=true`.

**NOT VERIFIED (à exécuter sur infrastructure)** : application réelle des migrations + RLS sur PostgreSQL, round-trips Supabase Auth, file worker en runtime PostgreSQL. Harnais de tests fourni et prêt (`test_postgres_integration.py`).
