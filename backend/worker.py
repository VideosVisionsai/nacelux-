"""Background worker daemon for NACELUX Rev. 2.1.

Processes asynchronous jobs and queues:
- PDF native extraction & selective Tesseract OCR
- Safe SEO audits & Performance scoring
- Evidence-backed Business Signal calculation & refresh
- Official RESA journal ingestion & PDF document downloads
- Compliant People Intelligence extraction
- Website discovery & digital footprint checks
- Opportunity score recalculation
"""
from __future__ import annotations
import argparse, json, logging, os, signal, sys, time, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

import config
import database as data
if os.getenv('NACELUX_ENV','development').lower() in ('production','prod'):
    import auth as _production_auth
    _production_auth.validate_production_auth()
from resa_connector import LBRResaConnector
from document_storage import ResaPdfStoragePipeline
from pdf_extraction import PdfTextExtractionEngine
from nace_importer import OfficialNaceImporter
from website_intelligence import WebsiteDiscoveryEngine, DigitalFootprintEngine
from seo_engine import SEOAuditEngine, BusinessSignalEngine
from people_engine import PeopleEngine

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [worker] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('nacelux.worker')

RUNNING = True
MAX_ATTEMPTS = max(1, int(os.getenv('WORKER_MAX_ATTEMPTS', '3')))
RETRY_BACKOFF_SECONDS = max(0, int(os.getenv('WORKER_RETRY_BACKOFF_SECONDS', '5')))

def handle_shutdown(signum, frame):
    global RUNNING
    sig_name = signal.Signals(signum).name
    logger.info(f"Received {sig_name}. Initiating graceful shutdown...")
    RUNNING = False

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat() + 'Z'

