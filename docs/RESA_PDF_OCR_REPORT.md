# NACELUX — Rapport : Renforcement pipeline PDF RESA (PyMuPDF + OCRmyPDF)

Date : 2026-08-22 · Branche : `arena/01a0270b-nacelux` · Commit : `f3e2f10`

**Renforcement du pipeline existant (pas de reconstruction).** Chaîne 100 % open source. **Aucune donnée PDF/personne/rôle/OCR inventée.** OCR (OCRmyPDF + Tesseract + Ghostscript) n'étant **pas installé** dans cet environnement → **REQUIRES_CONFIGURATION** (non simulé).

## Chaîne
`PDF RESA → validation (magic/size/pages) → SHA-256 → PyMuPDF (texte natif) → si insuffisant : OCRmyPDF + Tesseract → extraction par page → TEXT/OCR/MIXED → qualité → evidence → nom+fonction+entreprise (explicite) → validation humaine → pipeline commercial existant`

## Outils
- **PyMuPDF** (`pymupdf` 1.28.2) — extraction texte natif : **VERIFIED** (PDF réel reportlab).
- **OCRmyPDF + Tesseract + Ghostscript** — OCR : **REQUIRES_CONFIGURATION** (binaires non installables ici, apt bloqué ; Dockerfile porte les dépendances).
- Langues **fra + deu + eng**. Aucun service OCR propriétaire.

## Statut extraction (live)
`native_text: AVAILABLE (PyMuPDF) | ocrmypdf: NOT_INSTALLED | ocr_status: REQUIRES_CONFIGURATION | engine_version: nacelux-pdf-extractor-2`

## Extraction (par document / par page)
- **Document** : document_id, checksum, méthode (TEXT/OCR/MIXED), langue, qualité, nombre de pages, date, version moteur, provenance. (schéma `document_extractions` existant + `ENGINE_VERSION` bumped.)
- **Page** : page_number, extracted_text, extraction_method, quality, checksum, document_id. (schéma `document_page_extractions` existant.)
- **Règle absolue respectée** : le texte natif n'est **jamais** remplacé silencieusement par l'OCR ; la provenance de chaque page est conservée (method TEXT/OCR).

## Validation PDF
`validate_pdf_bytes` : magic `%PDF-` + taille max. **VERIFIED** (PDF valide accepté ; non-PDF / magic corrompu / oversize rejetés). `_materialize` valide aussi le magic après vérification SHA-256 + checksum.

## Extraction des personnes — **VERIFIED**
- **Uniquement les rôles explicitement étiquetés** (gérant, administrateur, associé, directeur, représentant, manager, commissaire). **Jamais de rôle déduit** (test : nom sans titre → rien ; email seul → rien).
- Chaque personne : nom, rôle, confidence, page, extrait de preuve (evidence), méthode (`PDF_EXTRACTION`), date. Persistance `PENDING_REVIEW` (jamais présentée comme décideur vérifié avant validation).

## Validation humaine — **VERIFIED**
États : `PENDING_REVIEW` / `APPROVED` / `REJECTED`. `POST /api/v1/resa/documents/:id/review` enregistre reviewer (session), reviewed_at, décision, **ancienne valeur** (audit), commentaire. La preuve originale (people_evidence) n'est jamais modifiée/supprimée. Migration **0019** : `people` += review_status, reviewer, reviewed_at, review_comment, source_page, evidence_excerpt (miroir SQLite).

## API — **VERIFIED** (live)
| Route | Fonction |
|---|---|
| `GET /api/v1/resa/documents` | liste paginée |
| `GET /api/v1/resa/documents/:id` | détail + extractions |
| `GET /api/v1/resa/documents/:id/pages` | pages (texte + méthode + qualité) |
| `GET /api/v1/resa/documents/:id/evidence` | personnes + statut review |
| `POST /api/v1/resa/documents/:id/people` | extraction personnes (PENDING_REVIEW) |
| `POST /api/v1/resa/documents/:id/review` | validation humaine (APPROVED/REJECTED) |
Toutes **Auth + membership + RLS** (org serveur-side). Vérifié : statuts corrects, 404 sur doc inconnu, liste vide paginée.

