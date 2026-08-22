# NACELUX — Étape 2 : Rapport (validation RÉELLE PostgreSQL / RLS / multi-tenant / jobs / health / cookies)

Date : 2026-08-22 · Branche : `arena/01a0270b-nacelux` · Commit : `7c4c8d6`

Statuts : **VERIFIED** (réellement exécuté et réussi) · **NOT VERIFIED** (non exécutable ici) · **REQUIRES CONFIGURATION** (code prêt, nécessite secrets/infra externes).

> **Méthode de vérification PostgreSQL** : un **vrai serveur PostgreSQL 16.2** (binaire réel, fourni par le wheel `pgserver` — **pas un mock, pas une base factice**) est démarré localement ; les migrations, rôles, RLS, requêtes et la file de jobs sont exécutés contre ce moteur réel. Aucune donnée n'est inventée.

## PostgreSQL — **VERIFIED** (connexions/rôles) · SSL **REQUIRES CONFIGURATION**

- Connexion réelle, migrations appliquées, rôles créés et vérifiés sur un cluster PostgreSQL 16.2 fraîchement initialisé. **VERIFIED**.
- Rôle applicatif `nacelux_runtime` et worker `nacelux_worker` : `NOSUPERUSER`, `NOBYPASSRLS`, ne possèdent **aucune** table public. **VERIFIED** (vérifié en runtime via `pg_roles`/`pg_class`).
- **SSL** : le binaire PG embarqué est compilé `--without-openssl` (« SSL is not supported by this build ») ; aucun PG avec SSL n'est provisionnable ici (mirrors Debian/apt bloqués, pas de compilateur). Le SSL est **appliqué au niveau adaptateur** (`sslmode=require` + `DB_SSLMODE=require` obligatoires en prod, `validate_database_url(require_ssl=True)`) — **VERIFIED (couche code)**. Le **handshake SSL réel** nécessite un PG/Supabase avec SSL : **REQUIRES CONFIGURATION**.

## Migrations — **VERIFIED** (15 appliquées réellement)

Toutes les 15 migrations s'appliquent sur un cluster vierge (exécution réelle, pas seulement syntaxe). Aucune ne nécessite SQLite ; aucun conflit. Les **40 tables requises** sont présentes avec contraintes/index ; RLS ENABLE+FORCE confirmé. `test_all_required_tables_exist` passe sur la liste complète demandée.

## RLS — **VERIFIED**

36 tables tenant ont RLS **ENABLE** + **FORCE** (vérifié via `pg_class.relrowsecurity`/`relforcerowsecurity`). `app_user_has_org_access()` exige `app.user_id` **+** appartenance `organization_members` — `organization_id` seul ne suffit jamais (test d'attaque par manipulation : **DENIED**).

## Tenant isolation — **VERIFIED** (A↔B réel)

Exécuté en SQL direct sur le vrai PostgreSQL, en tant que rôle non-owner :
- A lit ses données (1), **ne lit pas** B (0). B lit ses données (1), **ne lit pas** A (0).
- A **ne peut pas UPDATE** B (rowcount 0) ; A **ne peut pas DELETE** B (rowcount 0). Idem B→A.
- **Sans contexte** (`app.user_id`/`app.organization_id` vides) : 0 ligne partout.
- **Manipulation d'organization_id** : A positionne `app.organization_id = org_B` mais garde `app.user_id = A` → accès à B **DENIED** (l'autorisation = authentification + membership + RLS).
L'autorisation n'est **jamais** déterminée par un `organization_id` provenant du frontend.

## Supabase Auth — **REQUIRES CONFIGURATION**

Le code (signup/login/logout/recover/update-password/session/provisioning OWNER) est complet et **VERIFIED au niveau code + cookies**, mais les round-trips réels GoTAuth nécessitent un projet Supabase. Aucune clé n'a été fournie — **pas de simulation**. API NACELUX non authentifiée → 401 (testé). Pour valider : fournir `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `AUTH_REDIRECT_URL`, `AUTH_COOKIE_SECURE=true` (+ Storage : `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_STORAGE_BUCKET`).

## Cookies — **VERIFIED**

Exercice réel de `auth.cookie_headers()` : access/refresh = `HttpOnly` + `Secure` (prod) + `SameSite=Lax`, Max-Age distincts (3600 / 2592000) ; cookie CSRF **lisible par JS** (pas HttpOnly) + `SameSite=Lax`, aléatoire par session ; `clear` → `Max-Age=0`. Round-trip HTTP `Set-Cookie` sur login réel = REQUIRES CONFIGURATION (Supabase). Aucun token exposé au frontend ou dans les logs.

## Jobs — **VERIFIED** (concurrence atomique réelle)

`app_claim_jobs` (`FOR UPDATE SKIP LOCKED`, `SECURITY DEFINER`) : **deux workers concurrents** réservent des jobs **disjoints**, aucun job réservé deux fois (3e connexion ne reprend rien des déjà réservés). Mécanisme atomique PostgreSQL réel. Cycle QUEUED→RUNNING→RETRY→SUCCESS/FAILED couvert par `test_postgres_integration` (SSL-gated) et `test_worker` (SQLite).

