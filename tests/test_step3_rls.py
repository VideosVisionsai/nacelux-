"""Step 3 (ÉTAPE 3.15 items 7/18/19/20) — REAL PostgreSQL RLS verification for
the import pipeline and company access. Skipped without NACELUX_TEST_DATABASE_URL.

The pipeline writes organization_id from a server-provided value, but PostgreSQL
RLS is the actual enforcement layer: a user can only write/read the organization
they are a member of. Passing another tenant's organization_id is rejected by the
database, not by Python.

To keep per-test rollback isolation while letting the pipeline (which opens its
own connection via database.connect) share the test transaction, database.connect
is pointed at the shared test connection through a thin wrapper.
"""
import os
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
TEST_URL = os.getenv("NACELUX_TEST_DATABASE_URL", "")


class _SharedPgConn:
    """Wraps the shared test connection: adapts '?' -> '%s' and does NOT commit
    or rollback, leaving transaction control to the test (rollback per test)."""
    def __init__(self, raw):
        self._c = raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False  # no commit/rollback

    def execute(self, sql, params=()):
        return self._c.execute(sql.replace("?", "%s"), params)


@unittest.skipUnless(TEST_URL, "NACELUX_TEST_DATABASE_URL (non-owner runtime role) is required")
class Step3ImportRLSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg  # noqa
        import database as data  # noqa
        import import_pipeline as pipeline  # noqa
        cls.psycopg = psycopg
        cls.data = data
        cls.pipeline = pipeline
        cls.conn = psycopg.connect(TEST_URL, row_factory=psycopg.rows.dict_row)
        role = cls.conn.execute(
            "SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname=current_user").fetchone()
        if role["rolbypassrls"] or role["rolsuper"]:
            raise AssertionError("test role must not bypass RLS or be superuser")

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def setUp(self):
        # Route all database.connect()/rows()/one() calls to the shared connection.
        self.data.connect = lambda c=self.conn: _SharedPgConn(c)
        self.addCleanup(self.conn.rollback)
        self.org_a = "s3r_a_" + uuid.uuid4().hex[:10]
        self.org_b = "s3r_b_" + uuid.uuid4().hex[:10]
        self.user_a = "s3ru_a_" + uuid.uuid4().hex[:10]
        self.user_b = "s3ru_b_" + uuid.uuid4().hex[:10]
        self._provision(self.user_a, self.org_a)
        self._provision(self.user_b, self.org_b)

    def _ctx(self, org, user):
        self.conn.execute("SELECT set_config('app.organization_id', %s, false)", (org or "",))
        self.conn.execute("SELECT set_config('app.user_id', %s, false)", (user or "",))
        self.data.set_tenant_context(org, user)

    def _provision(self, user, org):
        self._ctx(None, user)
        self.conn.execute(
            "INSERT INTO users(id,email,display_name,created_at,auth_user_id,updated_at) "
            "VALUES(%s,%s,%s,CURRENT_TIMESTAMP,%s,CURRENT_TIMESTAMP)",
            (user, user + "@test.invalid", org, user))
        self.conn.execute("SELECT app_provision_workspace(%s,%s,%s,%s)", (org, org, org, user))

    def _row(self, name, rcs):
        return {"company_name": name, "rcs_number": rcs, "municipality": "Esch-sur-Alzette"}

    # 18 + 19: import is tenant-scoped; A's data is invisible to B (real RLS,
    #          no organization filter in the read WHERE -> pure RLS proof)
    def test_import_is_tenant_scoped_and_cross_tenant_denied(self):
        self._ctx(self.org_a, self.user_a)
        self.pipeline.run(self.org_a, None, [self._row("Alpha Real Sàrl", "R-A")], import_id="imp_a")
        self._ctx(self.org_a, self.user_a)
        self.assertEqual(len(self.data.rows("SELECT * FROM companies WHERE rcs_number=?", ("R-A",))), 1)
        self._ctx(self.org_b, self.user_b)
        self.assertEqual(len(self.data.rows("SELECT * FROM companies WHERE rcs_number=?", ("R-A",))), 0)

    # 20: a user cannot import INTO another tenant's organization, even when a
    #     different organization_id is supplied to the pipeline.
    def test_cannot_import_into_other_tenant_organization(self):
        self._ctx(self.org_a, self.user_a)  # authenticated as A
        with self.assertRaises(Exception):
            self.pipeline.run(self.org_b, None, [self._row("Forged Sàrl", "R-F")], import_id="imp_forge")
        self.conn.rollback()  # clear the aborted transaction caused by the RLS violation
        self._ctx(self.org_b, self.user_b)
        self.assertEqual(len(self.data.rows("SELECT * FROM companies WHERE rcs_number=?", ("R-F",))), 0)

    # raw_records and imports inherit the same tenant isolation
    def test_import_artifacts_are_tenant_isolated(self):
        self._ctx(self.org_a, self.user_a)
        self.pipeline.run(self.org_a, None, [self._row("Alpha Two Sàrl", "R-A2")], import_id="imp_a2")
        self._ctx(self.org_b, self.user_b)
        self.assertEqual(len(self.data.rows("SELECT * FROM imports WHERE id=?", ("imp_a2",))), 0)
        self.assertEqual(len(self.data.rows("SELECT * FROM raw_records")), 0)


if __name__ == "__main__":
    unittest.main()
