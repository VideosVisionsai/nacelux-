-- Trusted, atomic worker queue operations for a non-owner runtime role.
-- Functions are SECURITY DEFINER and return only jobs already present in the DB.

CREATE OR REPLACE FUNCTION app_reap_orphan_jobs(
    p_timeout_minutes integer,
    p_max_attempts integer
) RETURNS integer AS $$
DECLARE changed integer;
BEGIN
    UPDATE public.jobs
       SET status = CASE WHEN COALESCE(attempt,1) >= p_max_attempts THEN 'FAILED' ELSE 'RETRY' END,
           error = 'Recovered from unexpected worker termination',
           schedule = CASE
               WHEN COALESCE(attempt,1) >= p_max_attempts THEN NULL
               ELSE 'RETRY'
           END,
           started_at = CURRENT_TIMESTAMP
     WHERE status = 'RUNNING'
       AND started_at < CURRENT_TIMESTAMP - (p_timeout_minutes * INTERVAL '1 minute');
    GET DIAGNOSTICS changed = ROW_COUNT;
    RETURN changed;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public;

CREATE OR REPLACE FUNCTION app_claim_jobs(p_limit integer)
RETURNS TABLE(
    job_id text,
    organization_id text,
    job_type text,
    payload jsonb,
    attempt integer,
    context_user_id text
) AS $$
BEGIN
    RETURN QUERY
    WITH candidates AS (
        SELECT j.id
          FROM public.jobs j
         WHERE j.status IN ('QUEUED','RETRY')
           AND (j.schedule IS NULL OR (j.schedule = 'RETRY' AND j.started_at <= CURRENT_TIMESTAMP))
         ORDER BY j.started_at ASC NULLS FIRST
         FOR UPDATE SKIP LOCKED
         LIMIT GREATEST(p_limit, 1)
    ), claimed AS (
        UPDATE public.jobs j
           SET status = 'RUNNING',
               started_at = CURRENT_TIMESTAMP,
               attempt = COALESCE(j.attempt,0) + 1,
               schedule = NULL
          FROM candidates c
         WHERE j.id = c.id
        RETURNING j.id, j.organization_id, j.job_type, j.payload, j.attempt
    )
    SELECT c.id, c.organization_id, c.job_type, c.payload, c.attempt, owner.user_id
      FROM claimed c
      LEFT JOIN LATERAL (
          SELECT om.user_id
            FROM public.organization_members om
           WHERE om.organization_id = c.organization_id
           ORDER BY CASE om.role WHEN 'OWNER' THEN 1 WHEN 'ADMIN' THEN 2 ELSE 3 END
           LIMIT 1
      ) owner ON true;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nacelux_worker') THEN
        RAISE EXCEPTION 'Create the non-owner nacelux_worker role before applying production migrations';
    END IF;
    EXECUTE 'REVOKE ALL ON FUNCTION app_claim_jobs(integer) FROM PUBLIC';
    EXECUTE 'REVOKE ALL ON FUNCTION app_reap_orphan_jobs(integer,integer) FROM PUBLIC';
    EXECUTE 'GRANT EXECUTE ON FUNCTION app_claim_jobs(integer) TO nacelux_worker';
    EXECUTE 'GRANT EXECUTE ON FUNCTION app_reap_orphan_jobs(integer,integer) TO nacelux_worker';
    EXECUTE 'GRANT USAGE ON SCHEMA public TO nacelux_worker';
    EXECUTE 'GRANT SELECT,INSERT,UPDATE,DELETE ON organizations,users,organization_members TO nacelux_worker';
    EXECUTE 'GRANT SELECT,INSERT,UPDATE,DELETE ON companies,business_signals,opportunity_scores,prospects,data_sources,jobs,data_lineage,audit_logs,taxonomy_nodes,people,digital_checks,seo_audits,reports,territories,scoring_weights TO nacelux_worker';
    EXECUTE 'GRANT SELECT,INSERT,UPDATE,DELETE ON resa_journals,resa_entries,resa_documents,resa_sync_runs,storage_objects,document_extractions,document_page_extractions TO nacelux_worker';
END $$;