## Health — **VERIFIED**

- `GET /health` → HTTP 200 `{"status":"ALIVE","version":"2.1"}` même **DB down** (liveness, n'attend pas PG). **VERIFIED**.
- `GET /api/v1/health` → HTTP 200 `HEALTHY` / `CONNECTED` / `supabase-postgresql` contre le **vrai PostgreSQL**. **VERIFIED**.
- `GET /api/v1/health` DB injoignable → **HTTP 503** `DATABASE_UNAVAILABLE`, **0 fuite de secret** (password/URL/token absents). **VERIFIED**.

## Production fail-closed — **VERIFIED**

Tous les scénarios refusent le démarrage **sans jamais** basculer sur SQLite, créer un utilisateur/workspace Démo, exposer des données fictives ou contourner l'auth : `DATABASE_URL` absente → refuse ; `DB_PROVIDER` incorrect → refuse ; Supabase non configuré → refuse ; storage local en prod → refuse ; secrets incomplets → refuse. (0 secret dans les messages d'erreur — `redact_error`.)

## Tests

- `python3 -m unittest discover` → **89 passés, 15 skipped** (suites PostgreSQL conditionnelles).
- Vérification réelle embarquée (`python3 tests/run_step2_embedded.py`) → **11/11 RLS + jobs VERIFIED** contre vrai PostgreSQL.
- Cookies/CSRF → **7/7 VERIFIED**. Health → **3 scénarios réels VERIFIED**.
- **failed : 0**.
- **skipped restants = 15** : 11 step2-RLS (sans `NACELUX_TEST_DATABASE_URL`) + 4 `test_postgres_integration` (SSL-gated, à exécuter via `scripts/verify_rls.sh` sur un PG/Supabase SSL).

## Fichiers modifiés (cette étape)

| Fichier | Rôle |
|---|---|
| `tests/_pg_embedded.py` | **DEV/TEST** — démarre un vrai PostgreSQL embarqué (rôles + DB + migrations). Jamais importé par l'app. |
| `tests/test_step2_rls_isolation.py` | Suite RLS/tenant/jobs rigoureuse (skipped sans URL). |
| `tests/run_step2_embedded.py` | Runner de vérification locale reproductible. |
| `tests/test_step2_cookies_csrf.py` | Tests réels cookies/CSRF. |
| `scripts/verify_rls.sh` | Vérificateur opérateur (refuse sans `NACELUX_TEST_DATABASE_URL`, n'affiche jamais le mot de passe, aucun fallback SQLite). |

Aucune logique métier ajoutée. Aucun secret dans Git.

## Problèmes restants / bloquants pour la suite

1. **Supabase Auth (round-trips réels)** : REQUIRES CONFIGURATION — fournir `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `AUTH_REDIRECT_URL`, `AUTH_COOKIE_SECURE=true`. Sans cela, signup/login/etc. ne peuvent être exécutés en réel (aucune simulation faite).
2. **Supabase Storage** : REQUIRES CONFIGURATION — `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_STORAGE_BUCKET`.
3. **Handshake SSL réel** : REQUIRES CONFIGURATION — nécessite un PG/Supabase avec SSL. Vérifiable via `NACELUX_TEST_DATABASE_URL=<ssl pg> bash scripts/verify_rls.sh` (déclenche aussi les 4 tests `test_postgres_integration` qui exigent `ssl_in_use`).
4. **Test latent** : `test_postgres_integration.py` lit `schema_migrations` avec le rôle de test ; en production le rôle runtime n'a pas ce droit (résolu côté step2 en vérifiant les *outcomes* via catalogues). À harmoniser si vous voulez exécuter `test_postgres_integration` tel quel avec le rôle runtime.

## Variables nécessaires pour passer à VERIFIED complet

```
DATABASE_URL=<runtime non-owner, sslmode=require>
MIGRATION_DATABASE_URL=<migration owner, sslmode=require>
DB_PROVIDER=postgresql
DB_SSLMODE=require
DB_RUNTIME_ROLE=nacelux_runtime
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_ANON_KEY=<anon>
SUPABASE_SERVICE_ROLE_KEY=<service-role>   # backend uniquement, jamais frontend
SUPABASE_STORAGE_BUCKET=resa-documents
DOCUMENT_STORAGE_PROVIDER=supabase
AUTH_REDIRECT_URL=https://<domain>/reset-password
AUTH_COOKIE_SECURE=true
NACELUX_ENV=production
PORT=<railway>
# Pour vérification RLS opérateur :
NACELUX_TEST_DATABASE_URL=<runtime role, ssl>
NACELUX_WORKER_TEST_DATABASE_URL=<worker role, ssl>   # optionnel (test jobs)
```

---

**Conclusion** : PostgreSQL, migrations, RLS, isolation multi-tenant, jobs atomiques, health et cookies sont désormais **VERIFIED par exécution réelle**. Reste à brancher un **projet Supabase réel** (Auth + Storage + SSL) pour les 3 derniers points. Étape 2 terminée — je m'arrête ici (pas d'Étape 3 automatique).
