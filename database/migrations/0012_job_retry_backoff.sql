-- Durable PostgreSQL retry scheduling for background jobs. Additive only.
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS next_attempt_at timestamptz;
CREATE INDEX IF NOT EXISTS jobs_retry_schedule_idx ON jobs(status,next_attempt_at,started_at);
