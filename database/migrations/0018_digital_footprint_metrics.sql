-- NACELUX Rev. 2.1 — Website/digital-footprint technical metrics + history (ÉTAPE 5).
-- Additive and idempotent. No seed/demo data.

-- 1. digital_checks: technical verification columns (in addition to details/evidence jsonb)
ALTER TABLE digital_checks ADD COLUMN IF NOT EXISTS http_status integer;
ALTER TABLE digital_checks ADD COLUMN IF NOT EXISTS response_ms integer;
ALTER TABLE digital_checks ADD COLUMN IF NOT EXISTS page_bytes integer;
ALTER TABLE digital_checks ADD COLUMN IF NOT EXISTS https_status text;
ALTER TABLE digital_checks ADD COLUMN IF NOT EXISTS final_url text;
ALTER TABLE digital_checks ADD COLUMN IF NOT EXISTS value text;
ALTER TABLE digital_checks ADD COLUMN IF NOT EXISTS explanation text;
ALTER TABLE digital_checks ADD COLUMN IF NOT EXISTS rule_version text;

-- 2. Append-only history: every check is recorded, never silently overwritten,
--    so site-present -> site-gone and weak -> improved can be detected later.
CREATE TABLE IF NOT EXISTS digital_check_history(
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    company_id text NOT NULL REFERENCES companies(id),
    channel text NOT NULL,
    status text NOT NULL,
    source_url text,
    http_status integer,
    response_ms integer,
    page_bytes integer,
    https_status text,
    final_url text,
    checked_at timestamptz NOT NULL DEFAULT now(),
    details jsonb NOT NULL DEFAULT '{}',
    rule_version text
);
CREATE INDEX IF NOT EXISTS idx_dch_tenant ON digital_check_history(organization_id, company_id, channel, checked_at DESC);

-- 3. RLS on the history table (tenant-scoped via membership proof)
ALTER TABLE digital_check_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE digital_check_history FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_digital_check_history ON digital_check_history;
CREATE POLICY tenant_isolation_digital_check_history ON digital_check_history
    FOR ALL USING (app_user_has_org_access(organization_id))
    WITH CHECK (app_user_has_org_access(organization_id));

-- 4. Grants to the non-owner runtime/worker roles
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='digital_check_history') THEN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nacelux_runtime') THEN
            EXECUTE 'GRANT SELECT,INSERT,UPDATE,DELETE ON digital_check_history TO nacelux_runtime';
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nacelux_worker') THEN
            EXECUTE 'GRANT SELECT,INSERT,UPDATE,DELETE ON digital_check_history TO nacelux_worker';
        END IF;
    END IF;
END $$;
