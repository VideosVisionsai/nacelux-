-- Harden the previously installed RLS policies without modifying migration 0011.
-- No table or row is deleted. Runtime context must contain an authenticated user.

CREATE OR REPLACE FUNCTION app_user_has_org_access(target_org_id text) RETURNS boolean AS $$
DECLARE
    app_org text;
    app_user text;
    auth_user uuid;
BEGIN
    IF target_org_id IS NULL THEN
        RETURN false;
    END IF;
    app_org := NULLIF(current_setting('app.organization_id', true), '');
    app_user := NULLIF(current_setting('app.user_id', true), '');

    -- app.user_id is set by the backend only after Supabase Auth verification.
    -- app.organization_id narrows the already-authorized membership; it is not
    -- sufficient by itself to grant access.
    IF app_user IS NOT NULL
       AND (app_org IS NULL OR app_org = target_org_id)
       AND EXISTS (
           SELECT 1 FROM public.organization_members om
           JOIN public.users u ON u.id = om.user_id
           WHERE om.organization_id = target_org_id
             AND (om.user_id = app_user OR u.auth_user_id = app_user)
       ) THEN
        RETURN true;
    END IF;

    BEGIN
        auth_user := auth.uid();
    EXCEPTION WHEN OTHERS THEN
        auth_user := NULL;
    END;
    IF auth_user IS NOT NULL AND EXISTS (
        SELECT 1 FROM public.organization_members om
        JOIN public.users u ON u.id = om.user_id
        WHERE om.organization_id = target_org_id
          AND (u.auth_user_id = auth_user::text OR om.user_id = auth_user::text)
    ) THEN
        RETURN true;
    END IF;
    RETURN false;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public;

-- First-login provisioning is a narrow trusted operation. It requires the
-- caller context to identify the same authenticated user and avoids weakening
-- organization RLS merely to create the first workspace.
CREATE OR REPLACE FUNCTION app_provision_workspace(
    p_organization_id text,
    p_name text,
    p_slug text,
    p_user_id text
) RETURNS void AS $$
DECLARE
    caller text := NULLIF(current_setting('app.user_id', true), '');
BEGIN
    IF caller IS NULL OR caller <> p_user_id THEN
        RAISE EXCEPTION 'workspace provisioning requires authenticated user context';
    END IF;
    INSERT INTO public.organizations(id,name,slug,created_at)
        VALUES(p_organization_id,p_name,p_slug,now());
    INSERT INTO public.organization_members(organization_id,user_id,role)
        VALUES(p_organization_id,p_user_id,'OWNER');
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public;

ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS organizations_tenant_policy ON organizations;
CREATE POLICY organizations_tenant_policy ON organizations
    FOR ALL USING (app_user_has_org_access(id))
    WITH CHECK (app_user_has_org_access(id));

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS users_self_policy ON users;
CREATE POLICY users_self_policy ON users
    FOR ALL USING (
        id = NULLIF(current_setting('app.user_id', true), '')
        OR auth_user_id = auth.uid()::text
        OR id = auth.uid()::text
        OR EXISTS (
            SELECT 1 FROM public.organization_members om
            WHERE om.user_id = users.id
              AND app_user_has_org_access(om.organization_id)
        )
    )
    WITH CHECK (
        id = NULLIF(current_setting('app.user_id', true), '')
        OR auth_user_id = auth.uid()::text
        OR id = auth.uid()::text
    );

ALTER TABLE organization_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE organization_members FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_members_policy ON organization_members;
CREATE POLICY org_members_policy ON organization_members
    FOR ALL USING (app_user_has_org_access(organization_id))
    WITH CHECK (app_user_has_org_access(organization_id));

DO $$
DECLARE tbl text;
DECLARE tenant_tables text[] := ARRAY[
    'companies','documents','resa_documents','storage_objects',
    'document_extractions','document_page_extractions','business_signals',
    'business_signal_runs','opportunity_scores','prospects','data_sources',
    'jobs','data_lineage','audit_logs','taxonomy_nodes','people',
    'people_engine_runs','people_evidence','professional_profiles_public',
    'privacy_requests','digital_checks','website_discovery_runs',
    'website_candidates','google_business_profiles','seo_audits',
    'resa_publications','reports','territories','scoring_weights',
    'resa_journals','resa_entries','resa_sync_runs'
];
BEGIN
    FOREACH tbl IN ARRAY tenant_tables LOOP
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=tbl) THEN
            EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',tbl);
            EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',tbl);
            EXECUTE format('DROP POLICY IF EXISTS %I ON %I','tenant_isolation_'||tbl,tbl);
            EXECUTE format(
                'CREATE POLICY %I ON %I FOR ALL USING (app_user_has_org_access(organization_id)) WITH CHECK (app_user_has_org_access(organization_id))',
                'tenant_isolation_'||tbl,tbl
            );
        END IF;
    END LOOP;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nacelux_runtime') THEN
        RAISE EXCEPTION 'Create the non-owner nacelux_runtime role before applying production migrations';
    END IF;
    EXECUTE 'REVOKE ALL ON FUNCTION app_provision_workspace(text,text,text,text) FROM PUBLIC';
    EXECUTE 'GRANT EXECUTE ON FUNCTION app_provision_workspace(text,text,text,text) TO nacelux_runtime';
    EXECUTE 'GRANT USAGE ON SCHEMA public TO nacelux_runtime';
    EXECUTE 'GRANT SELECT,INSERT,UPDATE,DELETE ON organizations,users,organization_members TO nacelux_runtime';
    EXECUTE 'GRANT SELECT,INSERT,UPDATE,DELETE ON companies,business_signals,opportunity_scores,prospects,data_sources,jobs,data_lineage,audit_logs,taxonomy_nodes,people,digital_checks,seo_audits,reports,territories,scoring_weights TO nacelux_runtime';
    EXECUTE 'GRANT SELECT,INSERT,UPDATE,DELETE ON resa_journals,resa_entries,resa_documents,resa_sync_runs,storage_objects,document_extractions,document_page_extractions TO nacelux_runtime';
END $$;
