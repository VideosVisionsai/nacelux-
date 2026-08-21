# Website Discovery & Digital Footprint

## Website Discovery

Le moteur utilise uniquement des APIs de recherche documentées:

- Brave Search API: `https://api.search.brave.com/res/v1/web/search`
- Google Programmable Search: `https://www.googleapis.com/customsearch/v1`

Aucune page de résultats de recherche n’est scrapée.

Chaque candidat est vérifié côté backend avec:

- correspondance des mots de la dénomination;
- correspondance du domaine;
- nom exact;
- RCS public s’il est présent sur le site;
- commune;
- titre et contenu de la page.

Le résultat contient `website_url`, `confidence`, `discovery_source` et une liste de preuves. Le seuil par défaut est 0,72.

Les protections SSRF bloquent les réseaux privés, loopback, link-local, adresses réservées, credentials URL et ports non web. Chaque redirection est revalidée.

## Digital Footprint

Canaux:

- `Website`
- `LinkedIn company`
- `Google Business`
- `Facebook`

Statuts:

- `FOUND`: correspondance suffisamment forte après un contrôle exécuté;
- `NOT_FOUND`: source configurée, requête réussie, aucun résultat qualifié;
- `UNKNOWN`: résultat ambigu ou erreur ne permettant pas de conclure;
- `NOT_CHECKED`: connecteur non configuré ou contrôle non lancé.

NACELUX ne consulte pas directement les pages protégées LinkedIn ou Facebook. Les URLs publiques sont identifiées dans les résultats d’une API de recherche documentée.

Google Business utilise l’API officielle Google Places (New), endpoint `places:searchText`. `NOT_FOUND` n’est attribué qu’après une réponse valide sans correspondance.

## Configuration

### Brave

```env
SEARCH_PROVIDER=brave
BRAVE_SEARCH_API_KEY=server-secret
```

### Google Programmable Search

```env
SEARCH_PROVIDER=google_custom_search
GOOGLE_CUSTOM_SEARCH_API_KEY=server-secret
GOOGLE_CUSTOM_SEARCH_CX=search-engine-id
```

### Google Business

```env
GOOGLE_PLACES_API_KEY=server-secret
```

Les clés restent exclusivement côté serveur.

## Modèle et API

Migration additive: `database/migrations/0007_website_digital_intelligence.sql`

Tables:

- `website_discovery_runs`
- `website_candidates`
- `digital_checks`
- `google_business_profiles`

Endpoints:

- `POST /api/v1/companies/{id}/discover-website`
- `POST /api/v1/companies/{id}/digital-footprint`
- `GET /api/v1/digital`

Jobs:

- `WEBSITE_DISCOVERY`
- `DIGITAL_FOOTPRINT_CHECK`

Sans clé configurée, les canaux restent `NOT_CHECKED`. Ils ne sont jamais transformés artificiellement en `NOT_FOUND`.
