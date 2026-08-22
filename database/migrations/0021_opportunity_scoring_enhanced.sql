-- NACELUX Rev. 2.1 — Enhanced opportunity scoring (Étape 7).
-- Additive and idempotent. No seed/demo data.

ALTER TABLE opportunity_scores ADD COLUMN IF NOT EXISTS model_version text;
ALTER TABLE opportunity_scores ADD COLUMN IF NOT EXISTS factor_snapshot jsonb;
ALTER TABLE opportunity_scores ADD COLUMN IF NOT EXISTS input_snapshot jsonb;
ALTER TABLE opportunity_scores ADD COLUMN IF NOT EXISTS fingerprint text;
CREATE INDEX IF NOT EXISTS idx_opp_score_fingerprint ON opportunity_scores(organization_id, fingerprint);

CREATE TABLE IF NOT EXISTS opportunity_score_history(
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    company_id text NOT NULL REFERENCES companies(id),
    model_version text NOT NULL,
    total_score integer NOT NULL,
    level text NOT NULL,
    recommended_action text,
    factor_snapshot jsonb NOT NULL DEFAULT '{}',
    input_snapshot jsonb NOT NULL DEFAULT '{}',
    fingerprint text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_osh_tenant ON opportunity_score_history(organization_id, company_id, created_at DESC);

ALTER TABLE opportunity_score_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunity_score_history FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_opportunity_score_history ON opportunity_score_history;
CREATE POLICY tenant_isolation_opportunity_score_history ON opportunity_score_history
    FOR ALL USING (app_user_has_org_access(organization_id))
    WITH CHECK (app_user_has_org_access(organization_id));

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nacelux_runtime') THEN
        EXECUTE 'GRANT SELECT,INSERT,UPDATE,DELETE ON opportunity_score_history TO nacelux_runtime';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nacelux_worker') THEN
        EXECUTE 'GRANT SELECT,INSERT,UPDATE,DELETE ON opportunity_score_history TO nacelux_worker';
    END IF;
END $$;
