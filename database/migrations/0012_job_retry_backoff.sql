-- Durable PostgreSQL retry scheduling metadata. Additive and idempotent.
-- The existing jobs.schedule column stores RETRY state; started_at stores the
-- next eligible execution time. No new data column is required.
CREATE INDEX IF NOT EXISTS jobs_retry_schedule_idx ON jobs(status,schedule,started_at);
