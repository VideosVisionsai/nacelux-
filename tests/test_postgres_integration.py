"""Opt-in integration tests for a dedicated PostgreSQL test database.

These tests are intentionally skipped unless NACELUX_RUN_POSTGRES_INTEGRATION=1
and NACELUX_TEST_DATABASE_URL are supplied. They must never point at production.
No test performs DROP/TRUNCATE/DELETE; each fixture runs in a rolled-back
transaction and the worker test uses unique IDs in a dedicated test database.
"""
import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_URL = os.getenv('NACELUX_TEST_DATABASE_URL', '')
RUN = os.getenv('NACELUX_RUN_POSTGRES_INTEGRATION') == '1' and bool(TEST_URL)


@unittest.skipUnless(RUN, 'PostgreSQL integration requires NACELUX_RUN_POSTGRES_INTEGRATION=1 and NACELUX_TEST_DATABASE_URL')
class PostgreSQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.getenv('DATABASE_URL') and os.getenv('DATABASE_URL') == TEST_URL:
            raise RuntimeError('The PostgreSQL integration suite must not target the configured production DATABASE_URL')
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise unittest.SkipTest('psycopg is not installed') from exc
        cls.psycopg = psycopg
        cls.dict_row = dict_row
        cls.conn = psycopg.connect(TEST_URL, row_factory=dict_row)
        cls.conn.execute('SELECT 1').fetchone()
        if not cls.conn.info.ssl_in_use:
            raise AssertionError('PostgreSQL integration connection is not using SSL')
        versions = {r['version'] for r in cls.conn.execute('SELECT version FROM schema_migrations').fetchall()}
        required = {'0012_job_retry_backoff', '0013_rls_runtime_hardening', '0014_worker_rls_queue_functions'}
        missing = required - versions
        if missing:
            raise AssertionError(f'Dedicated PostgreSQL test database is missing migrations: {sorted(missing)}')

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, 'conn', None):
            cls.conn.close()

    def setUp(self):
        self.conn = self.psycopg.connect(TEST_URL, row_factory=self.dict_row)
        self.org_a = 'itest_org_a_' + uuid.uuid4().hex[:12]
        self.org_b = 'itest_org_b_' + uuid.uuid4().hex[:12]
        self.user_a = 'itest_user_a_' + uuid.uuid4().hex[:12]
        self.user_b = 'itest_user_b_' + uuid.uuid4().hex[:12]
        self.company_a = 'itest_company_a_' + uuid.uuid4().hex[:12]
        self.company_b = 'itest_company_b_' + uuid.uuid4().hex[:12]
        self.job_a = 'itest_job_a_' + uuid.uuid4().hex[:12]
        self.job_b = 'itest_job_b_' + uuid.uuid4().hex[:12]
        self._set_context(None, self.user_a)
        self.conn.execute(
            "INSERT INTO users(id,email,display_name,created_at,auth_user_id,updated_at) VALUES(%s,%s,%s,CURRENT_TIMESTAMP,%s,CURRENT_TIMESTAMP)",
            (self.user_a, self.user_a + '@test.invalid', 'Tenant A', self.user_a),
        )
        self.conn.execute('SELECT app_provision_workspace(%s,%s,%s,%s)', (self.org_a, 'Tenant A', self.org_a, self.user_a))
        self._set_context(self.org_a, self.user_a)
        self._insert_tenant_rows(self.org_a, self.user_a, self.company_a, self.job_a)
        self._set_context(None, self.user_b)
        self.conn.execute(
            "INSERT INTO users(id,email,display_name,created_at,auth_user_id,updated_at) VALUES(%s,%s,%s,CURRENT_TIMESTAMP,%s,CURRENT_TIMESTAMP)",
            (self.user_b, self.user_b + '@test.invalid', 'Tenant B', self.user_b),
        )
        self.conn.execute('SELECT app_provision_workspace(%s,%s,%s,%s)', (self.org_b, 'Tenant B', self.org_b, self.user_b))
        self._set_context(self.org_b, self.user_b)
        self._insert_tenant_rows(self.org_b, self.user_b, self.company_b, self.job_b)
        self._set_context(self.org_a, self.user_a)

    def tearDown(self):
        self.conn.rollback()
        self.conn.close()

    def _set_context(self, organization_id, user_id):
        self.conn.execute("SELECT set_config('app.organization_id', %s, false)", (organization_id or '',))
        self.conn.execute("SELECT set_config('app.user_id', %s, false)", (user_id or '',))

    def _insert_tenant_rows(self, org, user, company, job):
        self.conn.execute(
            """INSERT INTO companies(id,organization_id,company_name,created_at,updated_at)
               VALUES(%s,%s,%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""",
            (company, org, org + ' company'),
        )
        self.conn.execute(
            """INSERT INTO opportunity_scores(id,organization_id,company_id,score,level,breakdown,calculated_at)
               VALUES(%s,%s,%s,50,'MEDIUM','{}',CURRENT_TIMESTAMP)""",
            ('score_' + company, org, company),
        )
        self.conn.execute(
            "INSERT INTO prospects(id,organization_id,company_id,status,created_at,updated_at) VALUES(%s,%s,%s,'NEW',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
            ('prospect_' + company, org, company),
        )
        self.conn.execute(
            """INSERT INTO jobs(id,organization_id,job_type,status,started_at,finished_at,records_processed,error,payload,attempt,schedule,next_attempt_at)
               VALUES(%s,%s,'OPPORTUNITY_RECALCULATION','QUEUED',CURRENT_TIMESTAMP,NULL,0,NULL,'{}',0,NULL,NULL)""",
            (job, org),
        )
        self.conn.execute(
            "INSERT INTO audit_logs(id,organization_id,user_id,action,entity_type,entity_id,metadata,created_at) VALUES(%s,%s,%s,'CREATE','company',%s,'{}',CURRENT_TIMESTAMP)",
            ('audit_' + company, org, user, company),
        )

    def test_rls_blocks_cross_tenant_reads_and_writes(self):
        tables = {
            'companies': self.company_b,
            'opportunity_scores': 'score_' + self.company_b,
            'prospects': 'prospect_' + self.company_b,
            'jobs': self.job_b,
            'audit_logs': None,
        }
        for table, row_id in tables.items():
            if row_id:
                result = self.conn.execute(f'SELECT count(*) AS count FROM {table} WHERE id=%s', (row_id,)).fetchone()['count']
                self.assertEqual(result, 0, table)
        self.assertEqual(self.conn.execute('SELECT count(*) AS count FROM audit_logs WHERE organization_id=%s', (self.org_b,)).fetchone()['count'], 0)
        updated = self.conn.execute('UPDATE companies SET company_name=%s WHERE id=%s', ('forbidden', self.company_b))
        self.assertEqual(updated.rowcount, 0)
        self._set_context(self.org_b, self.user_b)
        self.assertEqual(self.conn.execute('SELECT company_name FROM companies WHERE id=%s', (self.company_b,)).fetchone()['company_name'], self.org_b + ' company')

    def test_jobs_use_explicit_columns_and_lifecycle(self):
        row = self.conn.execute('SELECT status,attempt,payload FROM jobs WHERE id=%s', (self.job_a,)).fetchone()
        self.assertEqual(row['status'], 'QUEUED')
        self.conn.execute("UPDATE jobs SET status='RUNNING',attempt=attempt+1 WHERE id=%s AND status='QUEUED'", (self.job_a,))
        self.conn.execute("UPDATE jobs SET status='RETRY',next_attempt_at=CURRENT_TIMESTAMP WHERE id=%s", (self.job_a,))
        self.conn.execute("UPDATE jobs SET status='RUNNING',attempt=attempt+1,next_attempt_at=NULL WHERE id=%s AND status='RETRY'", (self.job_a,))
        self.conn.execute("UPDATE jobs SET status='SUCCESS',finished_at=CURRENT_TIMESTAMP WHERE id=%s", (self.job_a,))
        self.assertEqual(self.conn.execute('SELECT status FROM jobs WHERE id=%s', (self.job_a,)).fetchone()['status'], 'SUCCESS')

    def test_two_postgres_claimers_get_disjoint_jobs(self):
        self.conn.commit()
        conn2 = self.psycopg.connect(TEST_URL, row_factory=self.dict_row)
        try:
            rows_a = self.conn.execute('SELECT * FROM app_claim_jobs(%s)', (1,)).fetchall()
            rows_b = conn2.execute('SELECT * FROM app_claim_jobs(%s)', (1,)).fetchall()
            self.conn.commit()
            conn2.commit()
            self.assertTrue(rows_a and rows_b)
            self.assertNotEqual(rows_a[0]['job_id'], rows_b[0]['job_id'])
        finally:
            conn2.rollback()
            conn2.close()

    def test_worker_processes_postgres_job_in_real_runtime(self):
        self.conn.execute("UPDATE jobs SET status='FAILED' WHERE id=%s", (self.job_b,))
        self.conn.commit()
        env = {
            **os.environ,
            'NACELUX_ENV': 'production',
            'DB_PROVIDER': 'postgresql',
            'DATABASE_URL': TEST_URL,
            'AUTO_MIGRATE': 'false',
            'WORKER_MAX_ATTEMPTS': '3',
        }
        script = """
import sys
sys.path.insert(0, 'backend')
import database
from worker import Worker
database.init_db()
assert Worker().process_queued_jobs(limit=1) == 1
"""
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.conn.execute('SELECT status FROM jobs WHERE id=%s', (self.job_a,)).fetchone()['status'], 'SUCCESS')


if __name__ == '__main__':
    unittest.main()
