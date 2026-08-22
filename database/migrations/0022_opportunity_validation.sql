-- NACELUX Rev. 2.1 — Commercial workspace: opportunity manual validation.
-- Additive and idempotent. No seed/demo data.

ALTER TABLE companies ADD COLUMN IF NOT EXISTS validation_status text DEFAULT 'REVIEW_PENDING';
ALTER TABLE companies ADD COLUMN IF NOT EXISTS validated_by text;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS validated_at timestamptz;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS validation_comment text;

CREATE TABLE IF NOT EXISTS opportunity_validations(
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    company_id text NOT NULL REFERENCES companies(id),
    previous_status text NOT NULL,
    new_status text NOT NULL,
    reviewer text,
    comment text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ov_tenant ON opportunity_validations(organization_id, company_id, created_at DESC);

ALTER TABLE opportunity_validations ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunity_validations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_opportunity_validations ON opportunity_validations;
CREATE POLICY tenant_isolation_opportunity_validations ON opportunity_validations
    FOR ALL USING (app_user_has_org_access(organization_id))
    WITH CHECK (app_user_has_org_access(organization_id));

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nacelux_runtime') THEN
        EXECUTE 'GRANT SELECT,INSERT,UPDATE,DELETE ON opportunity_validations TO nacelux_runtime';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nacelux_worker') THEN
        EXECUTE 'GRANT SELECT,INSERT,UPDATE,DELETE ON opportunity_validations TO nacelux_worker';
    END IF;
END $$;
