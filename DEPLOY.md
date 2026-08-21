# Déploiement NACELUX – SaaS fonctionnel

## Pourquoi le projet semblait "corrompu"

Le ZIP original était un dump complet d'un **workspace agent** (fichiers `.railway/`, binaires, skills, certificats, sessions…).  
Ce n'est **pas** le code de l'application. Le vrai code applicatif est propre et se trouve dans le dossier `nacelux/`.

## Architecture cible (déjà prête)

- **Backend** : Python 3 stdlib + `psycopg` + `PyJWT` (serveur HTTP natif)
- **Frontend** : SPA HTML/CSS/JS
- **Base de données** : Supabase PostgreSQL (déjà configuré dans ton `.env`)
- **Auth** : Supabase Auth (cookies HttpOnly + CSRF)
- **Stockage documents** : local ou Supabase Storage

## Option 1 – Railway (recommandé, déjà préparé)

1. Crée un **nouveau** projet Railway (ne réutilise pas l'ancien workspace corrompu).
2. Connecte ton repo GitHub (ou déploie depuis ce dossier propre).
3. Ajoute les variables d'environnement depuis `.env.example` (ne committe **jamais** le vrai `.env`).
4. Railway détecte `railway.json` et lance `python3 backend/app.py`.
5. Point le domaine custom si besoin.

```bash
# En local pour tester
cp .env.example .env
# édite .env avec tes vraies valeurs Supabase
pip install -r requirements.txt
python3 backend/app.py
```

## Option 2 – Render.com (très simple)

1. New → Web Service
2. Build Command : `pip install -r requirements.txt`
3. Start Command : `python3 backend/app.py`
4. Ajoute toutes les variables d'environnement
5. Health check path : `/api/v1/health` (si disponible) ou `/`

## Option 3 – Fly.io

```bash
fly launch
# choisis Python
fly secrets set DATABASE_URL=... SUPABASE_URL=... etc.
fly deploy
```

## Option 4 – VPS classique (DigitalOcean, Hetzner, OVH…)

```bash
# Sur le serveur
git clone <ton-repo>
cd nacelux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# copier .env
# systemd service
```

Exemple unit systemd :

```ini
[Unit]
Description=NACELUX SaaS
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/nacelux
EnvironmentFile=/opt/nacelux/.env
ExecStart=/opt/nacelux/.venv/bin/python3 backend/app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Puis Nginx en reverse proxy sur le port 8000.

## Option 5 – Docker (universel)

```bash
docker build -t nacelux .
docker run -p 8000:8000 --env-file .env nacelux
```

## Checklist pour un SaaS 100 % fonctionnel

- [ ] Nouveau projet Railway / Render / Fly (propre)
- [ ] Variables d'environnement correctement renseignées (surtout `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`)
- [ ] Migrations appliquées : `python3 scripts/supabase_db.py setup`
- [ ] Dans Supabase Dashboard → Authentication → URL Configuration : ajouter ton domaine de production
- [ ] `AUTH_REDIRECT_URL` pointe vers ton domaine
- [ ] Test : `GET /api/v1/health/database` → doit retourner CONNECTED
- [ ] Signup / Login fonctionne
- [ ] Création automatique d'organisation au premier login

## Sécurité critique

Le fichier `.env` original contient des **secrets en clair**.  
**Rotation obligatoire** :
1. Change le mot de passe de la base Supabase
2. Régénère les clés `anon` et `service_role` si elles ont fuité
3. Ne jamais recommitter un `.env`

## Support local rapide

```bash
cd nacelux
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# édite .env
python3 scripts/supabase_db.py test
python3 backend/app.py
```

Ouvre http://localhost:8000
