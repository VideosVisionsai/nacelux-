"""Step 4 (ÉTAPE 4.19) — NACE Rev. 2.1 official importer tests.

Parser, validation, hierarchy, security (SSRF/XXE/redirect/size), transactional
activation, checksum deduplication and the API are verified with clearly-labeled
synthetic fixtures and a controlled (monkeypatched) download. Fixtures are TEST
ONLY and can never become production nomenclature: validate_parsed() rejects any
dataset whose counts differ from the official 22/87/287/651.

The REAL official download (and the observed 22/87/287/651 counts) is verified
only by TestRealOfficialDownload, which is skipped unless the official ShowVoc
source is reachable AND NACE_RUN_REAL_DOWNLOAD=1. From this sandbox the source is
unreachable, so the real import stays REQUIRES CONFIGURATION (not simulated).
"""
import io, json, os, sys, tempfile, unittest, zipfile
from http.server import HTTPServer
from pathlib import Path
from urllib.request import urlopen, Request
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import nace_importer as ni
from nace_importer import (parse_rdf, validate_parsed, hierarchy_anomalies,
                           validate_source, code_level, EXPECTED, OfficialNaceImporter)

SAMPLE_RDF = b"""<?xml version="1.0" encoding="utf-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:skos="http://www.w3.org/2004/02/skos/core#">
  <rdf:Description rdf:about="http://data.europa.eu/ux2/nace2.1/J">
    <skos:notation>J</skos:notation>
    <skos:prefLabel xml:lang="fr">Information et communication</skos:prefLabel>
    <skos:prefLabel xml:lang="de">Information und Kommunikation</skos:prefLabel>
    <skos:prefLabel xml:lang="en">Information and communication</skos:prefLabel>
  </rdf:Description>
  <rdf:Description rdf:about="http://data.europa.eu/ux2/nace2.1/62">
    <skos:notation>62</skos:notation>
    <skos:broader rdf:resource="http://data.europa.eu/ux2/nace2.1/J"/>
    <skos:prefLabel xml:lang="fr">Programmation, conseil et autres activites informatiques</skos:prefLabel>
    <skos:prefLabel xml:lang="de">Erbringung von Dienstleistungen der Informationstechnologie</skos:prefLabel>
    <skos:prefLabel xml:lang="en">Computer programming, consultancy and related activities</skos:prefLabel>
  </rdf:Description>
  <rdf:Description rdf:about="http://data.europa.eu/ux2/nace2.1/62.1">
    <skos:notation>62.1</skos:notation>
    <skos:broader rdf:resource="http://data.europa.eu/ux2/nace2.1/62"/>
    <skos:prefLabel xml:lang="fr">Programmation informatique</skos:prefLabel>
    <skos:prefLabel xml:lang="de">Programmierungstaetigkeiten</skos:prefLabel>
    <skos:prefLabel xml:lang="en">Computer programming activities</skos:prefLabel>
  </rdf:Description>
  <rdf:Description rdf:about="http://data.europa.eu/ux2/nace2.1/62.10">
    <skos:notation>62.10</skos:notation>
    <skos:broader rdf:resource="http://data.europa.eu/ux2/nace2.1/62.1"/>
    <skos:prefLabel xml:lang="fr">Programmation informatique</skos:prefLabel>
    <skos:prefLabel xml:lang="de">Programmierungstaetigkeiten</skos:prefLabel>
    <skos:prefLabel xml:lang="en">Computer programming activities</skos:prefLabel>
    <skos:scopeNote xml:lang="fr">Comprend l'ecriture, la modification, le test et le support de logiciels.</skos:scopeNote>
  </rdf:Description>
  <rdf:Description rdf:about="http://data.europa.eu/ux2/nace2.1/NACE2.1_NACE2_62.10_62.01">
    <sourceConcept rdf:resource="http://data.europa.eu/ux2/nace2.1/62.10"/>
    <targetConcept rdf:resource="http://data.europa.eu/ux2/nace2/6201"/>
    <mapping_cardinality rdf:resource="http://data.europa.eu/ux2/nace2.1/1_1"/>
  </rdf:Description>
</rdf:RDF>"""

