# Import officiel NACE Rev. 2.1

## Source

Le connecteur télécharge directement la distribution RDF/XML publiée dans l’onglet **Downloads** du dataset Eurostat ShowVoc NACE Rev. 2.1:

`https://showvoc.op.europa.eu/semanticturkey/downloads/.../distributions/NACE_Rev_2.1.zip`

Le ZIP officiel et son checksum SHA-256 sont conservés dans `data/nace-imports`. Aucune position, note ou correspondance n’est saisie manuellement.

## Données importées

- 22 sections
- 87 divisions
- 287 groupes
- 651 classes
- libellés officiels FR, DE et EN pour les 1 047 positions
- notes `SCOPE`, `INCLUDES`, `INCLUDES_ALSO`, `EXCLUDES`
- correspondances officielles inversées sémantiquement en direction NACE Rev. 2 → NACE Rev. 2.1

La distribution décrit la relation NACE 2.1 → NACE 2 avec des concepts source/cible officiels. NACELUX conserve l’URI de mapping et expose la direction demandée Rev. 2 → Rev. 2.1 sans inventer de correspondance.

## Validation avant activation

L’import est refusé si:

- le host ou le chemin ne correspond pas à la distribution ShowVoc officielle;
- le fichier n’est pas un ZIP;
- le ZIP ne contient pas exactement `NACE_Rev_2.1.rdf`;
- les nombres de sections/divisions/groupes/classes diffèrent des totaux officiels;
- un des jeux de libellés FR/DE/EN est incomplet;
- aucune note explicative n’est disponible;
- la table de correspondance est manifestement incomplète.

La version passe à `ACTIVE` uniquement après tous les contrôles.

## Modèle

Migration additive: `database/migrations/0006_official_nace_21.sql`

- `nace_versions_official`
- `nace_items_official`
- `nace_labels_official`
- `nace_notes_official`
- `nace_correspondences_official`
- `nace_import_runs`

La table historique `nace_codes` n’est ni supprimée ni écrasée. Les positions absentes d’une future distribution sont désactivées par `is_current=false`, jamais supprimées.

## Exécution

```bash
python3 scripts/import_nace21.py
```

Ou:

```http
POST /api/v1/nace/import
```

Le job `NACE_SYNC` appelle le même importeur idempotent.
