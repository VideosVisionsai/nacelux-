# Pipeline PDF → Texte → OCR si nécessaire

## Pipeline

1. Charger le PDF depuis l’objet local ou le bucket Supabase privé.
2. Vérifier de nouveau le checksum SHA-256 avant traitement.
3. Extraire le texte natif page par page avec `pypdf`.
4. Calculer la qualité de chaque page: volume, caractères imprimables et proportion alphanumérique.
5. Déclencher l’OCR uniquement pour les pages sous les seuils configurés.
6. Rendre la page à 300 DPI avec PDFium.
7. Exécuter Tesseract avec les langues FR, DE et EN.
8. Comparer texte natif et OCR; conserver le meilleur résultat sauf OCR forcé.
9. Stocker texte, méthode, confiance, qualité et lineage par page.
10. Produire une extraction globale `TEXT`, `OCR` ou `MIXED`.

## Modèle

Migration additive: `database/migrations/0005_pdf_text_ocr.sql`

- `document_extractions`: résultat global, hash du texte, version moteur, statut et erreurs.
- `document_page_extractions`: texte et méthode par page, score de qualité et confiance OCR.
- `resa_documents.extraction_status`: état courant du pipeline.

Aucune extraction précédente n’est supprimée. La contrainte organisation/document/checksum/version rend les reprises idempotentes.

## Configuration

```env
PDF_EXTRACTION_MAX_PAGES=100
PDF_TEXT_MIN_CHARS_PER_PAGE=80
PDF_TEXT_MIN_QUALITY=0.55
PDF_OCR_ENABLED=true
PDF_OCR_LANGUAGES=fra+deu+eng
PDF_OCR_DPI=300
PDF_OCR_TIMEOUT_SECONDS=90
```

Dépendances système en production:

```bash
apt-get install tesseract-ocr tesseract-ocr-fra tesseract-ocr-deu tesseract-ocr-eng
pip install -r requirements.txt
```

## API et jobs

- `POST /api/v1/resa/documents/{id}/extract`
- Corps facultatif: `{"force_ocr": true}`
- `GET /api/v1/resa/extractions/{id}`
- Jobs `PDF_EXTRACTION` et `OCR_PROCESSING`

## Statuts

- `NOT_STARTED`
- `RUNNING`
- `SUCCESS`
- `PARTIAL`: texte disponible mais au moins une page OCR a échoué
- `FAILED`

Une absence totale de texte après OCR est un échec explicite, jamais une extraction vide réussie.