SOURCE_META = {"source_url": ni.DEFAULT_SOURCE, "checksum": "deadbeef" * 8, "retrieved_at": "2026-01-01T00:00:00Z",
               "artifact": "data/nace-imports/test.zip", "content_type": "application/zip",
               "size_bytes": 123, "http_status": 200, "filename": "NACE_Rev_2.1.zip"}


def _parsed():
    return parse_rdf(io.BytesIO(SAMPLE_RDF), ("fr", "de", "en"))


class NaceParserTests(unittest.TestCase):
    def test_parser_extracts_hierarchy_labels_notes_correspondences(self):
        p = _parsed()
        levels = {x["code"]: x["level"] for x in p["items"]}
        self.assertEqual(levels, {"J": "SECTION", "62": "DIVISION", "62.1": "GROUP", "62.10": "CLASS"})
        self.assertEqual(len(p["labels"]), 12)            # 4 items x 3 languages
        self.assertTrue(all(l["language"] in ("fr", "de", "en") for l in p["labels"]))
        self.assertEqual(len(p["notes"]), 1)
        self.assertEqual(len(p["correspondences"]), 1)
        self.assertEqual(p["correspondences"][0]["source_code"], "62.01")
        self.assertEqual(p["correspondences"][0]["target_code"], "62.10")

    def test_code_levels(self):
        self.assertEqual(code_level("A"), "SECTION")
        self.assertEqual(code_level("62"), "DIVISION")
        self.assertEqual(code_level("62.1"), "GROUP")
        self.assertEqual(code_level("62.10"), "CLASS")
        self.assertIsNone(code_level("nonsense"))


class ValidationTests(unittest.TestCase):
    def test_small_fixture_fails_validation(self):
        # A fixture with 4 items can never satisfy the official 22/87/287/651.
        with self.assertRaises(RuntimeError):
            validate_parsed(_parsed())

    def test_expected_counts_pass_validation(self):
        # Unit test of the validator logic only — NOT official data.
        codes_per_level = {lvl: [f"{lvl}{i}" for i in range(n)] for lvl, n in EXPECTED.items()}
        items = [{"code": c, "level": lvl, "parent_code": "p"} for lvl, codes in codes_per_level.items() for c in codes]
        all_codes = [c for codes in codes_per_level.values() for c in codes]
        labels = [{"code": c, "language": lang, "label_type": "PREF", "label": f"l-{c}-{lang}"}
                  for lang in ("fr", "de", "en") for c in all_codes]
        parsed = {"items": items, "labels": labels,
                  "notes": [{"code": "c0", "type": "SCOPE", "language": "en", "text": "n"}],
                  "correspondences": [{"source_code": "1", "target_code": "2"} for _ in range(1001)]}
        counts = validate_parsed(parsed)
        self.assertEqual(counts, dict(EXPECTED))

    def test_hierarchy_anomalies_detected(self):
        bad = {"items": [{"code": "A", "level": "SECTION", "parent_code": None},
                         {"code": "62", "level": "DIVISION", "parent_code": "ZZZ"},   # unknown parent
                         {"code": "62", "level": "DIVISION", "parent_code": "A"}]}     # duplicate code
        anomalies = hierarchy_anomalies(bad)
        self.assertTrue(any("Unknown parent" in a for a in anomalies))
        self.assertTrue(any("Duplicate" in a for a in anomalies))
        # the well-formed sample has no anomalies
        self.assertEqual(hierarchy_anomalies(_parsed()), [])


