"""Step 2 — REAL PostgreSQL RLS / tenant-isolation / migration / job verification.

Executed against a real PostgreSQL engine (a real Supabase/Postgres for
production, or the embedded real PostgreSQL used for local verification — never
a mock). Skipped unless NACELUX_TEST_DATABASE_URL (non-owner runtime role) is
provided. The connection role must NOT be superuser and must NOT bypass RLS.

Covers ÉTAPE 2.2 (migrations/constraints/indexes), 2.3 (RLS tenant isolation:
read/update/delete A<->B, no-context, organization_id-manipulation attack),
2.6 (atomic job claim) and the role-posture guarantees (2.1).
"""
import os
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_URL = os.getenv("NACELUX_TEST_DATABASE_URL", "")
WORKER_URL = os.getenv("NACELUX_WORKER_TEST_DATABASE_URL", "")

REQUIRED_TABLES = [
    "organizations", "users", "organization_members", "companies", "prospects",
    "opportunity_scores", "scoring_weights", "business_signals",
    "business_signal_definitions", "business_signal_runs", "data_sources",
    "raw_records", "documents", "storage_objects", "document_extractions",
    "document_page_extractions", "jobs", "audit_logs", "data_lineage",
    "taxonomy_nodes", "people", "people_evidence", "professional_profiles_public",
    "privacy_requests", "digital_checks", "website_discovery_runs",
    "website_candidates", "google_business_profiles", "seo_audits", "reports",
    "resa_journals", "resa_entries", "resa_documents", "resa_sync_runs",
    "nace_versions_official", "nace_items_official", "nace_labels_official",
    "nace_notes_official", "nace_correspondences_official", "nace_import_runs",
]

# Tables that must have RLS enabled AND forced (tenant-scoped).
RLS_TABLES = [
    "organizations", "users", "organization_members", "companies", "prospects",
    "opportunity_scores", "scoring_weights", "business_signals",
    "business_signal_runs", "data_sources", "raw_records", "documents",
    "storage_objects", "document_extractions", "document_page_extractions",
    "jobs", "audit_logs", "data_lineage", "taxonomy_nodes", "people",
    "people_evidence", "professional_profiles_public", "privacy_requests",
    "digital_checks", "website_discovery_runs", "website_candidates",
    "google_business_profiles", "seo_audits", "reports", "resa_journals",
    "resa_entries", "resa_documents", "resa_sync_runs",
]


