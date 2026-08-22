"""LLM provider + PDF block extraction tests.

The LLM validation logic (hallucination rejection, schema, signataire≠gérant,
AI_NOT_CONFIGURED) is VERIFIED. The actual LLM call is NOT executed (no API keys
in this environment). Block/coordinate extraction is VERIFIED with a real PDF.
"""
import json, os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import llm_provider as llm
from llm_provider import validate_extraction, classify_role_type, _extract_json, status, get_provider, PROMPT_VERSION
import pdf_extraction as pe


class LLMStatusTests(unittest.TestCase):
    def test_no_keys_means_not_configured(self):
        os.environ.pop("LLM_PROVIDER", None)
        os.environ.pop("OPENAI_API_KEY", None)
        self.assertIsNone(get_provider())
        self.assertEqual(status()["status"], "AI_NOT_CONFIGURED")


class SchemaValidationTests(unittest.TestCase):
    EXCERPT = "Par la présente, Jean Dupont est nommé gérant de la société Alpha Tech Sàrl."

    def test_valid_extraction_passes(self):
        out = {"person_name": "Jean Dupont", "role": "gérant", "role_confirmed": True,
               "evidence_quote": "Jean Dupont est nommé gérant", "confidence": 0.95, "needs_human_review": False}
        r = validate_extraction(out, self.EXCERPT)
        self.assertEqual(r["person_name"], "Jean Dupont")
        self.assertEqual(r["role_type"], "MANAGER")
        self.assertTrue(r["role_confirmed"])

    def test_hallucination_rejected(self):
        out = {"person_name": "Marie Curie", "role": "gérant", "role_confirmed": True,
               "evidence_quote": "Marie Curie est nommée gérante", "confidence": 0.9, "needs_human_review": False}
        with self.assertRaises(llm.LLMError) as ctx:
            validate_extraction(out, self.EXCERPT)
        self.assertIn("HALLUCINATION", str(ctx.exception))

    def test_role_confirmed_without_evidence_rejected(self):
        out = {"person_name": "Jean Dupont", "role": "gérant", "role_confirmed": True,
               "evidence_quote": None, "confidence": 0.9, "needs_human_review": False}
        with self.assertRaises(llm.LLMError):
            validate_extraction(out, self.EXCERPT)

    def test_missing_fields_become_null(self):
        out = {"person_name": None, "role": None, "role_confirmed": False,
               "evidence_quote": None, "confidence": 0.0, "needs_human_review": True}
        r = validate_extraction(out, self.EXCERPT)
        self.assertIsNone(r["person_name"])
        self.assertEqual(r["role_type"], "UNKNOWN")

    def test_confidence_normalized(self):
        out = {"person_name": "X", "role": None, "role_confirmed": False, "evidence_quote": None,
               "confidence": "high", "needs_human_review": True}
        r = validate_extraction(out, "")
        self.assertEqual(r["confidence"], 0.0)


class SignataireTests(unittest.TestCase):
    def test_signataire_is_not_manager(self):
        self.assertEqual(classify_role_type("signataire"), "NON_MANAGER")
        self.assertEqual(classify_role_type("mandataire"), "NON_MANAGER")

    def test_gerant_is_manager(self):
        self.assertEqual(classify_role_type("gérant"), "MANAGER")
        self.assertEqual(classify_role_type("administratrice"), "MANAGER")

    def test_signataire_extraction_forces_human_review(self):
        exc = "Signataire: Jean Dupont"
        out = {"person_name": "Jean Dupont", "role": "signataire", "role_confirmed": False,
               "evidence_quote": "Signataire: Jean Dupont", "confidence": 0.5, "needs_human_review": False}
        r = validate_extraction(out, exc)
        self.assertEqual(r["role_type"], "NON_MANAGER")
        self.assertTrue(r["needs_human_review"])  # signataire always needs review

    def test_unknown_role_is_unknown(self):
        self.assertEqual(classify_role_type(None), "UNKNOWN")
        self.assertEqual(classify_role_type("random title"), "UNKNOWN")


class JsonParsingTests(unittest.TestCase):
    def test_code_fenced_json(self):
        raw = '```json\n{"person_name": "X", "role": "gérant", "role_confirmed": true, "evidence_quote": "X", "confidence": 0.9, "needs_human_review": false}\n```'
        d = _extract_json(raw)
        self.assertEqual(d["person_name"], "X")

    def test_plain_json(self):
        d = _extract_json('{"person_name": "Y"}')
        self.assertEqual(d["person_name"], "Y")

    def test_invalid_json_raises(self):
        with self.assertRaises(llm.LLMError):
            _extract_json("not json at all")


class HashAndAuditTests(unittest.TestCase):
    def test_input_output_hashes_deterministic(self):
        excerpt = "Jean Dupont est nommé gérant."
        out = {"person_name": "Jean Dupont", "role": "gérant", "role_confirmed": True,
               "evidence_quote": "Jean Dupont est nommé gérant", "confidence": 0.95, "needs_human_review": False}
        import hashlib
        expected_input_hash = hashlib.sha256(excerpt.encode()).hexdigest()
        self.assertEqual(len(expected_input_hash), 64)
        validated = validate_extraction(out, excerpt)
        expected_output_hash = hashlib.sha256(json.dumps(validated, sort_keys=True, default=str).encode()).hexdigest()
        self.assertEqual(len(expected_output_hash), 64)
        # Same inputs -> same hashes (idempotence)
        self.assertEqual(validate_extraction(out, excerpt), validated)


class BlockExtractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        self.tmp.close()
        reportlab = __import__("reportlab.pdfgen", fromlist=["canvas"])
        c = reportlab.canvas.Canvas(self.tmp.name, pagesize=__import__("reportlab.lib.pagesizes", fromlist=["A4"]).A4)
        c.drawString(72, 800, "Dénomination: Test Co Sàrl")
        c.drawString(72, 780, "Gérant: Jean Dupont")
        c.showPage()
        c.save()

    def tearDown(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_blocks_have_coordinates(self):
        pages = pe.native_blocks_pymupdf(self.tmp.name, max_pages=10)
        self.assertEqual(len(pages), 1)
        blocks = pages[0]["blocks"]
        self.assertGreater(len(blocks), 0)
        b = blocks[0]
        for coord in ("x0", "y0", "x1", "y1"):
            self.assertIsInstance(b[coord], float)
        self.assertTrue(b["text"])

    def test_poppler_not_configured(self):
        self.assertFalse(pe.has_poppler())


class NoSecretsTests(unittest.TestCase):
    def test_status_has_no_keys(self):
        s = status()
        for forbidden in ("sk-", "api_key", "password", "secret", "Bearer"):
            self.assertNotIn(forbidden, json.dumps(s))


if __name__ == "__main__":
    unittest.main()
