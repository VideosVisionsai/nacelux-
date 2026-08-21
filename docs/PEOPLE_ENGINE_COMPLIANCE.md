# People Engine conforme

## Périmètre strict

Le moteur conserve uniquement:

- nom professionnel public;
- rôle officiel;
- entreprise associée;
- URL professionnelle publique;
- provenance;
- confiance et statut du rapprochement.

Il ne prévoit aucun champ pour date de naissance, adresse privée, email personnel, téléphone privé, nationalité ou données familiales.

## Dirigeants officiels

La source primaire est un document RESA public déjà stocké, validé, extrait et relié au RCS de l’entreprise.

Le moteur reconnaît uniquement des formulations explicites telles que:

- `Gérant : Jean Dupont`
- `Marie Dupont, administratrice`
- `Geschäftsführer: Max Mustermann`
- `Managing Director: Jane Smith`

Chaque personne officielle conserve:

- document source;
- extraction source;
- URL LBR;
- extrait justificatif;
- méthode `REGEX_EXPLICIT_ROLE_LABEL`;
- confiance;
- date de contrôle.

Une mention non explicite n’est pas transformée en dirigeant.

## Profils professionnels publics

La recherche utilise uniquement l’API de recherche documentée déjà configurée. NACELUX ne charge ni ne scrape les pages protégées LinkedIn.

Signaux de rapprochement:

- nom exact;
- entreprise;
- rôle;
- contexte Luxembourg/localisation;
- URL publique `linkedin.com/in/`.

Seuls les profils avec une confiance supérieure au seuil, 82 % par défaut, sont stockés. Statuts:

- `CONFIRMED` à partir de 92 %;
- `PROBABLE` de 82 % à 91 %;
- en dessous: non stocké.

Sans API de recherche configurée, le statut est `NOT_CONFIGURED`; aucun profil n’est inventé.

## GDPR

- minimisation des données;
- finalité professionnelle;
- provenance obligatoire;
- durée de rétention configurable;
- demandes `ACCESS`, `CORRECTION`, `SUPPRESSION`, `OBJECTION`;
- mise en revue immédiate lors d’une demande de suppression/opposition;
- aucune donnée privée ou sensible.

## Modèle

Migration additive: `database/migrations/0009_compliant_people_engine.sql`

- extensions de `people`;
- `people_engine_runs`;
- `people_evidence`;
- `professional_profiles_public`;
- `privacy_requests`.

## API et job

- `POST /api/v1/companies/{id}/people-intelligence`
- `GET /api/v1/people`
- `POST /api/v1/people/{id}/privacy-request`
- job `PEOPLE_INTELLIGENCE`
