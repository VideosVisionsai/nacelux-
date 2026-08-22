-- NACELUX Rev. 2.1 — Commercial outreach drafts and review history (Étape 9).
-- Additive and idempotent. No seed/demo data.

CREATE TABLE IF NOT EXISTS outreach_drafts(
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    company_id text NOT NULL REFERENCES companies(id),
    provider text NOT NULL,
    model text,
    prompt_version text,
    input_hash text,
    output_hash text,
    subject text,
    greeting text,
    body text,
    claims jsonb NOT NULL DEFAULT '[]',
    evidence_references jsonb NOT NULL DEFAULT '[]',
    confidence numeric(4,3),
    review_status text NOT NULL DEFAULT 'DRAFT',   -- DRAFT | REVIEW_REQUIRED | APPROVED | REJECTED | READY_TO_SEND
    reviewer text,
    reviewed_at timestamptz,
    review_comment text,
    edited_subject text,
    edited_body text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_outreach_tenant ON outreach_drafts(organization_id, company_id, created_at DESC);

CREATE TABLE IF NOT EXISTS outreach_reviews(
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    draft_id text NOT NULL REFERENCES outreach_drafts(id),
    previous_status text NOT NULL,
    new_status text NOT NULL,
    reviewer text,
    comment text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_or_tenant ON outreach_reviews(organization_id, draft_id, created_at DESC);

ALTER TABLE outreach_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE outreach_drafts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_outreach_drafts ON outreach_drafts;
CREATE POLICY tenant_isolation_outreach_drafts ON outreach_drafts
    FOR ALL USING (app_user_has_org_access(organization_id))
    WITH CHECK (app_user_has_org_access(organization_id));

ALTER TABLE outreach_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE outreach_reviews FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_outreach_reviews ON outreach_reviews;
CREATE POLICY tenant_isolation_outreach_reviews ON outreach_reviews
    FOR ALL USING (app_user_has_org_access(organization_id))
    WITH CHECK (app_user_has_org_access(organization_id));

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nacelux_runtime') THEN
        EXECUTE 'GRANT SELECT,INSERT,UPDATE,DELETE ON outreach_drafts, outreach_reviews TO nacelux_runtime';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nacelux_worker') THEN
        EXECUTE 'GRANT SELECT,INSERT,UPDATE,DELETE ON outreach_drafts, outreach_reviews TO nacelux_worker';
    END IF;
END $$;
