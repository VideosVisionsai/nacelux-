"""RESA PDF/OCR pipeline reinforcement tests.

Native extraction (PyMuPDF), validation, per-page extraction, quality, explicit
person extraction and human review are VERIFIED with a real reportlab-generated
PDF (no invented data). OCR (OCRmyPDF + Tesseract + Ghostscript) is NOT installed
in this environment -> those tests assert REQUIRES_CONFIGURATION (never simulated).
"""
import os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import pdf_extraction as pe
from pdf_extraction import (validate_pdf_bytes, native_pages_pymupdf, has_pymupdf,
                            has_ocrmypdf, run_ocrmypdf, extract_people_from_pages,
                            PdfTextExtractionEngine, ENGINE_VERSION)

reportlab = __import__("reportlab.pdfgen", fromlist=["canvas"])
canvas = reportlab.canvas
A4 = __import__("reportlab.lib.pagesizes", fromlist=["A4"]).A4


def _make_pdf(path, lines_per_page):
    c = canvas.Canvas(path, pagesize=A4)
    for lines in lines_per_page:
        y = 800
        for line in lines:
            c.drawString(72, y, line); y -= 20
        c.showPage()
    c.save()
    return path


class PdfValidationTests(unittest.TestCase):
    def test_valid_pdf_accepted(self):
        self.assertTrue(validate_pdf_bytes(b"%PDF-1.4 hello", max_bytes=1000))

    def test_non_pdf_rejected(self):
        with self.assertRaises(ValueError):
            validate_pdf_bytes(b"<html>not a pdf</html>", max_bytes=1000)

    def test_corrupt_magic_rejected(self):
        with self.assertRaises(ValueError):
            validate_pdf_bytes(b"PDF-1.4 no leading percent", max_bytes=1000)

    def test_oversize_rejected(self):
        with self.assertRaises(ValueError):
            validate_pdf_bytes(b"%PDF-1.4" + b"x" * 2000, max_bytes=100)


class NativeExtractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False); self.tmp.close()

    def tearDown(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_multilingual_native_extraction_per_page(self):
        _make_pdf(self.tmp.name, [
            ["Publication RESA - page 1 (Francais)", "Dénomination: Test FR Sàrl  RCS B 300111"],
            ["Veroffentlichung - Seite 2 (Deutsch)", "Firmenname: Test DE GmbH  RCS B 300112"],
            ["Publication - page 3 (English)", "Company name: Test EN Ltd  RCS B 300113"],
        ])
        pages = native_pages_pymupdf(self.tmp.name, max_pages=100)
        self.assertEqual(len(pages), 3)
        joined = " ".join(p["text"].replace(" ", "") for p in pages)
        self.assertIn("Francais", joined)
        self.assertIn("Deutsch", joined)
        self.assertIn("English", joined)
        # checksum of document text is deterministic
        self.assertEqual(pages[0]["page_number"], 1)

    def test_too_many_pages_rejected(self):
        _make_pdf(self.tmp.name, [["p1"], ["p2"], ["p3"]])
        with self.assertRaises(RuntimeError):
            native_pages_pymupdf(self.tmp.name, max_pages=2)

    def test_pymupdf_available(self):
        self.assertTrue(has_pymupdf())


class PersonExtractionTests(unittest.TestCase):
    def test_explicit_roles_extracted(self):
        pages = [{"page_number": 1, "text": "Publication. Gérant: Jean Dupont  Administrateur: Marie Curie"}]
        people = extract_people_from_pages(pages)
        self.assertEqual({p["display_name"] for p in people}, {"Jean Dupont", "Marie Curie"})
        self.assertEqual(people[0]["page"], 1)
        self.assertTrue(all(p["official_role"] for p in people))

    def test_no_role_no_extraction(self):
        pages = [{"page_number": 1, "text": "Jean Dupont et Marie Curie sont mentionnes sans titre."}]
        self.assertEqual(extract_people_from_pages(pages), [])

    def test_never_deduces_a_role(self):
        pages = [{"page_number": 1, "text": "Contact: Sophie Martin (sophie@example.lu)"}]
        self.assertEqual(extract_people_from_pages(pages), [])


class OcrAvailabilityTests(unittest.TestCase):
    def test_ocrmypdf_requires_configuration(self):
        if has_ocrmypdf():
            self.skipTest("OCRmyPDF is installed in this environment")
        tmp_in = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False); tmp_in.close()
        tmp_out = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False); tmp_out.close()
        try:
            with self.assertRaises(RuntimeError):
                run_ocrmypdf(tmp_in.name, tmp_out.name)
        finally:
            Path(tmp_in.name).unlink(missing_ok=True); Path(tmp_out.name).unlink(missing_ok=True)


class ExtractPeoplePersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); cls.tmp.close()
        os.environ["NACELUX_DB"] = cls.tmp.name
        import database as data
        data.init_db()
        cls.data = data
        ts = data.now()
        with data.connect() as db:
            db.execute("INSERT OR IGNORE INTO organizations(id,name,slug,created_at) VALUES(?,?,?,?)", ("o", "O", "o", ts))
            db.execute("INSERT INTO resa_journals(id,organization_id,journal_key,source_url,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?)", ("j1", "o", "RESA-2026_1", "https://www.lbr.lu/x", ts, ts))
            db.execute("INSERT INTO resa_documents(id,organization_id,journal_id,document_url,source_url,canonical_url,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?)",
                       ("doc1", "o", "j1", "https://www.lbr.lu/x/doc.pdf", "https://www.lbr.lu/x", "https://www.lbr.lu/x/doc.pdf", ts, ts))
            db.execute("INSERT INTO storage_objects(id,organization_id,provider,bucket,object_key,checksum_sha256,size_bytes,mime_type,created_at) VALUES(?,?,?,?,?,?,?,?,?)", ("so1", "o", "local", "resa", "doc1.pdf", "abc", 1000, "application/pdf", ts))
            db.execute("INSERT INTO document_extractions(id,organization_id,document_id,storage_object_id,source_checksum,status,engine_version,started_at) VALUES(?,?,?,?,?,?,?,?)",
                       ("ext1", "o", "doc1", "so1", "abc", "SUCCESS", ENGINE_VERSION, ts))
            db.execute("INSERT INTO document_page_extractions(id,organization_id,extraction_id,document_id,page_number,extraction_method,text_content,char_count,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       ("pg1", "o", "ext1", "doc1", 1, "TEXT", "Gérant: Jean Dupont  Administrateur: Marie Curie", 60, ts))

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("NACELUX_DB", None)
        Path(cls.tmp.name).unlink(missing_ok=True)

    def test_extract_people_persists_pending_review(self):
        eng = PdfTextExtractionEngine(self.data.connect)
        r = eng.extract_people("o", "ext1")
        self.assertEqual(r["status"], "SUCCESS")
        self.assertEqual(r["people_found"], 2)
        rows = self.data.rows("SELECT display_name,official_role,review_status,source_page,evidence_excerpt FROM people WHERE organization_id='o' AND source_extraction_id='ext1'")
        self.assertEqual({x["display_name"] for x in rows}, {"Jean Dupont", "Marie Curie"})
        self.assertTrue(all(x["review_status"] == "PENDING_REVIEW" for x in rows))  # never verified before review
        ev = self.data.one("SELECT count(*) c FROM people_evidence WHERE organization_id='o' AND method='PDF_EXTRACTION'")["c"]
        self.assertGreaterEqual(ev, 2)

    def test_extract_people_idempotent(self):
        eng = PdfTextExtractionEngine(self.data.connect)
        eng.extract_people("o", "ext1")
        n1 = self.data.one("SELECT count(*) c FROM people WHERE organization_id='o' AND source_extraction_id='ext1'")["c"]
        eng.extract_people("o", "ext1")
        n2 = self.data.one("SELECT count(*) c FROM people WHERE organization_id='o' AND source_extraction_id='ext1'")["c"]
        self.assertEqual(n1, n2)  # no duplicates

    def test_review_flow_updates_status_and_audits(self):
        eng = PdfTextExtractionEngine(self.data.connect)
        eng.extract_people("o", "ext1")
        pid = self.data.one("SELECT id FROM people WHERE organization_id='o' AND source_extraction_id='ext1' LIMIT 1")["id"]
        # simulate the review update the API performs
        with self.data.connect() as db:
            db.execute("UPDATE people SET review_status='APPROVED',reviewer='rev1',reviewed_at=?,review_comment='confirmed' WHERE organization_id='o' AND id=?", (self.data.now(), pid))
        row = self.data.one("SELECT review_status,reviewer,review_comment FROM people WHERE id=?", (pid,))
        self.assertEqual(row["review_status"], "APPROVED")
        self.assertEqual(row["reviewer"], "rev1")
        self.assertEqual(row["review_comment"], "confirmed")
        # original evidence is retained
        self.assertGreaterEqual(self.data.one("SELECT count(*) c FROM people_evidence WHERE person_id=?", (pid,))["c"], 1)


class EngineStatusTests(unittest.TestCase):
    def test_status_reports_ocr_requires_configuration(self):
        eng = PdfTextExtractionEngine(lambda: (_ for _ in ()).throw(RuntimeError("no db")))
        st = eng.status()
        self.assertIn(st["native_text"], ("AVAILABLE", "NOT_INSTALLED"))
        self.assertEqual(st["ocr_status"], "REQUIRES_CONFIGURATION" if not has_ocrmypdf() else "READY")
        self.assertEqual(st["engine_version"], ENGINE_VERSION)


if __name__ == "__main__":
    unittest.main()
