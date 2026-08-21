import json, os, sqlite3, sys, tempfile, unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

import database
from worker import Worker

class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()

        def connect():
            db = sqlite3.connect(self.tmp.name)
            db.row_factory = sqlite3.Row
            return db

        self.connect = connect
        with connect() as db:
            db.executescript(database.SCHEMA)
            ts = '2026-08-21T00:00:00Z'
            db.execute("INSERT INTO organizations VALUES(?,?,?,?)", ('org_worker_test', 'Test Workspace', 'test-ws', ts))
            db.execute("INSERT INTO users VALUES(?,?,?,?)", ('user_worker_test', 'worker@nacelux.local', 'Worker Tester', ts))
            db.execute("INSERT INTO organization_members VALUES(?,?,?)", ('org_worker_test', 'user_worker_test', 'OWNER'))

        self.worker = Worker(self.connect)

    def tearDown(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_worker_opportunity_recalculation_job(self):
        job_id = 'job_test_opp'
        with self.connect() as db:
            db.execute(
                "INSERT INTO jobs(id, organization_id, job_type, status, started_at, payload) VALUES(?,?,?,?,?,?)",
                (job_id, 'org_worker_test', 'OPPORTUNITY_RECALCULATION', 'QUEUED', '2026-08-21T00:00:00Z', '{}')
            )

        processed = self.worker.process_queued_jobs(limit=10)
        self.assertEqual(processed, 1)

        with self.connect() as db:
            job = dict(db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())
            self.assertEqual(job['status'], 'SUCCESS')
            self.assertIsNotNone(job['finished_at'])

    def test_worker_handles_unknown_job_gracefully(self):
        job_id = 'job_unknown'
        with self.connect() as db:
            db.execute(
                "INSERT INTO jobs(id, organization_id, job_type, status, started_at, payload) VALUES(?,?,?,?,?,?)",
                (job_id, 'org_worker_test', 'INVALID_JOB_TYPE', 'QUEUED', '2026-08-21T00:00:00Z', '{}')
            )

        processed = self.worker.process_queued_jobs(limit=10)
        self.assertEqual(processed, 1)

        with self.connect() as db:
            job = dict(db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())
            self.assertEqual(job['status'], 'FAILED')
            self.assertIn('Unsupported job type', job['error'])

    def test_worker_run_cycle_returns_total(self):
        count = self.worker.run_cycle()
        self.assertIsInstance(count, int)
        self.assertGreaterEqual(count, 0)

    def test_retry_then_failed_after_max_attempts(self):
        job_id = 'job_retry_policy'
        with self.connect() as db:
            db.execute(
                "INSERT INTO jobs(id, organization_id, job_type, status, started_at, payload) VALUES(?,?,?,?,?,?)",
                (job_id, 'org_worker_test', 'OPPORTUNITY_RECALCULATION', 'QUEUED', '2026-08-21T00:00:00Z', '{}')
            )
        with patch.object(database, 'recalculate_all', side_effect=RuntimeError('transient failure')):
            self.assertEqual(self.worker.process_queued_jobs(limit=1), 1)
            with self.connect() as db:
                row=db.execute('SELECT status,attempt,schedule FROM jobs WHERE id=?', (job_id,)).fetchone()
                self.assertEqual(row['status'], 'RETRY')
                self.assertEqual(row['schedule'], 'RETRY')
            for expected in ('RETRY', 'FAILED'):
                with self.connect() as db:
                    db.execute("UPDATE jobs SET schedule='RETRY',started_at=datetime('now') WHERE id=?", (job_id,))
                self.assertEqual(self.worker.process_queued_jobs(limit=1), 1)
                with self.connect() as db:
                    self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()['status'], expected)

if __name__ == '__main__':
    unittest.main()
