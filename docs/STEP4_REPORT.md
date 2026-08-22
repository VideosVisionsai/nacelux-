# NACELUX — Rapport Étape 4 (import officiel NACE Rev. 2.1)

Date : 2026-08-22 · Branche : `arena/01a0270b-nacelux` · Commit : `1e105d8`

**Aucune donnée NACE fictive en production.** La source officielle Eurostat/ShowVoc étant **inaccessible depuis cet environnement**, le téléchargement réel n'a **pas été simulé** : statut **REQUIRES CONFIGURATION**. Le pipeline, le parser, la validation, la sécurité, la transactionnalité, la déduplication, l'API et le frontend sont **VERIFIED** via fixtures + vrai PostgreSQL embarqué.

## Source officielle — **REQUIRES CONFIGURATION**
- Fournisseur : **Eurostat / ShowVoc** (RDF/XML). URL : `https://showvoc.op.europa.eu/semanticturkey/downloads/ESTAT_...NACE_2.1.../distributions/NACE_Rev_2.1.zip` (dans `NACE21_SOURCE_URL`).
- **Joignabilité** : `showvoc.op.europa.eu`, `ec.europa.eu`, `wikidata.org` sont **bloqués** depuis le sandbox (seuls `pypi.org`/`github.com` passent). Aucune source tierce/PyPI n'est utilisée comme « officielle » (interdit par le cahier des charges).
- Le pipeline capture et enregistre **toute** la provenance dès qu'il peut télécharger : URL, nom de fichier, format (RDF/XML ZIP), taille, Content-Type, HTTP status, SHA-256, retrieved_at, import_run_id.

## NACE — **REQUIRES CONFIGURATION** (import réel) · pipeline **VERIFIED**
Version `2.1`, statut **NOT_IMPORTED** (aucun import réel possible ici). Mécanisme version : `IMPORTING → ACTIVE` (atomique) ; échec → `FAILED` au niveau `nace_import_runs`, aucune nomenclature partielle active.

## Comptages réels — **NOT VERIFIED**
22 sections / 87 divisions / 287 groupes / 651 classes : exigés par `validate_parsed` (porte dure), mais **non observés** depuis un import réel (source injoignable). Aucune donnée modifiée pour atteindre ces chiffres. À observer via `TestRealOfficialDownload` (`NACE_RUN_REAL_DOWNLOAD=1`) quand le réseau le permettra.

## Langues — pipeline **VERIFIED**, données réelles **NOT VERIFIED**
FR/DE/EN : import des `prefLabel` réellement présents ; libellé absent → **NULL** (jamais traduit). Vérifié sur fixture (12 libellés = 4 items × 3 langues). Labels officiels réels : NOT VERIFIED.

## Notes — pipeline **VERIFIED**, réelles **NOT VERIFIED**
Notes `scopeNote`/`INCLUDES`/`EXCLUDES` importées telles quelles (jamais résumées) avec langue, code, URI, provenance. Vérifié sur fixture (1 note). Réelles : NOT VERIFIED.

## Correspondances — pipeline **VERIFIED**, réelles **NOT VERIFIED**
Correspondances Rev.2 → Rev.2.1 importées uniquement si présentes dans la source ; aucune créée manuellement ; provenance conservée. Vérifié sur fixture. Réelles : NOT VERIFIED.

## API — **VERIFIED**
`GET /api/v1/nace` : recherche par **code** (`code=62`), par **libellé** (`q=software`), filtres **level / language / version**, **pagination** (`limit`/`offset`, max 200), métadonnées `pagination`. `GET /api/v1/nace/:code` (détail + notes + correspondances + labels multilingues) inchangé. `POST /api/v1/nace/import` et job `NACE_SYNC` inchangés (via le pipeline durci). Vérifié en HTTP (code/q/level/pagination).

## Frontend — **VERIFIED**
Page NACE : version, statut, checksum, retrieved_at, comptages (sections/divisions/groups/classes), recherche, filtres langue, **pagination**. État vide explicite **« NACE OFFICIAL DATA NOT AVAILABLE »** quand non importé (vérifié en live : `status: NOT_IMPORTED`, total 0). Aucune donnée synthétique affichée.

## Jobs — **VERIFIED**
`NACE_SYNC` traité par le worker via la file atomique PostgreSQL (`app_claim_jobs`, `FOR UPDATE SKIP LOCKED`, `SECURITY DEFINER`) — deux workers ne peuvent pas importer deux fois la même version (déjà vérifié étape 2 ; déduplication par checksum en amont). Soumission synchrone `POST /api/v1/nace/import` et `/jobs` toujours disponibles.