class SecurityTests(unittest.TestCase):
    def test_source_url_is_pinned_to_official_host(self):
        validate_source(ni.DEFAULT_SOURCE)
        for bad in ("http://showvoc.op.europa.eu/semanticturkey/downloads/x/NACE_Rev_2.1.zip",
                    "https://evil.example.com/NACE_Rev_2.1.zip",
                    "https://showvoc.op.europa.evil/NACE_Rev_2.1.zip"):
            with self.assertRaises(ValueError):
                validate_source(bad)

    def test_xxe_external_entity_is_not_resolved(self):
        xxe = (b'<?xml version="1.0"?>\n<!DOCTYPE r [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>\n'
               b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
               b'xmlns:skos="http://www.w3.org/2004/02/skos/core#">'
               b'<rdf:Description rdf:about="http://data.europa.eu/ux2/nace2.1/A">'
               b'<skos:notation>A</skos:notation><skos:prefLabel xml:lang="en">&xxe;</skos:prefLabel>'
               b'</rdf:Description></rdf:RDF>')
        leaked = False
        try:
            out = parse_rdf(io.BytesIO(xxe), ("en",))
            leaked = any("root:" in (l.get("label") or "") for l in out["labels"])
        except Exception:
            leaked = False  # defusedxml forbids the DOCTYPE outright -> safe
        self.assertFalse(leaked, "XXE external entity was resolved")

    def test_redirect_leaving_official_host_is_rejected(self):
        handler = ni._SafeRedirect()
        req = type("R", (), {"full_url": ni.DEFAULT_SOURCE})()
        with self.assertRaises(ValueError):
            handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example.com/x.zip")
        # redirect that stays on the official host is allowed through to the base handler
        try:
            handler.redirect_request(req, None, 302, "Found", {},
                                     "https://showvoc.op.europa.eu/semanticturkey/downloads/y/NACE_Rev_2.1.zip")
        except Exception as exc:
            self.assertNotIsInstance(exc, ValueError)

    def test_download_rejects_oversize_and_non_zip(self):
        importer = OfficialNaceImporter(lambda: (_ for _ in ()).throw(RuntimeError("no db")))  # db not used here

        class FakeResp:
            def __init__(self, data):
                self.data, self.headers, self.status = data, {"Content-Type": "application/zip"}, 200
            def read(self, n=-1):
                return self.data if n == -1 else self.data[:n]
            def __enter__(self): return self
            def __exit__(self, *a): return False

        class FakeOpener:
            def __init__(self, data): self.data = data
            def open(self, req, timeout=None): return FakeResp(self.data)

        orig = ni.urllib.request.build_opener
        importer.max_bytes = 100
        try:
            ni.urllib.request.build_opener = lambda *a, **k: FakeOpener(b"PK\x03\x04" + b"x" * 200)
            with self.assertRaises(RuntimeError):
                importer._download()
            ni.urllib.request.build_opener = lambda *a, **k: FakeOpener(b"NOTAZIP" * 5)
            with self.assertRaises(RuntimeError):
                importer._download()
            good = b"PK\x03\x04" + b"validzip"
            ni.urllib.request.build_opener = lambda *a, **k: FakeOpener(good)
            importer.max_bytes = 10_000_000
            meta = importer._download()
            import hashlib
            self.assertEqual(meta["checksum"], hashlib.sha256(good).hexdigest())
            self.assertEqual(meta["http_status"], 200)
        finally:
            ni.urllib.request.build_opener = orig


class PersistAndImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.tmp.close()
        os.environ["NACELUX_DB"] = cls.tmp.name
        import database as data
        data.init_db()
        cls.data = data
        cls.importer = OfficialNaceImporter(data.connect)

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("NACELUX_DB", None)
        Path(cls.tmp.name).unlink(missing_ok=True)

    def test_persist_parsed_activates_version_atomically(self):
        self.importer.persist_parsed(_parsed(), SOURCE_META)
        v = self.data.one("SELECT status,item_count,source_checksum FROM nace_versions_official WHERE version_code='2.1'")
        self.assertEqual(v["status"], "ACTIVE")
        self.assertEqual(v["item_count"], 4)
        self.assertEqual(v["source_checksum"], SOURCE_META["checksum"])
        self.assertEqual(self.data.one("SELECT count(*) c FROM nace_items_official WHERE version_id=(SELECT id FROM nace_versions_official WHERE version_code='2.1')")["c"], 4)
        self.assertGreaterEqual(self.data.one("SELECT count(*) c FROM nace_labels_official")["c"], 12)
        self.assertGreaterEqual(self.data.one("SELECT count(*) c FROM nace_notes_official")["c"], 1)
        self.assertGreaterEqual(self.data.one("SELECT count(*) c FROM nace_correspondences_official")["c"], 1)

    def test_persist_is_idempotent_no_duplicate_version(self):
        self.importer.persist_parsed(_parsed(), SOURCE_META)
        n = self.data.one("SELECT count(*) c FROM nace_versions_official WHERE version_code='2.1'")["c"]
        self.assertEqual(n, 1)

    def test_import_official_fails_closed_on_incomplete_data(self):
        # Controlled download returns the small fixture zip -> validate_parsed
        # rejects it -> FAILED, and NO ACTIVE partial nomenclature is left.
        import io as _io
        buf = _io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("NACE_Rev_2.1.rdf", SAMPLE_RDF)
        zip_data = buf.getvalue()

        class FakeResp:
            def __init__(self, d): self.d = d; self.headers = {"Content-Type": "application/zip"}; self.status = 200
            def read(self, n=-1): return self.d
            def __enter__(self): return self
            def __exit__(self, *a): return False
        class FakeOpener:
            def open(self, req, timeout=None): return FakeResp(zip_data)

        orig = ni.urllib.request.build_opener
        ni.urllib.request.build_opener = lambda *a, **k: FakeOpener()
        try:
            result = self.importer.import_official()
        finally:
            ni.urllib.request.build_opener = orig
        self.assertEqual(result["status"], "FAILED")
        run = self.data.one("SELECT status FROM nace_import_runs WHERE id=?", (result["run_id"],))
        self.assertEqual(run["status"], "FAILED")

    def test_dedup_skips_identical_checksum(self):
        # Active version already has SOURCE_META checksum; a download returning
        # the same checksum must be UNCHANGED (no re-import).
        self.importer.persist_parsed(_parsed(), SOURCE_META)  # ensure ACTIVE with this checksum
        orig_download = OfficialNaceImporter._download

        def fake_download(self):
            return dict(SOURCE_META, data=b"PK\x03\x04")
        OfficialNaceImporter._download = fake_download
        try:
            result = self.importer.import_official()
        finally:
            OfficialNaceImporter._download = orig_download
        self.assertEqual(result["status"], "UNCHANGED")


class NaceApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.tmp.close()
        os.environ["NACELUX_DB"] = cls.tmp.name
        import database as data
        data.init_db()
        OfficialNaceImporter(data.connect).persist_parsed(_parsed(), SOURCE_META)
        import app
        cls.server = HTTPServer(("127.0.0.1", 0), app.API)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close()
        os.environ.pop("NACELUX_DB", None)
        Path(cls.tmp.name).unlink(missing_ok=True)

    def _get(self, qs=""):
        with urlopen(Request(f"http://127.0.0.1:{self.port}/api/v1/nace?{qs}"), timeout=5) as r:
            return json.loads(r.read().decode())

    def test_lists_items_with_pagination(self):
        d = self._get("limit=2&offset=0&language=en")
        self.assertIn("pagination", d)
        self.assertEqual(d["pagination"]["limit"], 2)
        self.assertLessEqual(len(d["items"]), 2)

    def test_search_by_code_and_label(self):
        by_code = self._get("code=62&language=en")
        self.assertTrue(all(i["code"].startswith("62") for i in by_code["items"]))
        by_label = self._get("q=programming&language=en")
        self.assertTrue(all("programming" in (i["label"] or "").lower() for i in by_label["items"]))

    def test_level_filter(self):
        d = self._get("level=SECTION&language=en")
        self.assertTrue(all(i["level"] == "SECTION" for i in d["items"]))


