-- Website discovery and digital-footprint evidence. Additive only.
CREATE TABLE IF NOT EXISTS website_discovery_runs(
 id text PRIMARY KEY, organization_id text NOT NULL REFERENCES organizations(id),
 company_id text NOT NULL REFERENCES companies(id), status text NOT NULL,
 provider text, query_text text, started_at timestamptz NOT NULL, completed_at timestamptz,
 candidates_found integer NOT NULL DEFAULT 0, selected_candidate_id text,
 error_code text, error_message text, metadata jsonb NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS website_candidates(
 id text PRIMARY KEY, organization_id text NOT NULL REFERENCES organizations(id),
 company_id text NOT NULL REFERENCES companies(id), run_id text NOT NULL REFERENCES website_discovery_runs(id),
 url text NOT NULL, canonical_url text NOT NULL, domain text NOT NULL, title text, snippet text,
 confidence double precision NOT NULL, match_status text NOT NULL, evidence jsonb NOT NULL DEFAULT '{}',
 discovery_source text NOT NULL, checked_at timestamptz NOT NULL,
 UNIQUE(organization_id,company_id,canonical_url));
ALTER TABLE digital_checks ADD COLUMN IF NOT EXISTS source_provider text;
ALTER TABLE digital_checks ADD COLUMN IF NOT EXISTS evidence jsonb NOT NULL DEFAULT '{}';
ALTER TABLE digital_checks ADD COLUMN IF NOT EXISTS error_code text;
ALTER TABLE digital_checks ADD COLUMN IF NOT EXISTS check_method text;
CREATE TABLE IF NOT EXISTS google_business_profiles(
 id text PRIMARY KEY, organization_id text NOT NULL REFERENCES organizations(id),
 company_id text NOT NULL REFERENCES companies(id), place_id text, business_name text,
 formatted_address text, primary_type text, website_url text, phone text,
 rating double precision, review_count integer, status text NOT NULL,
 source_url text, checked_at timestamptz NOT NULL, raw_data jsonb NOT NULL DEFAULT '{}',
 UNIQUE(organization_id,company_id));
CREATE INDEX IF NOT EXISTS website_candidates_company_idx ON website_candidates(organization_id,company_id,confidence DESC);
CREATE INDEX IF NOT EXISTS digital_checks_company_idx ON digital_checks(organization_id,company_id,channel);
