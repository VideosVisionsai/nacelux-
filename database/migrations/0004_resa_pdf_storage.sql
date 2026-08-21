-- RESA PDF storage metadata. Additive only; no existing object is deleted.
ALTER TABLE resa_documents ADD COLUMN IF NOT EXISTS storage_object_id text;
ALTER TABLE resa_documents ADD COLUMN IF NOT EXISTS storage_provider text;
ALTER TABLE resa_documents ADD COLUMN IF NOT EXISTS storage_bucket text;
ALTER TABLE resa_documents ADD COLUMN IF NOT EXISTS storage_key text;
ALTER TABLE resa_documents ADD COLUMN IF NOT EXISTS mime_type text;
ALTER TABLE resa_documents ADD COLUMN IF NOT EXISTS size_bytes bigint;
ALTER TABLE resa_documents ADD COLUMN IF NOT EXISTS downloaded_at timestamptz;
ALTER TABLE resa_documents ADD COLUMN IF NOT EXISTS http_status integer;
ALTER TABLE resa_documents ADD COLUMN IF NOT EXISTS last_error text;
CREATE TABLE IF NOT EXISTS storage_objects(
 id text PRIMARY KEY, organization_id text NOT NULL REFERENCES organizations(id),
 provider text NOT NULL, bucket text NOT NULL, object_key text NOT NULL,
 checksum_sha256 text NOT NULL, size_bytes bigint NOT NULL, mime_type text NOT NULL,
 original_filename text, source_url text, local_reference text,
 created_at timestamptz NOT NULL, verified_at timestamptz,
 UNIQUE(organization_id,checksum_sha256), UNIQUE(provider,bucket,object_key));
CREATE INDEX IF NOT EXISTS storage_objects_checksum_idx ON storage_objects(organization_id,checksum_sha256);
CREATE INDEX IF NOT EXISTS resa_documents_storage_idx ON resa_documents(organization_id,download_status,storage_object_id);