@unittest.skipUnless(os.getenv("NACE_RUN_REAL_DOWNLOAD") == "1",
                     "Real official download requires NACE_RUN_REAL_DOWNLOAD=1 and a reachable ShowVoc source")
class TestRealOfficialDownload(unittest.TestCase):
    def test_real_official_import(self):
        import database as data
        importer = OfficialNaceImporter(data.connect)
        result = importer.import_official()
        self.assertEqual(result["status"], "SUCCESS", result)
        self.assertEqual(result["sections"], 22)
        self.assertEqual(result["divisions"], 87)
        self.assertEqual(result["groups"], 287)
        self.assertEqual(result["classes"], 651)


NACE_PG_URL = os.getenv("NACELUX_TEST_DATABASE_URL", "")


@unittest.skipUnless(NACE_PG_URL, "NACELUX_TEST_DATABASE_URL (non-owner runtime role) is required")
class NaceReferenceRLSTests(unittest.TestCase):
    """NACE official data is GLOBAL reference data: not tenant-scoped (no
    organization_id), readable by every tenant, and writable only by the trusted
    importer roles. Verified on a real PostgreSQL engine."""

    @classmethod
    def setUpClass(cls):
        import psycopg, uuid
        cls.psycopg = psycopg
        cls.conn = psycopg.connect(NACE_PG_URL, row_factory=psycopg.rows.dict_row)
        role = cls.conn.execute(
            "SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname=current_user").fetchone()
        if role["rolbypassrls"] or role["rolsuper"]:
            raise AssertionError("test role must not bypass RLS or be superuser")

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def setUp(self):
        self.addCleanup(self.conn.rollback)
        import uuid
        self.user = "s4nr_" + uuid.uuid4().hex[:10]
        self.org_a = "s4nra_" + uuid.uuid4().hex[:10]
        self.org_b = "s4nrb_" + uuid.uuid4().hex[:10]

    def _ctx(self, org, user):
        self.conn.execute("SELECT set_config('app.organization_id', %s, false)", (org or "",))
        self.conn.execute("SELECT set_config('app.user_id', %s, false)", (user or "",))

    def test_nace_tables_are_not_tenant_scoped(self):
        for t in ("nace_versions_official", "nace_items_official", "nace_labels_official"):
            cols = [r["column_name"] for r in self.conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s", (t,)).fetchall()]
            self.assertNotIn("organization_id", cols)

    def test_importer_role_can_write_and_all_tenants_read(self):
        self._ctx(None, self.user)
        self.conn.execute(
            "INSERT INTO users(id,email,display_name,created_at,auth_user_id,updated_at) "
            "VALUES(%s,%s,%s,CURRENT_TIMESTAMP,%s,CURRENT_TIMESTAMP)",
            (self.user, self.user + "@t.invalid", "NACE", self.user))
        self.conn.execute(
            "INSERT INTO nace_versions_official(id,version_code,title,status,source_url,source_format,retrieved_at) "
            "VALUES('s4nrv','2.1','NACE','ACTIVE','u','RDF',CURRENT_TIMESTAMP) ON CONFLICT (version_code) DO NOTHING")
        self.conn.execute(
            "INSERT INTO nace_items_official(id,version_id,code,level,concept_uri,is_current,source_url,retrieved_at) "
            "VALUES('s4nri','s4nrv','ZZ','SECTION','uri',TRUE,'u',CURRENT_TIMESTAMP)")
        self.conn.execute("COMMIT")
        for o in (self.org_a, self.org_b):
            self._ctx(o, self.user)
            cnt = self.conn.execute("SELECT count(*) AS c FROM nace_items_official").fetchone()["c"]
            self.assertGreaterEqual(cnt, 1)


if __name__ == "__main__":
    unittest.main()
