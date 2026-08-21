# Business Signal Engine

## Principe

Un signal négatif n’est créé que si sa preuve requise existe. Un champ `UNKNOWN` ou un connecteur absent ne produit jamais `NO_WEBSITE` ou `NO_GOOGLE_BUSINESS`.

## Règles version 1.0

- `NEW_COMPANY`: création dans les 90 derniers jours.
- `RECENT_INCORPORATION`: création dans les 30 derniers jours.
- `NO_WEBSITE`: contrôle Website terminé avec `NOT_FOUND` et sans erreur.
- `WEAK_WEBSITE`: site trouvé et Digital Score inférieur à 40.
- `WEAK_SEO`: audit SEO réussi avec score inférieur à 50.
- `NO_GOOGLE_BUSINESS`: contrôle Google Places terminé avec `NOT_FOUND` et sans erreur.
- `DECISION_MAKER_FOUND`: dirigeant officiel ou profil professionnel ≥ 82 %.
- `HIGH_VALUE_NICHE`: attractivité de niche ≥ 80.

Chaque signal conserve valeur, confiance, source, preuve, explication, sévérité, version de règle, qualité de donnée, première détection, dernière observation et expiration éventuelle.

## Cycle de vie

À chaque recalcul:

1. évaluer les règles sur les preuves actuelles;
2. réactiver ou créer les signaux valides;
3. marquer `INACTIVE` les signaux qui ne sont plus justifiés;
4. ne supprimer aucune ligne historique;
5. journaliser activations et désactivations.

## Modèle

Migration additive: `database/migrations/0010_business_signal_engine.sql`

- extensions de `business_signals`;
- `business_signal_runs`;
- `business_signal_definitions`.

## API et automation

- `GET /api/v1/signals`
- `POST /api/v1/signals/refresh`
- job `BUSINESS_SIGNAL_REFRESH`

Les seuils sont configurables par variables d’environnement et chaque changement de logique doit incrémenter `SIGNAL_RULE_VERSION`.
