-- Versioned, evidence-backed business signal engine. Additive only.
ALTER TABLE business_signals ADD COLUMN IF NOT EXISTS severity text;
ALTER TABLE business_signals ADD COLUMN IF NOT EXISTS rule_version text;
ALTER TABLE business_signals ADD COLUMN IF NOT EXISTS explanation text;
ALTER TABLE business_signals ADD COLUMN IF NOT EXISTS expires_at timestamptz;
ALTER TABLE business_signals ADD COLUMN IF NOT EXISTS data_quality text NOT NULL DEFAULT 'UNKNOWN';
CREATE TABLE IF NOT EXISTS business_signal_runs(
 id text PRIMARY KEY,organization_id text NOT NULL REFERENCES organizations(id),company_id text REFERENCES companies(id),
 status text NOT NULL,rule_version text NOT NULL,started_at timestamptz NOT NULL,completed_at timestamptz,
 companies_processed integer NOT NULL DEFAULT 0,active_signals integer NOT NULL DEFAULT 0,
 activated integer NOT NULL DEFAULT 0,deactivated integer NOT NULL DEFAULT 0,
 error_code text,error_message text,metadata jsonb NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS business_signal_definitions(
 signal_type text PRIMARY KEY,label text NOT NULL,description text NOT NULL,severity text NOT NULL,
 required_evidence text NOT NULL,is_active boolean NOT NULL DEFAULT true,rule_version text NOT NULL,
 created_at timestamptz NOT NULL,updated_at timestamptz NOT NULL);
CREATE INDEX IF NOT EXISTS business_signals_active_idx ON business_signals(organization_id,status,signal_type,last_seen_at DESC);
CREATE INDEX IF NOT EXISTS business_signal_runs_org_idx ON business_signal_runs(organization_id,started_at DESC);
