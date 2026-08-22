-- NACELUX Rev. 2.1 — Generic pipeline staging and document registry.
-- Additive and idempotent: no DROP, TRUNCATE, or destructive ALTER statements.
-- Both tables are tenant-scoped (organization_id) and protected by Row Level
-- Security, mirroring the hardened posture installed by migrations 0011/0013.
-- No seed, demo or fixture data is introduced here.

-- 1. raw_records: canonical staging area for ingested records before enrichment.
CREATE TABLE IF NOT EXISTS raw_records(
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    source_id text REFERENCES data_sources(id),
    external_id text,
    payload jsonb NOT NULL DEFAULT '{}',
    checksum text,
    retrieved_at timestamptz NOT NULL DEFAULT now(),
    stage text NOT NULL DEFAULT 'RAW',
    UNIQUE(organization_id, source_id, external_id, checksum)
);
CREATE INDEX IF NOT EXISTS idx_raw_records_tenant ON raw_records(organization_id);
CREATE INDEX IF NOT EXISTS idx_raw_records_org_stage ON raw_records(organization_id, stage);

-- 2. documents: generic document registry (any source/provider), distinct from the
--    RESA-specific resa_documents table. Points at the immutable storage object.
CREATE TABLE IF NOT EXISTS documents(
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    source_id text REFERENCES data_sources(id),
    source_url text NOT NULL,
    storage_key text,
    storage_object_id text REFERENCES storage_objects(id),
    document_type text DEFAULT 'PDF',
    publication_date date,
    downloaded_at timestamptz,
    checksum text,
    download_status text DEFAULT 'NOT_DOWNLOADED',
    extraction_status text DEFAULT 'NOT_STARTED',
    UNIQUE(organization_id, checksum)
);
CREATE INDEX IF NOT EXISTS idx_documents_tenant ON documents(organization_id);
CREATE INDEX IF NOT EXISTS idx_documents_org_type ON documents(organization_id, document_type);

-- 3. Row Level Security: enable + FORCE so even the table owner is subject to
--    tenant isolation. Access is granted only to the authenticated membership via
--    the app_user_has_org_access() helper (which never trusts organization_id
--    alone — it requires the backend-proven app.user_id + membership).
ALTER TABLE raw_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_records FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_raw_records ON raw_records;
CREATE POLICY tenant_isolation_raw_records ON raw_records
    FOR ALL USING (app_user_has_org_access(organization_id))
    WITH CHECK (app_user_has_org_access(organization_id));

ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_documents ON documents;
CREATE POLICY tenant_isolation_documents ON documents
    FOR ALL USING (app_user_has_org_access(organization_id))
    WITH CHECK (app_user_has_org_access(organization_id));

-- 4. Grant the non-owner runtime + worker roles the same CRUD as other tenant
--    tables. Roles are created out-of-band (see DEPLOY.md); guard with IF EXISTS
--    so this migration remains applicable in any environment that has them.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nacelux_runtime') THEN
        EXECUTE 'GRANT SELECT,INSERT,UPDATE,DELETE ON raw_records,documents TO nacelux_runtime';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nacelux_worker') THEN
        EXECUTE 'GRANT SELECT,INSERT,UPDATE,DELETE ON raw_records,documents TO nacelux_worker';
    END IF;
END $$;