class Worker:
    def __init__(self, db_connect=None):
        self.connect = db_connect or data.connect
        self.pdf_extraction = PdfTextExtractionEngine(self.connect)
        self.pdf_storage = ResaPdfStoragePipeline(self.connect)
        self.seo_audit = SEOAuditEngine(self.connect)
        self.business_signals = BusinessSignalEngine(self.connect)
        self.people_engine = PeopleEngine(self.connect)
        self.website_discovery = WebsiteDiscoveryEngine(self.connect)
        self.digital_footprint = DigitalFootprintEngine(self.connect)
        self.nace_importer = OfficialNaceImporter(self.connect)
        self.resa_connector = LBRResaConnector(self.connect)

    def process_queued_jobs(self, limit=10) -> int:
        """Fetch and atomically claim jobs marked as QUEUED in the database."""
        processed = 0
        now_iso = utcnow()
        claimed_jobs = []

        with self.connect() as db:
            # PostgreSQL uses SECURITY DEFINER queue functions so the worker
            # role does not own tenant tables or bypass RLS. SQLite keeps the
            # equivalent conditional-update implementation for development.
            if data.BACKEND == 'postgresql':
                db.execute("SELECT app_reap_orphan_jobs(?,?)", (15, MAX_ATTEMPTS)).fetchone()
                claimed_jobs = [dict(row) for row in db.execute(
                    "SELECT job_id,organization_id,job_type,payload,attempt,context_user_id FROM app_claim_jobs(?)",
                    (limit,)
                ).fetchall()]
            else:
                self._reap_stuck_jobs(db)
                ready_clause = "(next_attempt_at IS NULL OR next_attempt_at <= datetime('now'))"
                candidates = db.execute(
                    f"SELECT id, organization_id, job_type, payload, attempt FROM jobs WHERE status IN ('QUEUED','RETRY') AND {ready_clause} ORDER BY started_at ASC LIMIT ?",
                    (limit,)
                ).fetchall()
                for row in candidates:
                    job_id = row['id']
                    res = db.execute(
                        "UPDATE jobs SET status = 'RUNNING', started_at = ?, attempt = COALESCE(attempt, 0) + 1, next_attempt_at = NULL WHERE id = ? AND status IN ('QUEUED','RETRY')",
                        (now_iso, job_id)
                    )
                    if getattr(res, 'rowcount', 1) > 0:
                        claimed_jobs.append(dict(row))

        for job in claimed_jobs:
            if not RUNNING:
                break
            payload = {}
            if job.get('payload'):
                try:
                    payload = json.loads(job['payload']) if isinstance(job['payload'], str) else job['payload']
                except Exception:
                    payload = {}
            self.execute_job(job['id'], job['organization_id'], job['job_type'], payload, job.get('context_user_id'))
            processed += 1

        return processed

    def _reap_stuck_jobs(self, db, timeout_minutes=15):
        """Recover RUNNING jobs after a worker crash without hiding database errors."""
        if data.BACKEND == 'postgresql':
            cutoff = "CURRENT_TIMESTAMP - (%s * INTERVAL '1 minute')"
        else:
            cutoff = "datetime('now', '-' || ? || ' minutes')"
        retry_at = utcnow() if data.BACKEND == 'postgresql' else datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        db.execute(
            f"""UPDATE jobs
                SET status = CASE WHEN COALESCE(attempt, 1) >= ? THEN 'FAILED' ELSE 'RETRY' END,
                    error = 'Recovered from unexpected worker termination',
                    next_attempt_at = CASE WHEN COALESCE(attempt, 1) >= ? THEN NULL ELSE ? END
                WHERE status = 'RUNNING' AND started_at < {cutoff}""",
            (MAX_ATTEMPTS, MAX_ATTEMPTS, retry_at, timeout_minutes)
        )

    def execute_job(self, job_id: str, org_id: str, job_type: str, payload: dict, context_user_id: str | None = None) -> dict:
        """Execute a job inside its PostgreSQL tenant context."""
        previous = data.tenant_context()
        data.set_tenant_context(org_id, context_user_id)
        try:
            return self._execute_job(job_id, org_id, job_type, payload)
        finally:
            data.set_tenant_context(*previous)

    def _execute_job(self, job_id: str, org_id: str, job_type: str, payload: dict) -> dict:
        """Execute a single job and update its lifecycle status in the database."""
        started_at = utcnow()
        logger.info(f"Starting job {job_id} ({job_type}) for org {org_id}")

        with self.connect() as db:
            db.execute("UPDATE jobs SET status = 'RUNNING', started_at = ? WHERE id = ?", (started_at, job_id))

        status = 'SUCCESS'
        error = None
        records_processed = 0
        result = {}
        retryable = True

        try:
            if job_type == 'OPPORTUNITY_RECALCULATION':
                with self.connect() as db:
                    data.recalculate_all(db, org_id)
                records_processed = 1
                result = {'status': 'SUCCESS'}

            elif job_type == 'SEO_AUDIT':
                company_id = payload.get('company_id')
                if not company_id:
                    raise ValueError("company_id is required for SEO_AUDIT")
                result = self.seo_audit.audit(org_id, company_id)
                with self.connect() as db:
                    data.recalculate_all(db, org_id)
                records_processed = 1
                if result.get('status') not in ('SUCCESS', 'NOT_APPLICABLE'):
                    status = 'FAILED'
                    error = result.get('message')

            elif job_type == 'BUSINESS_SIGNAL_REFRESH':
                company_id = payload.get('company_id')
                result = self.business_signals.refresh(org_id, company_id)
                with self.connect() as db:
                    data.recalculate_all(db, org_id)
                records_processed = result.get('companies_processed', 0)
                if result.get('status') != 'SUCCESS':
                    status = 'FAILED'
                    error = result.get('message')

            elif job_type == 'PDF_EXTRACTION' or job_type == 'OCR_PROCESSING':
                document_id = payload.get('document_id')
                force_ocr = (job_type == 'OCR_PROCESSING') or bool(payload.get('force_ocr', False))
                if not document_id:
                    raise ValueError("document_id is required for PDF_EXTRACTION")
                result = self.pdf_extraction.extract_document(org_id, document_id, force_ocr=force_ocr)
                records_processed = result.get('extracted_pages', 0)
                if result.get('status') not in ('SUCCESS', 'PARTIAL', 'ALREADY_EXTRACTED'):
                    status = 'FAILED'
                    error = result.get('message')

            elif job_type == 'DOCUMENT_DOWNLOAD':
                document_id = payload.get('document_id')
                if not document_id:
                    raise ValueError("document_id is required for DOCUMENT_DOWNLOAD")
                result = self.pdf_storage.store_document(org_id, document_id)
                records_processed = 1 if result.get('status') == 'STORED' else 0
                if result.get('status') not in ('STORED', 'DUPLICATE', 'ALREADY_STORED'):
                    status = 'FAILED'
                    error = result.get('message')

            elif job_type == 'RESA_SYNC':
                source_url = payload.get('source_url', '')
                allow_browser = payload.get('allow_browser', True)
                result = self.resa_connector.analyze(org_id, source_url, allow_browser=allow_browser)
                records_processed = result.get('rows_detected', 0)
                if result.get('status') != 'SUCCESS':
                    status = 'FAILED'
                    error = result.get('message')

            elif job_type == 'PEOPLE_INTELLIGENCE':
                company_id = payload.get('company_id')
                if not company_id:
                    raise ValueError("company_id is required for PEOPLE_INTELLIGENCE")
                result = self.people_engine.analyze(org_id, company_id)
                self.business_signals.detect(org_id, company_id)
                with self.connect() as db:
                    data.recalculate_all(db, org_id)
                records_processed = result.get('official_people_found', 0)
                if result.get('status') != 'SUCCESS':
                    status = 'FAILED'
                    error = result.get('message')

            elif job_type == 'WEBSITE_DISCOVERY':
                company_id = payload.get('company_id')
                if not company_id:
                    raise ValueError("company_id is required for WEBSITE_DISCOVERY")
                result = self.website_discovery.discover(org_id, company_id)
                if result.get('status') == 'FOUND':
                    with self.connect() as db:
                        data.recalculate_all(db, org_id)
                records_processed = 1
                if result.get('status') not in ('FOUND', 'NOT_FOUND', 'NOT_CONFIGURED'):
                    status = 'FAILED'
                    error = result.get('message')

            elif job_type == 'DIGITAL_FOOTPRINT_CHECK':
                company_id = payload.get('company_id')
                if not company_id:
                    raise ValueError("company_id is required for DIGITAL_FOOTPRINT_CHECK")
                result = self.digital_footprint.analyze(org_id, company_id)
                with self.connect() as db:
                    data.recalculate_all(db, org_id)
                records_processed = 1
                if result.get('status') != 'SUCCESS':
                    status = 'FAILED'
                    error = result.get('message')

            elif job_type == 'NACE_SYNC':
                result = self.nace_importer.import_official()
                records_processed = result.get('classes', 0)
                if result.get('status') != 'SUCCESS':
                    status = 'FAILED'
                    error = result.get('message')

            else:
                status = 'FAILED'
                retryable = False
                error = f"Unsupported job type: {job_type}"

        except Exception as exc:
            status = 'FAILED'
            error = data.redact_error(exc)
            logger.error(f"Error executing job {job_id}: {error}")

        finished_at = utcnow()
        next_attempt_at = None
        with self.connect() as db:
            if status == 'FAILED' and retryable and error:
                row = db.execute("SELECT attempt FROM jobs WHERE id = ?", (job_id,)).fetchone()
                attempt = int(row['attempt'] or 0) if row else MAX_ATTEMPTS
                if attempt < MAX_ATTEMPTS:
                    delay = RETRY_BACKOFF_SECONDS * (2 ** max(0, attempt - 1))
                    next_attempt_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).replace(microsecond=0).isoformat()
                    status = 'RETRY'
            db.execute(
                "UPDATE jobs SET status = ?, finished_at = ?, records_processed = ?, error = ?, next_attempt_at = ? WHERE id = ?",
                (status, finished_at, records_processed, error, next_attempt_at, job_id)
            )

        logger.info(f"Finished job {job_id} with status {status} ({records_processed} items)")
        return {'job_id': job_id, 'status': status, 'records_processed': records_processed, 'error': error, 'result': result}

    def process_pending_extractions(self, limit=5) -> int:
        """Find downloaded RESA PDFs that have not yet had text extracted."""
        processed = 0
        with self.connect() as db:
            rows = db.execute(
                "SELECT id, organization_id FROM resa_documents WHERE download_status = 'STORED' AND (extraction_status IS NULL OR extraction_status IN ('NOT_STARTED', 'QUEUED')) LIMIT ?",
                (limit,)
            ).fetchall()

        for row in rows:
            if not RUNNING:
                break
            doc = dict(row)
            res = self.pdf_extraction.extract_document(doc['organization_id'], doc['id'])
            logger.info(f"Processed PDF extraction for doc {doc['id']}: {res.get('status')}")
            processed += 1

        return processed

    def process_pending_seo_audits(self, limit=5) -> int:
        """Find companies with verified websites that have not yet been SEO audited."""
        processed = 0
        with self.connect() as db:
            rows = db.execute(
                "SELECT c.id, c.organization_id FROM companies c LEFT JOIN seo_audits s ON s.company_id = c.id AND s.organization_id = c.organization_id WHERE c.website_status = 'FOUND' AND c.website IS NOT NULL AND (s.id IS NULL OR s.status = 'QUEUED') LIMIT ?",
                (limit,)
            ).fetchall()

        for row in rows:
            if not RUNNING:
                break
            c = dict(row)
            res = self.seo_audit.audit(c['organization_id'], c['id'])
            logger.info(f"Processed SEO audit for company {c['id']}: {res.get('status')}")
            processed += 1

        return processed

    def run_cycle(self) -> int:
        """Execute one complete polling cycle across all queues."""
        total = 0
        total += self.process_queued_jobs()
        total += self.process_pending_extractions()
        total += self.process_pending_seo_audits()
        return total

    def start_loop(self, interval_seconds: float = 5.0):
        """Start the continuous background worker polling loop."""
        logger.info(f"NACELUX background worker started (polling interval: {interval_seconds}s)")
        while RUNNING:
            try:
                processed = self.run_cycle()
                if processed > 0:
                    logger.info(f"Worker cycle processed {processed} item(s)")
            except Exception as exc:
                logger.error(f"Error during worker cycle: {data.redact_error(exc)}")

            # Sleep in 0.5s increments to respond promptly to shutdown signals
            slept = 0.0
            while RUNNING and slept < interval_seconds:
                time.sleep(0.5)
                slept += 0.5

        logger.info("NACELUX background worker stopped cleanly.")

