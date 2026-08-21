# Pipeline RESA → PDF → Storage

## Étapes

1. Une ligne RESA conserve son lien documentaire public.
2. `DOCUMENT_DOWNLOAD` valide l’organisation et le document.
3. L’URL doit être HTTPS et appartenir à un host LBR autorisé.
4. Chaque redirection est validée avec la même allowlist.
5. Le téléchargement est streamé avec une limite de taille.
6. Le contenu doit contenir une signature `%PDF-`; une page HTML n’est jamais stockée comme PDF.
7. SHA-256 et taille sont calculés pendant le téléchargement.
8. Un checksum déjà connu est relié à l’objet existant sans nouvel upload.
9. Le PDF est écrit sous une clé immuable contenant son checksum.
10. `resa_documents` reçoit le provider, bucket, clé, checksum, MIME, taille et date.

## Providers

### Local — développement

```env
DOCUMENT_STORAGE_PROVIDER=local
LOCAL_DOCUMENT_STORAGE_DIR=data/document-storage
```

L’écriture utilise un fichier temporaire puis un renommage atomique.

### Supabase Storage — production

```env
DOCUMENT_STORAGE_PROVIDER=supabase
SUPABASE_URL=https://PROJECT_REF.supabase.co
SUPABASE_STORAGE_BUCKET=resa-documents
SUPABASE_SERVICE_ROLE_KEY=server-secret
```

La service-role key reste exclusivement côté serveur. Elle n’est jamais incluse dans l’API ou le frontend. Le bucket doit être privé; l’accès futur se fera par URL signée et autorisation tenant.

## Modèle

La migration additive `0004_resa_pdf_storage.sql` étend `resa_documents` et crée `storage_objects`. Aucun fichier ou enregistrement existant n’est supprimé.

Statuts de téléchargement:

- `NOT_DOWNLOADED`
- `DOWNLOADING`
- `STORED`
- `DUPLICATE`
- `FAILED`

## API et job

- `POST /api/v1/resa/documents/{id}/store`
- `POST /api/v1/jobs` avec `job_type=DOCUMENT_DOWNLOAD` et `document_id`

Toutes les opérations restent liées à `organization_id` et sont journalisées.
