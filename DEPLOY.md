# Déploiement NACELUX Rev. 2.1 — Production Ready

Ce guide fournit toutes les instructions pour déployer NACELUX en production sur **Railway**, **Docker**, **Render** ou **Fly.io** avec **Supabase** (PostgreSQL, Auth, Storage, RLS) et les **workers OCR / SEO / RESA**.

---

## 1. Architecture Déployée

```text
┌────────────────────────────────────────────────────────┐
│               Railway / Container Cloud                │
│                                                        │
│  ┌──────────────────────┐    ┌──────────────────────┐  │
│  │   Web Service (API)  │    │  Background Worker   │  │
│  │   python3 app.py     │    │  python3 worker.py   │  │
│  └──────────┬───────────┘    └──────────┬───────────┘  │
└─────────────┼───────────────────────────┼──────────────┘
              │                           │
              ▼                           ▼
┌────────────────────────────────────────────────────────┐
│                   Supabase Cloud                       │
│  ├── PostgreSQL Database (Migrations 0001-0011 + RLS) │
│  ├── GoTrue Auth (Cookies HttpOnly + CSRF)             │
│  └── Storage Bucket (resa-documents PDF deduplicated)  │
└────────────────────────────────────────────────────────┘
```

---

## 2. Déploiement en 1 Clic sur Railway

### Étape 1 : Créer le projet Railway
1. Va sur [Railway.app](https://railway.app) → **New Project**.
2. Sélectionne **Deploy from GitHub repo** et choisis ce repository.
3. Railway utilise automatiquement le `Dockerfile` et `railway.json`.

### Étape 2 : Configurer les Variables d'Environnement
Dans Railway, va dans l'onglet **Variables** du service et ajoute :

```env
DATABASE_URL=postgresql://postgres.VOTRE_REF:PASSWORD@aws-0-eu-west-2.pooler.supabase.com:5432/postgres?sslmode=require
DB_PROVIDER=postgresql
DB_RUNTIME_ROLE=nacelux_runtime
DB_SSLMODE=require
MIGRATION_DATABASE_URL=postgresql://postgres.VOTRE_REF:PASSWORD@aws-0-eu-west-2.pooler.supabase.com:5432/postgres?sslmode=require
SUPABASE_URL=https://VOTRE_REF.supabase.co
SUPABASE_ANON_KEY=<server-side-anon-key>
SUPABASE_SERVICE_ROLE_KEY=<server-side-service-role-key>
SUPABASE_STORAGE_BUCKET=resa-documents
DOCUMENT_STORAGE_PROVIDER=supabase
AUTH_REDIRECT_URL=https://votre-app.up.railway.app
AUTH_COOKIE_SECURE=true
AUTO_MIGRATE=true
MIGRATE_SQLITE_DATA=false
NACELUX_ENV=production
LBR_RESA_ENABLED=false
PDF_OCR_ENABLED=true
PORT=8000
```

### Étape 3 : Lancer le Worker de fond (Optionnel mais recommandé)
Dans le même projet Railway :
1. Clique sur **+ New Service** → **GitHub Repo** (même repo).
2. Nomme ce service `nacelux-worker`.
3. Dans **Variables**, ajoute les mêmes variables que le service Web, avec en plus :
   ```env
   PROCESS_TYPE=worker
   ```
4. Le worker s'exécute en continu pour traiter l'OCR Tesseract, les audits SEO et les signaux en arrière-plan.

---

## 3. Configuration Supabase

1. **Database** :
   - Récupère l'URI de connexion dans **Project Settings → Database → Connection string (Session pooler)**.
   - Assure-toi que `AUTO_MIGRATE=true` est activé : au démarrage, `start.sh` applique automatiquement les migrations additives `0001` à `0014` sans intervention manuelle.
   - Crée deux rôles non propriétaires avant migration : `nacelux_runtime` pour le web et `nacelux_worker` pour le worker. Aucun ne doit avoir `BYPASSRLS` ou `SUPERUSER`.
   - Configure `DATABASE_URL` avec le rôle runtime et `DB_RUNTIME_ROLE` avec le nom exact du rôle. Configure le worker avec son propre `DATABASE_URL` et `DB_RUNTIME_ROLE=nacelux_worker`.
   - `MIGRATION_DATABASE_URL` reste réservé aux migrations privilégiées et doit être différent de `DATABASE_URL`. Les migrations vérifient les rôles et accordent les privilèges tenant sous RLS.
2. **Authentication** :
   - Dans **Authentication → URL Configuration**, ajoute l'URL de ton application Railway dans **Site URL** et **Redirect URLs**.
3. **Storage** :
   - Crée un bucket nommé `resa-documents` (privé).
   - Renseigne `SUPABASE_SERVICE_ROLE_KEY` pour autoriser le backend à y écrire.

---

## 4. Déploiement Local avec Docker Compose

Pour tester l'ensemble de l'infrastructure en local (Web + Worker + PostgreSQL) :

```bash
# Lance PostgreSQL, le Web API et le Worker en conteneurs isolés
docker compose up --build
```

- Web API : `http://localhost:8000`
- Healthcheck : `http://localhost:8000/api/v1/health`
- Base PostgreSQL locale : `localhost:5432`

---

## 5. Commandes CLI utiles

```bash
# Vérifier la connexion Supabase et les migrations
python3 scripts/supabase_db.py test
python3 scripts/supabase_db.py migrate

# Exécuter un cycle de worker en direct
python3 backend/worker.py --once

# Lancer le connecteur RESA manuellement
python3 scripts/resa_sync.py https://www.lbr.lu/mjrcs-web-front/publication-journal/RESA-2026_231_1_0

# Importer la nomenclature NACE Rev. 2.1 officielle
python3 scripts/import_nace21.py
```

---

## 6. Endpoints de Contrôle & Santé

| Endpoint | Méthode | Rôle |
|---|---|---|
| `/health` | GET | Liveness immédiate, `ALIVE`, sans accès DB |
| `/api/v1/health` | GET | Readiness PostgreSQL/stockage/OCR/connecteurs, `503` si DB indisponible |
| `/api/v1/health/database` | GET | Statut détaillé de la connexion PostgreSQL Supabase |
| `/api/v1/session` | GET | Session active, utilisateur et tenant courant |
| `/api/v1/jobs` | POST | Déclenchement d'un job asynchrone (OCR, SEO, RESA, NACE...) |
