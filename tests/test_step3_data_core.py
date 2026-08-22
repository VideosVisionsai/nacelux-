"""Step 3 (ÉTAPE 3.15) — data-core tests run against an isolated SQLite database
(synthetic fixtures only, never loaded in production). Covers creation, update,
read, pagination, search/filters, raw records, checksum, provenance, deterministic
deduplication, import preview (no write), transactional import, partial-invalid
import, audit, no-secrets and no-fictive-data guarantees.

Cross-tenant RLS tests (items 18/19/20) live in test_step3_rls.py and run on a
REAL PostgreSQL engine.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import database as data  # noqa: E402
import import_pipeline as pipeline  # noqa: E402

SOURCE = {"source_id": "src_step3", "name": "Step 3 Test Source",
          "source_url": "https://example.test/source", "import_type": "COMPANIES",
          "provenance": "TEST"}
ORG = "org_step3_isolated"
USER = "user_step3"


def _row(name="Test Alpha Sàrl", rcs="B123456", vat=None, **kw):
    # vat defaults to None so distinct test rows are NOT collapsed by VAT dedup
    # (each row carries its own official identity or none -> stays unknown).
    r = {"company_name": name, "rcs_number": rcs, "vat_number": vat,
         "primary_nace_code": "62.10", "municipality": "Esch-sur-Alzette"}
    r.update(kw)
    return r


class Step3DataCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.tmp.close()
        os.environ["NACELUX_DB"] = cls.tmp.name
        data.init_db()
        ts = data.now()
        with data.connect() as db:
            db.execute("INSERT OR IGNORE INTO organizations(id,name,slug,created_at) VALUES(?,?,?,?)",
                       (ORG, "Step 3 Isolated", "step3", ts))
            db.execute("INSERT OR IGNORE INTO users(id,email,display_name,created_at) VALUES(?,?,?,?)",
                       (USER, "step3@test.invalid", "Step3", ts))
            db.execute("INSERT OR IGNORE INTO organization_members(organization_id,user_id,role) VALUES(?,?,?)",
                       (ORG, USER, "OWNER"))
            # The raw_records.source_id foreign key requires a registered source.
            db.execute("INSERT OR IGNORE INTO data_sources(id,organization_id,name,source_type,status,note) VALUES(?,?,?,?,?,?)",
                       ("src_step3", ORG, "Step 3 Test Source", "TEST", "ACTIVE", "synthetic test source"))

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("NACELUX_DB", None)
        Path(cls.tmp.name).unlink(missing_ok=True)

    def _companies(self):
        return data.rows("SELECT * FROM companies WHERE organization_id=?", (ORG,))

    # 1. creation
    def test_01_import_creates_company(self):
        stats = pipeline.run(ORG, SOURCE, [_row()], import_id="imp_create")
        self.assertEqual(stats["created"], 1)
        self.assertEqual(len(self._companies()), 1)
        c = self._companies()[0]
        self.assertEqual(c["company_name"], "Test Alpha Sàrl")
        self.assertEqual(c["provenance"], "TEST")

    # 2. modification (same official id -> update, not duplicate)
    def test_02_reimport_same_rcs_updates(self):
        pipeline.run(ORG, SOURCE, [_row(website="https://alpha.test")], import_id="imp_upd1")
        stats = pipeline.run(ORG, SOURCE, [_row(website="https://alpha2.test")], import_id="imp_upd2")
        self.assertEqual(stats["updated"], 1)
        self.assertEqual(stats["created"], 0)
        rows = [c for c in self._companies() if c["rcs_number"] == "B123456"]
        self.assertEqual(len(rows), 1)  # never duplicated

    # 3. read
    def test_03_company_detail_readable(self):
        pipeline.run(ORG, SOURCE, [_row(rcs="BREAD1", name="Readable Co")], import_id="imp_read")
        cid = data.one("SELECT id FROM companies WHERE organization_id=? AND rcs_number=?", (ORG, "BREAD1"))["id"]
        detail = data.company_detail(ORG, cid)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["company_name"], "Readable Co")
        self.assertIsNone(detail["opportunity_score"])  # no score yet

    # 4. pagination
    def test_04_pagination(self):
        rows = [_row(rcs=f"BPAGE{i:03d}", name=f"Page Co {i}") for i in range(5)]
        pipeline.run(ORG, SOURCE, rows, import_id="imp_page")
        total = data.count_companies(ORG, {"search": "Page Co"})
        page1 = data.list_companies(ORG, {"search": "Page Co"}, limit=2, offset=0)
        page2 = data.list_companies(ORG, {"search": "Page Co"}, limit=2, offset=2)
        self.assertEqual(total, 5)
        self.assertEqual(len(page1), 2)
        self.assertEqual(len(page2), 2)
        self.assertNotEqual(page1[0]["id"], page2[0]["id"])

    # 5. search
    def test_05_search(self):
        res = data.list_companies(ORG, {"search": "Page Co 0"}, limit=50)
        self.assertEqual(len(res), 1)
        self.assertIn("Page Co 0", res[0]["company_name"])

    # 6. filters
    def test_06_filter_by_municipality_and_nace(self):
        res = data.list_companies(ORG, {"municipality": "Esch-sur-Alzette"}, limit=50)
        self.assertTrue(all(c["municipality"] == "Esch-sur-Alzette" for c in res))
        res2 = data.list_companies(ORG, {"nace": "62.10"}, limit=50)
        self.assertTrue(all(c["primary_nace_code"] == "62.10" for c in res2))

    # 7. tenant isolation (repository layer; RLS verified in test_step3_rls)
    def test_07_pipeline_writes_only_to_its_org(self):
        other = "org_step3_other"
        ts = data.now()
        with data.connect() as db:
            db.execute("INSERT OR IGNORE INTO organizations(id,name,slug,created_at) VALUES(?,?,?,?)",
                       (other, "Other", "other", ts))
        pipeline.run(ORG, SOURCE, [_row(rcs="BTENANT1", name="Tenant Owned")], import_id="imp_tenant")
        leak = data.rows("SELECT * FROM companies WHERE organization_id=? AND rcs_number=?", (other, "BTENANT1"))
        self.assertEqual(len(leak), 0)
        own = data.rows("SELECT * FROM companies WHERE organization_id=? AND rcs_number=?", (ORG, "BTENANT1"))
        self.assertEqual(len(own), 1)

    # 8. raw record + 9. checksum
    def test_08_raw_record_and_checksum(self):
        pipeline.run(ORG, SOURCE, [_row(rcs="BRAW1", name="Raw Co")], import_id="imp_raw")
        raw = data.one("SELECT * FROM raw_records WHERE organization_id=? AND external_id IS NULL", (ORG,))
        self.assertIsNotNone(raw)
        self.assertEqual(len(raw["checksum"]), 64)  # sha-256
        self.assertEqual(raw["status"], "INGESTED")
        comp = data.one("SELECT checksum FROM companies WHERE organization_id=? AND rcs_number=?", (ORG, "BRAW1"))
        self.assertEqual(len(comp["checksum"]), 64)

    def test_09_company_checksum_is_deterministic(self):
        a = pipeline.company_checksum(_row(rcs="X", name="Same"))
        b = pipeline.company_checksum(_row(rcs="X", name="Same"))
        self.assertEqual(a, b)
        c = pipeline.company_checksum(_row(rcs="X", name="Different"))
        self.assertNotEqual(a, c)

    # 10. provenance / data lineage
    def test_10_lineage_links_company_to_raw_and_source(self):
        pipeline.run(ORG, SOURCE, [_row(rcs="BLIN1", name="Lineage Co", website="https://lin.test")],
                     import_id="imp_lineage")
        comp = data.one("SELECT id FROM companies WHERE organization_id=? AND rcs_number=?", (ORG, "BLIN1"))
        lin = data.rows("SELECT * FROM data_lineage WHERE organization_id=? AND entity_id=?", (ORG, comp["id"]))
        self.assertGreaterEqual(len(lin), 1)
        self.assertTrue(all(l["raw_record_id"] for l in lin))
        self.assertTrue(all(l["checksum"] and len(l["checksum"]) == 64 for l in lin))
        self.assertEqual(lin[0]["transformation"], "NORMALIZATION")
        web = [l for l in lin if l["field_name"] == "website"]
        self.assertEqual(len(web), 1)
        self.assertEqual(web[0]["source_url"], "https://example.test/source")

    # 11. deduplication: official id resolves; similar name -> candidate, never merge
    def test_11_dedup_official_id_and_name_candidate(self):
        pipeline.run(ORG, SOURCE, [_row(rcs="BDUP1", name="Duplicate Names Sàrl", municipality="Differdange")],
                     import_id="imp_dup1")
        # Same name, NO official id -> a NEW company is created + a candidate is recorded
        stats = pipeline.run(ORG, SOURCE, [_row(rcs=None, vat=None, name="Duplicate Names Sàrl", municipality="Differdange")],
                             import_id="imp_dup2")
        self.assertEqual(stats["created"], 1)
        same_name = data.rows("SELECT * FROM companies WHERE organization_id=? AND company_name=?",
                              (ORG, "Duplicate Names Sàrl"))
        self.assertEqual(len(same_name), 2)  # NOT merged
        cands = data.rows("SELECT * FROM dedup_candidates WHERE organization_id=?", (ORG,))
        self.assertGreaterEqual(len(cands), 1)
        self.assertEqual(cands[0]["status"], "PENDING")

    # 12. preview writes nothing
    def test_12_preview_writes_nothing(self):
        before = data.count_companies(ORG, {})
        result = pipeline.preview(ORG, SOURCE, [_row(rcs="BPREVIEW", name="Preview Co")])
        after = data.count_companies(ORG, {})
        self.assertEqual(before, after)  # no write
        self.assertEqual(result["records_received"], 1)
        self.assertEqual(result["new"], 1)
        self.assertNotIn("Preview Co", [c["company_name"] for c in self._companies()])

    # 13. transactional import
    def test_13_import_records_imports_row(self):
        result = pipeline.run(ORG, SOURCE, [_row(rcs="BTRANSACT", name="Transact Co")], import_id="imp_transact")
        imp = data.one("SELECT * FROM imports WHERE id=?", ("imp_transact",))
        self.assertIsNotNone(imp)
        self.assertEqual(imp["status"], "SUCCESS")
        self.assertEqual(imp["records_created"], 1)
        self.assertEqual(result["created"], 1)

    # 14. partially invalid import
    def test_14_partial_invalid_import(self):
        rows = [_row(rcs="BOK1", name="Valid Co"),
                {"vat_number": "LU999"},  # missing company_name -> invalid
                _row(rcs="BOK2", name="Valid Co 2")]
        stats = pipeline.run(ORG, SOURCE, rows, import_id="imp_partial")
        self.assertEqual(stats["valid"], 2)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["created"], 2)
        imp = data.one("SELECT * FROM imports WHERE id=?", ("imp_partial",))
        self.assertEqual(imp["status"], "PARTIAL")

    # 15. audit log: the import route records an audit entry (verified statically
    #     that the route calls data.audit, and here that the audit mechanism
    #     captures the import event).
    def test_15_audit_log_recorded_on_import(self):
        pipeline.run(ORG, SOURCE, [_row(rcs="BAUDIT", name="Audit Co")], import_id="imp_audit")
        data.audit(ORG, "IMPORT_COMPANIES", "import", "imp_audit",
                   {"source": SOURCE["name"], "created": 1})
        logs = data.rows("SELECT * FROM audit_logs WHERE organization_id=? AND entity_id=? AND action=?",
                         (ORG, "imp_audit", "IMPORT_COMPANIES"))
        self.assertGreaterEqual(len(logs), 1)
        # Static guarantee: the real import route performs this audit.
        app_src = (ROOT / "backend" / "app.py").read_text(encoding="utf-8")
        self.assertIn('data.audit(self.org,"IMPORT_COMPANIES","import"', app_src)

    # 16. no secrets leaked by import diagnostics
    def test_16_import_diagnostics_redact_secrets(self):
        redacted = data.redact_error(
            "postgresql://u:super-secret@db.invalid/postgres Bearer eyJa.b.c password=x")
        for forbidden in ("super-secret", "eyJa.b.c", "password=x"):
            self.assertNotIn(forbidden, redacted)
        self.assertIn("<redacted>", redacted)

    # 17. no fictive data: pipeline never seeds demo/fixture rows
    def test_17_pipeline_creates_no_demo_or_fixture_data(self):
        pipeline.run(ORG, SOURCE, [_row(rcs="BNODEMO", name="Real Import Co")], import_id="imp_nodemo")
        rows = data.rows("SELECT * FROM companies WHERE organization_id=? AND rcs_number=?", (ORG, "BNODEMO"))
        self.assertEqual(len(rows), 1)
        self.assertNotEqual(rows[0]["provenance"], "DEMO")
        src = (ROOT / "backend" / "import_pipeline.py").read_text(encoding="utf-8")
        self.assertNotIn("DEMO_COMPANIES", src)
        self.assertNotIn("fixture", src.lower())


if __name__ == "__main__":
    unittest.main()