## Sécurité — **VERIFIED**
- **SSRF** : `validate_source` épingle l'hôte officiel HTTPS + chemin (toute autre URL refusée) ; aucune URL utilisateur téléchargée.
- **XML/XXE** : parsing sécurisé via `defusedxml` (DTO/entities externes interdits) ; test XXE : aucune fuite de fichier.
- **Taille/timeout** : `NACE21_MAX_BYTES` (défaut 25 Mo), timeout `NACE21_DOWNLOAD_TIMEOUT`, contrôle magic ZIP. Testés (oversize → refus, non-zip → refus).
- **Redirections** : `_SafeRedirect` refuse toute redirection quittant l'hôte officiel.
- **Secrets** : aucun log de `DATABASE_URL`/clé service-role/JWT/mot de passe ; `redact_error` appliqué.
- **RLS/tenant** : tables NACE de référence **globales** (aucune `organization_id` → aucun vecteur de fuite tenant), lisibles par tous les tenants (partagées) ; `companies` reste isolé. **Correctif RLS 0017** : les rôles importeur (`nacelux_runtime`/`nacelux_worker`) n'avaient ni privilege INSERT ni policy d'écriture sur `nace_*_official` → `NACE_SYNC` production aurait échoué. Corrigé (grants + policy). Vérifié sur vrai PostgreSQL.

## Tests — **128 passed, 0 failed, 21 skipped**
- `unittest discover` : 128 OK, 21 skipped (18 suites PostgreSQL conditionnelles + 1 téléchargement réel NACE gated + 2 NACE-RLS gated).
- Step 4 (SQLite/fixtures) : 17 OK (parser, validation, hiérarchie, SSRF, XXE, redirect, taille/magic, persist atomique, idempotence, échec close, dédup, API).
- Step 4 (vrai PostgreSQL embarqué) : 2/2 NACE RLS (pas tenant-scoped, importeur écrit, les deux tenants lisent).

## Fichiers modifiés
- `backend/nace_importer.py` (durci + refactorisé : `_download`, `persist_parsed`, `validate_parsed`, `hierarchy_anomalies`, `_SafeRedirect`, dédup checksum, parsing XXE-safe)
- `backend/app.py` (API NACE code/q/level/version/pagination ; dashboard NULL-score-safe)
- `frontend/app.js` (page NACE : état vide, recherche, pagination)
- `requirements.txt` (`defusedxml`)
- `database/migrations/0017_nace_reference_write_access.sql` (correctif RLS NACE)
- `tests/test_step4_nace.py`, `tests/run_step4_embedded.py` (nouveaux)

## Statuts
| Élément | Statut |
|---|---|
| Source officielle (URL/provenance) | code VERIFIED · téléchargement réel **REQUIRES CONFIGURATION** |
| Téléchargement sécurisé (SSRF/size/magic/redirect/XXE) | **VERIFIED** |
| Checksum SHA-256 | **VERIFIED** |
| Parser RDF/XML | **VERIFIED** (fixture) |
| Version IMPORTING/ACTIVE/FAILED | **VERIFIED** |
| Rollback / atomicité | **VERIFIED** |
| Déduplication checksum | **VERIFIED** |
| Comptages 22/87/287/651 | **NOT VERIFIED** (source injoignable) |
| FR/DE/EN (réels) | **NOT VERIFIED** |
| Notes / Correspondances (réelles) | **NOT VERIFIED** |
| Hiérarchie | **VERIFIED** (détection d'anomalies) |
| API NACE | **VERIFIED** |
| Frontend NACE | **VERIFIED** |
| NACE_SYNC / file atomique | **VERIFIED** |
| RLS NACE + correctif 0017 | **VERIFIED** |
| Tenant isolation (companies) | **VERIFIED** |

## Données inventées
**AUCUNE DONNÉE NACE INVENTÉE EN PRODUCTION.** Les fixtures NACE sont **test-only** (`tests/test_step4_nace.py`), ne sont jamais chargées en runtime, et ne peuvent pas devenir la nomenclature de production : `validate_parsed` refuse tout jeu de données dont les comptes diffèrent de 22/87/287/651. La base de prod reste sans nomenclature officielle jusqu'à un import réel.

---

**Pour passer les éléments NOT VERIFIED → VERIFIED** : exécuter l'import depuis un environnement avec accès réseau à `showvoc.op.europa.eu`, via `NACE_RUN_REAL_DOWNLOAD=1` (déclenche `TestRealOfficialDownload`) ou via l'UI/le job `NACE_SYNC`. Je m'arrête à la fin de l'Étape 4 (pas d'Étape 5 automatique).
