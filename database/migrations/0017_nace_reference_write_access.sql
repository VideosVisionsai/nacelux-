-- NACELUX Rev. 2.1 — Grant write access on the official NACE reference tables.
-- Additive and idempotent.
--
-- The nace_*_official + nace_import_runs tables are GLOBAL reference data: they
-- have NO organization_id column, so they carry no tenant-isolation value. They
-- are written only by the trusted application roles (the worker via NACE_SYNC,
-- the runtime via the admin import route) and only after validate_parsed() has
-- confirmed the official 22/87/287/651 structure.
--
-- Migration 0011 enabled RLS + a SELECT-only (reference_read) policy on them but
-- granted no INSERT/UPDATE privilege and no write policy, so a non-owner role
-- could not import (permission denied / RLS blocked the write). This grants the
-- write privilege and a permissive write policy so the official importer works
-- under the non-owner roles, without weakening tenant isolation (these tables
-- are not tenant-scoped and never carry an organization_id).

DO $$
DECLARE t text;
DECLARE ref_tables text[] := ARRAY[
  'nace_versions_official','nace_items_official','nace_labels_official',
  'nace_notes_official','nace_correspondences_official','nace_import_runs'
];
BEGIN
  FOREACH t IN ARRAY ref_tables LOOP
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=t) THEN
      EXECUTE format('DROP POLICY IF EXISTS nace_reference_write ON %I', t);
      EXECUTE format('CREATE POLICY nace_reference_write ON %I FOR ALL USING (true) WITH CHECK (true)', t);
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nacelux_runtime') THEN
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO nacelux_runtime', t);
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nacelux_worker') THEN
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO nacelux_worker', t);
      END IF;
    END IF;
  END LOOP;
END $$;
