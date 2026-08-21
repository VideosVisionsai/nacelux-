# Connexion Supabase PostgreSQL

## 1. Récupérer l’URI

Dans Supabase: **Project Settings → Database → Connect**. Utiliser de préférence l’URI **Session pooler** dans un environnement IPv4. L’URI doit terminer par `?sslmode=require`.

Ne jamais utiliser l’URL HTTP Supabase ou la clé `anon` comme `DATABASE_URL`. NACELUX se connecte côté serveur avec l’URI PostgreSQL.

## 2. Variables

Configurer également `SUPABASE_URL`, `SUPABASE_ANON_KEY` et `AUTH_REDIRECT_URL`. Dans le dashboard Supabase, ajouter l’URL NACELUX à **Authentication → URL Configuration → Redirect URLs**. Activer le provider Email et choisir si la confirmation email est obligatoire.

```bash
cp .env.example .env
```

Renseigner `DATABASE_URL` dans `.env`. Ce fichier est ignoré par Git.

## 3. Tester et migrer

```bash
pip install -r requirements.txt
python3 scripts/supabase_db.py test
python3 scripts/supabase_db.py migrate
python3 scripts/supabase_db.py copy-sqlite
```

Ou exécuter l’ensemble de façon idempotente:

```bash
python3 scripts/supabase_db.py setup
```

`setup` teste la connexion, applique les migrations additives puis copie les données SQLite avec `ON CONFLICT DO NOTHING`. Il ne supprime et n’écrase aucune ligne PostgreSQL existante.

## 4. Démarrer NACELUX

```bash
python3 backend/app.py
```

Avec `DATABASE_URL` et `DB_PROVIDER=postgresql`, toutes les lectures et écritures passent par PostgreSQL. L’endpoint `GET /api/v1/health/database` doit afficher `CONNECTED` et `supabase-postgresql`.

Quand les variables Auth sont présentes, NACELUX active automatiquement l’inscription, la connexion, la récupération et le changement de mot de passe. Au premier login vérifié, une organisation est créée dans une transaction et l’utilisateur reçoit le rôle `OWNER`. Les memberships suivants acceptent `OWNER`, `ADMIN` et `MEMBER`. Les jetons Supabase sont conservés dans des cookies `HttpOnly`; les mutations métier utilisent un jeton CSRF.

## Sécurité

- URI uniquement côté serveur.
- SSL obligatoire.
- Utiliser un mot de passe DB dédié et le faire tourner après exposition accidentelle.
- Ne jamais committer `.env`.
- Pour une charge élevée, préférer le pooler Supabase et limiter le nombre de connexions applicatives.
- Les migrations sont contrôlées par checksum et ne contiennent aucune suppression de table.