@unittest.skipUnless(TEST_URL, "NACELUX_TEST_DATABASE_URL (non-owner runtime role) is required")
class PostgresRLSVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg.rows import dict_row
        cls.psycopg = psycopg
        cls.conn = psycopg.connect(TEST_URL, row_factory=dict_row)
        # Hard security gate: the test role must not be able to bypass RLS.
        role = cls.conn.execute(
            "SELECT rolname, rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        if not role:
            raise AssertionError("cannot resolve current database role")
        if role["rolbypassrls"]:
            raise AssertionError("test role must NOT have BYPASSRLS")
        if role["rolsuper"]:
            raise AssertionError("test role must NOT be superuser")

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def setUp(self):
        self.addCleanup(self.conn.rollback)  # always reset, even if setUp fails mid-way
        self.org_a = "s2_org_a_" + uuid.uuid4().hex[:12]
        self.org_b = "s2_org_b_" + uuid.uuid4().hex[:12]
        self.user_a = "s2_user_a_" + uuid.uuid4().hex[:12]
        self.user_b = "s2_user_b_" + uuid.uuid4().hex[:12]
        self.company_a = "s2_comp_a_" + uuid.uuid4().hex[:12]
        self.company_b = "s2_comp_b_" + uuid.uuid4().hex[:12]
        self._provision(self.user_a, self.org_a, "Tenant A")
        self._provision(self.user_b, self.org_b, "Tenant B")
        self._ctx(self.org_a, self.user_a)
        self._insert_company(self.company_a, self.org_a)
        # Insert B's rows under B's own context (RLS would (correctly) block A
        # from creating rows in B's organization — that property is asserted
        # explicitly in test_organization_id_manipulation_is_denied).
        self._ctx(self.org_b, self.user_b)
        self._insert_company(self.company_b, self.org_b)
        self.assertEqual(self._count("companies", self.company_b, self.org_b), 1)

    # --- helpers -----------------------------------------------------------
    def _ctx(self, org, user):
        self.conn.execute("SELECT set_config('app.organization_id', %s, false)", (org or "",))
        self.conn.execute("SELECT set_config('app.user_id', %s, false)", (user or "",))

    def _clear_ctx(self):
        self.conn.execute("SELECT set_config('app.organization_id', '', false)")
        self.conn.execute("SELECT set_config('app.user_id', '', false)")

    def _provision(self, user, org, name):
        self._ctx(None, user)
        self.conn.execute(
            "INSERT INTO users(id,email,display_name,created_at,auth_user_id,updated_at) "
            "VALUES(%s,%s,%s,CURRENT_TIMESTAMP,%s,CURRENT_TIMESTAMP)",
            (user, user + "@test.invalid", name, user),
        )
        self.conn.execute("SELECT app_provision_workspace(%s,%s,%s,%s)", (org, name, org, user))

    def _insert_company(self, cid, org):
        self.conn.execute(
            "INSERT INTO companies(id,organization_id,company_name,created_at,updated_at) "
            "VALUES(%s,%s,%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)", (cid, org, org + " company"))
        self.conn.execute(
            "INSERT INTO prospects(id,organization_id,company_id,status,created_at,updated_at) "
            "VALUES(%s,%s,%s,'NEW',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
            ("prospect_" + cid, org, cid))

    def _count(self, table, row_id, org):
        return self.conn.execute(
            f"SELECT count(*) AS c FROM {table} WHERE id = %s AND organization_id = %s",
            (row_id, org)).fetchone()["c"]

    # --- 2.2 migrations, constraints, indexes ------------------------------
    def test_migration_outcomes_present(self):
        """The non-owner runtime role cannot read schema_migrations (it is not a
        tenant table and is not granted to it). Instead, verify the *outcomes* of
        the key migrations via the catalog: the RLS/provisioning/queue functions
        created by migrations 0011/0013/0014 must exist. (The migration runner —
        run as the migration/superuser role — reports the full applied set.)"""
        funcs = {r["proname"] for r in self.conn.execute(
            "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public'").fetchall()}
        for fn in ("app_user_has_org_access", "app_provision_workspace",
                   "app_claim_jobs", "app_reap_orphan_jobs"):
            self.assertIn(fn, funcs, f"migration function {fn} missing")

    def test_all_required_tables_exist(self):
        missing = []
        for t in REQUIRED_TABLES:
            exists = self.conn.execute(
                "SELECT to_regclass(%s) AS r", ("public." + t,)).fetchone()["r"]
            if exists is None:
                missing.append(t)
        self.assertEqual(missing, [], f"missing tables: {missing}")

    def test_rls_enabled_and_forced_on_tenant_tables(self):
        rows = self.conn.execute(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relnamespace='public'::regnamespace AND relkind IN ('r','p')").fetchall()
        info = {r["relname"]: (r["relrowsecurity"], r["relforcerowsecurity"]) for r in rows}
        for t in RLS_TABLES:
            self.assertIn(t, info, f"RLS table {t} not found")
            enabled, forced = info[t]
            self.assertTrue(enabled, f"RLS not ENABLED on {t}")
            self.assertTrue(forced, f"RLS not FORCED on {t}")

    def test_runtime_role_owns_no_tenant_tables_and_no_bypass(self):
        owned = self.conn.execute(
            "SELECT count(*) AS c FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE c.relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user) "
            "AND n.nspname='public' AND c.relkind IN ('r','p')").fetchone()["c"]
        self.assertEqual(owned, 0, "runtime role must not own any public table")
        role = self.conn.execute(
            "SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname=current_user").fetchone()
        self.assertFalse(role["rolbypassrls"])
        self.assertFalse(role["rolsuper"])

    # --- 2.3 tenant isolation A <-> B --------------------------------------
    def test_tenant_a_reads_own_not_b(self):
        self._ctx(self.org_a, self.user_a)
        self.assertEqual(self._count("companies", self.company_a, self.org_a), 1)
        self.assertEqual(self._count("companies", self.company_b, self.org_b), 0)
        self.assertEqual(
            self.conn.execute("SELECT count(*) AS c FROM prospects WHERE organization_id=%s",
                              (self.org_b,)).fetchone()["c"], 0)

    def test_tenant_a_cannot_update_or_delete_tenant_b(self):
        self._ctx(self.org_a, self.user_a)
        upd = self.conn.execute(
            "UPDATE companies SET company_name='stolen' WHERE id=%s", (self.company_b,))
        self.assertEqual(upd.rowcount, 0, "A must not be able to UPDATE B's rows")
        dele = self.conn.execute("DELETE FROM companies WHERE id=%s", (self.company_b,))
        self.assertEqual(dele.rowcount, 0, "A must not be able to DELETE B's rows")

    def test_tenant_b_reads_own_not_a(self):
        self._ctx(self.org_b, self.user_b)
        self.assertEqual(self._count("companies", self.company_b, self.org_b), 1)
        self.assertEqual(self._count("companies", self.company_a, self.org_a), 0)
        upd = self.conn.execute(
            "UPDATE companies SET company_name='stolen' WHERE id=%s", (self.company_a,))
        self.assertEqual(upd.rowcount, 0)
        dele = self.conn.execute("DELETE FROM companies WHERE id=%s", (self.company_a,))
        self.assertEqual(dele.rowcount, 0)

    def test_no_context_sees_nothing(self):
        self._clear_ctx()
        self.assertEqual(
            self.conn.execute("SELECT count(*) AS c FROM companies").fetchone()["c"], 0)
        self.assertEqual(
            self.conn.execute("SELECT count(*) AS c FROM prospects").fetchone()["c"], 0)

    def test_organization_id_manipulation_is_denied(self):
        """A sets app.organization_id = B's org but keeps its own user_id.
        Access to B MUST still be denied: authorization = user_id + membership +
        RLS, never organization_id alone."""
        self.conn.execute("SELECT set_config('app.organization_id', %s, false)", (self.org_b,))
        self.conn.execute("SELECT set_config('app.user_id', %s, false)", (self.user_a,))
        self.assertEqual(self._count("companies", self.company_b, self.org_b), 0)
        self.assertEqual(
            self.conn.execute("SELECT count(*) AS c FROM companies WHERE organization_id=%s",
                              (self.org_b,)).fetchone()["c"], 0)
        self.assertFalse(self.conn.execute(
            "SELECT app_user_has_org_access(%s) AS ok", (self.org_b,)).fetchone()["ok"])

    def test_app_user_has_org_access_requires_membership(self):
        self._ctx(self.org_a, self.user_a)
        self.assertTrue(self.conn.execute(
            "SELECT app_user_has_org_access(%s) AS ok", (self.org_a,)).fetchone()["ok"])
        self.assertFalse(self.conn.execute(
            "SELECT app_user_has_org_access(%s) AS ok", (self.org_b,)).fetchone()["ok"])
        self.assertFalse(self.conn.execute(
            "SELECT app_user_has_org_access(NULL) AS ok").fetchone()["ok"])


@unittest.skipUnless(WORKER_URL, "NACELUX_WORKER_TEST_DATABASE_URL is required for the job-queue test")
class JobQueueAtomicityTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg.rows import dict_row
        self.psycopg = psycopg
        self.runtime = psycopg.connect(TEST_URL, row_factory=dict_row)
        self.org = "s2_jobs_" + uuid.uuid4().hex[:12]
        self.user = "s2_jobuser_" + uuid.uuid4().hex[:12]
        self.runtime.execute("SELECT set_config('app.organization_id', '', false)")
        self.runtime.execute("SELECT set_config('app.user_id', %s, false)", (self.user,))
        self.runtime.execute(
            "INSERT INTO users(id,email,display_name,created_at,auth_user_id,updated_at) "
            "VALUES(%s,%s,%s,CURRENT_TIMESTAMP,%s,CURRENT_TIMESTAMP)",
            (self.user, self.user + "@test.invalid", "Jobs Tenant", self.user))
        self.runtime.execute("SELECT app_provision_workspace(%s,%s,%s,%s)", (self.org, "Jobs", self.org, self.user))
        self.runtime.execute("SELECT set_config('app.organization_id', %s, false)", (self.org,))
        self.job_ids = ["s2_job_" + uuid.uuid4().hex[:12] for _ in range(3)]
        for jid in self.job_ids:
            self.runtime.execute(
                "INSERT INTO jobs(id,organization_id,job_type,status,started_at,finished_at,"
                "records_processed,error,payload,attempt,schedule) "
                "VALUES(%s,%s,'OPPORTUNITY_RECALCULATION','QUEUED',CURRENT_TIMESTAMP,NULL,0,NULL,'{}',0,NULL)",
                (jid, self.org))
        self.runtime.commit()

    def tearDown(self):
        try:
            for jid in self.job_ids:
                self.runtime.execute("DELETE FROM jobs WHERE id=%s", (jid,))
            self.runtime.execute("DELETE FROM organization_members WHERE organization_id=%s", (self.org,))
            self.runtime.execute("DELETE FROM organizations WHERE id=%s", (self.org,))
            self.runtime.execute("DELETE FROM users WHERE id=%s", (self.user,))
            self.runtime.commit()
        finally:
            self.runtime.close()

    def test_two_workers_claim_disjoint_and_atomic(self):
        w1 = self.psycopg.connect(WORKER_URL, row_factory=__import__("psycopg").rows.dict_row)
        w2 = self.psycopg.connect(WORKER_URL, row_factory=__import__("psycopg").rows.dict_row)
        try:
            claimed1 = [r["job_id"] for r in w1.execute("SELECT * FROM app_claim_jobs(2)").fetchall()]
            claimed2 = [r["job_id"] for r in w2.execute("SELECT * FROM app_claim_jobs(2)").fetchall()]
            w1.commit()
            w2.commit()
            self.assertGreater(len(claimed1), 0)
            self.assertGreater(len(claimed2), 0)
            self.assertEqual(set(claimed1) & set(claimed2), set(), "a job was claimed by both workers")
            self.assertTrue(set(claimed1) <= set(self.job_ids))
            self.assertTrue(set(claimed2) <= set(self.job_ids))
            # No job can be claimed twice: claim again from a third connection returns nothing of the claimed set.
            w3 = self.psycopg.connect(WORKER_URL, row_factory=__import__("psycopg").rows.dict_row)
            claimed3 = [r["job_id"] for r in w3.execute("SELECT * FROM app_claim_jobs(5)").fetchall()]
            w3.rollback()
            w3.close()
            self.assertEqual(set(claimed3) & set(claimed1), set())
            self.assertEqual(set(claimed3) & set(claimed2), set())
        finally:
            w1.close()
            w2.close()


if __name__ == "__main__":
    unittest.main()
