-- NACELUX Rev. 2.1 — AI/LLM extraction audit + person role/coordinate columns.
-- Additive and idempotent. No seed/demo data.
-- The LLM output is NEVER an evidence: ai_extractions keeps raw LLM output,
-- normalized data and provenance separately. The source of truth remains the
-- original PDF page text + coordinates + SHA-256.

-- 1. People: role typing, human-review flag, and the page coordinates where the
--    role was observed (so a reviewer can locate the exact passage).
ALTER TABLE people ADD COLUMN IF NOT EXISTS role_type text;            -- e.g. MANAGER, BOARD, REPRESENTATIVE, SIGNATORY, UNKNOWN
ALTER TABLE people ADD COLUMN IF NOT EXISTS role_confirmed boolean DEFAULT false;
ALTER TABLE people ADD COLUMN IF NOT EXISTS needs_human_review boolean DEFAULT false;
ALTER TABLE people ADD COLUMN IF NOT EXISTS x0 double precision;
ALTER TABLE people ADD COLUMN IF NOT EXISTS y0 double precision;
ALTER TABLE people ADD COLUMN IF NOT EXISTS x1 double precision;
ALTER TABLE people ADD COLUMN IF NOT EXISTS y1 double precision;
ALTER TABLE people ADD COLUMN IF NOT EXISTS block_text text;

-- 2. AI extraction audit (raw output / normalized / original evidence kept apart)
CREATE TABLE IF NOT EXISTS ai_extractions(
    id text PRIMARY KEY,
    organization_id text NOT NULL REFERENCES organizations(id),
    source_document_id text,
    source_extraction_id text,
    source_page_id text,
    person_id text,
    provider text,
    model text,
    model_version text,
    prompt_version text,
    input_hash text,
    output_hash text,
    raw_output jsonb NOT NULL DEFAULT '{}',
    normalized jsonb NOT NULL DEFAULT '{}',
    evidence_quote text,
    confidence numeric(4,3),
    needs_human_review boolean DEFAULT false,
    status text NOT NULL DEFAULT 'PENDING',             -- PENDING | APPLIED | REJECTED
    rejection_reason text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ai_tenant ON ai_extractions(organization_id, created_at DESC);

-- 3. RLS on the AI audit table (tenant-scoped via membership proof)
ALTER TABLE ai_extractions ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_extractions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_ai_extractions ON ai_extractions;
CREATE POLICY tenant_isolation_ai_extractions ON ai_extractions
    FOR ALL USING (app_user_has_org_access(organization_id))
    WITH CHECK (app_user_has_org_access(organization_id));

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nacelux_runtime') THEN
        EXECUTE 'GRANT SELECT,INSERT,UPDATE,DELETE ON ai_extractions TO nacelux_runtime';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nacelux_worker') THEN
        EXECUTE 'GRANT SELECT,INSERT,UPDATE,DELETE ON ai_extractions TO nacelux_worker';
    END IF;
END $$;
