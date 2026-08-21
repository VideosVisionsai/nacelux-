# Architecture technique — NACELUX Rev. 2.1

## Décisions

**Development/Test:** Python 3 standard library, API REST, explicit SQLite adapter and SPA without dependencies. **Production:** PostgreSQL over TLS, Supabase Auth, workers séparés, private object storage and reverse proxy. Production is fail-closed and never selects the development adapter.

### Composants cibles

1. Web app responsive
2. API stateless sécurisée
3. PostgreSQL avec isolation stricte par `organization_id`
4. Queue Redis-compatible + workers pour PDF/OCR/crawl/SEO/imports
5. Object storage S3-compatible pour documents et checksums
6. Scheduler persistant
7. Connecteurs externes isolés par interface
8. Observabilité: logs structurés, métriques, traces, audit

## Flux de données

`source → raw record → normalized record → validation → lineage → company graph → classification → digital intelligence → scoring → prospect`

Aucune donnée inconnue n'est convertie en valeur négative certaine. `NOT_CHECKED`, `NOT_FOUND`, `UNKNOWN` et `NOT_CONNECTED` restent distincts.

## Isolation SaaS

Toutes les requêtes métier sont filtrées par organisation. En production, cela est doublé par PostgreSQL Row Level Security avec un contexte transactionnel `app.organization_id`. Les exports, jobs, logs et clés API sont eux aussi tenant-scoped.

## Intégrations externes

### LBR / RESA

Aucune API publique n'est présumée. Le connecteur reste désactivé. Étapes requises: validation conditions/robots, identification du parcours public autorisé, browser worker Playwright à fréquence limitée, conservation URL/date/hash, capture des erreurs, tests de non-régression.

### Eurostat / NACE

La page officielle et le catalogue NACE Rev. 2.1 sont identifiés. Avant activation: choisir l'export officiel exact, documenter l'URL et le format, valider les langues et notes, importer en staging, contrôler le nombre de codes et publier atomiquement une version.

### Digital / SEO

Les contrôles passent exclusivement par le backend. Politiques: robots, timeouts, limites par domaine, user-agent identifiable, pas de contournement, cache, provenance de chaque observation.

## Sécurité avant production

- Auth OIDC ou mot de passe avec Argon2id
- Cookies session HttpOnly/Secure/SameSite, CSRF
- RBAC OWNER/ADMIN/MEMBER
- RLS PostgreSQL et tests de fuite inter-tenant
- Secrets manager; rotation des clés
- SSRF guard pour l'analyse de sites
- Antivirus et limites de taille pour PDF/imports
- Validation MIME et stockage hors webroot
- Rate limiting API
- Journal d'audit append-only
- Politique GDPR: minimisation, rétention, correction/suppression

## Roadmap d'exécution

- Phase 1: remplacer auth demo; migrer PostgreSQL; CRUD companies/taxonomie/géographie
- Phase 2: revue LBR, connecteur RESA, stockage document, extraction/OCR
- Phase 3: découverte website et people public avec matching explicable
- Phase 4: audit SEO et signaux
- Phase 5: poids de scoring administrables et versions de modèles
- Phase 6: prospects, XLSX/PDF et rapports asynchrones
- Phase 7: API keys, webhooks, scheduler et architecture billing

## Tests attendus

Unitaires: scoring, déduplication, normalisation RCS, taxonomie. Intégration: tenant isolation, import idempotent, lineage, retry jobs. Contract tests: connecteurs officiels. E2E: filtres, détail, export et promotion en prospect. Sécurité: SSRF, uploads, permissions et RLS.
