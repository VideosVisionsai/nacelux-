-- NACELUX Rev. 2.1 — Human review for PDF-extracted people (RESA PDF reinforcement).
-- Additive and idempotent. No seed/demo data.
-- A decision-maker extracted from a scanned RESA PDF is PENDING_REVIEW until a
-- human confirms identity/role/company; it must never be presented as a verified
-- decider before approval.

ALTER TABLE people ADD COLUMN IF NOT EXISTS review_status text;   -- PENDING_REVIEW | APPROVED | REJECTED
ALTER TABLE people ADD COLUMN IF NOT EXISTS reviewer text;
ALTER TABLE people ADD COLUMN IF NOT EXISTS reviewed_at timestamptz;
ALTER TABLE people ADD COLUMN IF NOT EXISTS review_comment text;
ALTER TABLE people ADD COLUMN IF NOT EXISTS source_page integer;  -- page where the role was observed
ALTER TABLE people ADD COLUMN IF NOT EXISTS evidence_excerpt text;

CREATE INDEX IF NOT EXISTS idx_people_review ON people(organization_id, review_status);
