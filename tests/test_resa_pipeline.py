"""RESA -> commercial pipeline integration tests (Étape: RESA integration).

The real LBR/RESA source is unreachable from this sandbox, so the connector stays
REQUIRES_CONFIGURATION. These tests verify the INTEGRATION logic (extraction,
company matching, official people evidence, lineage, dedup, idempotence, tenant
isolation) with clearly-labeled synthetic RESA-like text (never production data).
"""
import json, os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import database as data
import resa_pipeline as rp

RESA_URL = "https://www.lbr.lu/mjrcs-web-front/publication-journal/RESA-2026_1_1_0"
SAMPLE = ("Dénomination: Alpha Tech Sàrl  RCS B 299777  Activité principale: 62.10  "
          "Gérant: Sophie Weber  Administrateur: Marc Hoffmann")


class ResaPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.tmp.close()
        os.environ["NACELUX_DB"] = cls.tmp.name
        data.init_db()
        ts = data.now()
        with data.connect() as db:
            db.execute("INSERT OR IGNORE INTO organizations(id,name,slug,created_at) VALUES(?,?,?,?)", ("o", "O", "o", ts))
            db.execute("INSERT OR IGNORE INTO organizations(id,name,slug,created_at) VALUES(?,?,?,?)", ("o2", "O2", "o2", ts))

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("NACELUX_DB", None)
        Path(cls.tmp.name).unlink(missing_ok=True)

    def test_extraction_is_explicit_only(self):
        facts = rp.extract_company_facts(SAMPLE)
        self.assertEqual(facts["company_name"], "Alpha Tech Sàrl")
        self.assertEqual(facts["rcs_number"], "B299777")
        self.assertEqual(facts["primary_nace_code"], "62.10")
        people = rp.extract_people_facts(SAMPLE)
        self.assertEqual({p["display_name"] for p in people}, {"Sophie Weber", "Marc Hoffmann"})
        # nothing labelled -> nothing extracted (no invention)
        self.assertEqual(rp.extract_company_facts("random text"), {})
        self.assertEqual(rp.extract_people_facts("no directors named here"), [])

    def test_ingest_creates_company_people_lineage(self):
        r = rp.ingest("o", source_url=RESA_URL, document_text=SAMPLE, resa_entry_id="re1")
        self.assertEqual(r["status"], "SUCCESS")
        self.assertEqual(r["company_name"], "Alpha Tech Sàrl")
        self.assertEqual(r["people_found"], 2)
        # company + people persisted
        self.assertEqual(data.one("SELECT company_name FROM companies WHERE id=?", (r["company_id"],))["company_name"], "Alpha Tech Sàrl")
        self.assertEqual(data.one("SELECT count(*) c FROM people WHERE organization_id='o' AND company_id=?", (r["company_id"],))["c"], 2)
        # official people evidence
        ev = data.one("SELECT count(*) c FROM people_evidence WHERE organization_id='o' AND method='RESA_EXTRACTION'")["c"]
        self.assertGreaterEqual(ev, 2)
        # raw_record + lineage with SHA-256 + RESA source
        prov = rp.provenance("o", r["company_id"])
        self.assertGreater(len(prov["lineage"]), 0)
        self.assertTrue(all(len(l["checksum"]) == 64 for l in prov["lineage"]))
        self.assertGreaterEqual(len(prov["raw_records"]), 1)
        self.assertEqual(prov["source"]["status"], "REQUIRES_CONFIRMATION")

    def test_idempotent_reingest(self):
        r1 = rp.ingest("o", source_url=RESA_URL, document_text=SAMPLE, resa_entry_id="re2")
        raw_before = data.one("SELECT count(*) c FROM raw_records WHERE organization_id='o' AND external_id='re2'")["c"]
        r2 = rp.ingest("o", source_url=RESA_URL, document_text=SAMPLE, resa_entry_id="re2")
        raw_after = data.one("SELECT count(*) c FROM raw_records WHERE organization_id='o' AND external_id='re2'")["c"]
        self.assertEqual(r2["company_id"], r1["company_id"])  # same company
        self.assertEqual(raw_before, raw_after)  # no duplicate raw record
        self.assertEqual(data.one("SELECT count(*) c FROM people WHERE organization_id='o' AND company_id=?", (r1["company_id"],))["c"], 2)

    def test_company_matching_by_rcs(self):
        r1 = rp.ingest("o", source_url=RESA_URL, document_text="Dénomination: Match Co  RCS B299888  Activité principale: 62.10", resa_entry_id="re3")
        # a second publication for the same RCS -> matched to the SAME company (not a new one)
        r2 = rp.ingest("o", source_url=RESA_URL, document_text="Dénomination: Match Co  RCS B299888  Activité principale: 62.10", resa_entry_id="re4")
        self.assertEqual(r2["company_id"], r1["company_id"])  # deterministic RCS match
        self.assertEqual(r2["action"], "UNCHANGED")

    def test_no_company_name_no_invention(self):
        r = rp.ingest("o", source_url=RESA_URL, document_text="Publication mentions RCS B000111 but no company name label", resa_entry_id="re5")
        self.assertEqual(r["status"], "NO_COMPANY")
        self.assertIsNone(r["company_name"])

    def test_tenant_isolation(self):
        r = rp.ingest("o", source_url=RESA_URL, document_text="Dénomination: Tenant A Co  RCS B300001", resa_entry_id="reA")
        leak = data.rows("SELECT * FROM companies WHERE organization_id='o2' AND rcs_number='B300001'")
        self.assertEqual(len(leak), 0)
        prov_o2 = rp.provenance("o2", r["company_id"])
        self.assertIsNone(prov_o2)  # other tenant cannot see the chain

    def test_no_secrets_in_pipeline_output(self):
        r = rp.ingest("o", source_url=RESA_URL, document_text="Dénomination: Secret Co  RCS B300002", resa_entry_id="reS")
        blob = json.dumps(r, default=str) + json.dumps(rp.provenance("o", r["company_id"]), default=str)
        for forbidden in ("password", "postgresql://", "service_role", "eyJ", "supabase"):
            self.assertNotIn(forbidden, blob.lower())

    def test_data_source_registered_as_requires_confirmation(self):
        rp.ingest("o", source_url=RESA_URL, document_text="Dénomination: Source Co  RCS B300003", resa_entry_id="reSrc")
        src = data.one("SELECT status,provider FROM data_sources WHERE organization_id='o' AND provider='LBR'")
        self.assertIsNotNone(src)
        self.assertEqual(src["status"], "REQUIRES_CONFIRMATION")  # never VERIFIED without real access


if __name__ == "__main__":
    unittest.main()