def main():
    parser = argparse.ArgumentParser(description="NACELUX Background Worker")
    parser.add_argument('--once', action='store_true', help="Run one pass of all queues and exit")
    parser.add_argument('--interval', type=float, default=float(os.getenv('WORKER_INTERVAL_SECONDS', '5.0')), help="Polling interval in seconds (default: 5.0)")
    parser.add_argument('--job', type=str, help="Execute a specific job ID and exit")
    args = parser.parse_args()

    data.init_db()
    worker = Worker()

    if args.job:
        with data.connect() as db:
            row = db.execute("""SELECT j.id,j.organization_id,j.job_type,j.payload,
                (SELECT om.user_id FROM organization_members om WHERE om.organization_id=j.organization_id
                 ORDER BY CASE om.role WHEN 'OWNER' THEN 1 WHEN 'ADMIN' THEN 2 ELSE 3 END LIMIT 1) context_user_id
                FROM jobs j WHERE j.id = ?""", (args.job,)).fetchone()
            if not row:
                logger.error(f"Job {args.job} not found")
                sys.exit(1)
            job = dict(row)
            payload = json.loads(job['payload']) if isinstance(job.get('payload'), str) else (job.get('payload') or {})
            res = worker.execute_job(job['id'], job['organization_id'], job['job_type'], payload, job.get('context_user_id'))
            print(json.dumps(res, indent=2))
            sys.exit(0 if res.get('status') == 'SUCCESS' else 1)

    if args.once:
        logger.info("Running single worker pass...")
        count = worker.run_cycle()
        logger.info(f"Pass complete: {count} task(s) processed.")
        sys.exit(0)

    worker.start_loop(interval_seconds=args.interval)

if __name__ == '__main__':
    main()
