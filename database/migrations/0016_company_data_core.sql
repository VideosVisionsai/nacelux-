-- NACELUX Rev. 2.1 — Data-import core (ÉTAPE 3).
-- Additive and idempotent: no DROP/TRUNCATE, no seed/demo data.
-- Extends companies / data_sources / raw_records / data_lineage for provenance,
-- checksums and retrieval timestamps, and adds dedup_candidates + imports.
-- New tenant tables are RLS-enabled + forced and isolated via membership proof.

-- 1. companies: provenance summary, source link, retrieval time, content checksum
ALTER TABLE companies ADD COLUMN IF NOT EXISTS source_id text;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS retrieved_at timestamptz;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS provenance text;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS checksum text;
CREATE INDEX IF NOT EXISTS idx_company_checksum ON companies(organization_id, checksum);

-- 2. data_sources: provider, version, source checksum, configuration, timestamps
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS provider text;
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS source_version text;
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS source_checksum text;
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS configuration jsonb NOT NULL DEFAULT '{}';
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS retrieved_at timestamptz;
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
-- Allowed status values (enforced in code): ACTIVE, INACTIVE, REQUIRES_CONFIRMATION, FAILED.

-- 3. raw_records: explicit raw content, format, status and metadata
ALTER TABLE raw_records ADD COLUMN IF NOT EXISTS source_url text;
ALTER TABLE raw_records ADD COLUMN IF NOT EXISTS raw_content text;
ALTER TABLE raw_records ADD COLUMN IF NOT EXISTS content_format text;
ALTER TABLE raw_records ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'RAW';
ALTER TABLE raw_records ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_raw_records_ext ON raw_records(organization_id, source_id, external_id);
CREATE INDEX IF NOT EXISTS idx_raw_records_checksum ON raw_records(organization_id, checksum);

-- 4. data_lineage: link to the raw record, content checksum and transformation step
ALTER TABLE data_lineage ADD COLUMN IF NOT EXISTS raw_record_id text REFERENCES raw_records(id);
ALTER TABLE data_lineage ADD COLUMN IF NOT EXISTS checksum text;
ALTER TABLE data_lineage ADD COLUMN IF NOT EXISTS transformation text;
CREATE INDEX IF NOT EXISTS idx_lineage_entity ON data_lineage(organization_id, entity_type, entity_id);

-- 5. dedup_candidates: possible duplicates recorded but NEVER auto-merged.
--    A row here means "these two might be the same entity"; it is never proof.
CREATE TABLE IF NOT EXISTS dedup_candidates(
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    company_a_id text NOT NULL REFERENCES companies(id),
    company_b_id text NOT NULL REFERENCES companies(id),
    match_basis text NOT NULL,                       -- e.g. NAME_SIMILARITY (never an official id)
    confidence numeric(4,3),
    status text NOT NULL DEFAULT 'PENDING',          -- PENDING | CONFIRMED_SAME | REJECTED
    metadata jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    CHECK (company_a_id <> company_b_id),
    CHECK (match_basis NOT IN ('RCS','VAT','EXTERNAL_ID'))  -- official ids resolve directly, never as "candidates"
);
CREATE INDEX IF NOT EXISTS idx_dedup_tenant ON dedup_candidates(organization_id, status);

-- 6. imports: transactional import registry / audit
CREATE TABLE IF NOT EXISTS imports(
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    source_id text REFERENCES data_sources(id),
    import_type text NOT NULL,
    status text NOT NULL,                             -- RUNNING | SUCCESS | FAILED | PARTIAL
    records_received integer NOT NULL DEFAULT 0,
    records_valid integer NOT NULL DEFAULT 0,
    records_created integer NOT NULL DEFAULT 0,
    records_updated integer NOT NULL DEFAULT 0,
    records_skipped integer NOT NULL DEFAULT 0,
    records_failed integer NOT NULL DEFAULT 0,
    error_summary text,
    metadata jsonb NOT NULL DEFAULT '{}',
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);
CREATE INDEX IF NOT EXISTS idx_imports_tenant ON imports(organization_id, started_at DESC);

-- 7. RLS on the new tenant tables (enable + force + membership policy)
ALTER TABLE dedup_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE dedup_candidates FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_dedup_candidates ON dedup_candidates;
CREATE POLICY tenant_isolation_dedup_candidates ON dedup_candidates
    FOR ALL USING (app_user_has_org_access(organization_id))
    WITH CHECK (app_user_has_org_access(organization_id));

ALTER TABLE imports ENABLE ROW LEVEL SECURITY;
ALTER TABLE imports FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_imports ON imports;
CREATE POLICY tenant_isolation_imports ON imports
    FOR ALL USING (app_user_has_org_access(organization_id))
    WITH CHECK (app_user_has_org_access(organization_id));

-- 8. Grants to the non-owner runtime/worker roles (created out-of-band)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nacelux_runtime') THEN
        EXECUTE 'GRANT SELECT,INSERT,UPDATE,DELETE ON dedup_candidates,imports TO nacelux_runtime';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nacelux_worker') THEN
        EXECUTE 'GRANT SELECT,INSERT,UPDATE,DELETE ON dedup_candidates,imports TO nacelux_worker';
    END IF;
END $$;
