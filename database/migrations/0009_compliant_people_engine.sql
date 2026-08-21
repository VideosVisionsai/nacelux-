-- Compliant professional People Engine. Additive; no private-data fields.
ALTER TABLE people ADD COLUMN IF NOT EXISTS name_normalized text;
ALTER TABLE people ADD COLUMN IF NOT EXISTS official_role text;
ALTER TABLE people ADD COLUMN IF NOT EXISTS source_url text;
ALTER TABLE people ADD COLUMN IF NOT EXISTS source_document_id text;
ALTER TABLE people ADD COLUMN IF NOT EXISTS source_extraction_id text;
ALTER TABLE people ADD COLUMN IF NOT EXISTS checked_at timestamptz;
ALTER TABLE people ADD COLUMN IF NOT EXISTS privacy_status text NOT NULL DEFAULT 'ACTIVE';
ALTER TABLE people ADD COLUMN IF NOT EXISTS retention_until date;
CREATE UNIQUE INDEX IF NOT EXISTS people_company_name_uidx ON people(organization_id,company_id,name_normalized) WHERE name_normalized IS NOT NULL;
CREATE TABLE IF NOT EXISTS people_engine_runs(
 id text PRIMARY KEY,organization_id text NOT NULL REFERENCES organizations(id),company_id text NOT NULL REFERENCES companies(id),
 status text NOT NULL,started_at timestamptz NOT NULL,completed_at timestamptz,
 official_people_found integer NOT NULL DEFAULT 0,professional_profiles_found integer NOT NULL DEFAULT 0,
 provider text,error_code text,error_message text,metadata jsonb NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS people_evidence(
 id text PRIMARY KEY,organization_id text NOT NULL REFERENCES organizations(id),person_id text NOT NULL REFERENCES people(id),
 evidence_type text NOT NULL,source_url text NOT NULL,source_document_id text,source_extraction_id text,
 excerpt text,confidence double precision NOT NULL,method text NOT NULL,created_at timestamptz NOT NULL,
 UNIQUE(person_id,evidence_type,source_url));
CREATE TABLE IF NOT EXISTS professional_profiles_public(
 id text PRIMARY KEY,organization_id text NOT NULL REFERENCES organizations(id),person_id text NOT NULL REFERENCES people(id),
 company_id text NOT NULL REFERENCES companies(id),platform text NOT NULL,profile_url text NOT NULL,
 public_title text,match_status text NOT NULL,match_confidence double precision NOT NULL,
 evidence jsonb NOT NULL DEFAULT '{}',source_provider text NOT NULL,checked_at timestamptz NOT NULL,
 UNIQUE(organization_id,platform,profile_url));
CREATE TABLE IF NOT EXISTS privacy_requests(
 id text PRIMARY KEY,organization_id text NOT NULL REFERENCES organizations(id),person_id text REFERENCES people(id),
 request_type text NOT NULL,status text NOT NULL,requester_reference text,notes text,
 created_at timestamptz NOT NULL,resolved_at timestamptz);
CREATE INDEX IF NOT EXISTS people_runs_company_idx ON people_engine_runs(organization_id,company_id,started_at DESC);
CREATE INDEX IF NOT EXISTS public_profiles_person_idx ON professional_profiles_public(organization_id,person_id,match_confidence DESC);
