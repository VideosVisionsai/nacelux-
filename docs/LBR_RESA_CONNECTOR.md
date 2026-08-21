# Connecteur officiel-public LBR / RESA

## Limite d’intégration

Le connecteur utilise uniquement les pages publiques canoniques:

`https://www.lbr.lu/mjrcs-web-front/publication-journal/RESA-YYYY_…`

Il n’appelle pas `/mjrcs-web-api`, `/mjrcs-web-front/api` ou une API supposée. `robots.txt` est contrôlé avant chaque analyse. Au 20 août 2026, le chemin public `publication-journal` n’est pas interdit, tandis que plusieurs chemins API/auth le sont.

## Pipeline

1. Validation stricte du host, HTTPS et chemin.
2. Consultation de `robots.txt`.
3. Requête HTML standard avec user-agent identifiable.
4. Si aucune ligne n’est disponible parce que la page est rendue en JavaScript, lancement de Playwright.
5. Détection conservative des lignes visibles et liens documentaires.
6. Blocage explicite si Friendly Captcha reste requis. Aucun contournement.
7. Normalisation RCS et extraction uniquement des champs explicitement libellés.
8. Hash du snapshot, des lignes et URLs.
9. Upsert idempotent des journaux, lignes et documents.
10. Historique complet du run et artefact HTML local pour adapter les sélecteurs.

## Modèle

- `resa_journals`
- `resa_entries`
- `resa_documents`
- `resa_sync_runs`

La migration `0003_lbr_resa_connector.sql` est additive. Aucun objet existant n’est supprimé.

## Statuts

- Run: `RUNNING`, `SUCCESS`, `BLOCKED`, `FAILED`, `INVALIDATED`
- Changement ligne: `NEW`, `UPDATED`, `UNCHANGED`, `DUPLICATE`
- Captcha: `NOT_PRESENT`, `RESOLVED`, `REQUIRED`
- Documents: `NOT_DOWNLOADED`, puis pipeline futur de téléchargement/extraction
- Type: `PDF` uniquement si l’URL l’indique explicitement; sinon `PUBLIC_DOCUMENT_LINK`

Une page rendue avec zéro ligne n’est jamais déclarée réussie.

## Configuration

```env
LBR_RESA_ENABLED=true
LBR_RESA_HEADLESS=true
LBR_RESA_TIMEOUT_MS=45000
LBR_RESA_MIN_INTERVAL_SECONDS=8
LBR_USER_AGENT=NACELUX/1.0 (+https://your-domain.example/data-policy; contact@example.com)
LBR_RESA_ARTIFACT_DIR=data/resa-artifacts
```

L’activation doit suivre une validation interne des conditions LBR et une fréquence raisonnable. Pour un captcha nécessitant une interaction légitime, un opérateur peut lancer un navigateur visible:

```bash
python3 -m playwright install chromium
python3 scripts/resa_sync.py --headed 'https://www.lbr.lu/mjrcs-web-front/publication-journal/RESA-…'
```

Le mode `--headed` n’automatise pas la résolution du captcha.

## Synchronisations futures

`RESA_SYNC` accepte une `source_url`, crée un run auditable et reste idempotent. Un scheduler pourra fournir les URLs de journaux connues sans modifier la logique de stockage. La découverte automatique de journaux n’est pas activée tant qu’un parcours public conforme n’a pas été validé.
