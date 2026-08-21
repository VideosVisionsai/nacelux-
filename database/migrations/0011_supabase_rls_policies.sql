-- NACELUX Rev. 2.1 — Supabase PostgreSQL Row Level Security (RLS) policies.
-- Additive and idempotent: enables RLS on all tenant tables and enforces organization isolation.

-- 1. Ensure auth schema compatibility for environments outside Supabase managed cloud.
CREATE SCHEMA IF NOT EXISTS auth;
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid AS $$
BEGIN
    RETURN NULLIF(current_setting('request.jwt.claim.sub', true), '')::uuid;
EXCEPTION
    WHEN OTHERS THEN
        RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

-- 2. Tenant verification helper function
CREATE OR REPLACE FUNCTION app_user_has_org_access(target_org_id text) RETURNS boolean AS $$
DECLARE
    app_org text;
    auth_user uuid;
BEGIN
    IF target_org_id IS NULL THEN
        RETURN false;
    END IF;

    -- Context variable set by backend session
    app_org := NULLIF(current_setting('app.organization_id', true), '');
    IF app_org IS NOT NULL AND app_org = target_org_id THEN
        RETURN true;
    END IF;

    -- Supabase Auth JWT identity check
    BEGIN
        auth_user := auth.uid();
    EXCEPTION WHEN OTHERS THEN
        auth_user := NULL;
    END;

    IF auth_user IS NOT NULL THEN
        IF EXISTS (
            SELECT 1 FROM organization_members om
            JOIN users u ON u.id = om.user_id
            WHERE om.organization_id = target_org_id
              AND (u.auth_user_id = auth_user::text OR om.user_id = auth_user::text)
        ) THEN
            RETURN true;
        END IF;
    END IF;

    RETURN false;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- 3. Organizations and Membership RLS
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS organizations_tenant_policy ON organizations;
CREATE POLICY organizations_tenant_policy ON organizations
    FOR ALL
    USING (
        id = NULLIF(current_setting('app.organization_id', true), '')
        OR id IN (
            SELECT om.organization_id FROM organization_members om
            JOIN users u ON u.id = om.user_id
            WHERE u.auth_user_id = auth.uid()::text OR om.user_id = auth.uid()::text
        )
    )
    WITH CHECK (
        id = NULLIF(current_setting('app.organization_id', true), '')
        OR id IN (
            SELECT om.organization_id FROM organization_members om
            JOIN users u ON u.id = om.user_id
            WHERE (u.auth_user_id = auth.uid()::text OR om.user_id = auth.uid()::text)
              AND om.role IN ('OWNER', 'ADMIN')
        )
    );

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS users_self_policy ON users;
CREATE POLICY users_self_policy ON users
    FOR ALL
    USING (
        id = NULLIF(current_setting('app.user_id', true), '')
        OR auth_user_id = auth.uid()::text
        OR id = auth.uid()::text
        OR id IN (
            SELECT om.user_id FROM organization_members om
            WHERE om.organization_id = NULLIF(current_setting('app.organization_id', true), '')
        )
    )
    WITH CHECK (
        id = NULLIF(current_setting('app.user_id', true), '')
        OR auth_user_id = auth.uid()::text
        OR id = auth.uid()::text
    );

ALTER TABLE organization_members ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_members_policy ON organization_members;
CREATE POLICY org_members_policy ON organization_members
    FOR ALL
    USING (
        organization_id = NULLIF(current_setting('app.organization_id', true), '')
        OR user_id = auth.uid()::text
        OR organization_id IN (
            SELECT om.organization_id FROM organization_members om
            JOIN users u ON u.id = om.user_id
            WHERE u.auth_user_id = auth.uid()::text OR om.user_id = auth.uid()::text
        )
    )
    WITH CHECK (
        organization_id = NULLIF(current_setting('app.organization_id', true), '')
        OR organization_id IN (
            SELECT om.organization_id FROM organization_members om
            JOIN users u ON u.id = om.user_id
            WHERE (u.auth_user_id = auth.uid()::text OR om.user_id = auth.uid()::text)
              AND om.role IN ('OWNER', 'ADMIN')
        )
    );

-- 4. Enable RLS and apply policies to all tenant-scoped tables
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS payload jsonb NOT NULL DEFAULT '{}';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS attempt integer NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS schedule text;

DO $$
DECLARE
    tbl text;
    tenant_tables text[] := ARRAY[
        'companies',
        'business_signals',
        'business_signal_runs',
        'opportunity_scores',
        'prospects',
        'data_sources',
        'jobs',
        'data_lineage',
        'audit_logs',
        'taxonomy_nodes',
        'people',
        'people_engine_runs',
        'people_evidence',
        'professional_profiles_public',
        'privacy_requests',
        'digital_checks',
        'website_discovery_runs',
        'website_candidates',
        'google_business_profiles',
        'seo_audits',
        'resa_publications',
        'reports',
        'territories',
        'scoring_weights',
        'resa_journals',
        'resa_entries',
        'resa_documents',
        'resa_sync_runs',
        'storage_objects',
        'document_extractions',
        'document_page_extractions'
    ];
BEGIN
    FOREACH tbl IN ARRAY tenant_tables
    LOOP
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = tbl) THEN
            EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', tbl);
            EXECUTE format('DROP POLICY IF EXISTS %I ON %I;', 'tenant_isolation_' || tbl, tbl);
            EXECUTE format(
                'CREATE POLICY %I ON %I FOR ALL USING (app_user_has_org_access(organization_id)) WITH CHECK (app_user_has_org_access(organization_id));',
                'tenant_isolation_' || tbl,
                tbl
            );
        END IF;
    END LOOP;
END $$;

-- 5. Read-only access for reference and taxonomy tables
DO $$
DECLARE
    ref_tbl text;
    ref_tables text[] := ARRAY[
        'nace_codes',
        'nace_versions_official',
        'nace_items_official',
        'nace_labels_official',
        'nace_notes_official',
        'nace_correspondences_official',
        'nace_import_runs',
        'business_signal_definitions'
    ];
BEGIN
    FOREACH ref_tbl IN ARRAY ref_tables
    LOOP
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = ref_tbl) THEN
            EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', ref_tbl);
            EXECUTE format('DROP POLICY IF EXISTS %I ON %I;', 'reference_read_' || ref_tbl, ref_tbl);
            EXECUTE format(
                'CREATE POLICY %I ON %I FOR SELECT USING (true);',
                'reference_read_' || ref_tbl,
                ref_tbl
            );
        END IF;
    END LOOP;
END $$;
