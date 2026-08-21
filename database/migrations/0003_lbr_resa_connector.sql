-- LBR/RESA ingestion model. Additive and idempotent; preserves all existing tables/data.
CREATE TABLE IF NOT EXISTS resa_journals(
 id text PRIMARY KEY, organization_id text NOT NULL REFERENCES organizations(id),
 journal_key text NOT NULL, publication_date date, sequence_number text, source_url text NOT NULL,
 source_status text NOT NULL DEFAULT 'OFFICIAL', first_seen_at timestamptz NOT NULL,
 last_seen_at timestamptz NOT NULL, content_hash text, UNIQUE(organization_id,journal_key));
CREATE TABLE IF NOT EXISTS resa_entries(
 id text PRIMARY KEY, organization_id text NOT NULL REFERENCES organizations(id),
 journal_id text NOT NULL REFERENCES resa_journals(id), natural_key text NOT NULL,
 row_index integer NOT NULL, publication_number text, entry_type text, company_name text,
 rcs_number text, row_text text NOT NULL, source_url text NOT NULL,
 change_status text NOT NULL DEFAULT 'NEW', content_hash text NOT NULL,
 first_seen_at timestamptz NOT NULL, last_seen_at timestamptz NOT NULL,
 UNIQUE(organization_id,journal_id,natural_key));
CREATE TABLE IF NOT EXISTS resa_documents(
 id text PRIMARY KEY, organization_id text NOT NULL REFERENCES organizations(id),
 journal_id text NOT NULL REFERENCES resa_journals(id), entry_id text REFERENCES resa_entries(id),
 document_url text NOT NULL, canonical_url text NOT NULL, document_type text NOT NULL DEFAULT 'PDF',
 link_text text, source_url text NOT NULL, download_status text NOT NULL DEFAULT 'NOT_DOWNLOADED',
 extraction_status text NOT NULL DEFAULT 'NOT_STARTED', checksum text, first_seen_at timestamptz NOT NULL,
 last_seen_at timestamptz NOT NULL, UNIQUE(organization_id,canonical_url));
CREATE TABLE IF NOT EXISTS resa_sync_runs(
 id text PRIMARY KEY, organization_id text NOT NULL REFERENCES organizations(id), journal_id text REFERENCES resa_journals(id),
 source_url text NOT NULL, status text NOT NULL, fetch_method text, started_at timestamptz NOT NULL,
 finished_at timestamptz, rows_detected integer NOT NULL DEFAULT 0, documents_detected integer NOT NULL DEFAULT 0,
 new_entries integer NOT NULL DEFAULT 0, updated_entries integer NOT NULL DEFAULT 0, unchanged_entries integer NOT NULL DEFAULT 0,
 duplicate_entries integer NOT NULL DEFAULT 0, robots_status text, captcha_status text, error_code text, error_message text,
 snapshot_hash text, metadata jsonb NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS resa_entries_company_idx ON resa_entries(organization_id,rcs_number,company_name);
CREATE INDEX IF NOT EXISTS resa_entries_journal_idx ON resa_entries(organization_id,journal_id,row_index);
CREATE INDEX IF NOT EXISTS resa_documents_entry_idx ON resa_documents(organization_id,entry_id);
CREATE INDEX IF NOT EXISTS resa_runs_started_idx ON resa_sync_runs(organization_id,started_at DESC);