## Jobs
`DOCUMENT_DOWNLOAD`, `PDF_EXTRACTION`, `OCR_PROCESSING` via la file atomique PostgreSQL (`FOR UPDATE SKIP LOCKED`, retries/backoff/orphan — vérifiés Étape 2). Idempotence extraction (extraction existante réutilisée). **VERIFIED** (mécanisme existant).

## Sécurité
Taille max, nombre max de pages, timeout, validation magic bytes, SHA-256, checksum stocké vs DB, stockage Supabase Storage privé (local dev isolé hors webroot), **protection path traversal** (`_materialize` résout et vérifie `root in path.parents`), hosts autorisés (connecteur RESA), aucune URL arbitraire comme preuve, aucun secret dans les logs (`redact_error`). **VERIFIED** (tests + existant).

## RLS / Tenant isolation
Tables `document_extractions`, `document_page_extractions`, `people`, `people_evidence`, `resa_documents` tenant-scoped ENABLE+FORCE. Les endpoints utilisent `self.org` (session). **VERIFIED** (RLS existant + Étapes 2/3).

## Tests — **190 passed, 0 failed, 21 skipped**
Suite RESA PDF/OCR (15) : validation (valide/non-PDF/corrompu/oversize), extraction native multilingue par page (FR/DE/EN), trop de pages, personne avec rôle explicite, personne sans rôle (pas de déduction), OCR REQUIRES_CONFIGURATION, extraction personnes PENDING_REVIEW, idempotence, flow de review (APPROVED + commentaire + preuve conservée), statut moteur. Skipped = suites PostgreSQL conditionnelles.

## Données
**AUCUNE DONNÉE PDF/PERSONNE/RÔLE/OCR INVENTÉE.** Les PDF de test sont générés par reportlab (test-only, jamais en runtime). OCR non simulé.

## Statuts par élément
| Élément | Statut |
|---|---|
| PyMuPDF texte natif (validation/magic/size/pages/per-page/multilingue) | **VERIFIED** |
| SHA-256 (checksum + validation) | **VERIFIED** |
| Extraction personnes explicites + page + evidence | **VERIFIED** |
| Validation humaine (PENDING_REVIEW/APPROVED/REJECTED) | **VERIFIED** |
| API documents/pages/evidence/review | **VERIFIED** |
| Jobs / RLS / tenant / path traversal / no-secrets | **VERIFIED** |
| OCR (OCRmyPDF + Tesseract + Ghostscript) | **REQUIRES_CONFIGURATION** (binaires absents ; Dockerfile porte les deps) |
| Extraction end-to-end sur un vrai PDF RESA | **NOT VERIFIED** (source RESA injoignable) |

## Configuration OCR (production)
Dockerfile installe déjà `tesseract-ocr` + `fra/deu/eng` ; ajouté `ghostscript` + `qpdf` ; `requirements` ajouté `ocrmypdf` + `pymupdf`. Avec ces dépendances, `has_ocrmypdf()` → AVAILABLE et le chemin OCR (TEXT insuffisant → OCRmyPDF) devient actif. Dans le sandbox actuel, OCR reste **REQUIRES_CONFIGURATION**.

## Limitations
- **REQUIRES_CONFIGURATION** : OCR réel (binaires non installables ici) ; source RESA réelle injoignable. Aucun résultat OCR simulé.
- **NOT VERIFIED** : extraction end-to-end sur un vrai PDF RESA (connecteur injoignable). La logique (native + personnes + review) est VERIFIED via un PDF réel reportlab.
- Scoring commercial : non développé.

---

VERIFIED = code exécuté + test réel + résultat observé. ARRÊT ici : aucune nouvelle fonctionnalité commencée.
