import json, sqlite3, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

import database
from worker import Worker

class WorkerConcurrencyTests(unittest.TestCase):
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
            db.execute("INSERT INTO organizations VALUES(?,?,?,?)", ('org_conc_test', 'Conc Test Workspace', 'conc-ws', ts))
            db.execute("INSERT INTO users VALUES(?,?,?,?)", ('user_conc_test', 'conc@nacelux.local', 'Conc Tester', ts))
            db.execute("INSERT INTO organization_members VALUES(?,?,?)", ('org_conc_test', 'user_conc_test', 'OWNER'))

        self.worker1 = Worker(self.connect)
        self.worker2 = Worker(self.connect)

    def tearDown(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_concurrent_worker_instances_claim_disjoint_jobs(self):
        # Insert 4 jobs into the queue
        with self.connect() as db:
            for i in range(1, 5):
                db.execute(
                    "INSERT INTO jobs(id, organization_id, job_type, status, started_at, payload) VALUES(?,?,?,?,?,?)",
                    (f'job_conc_{i}', 'org_conc_test', 'OPPORTUNITY_RECALCULATION', 'QUEUED', '2026-08-21T00:00:00Z', '{}')
                )

        # Worker 1 processes up to 2 jobs
        p1 = self.worker1.process_queued_jobs(limit=2)
        # Worker 2 processes up to 2 jobs
        p2 = self.worker2.process_queued_jobs(limit=2)

        self.assertEqual(p1, 2)
        self.assertEqual(p2, 2)

        with self.connect() as db:
            success_count = db.execute("SELECT count(*) FROM jobs WHERE organization_id = 'org_conc_test' AND status = 'SUCCESS'").fetchone()[0]
            self.assertEqual(success_count, 4)

    def test_stuck_job_reaper_recovers_orphaned_jobs(self):
        job_id = 'job_stuck_1'
        # Insert a job stuck in RUNNING state from 30 minutes ago
        with self.connect() as db:
            db.execute(
                "INSERT INTO jobs(id, organization_id, job_type, status, started_at, payload, attempt, schedule) VALUES(?,?,?,?,datetime('now', '-30 minutes'),?,?, 'RETRY')",
                (job_id, 'org_conc_test', 'OPPORTUNITY_RECALCULATION', 'RUNNING', '{}', 1)
            )

        # Running a cycle should recover and execute the stuck job
        processed = self.worker1.process_queued_jobs(limit=10)
        self.assertEqual(processed, 1)

        with self.connect() as db:
            job = dict(db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())
            self.assertEqual(job['status'], 'SUCCESS')
            self.assertGreaterEqual(job['attempt'], 2)

if __name__ == '__main__':
    unittest.main()
