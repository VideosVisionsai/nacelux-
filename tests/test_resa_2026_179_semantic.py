"""ATTACHMENT_DERIVED_SEMANTIC_FIXTURE tests — RESA_2026_179.931.

Validates legal-entity rejection logic and scoring safety rules against the
manually-reviewed semantic fixture. This is NOT an actual PDF processing test.
The original PDF was NOT opened inside the Arena sandbox.

Tests verify:
1-4.  Legal entities stored as LEGAL_ENTITY, never as natural persons.
5-6.  No DECISION_MAKER_FOUND; decision-maker points = 0.
7-10. UNKNOWN/NOT_CHECKED signals contribute 0 points.
11-12. "solidairement responsable" and "gérant" never parsed as person names.
13-14. No external enrichment; no fictional data.
15-16. Fixture metadata honest; never reported as real PDF integration.
17-20. Existing Step 7 tests, tenant isolation, fingerprint, append-only history.
"""
import json, os, sys, tempfile, unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))

import resa_pipeline as rp
from scoring import calculate, MODEL_VERSION
from resa_2026_179_semantic import (
    FIXTURE_METADATA, COMPANY, RELATED_ENTITIES, NATURAL_PERSONS, EXPECTED_SIGNALS,
)


class FixtureMetadataTests(unittest.TestCase):
    """Tests 15-16: fixture metadata honesty."""

    def test_fixture_is_not_actual_pdf(self):
        self.assertFalse(FIXTURE_METADATA["original_pdf_processed"])
        self.assertFalse(FIXTURE_METADATA["live_resa_data"])
        self.assertFalse(FIXTURE_METADATA["arena_filesystem_access"])
        self.assertEqual(FIXTURE_METADATA["fixture_type"], "ATTACHMENT_DERIVED_SEMANTIC_FIXTURE")
        self.assertEqual(FIXTURE_METADATA["source_confidence"], "MANUALLY_REVIEWED_ATTACHMENT_CONTENT")


class LegalEntityRejectionTests(unittest.TestCase):
    """Tests 1-4: legal entities must never become natural persons."""

    # Simulated page text derived from the manually reviewed attachment content.
    PAGE_GP = (
        "Associé solidairement responsable: Roundtable Lux GP (RCS B266208), "
        "société en commandite par actions, ayant son siège à Luxembourg."
    )
    PAGE_MANAGER = (
        "Il est nommé gérant: Roundtable Lux Ops (RCS B266215), "
        "société à responsabilité limitée, ayant son siège social à Luxembourg. "
        "Le gérant n'est pas associé."
    )

    def test_roundtable_lux_gp_not_extracted_as_person(self):
        people = rp.extract_people_facts(self.PAGE_GP)
        names = {p["display_name"] for p in people}
        self.assertNotIn("Roundtable Lux GP", names)

    def test_roundtable_lux_ops_not_extracted_as_person(self):
        people = rp.extract_people_facts(self.PAGE_MANAGER)
        names = {p["display_name"] for p in people}
        self.assertNotIn("Roundtable Lux Ops", names)

    def test_people_result_is_empty(self):
        people = rp.extract_people_facts(self.PAGE_GP + "\n" + self.PAGE_MANAGER)
        self.assertEqual(people, [])

    def test_legal_entities_classified_correctly(self):
        for entity in RELATED_ENTITIES:
            self.assertFalse(entity["natural_person"])
            self.assertEqual(entity["entity_type"], "LEGAL_ENTITY")


class SafetyPhraseTests(unittest.TestCase):
    """Tests 11-12: legal phrases never parsed as person names."""

    def test_solidairement_responsable_not_a_person(self):
        self.assertFalse(rp._is_natural_person("solidairement responsable",
                                                "associé solidairement responsable"))

    def test_gerant_alone_not_a_person(self):
        self.assertFalse(rp._is_natural_person("gérant", "gérant: test"))

    def test_legal_phrase_in_context_rejected(self):
        text = "associé solidairement responsable: quelque chose"
        people = rp.extract_people_facts(text)
        self.assertEqual(people, [])


class ScoringSafetyTests(unittest.TestCase):
    """Tests 5-10: scoring rules for the RESA legal-entity scenario."""

    def setUp(self):
        # Company with only the facts available from the fixture (no enrichment).
        self.company = {
            "company_name": COMPANY["legal_name"],
            "creation_date": COMPANY["formation_date"],
            "website_status": "NOT_CHECKED",
            "digital_score": None,
            "seo_opportunity": None,
            "google_status": "NOT_CHECKED",
            "decision_maker_status": "UNKNOWN",
            "niche_attractiveness": None,
            "commercial_potential": None,
        }
        # No signals (nothing verified independently).
        self.signals = []

    def test_no_decision_maker_found(self):
        r = calculate(self.company, signals=self.signals)
        self.assertNotIn("DECISION_MAKER_FOUND", self.signals)
        dm = [f for f in r["factors"] if f["key"] == "decision_maker"][0]
        self.assertEqual(dm["points"], 0)

    def test_unknown_niche_zero_points(self):
        r = calculate(self.company, signals=self.signals)
        niche = [f for f in r["factors"] if f["key"] == "niche"][0]
        self.assertEqual(niche["points"], 0)

    def test_not_checked_website_zero_points(self):
        r = calculate(self.company, signals=self.signals)
        dg = [f for f in r["factors"] if f["key"] == "digital_gap"][0]
        self.assertEqual(dg["points"], 0)

    def test_not_checked_seo_zero_points(self):
        r = calculate(self.company, signals=self.signals)
        seo = [f for f in r["factors"] if f["key"] == "seo_opportunity"][0]
        self.assertEqual(seo["points"], 0)

    def test_not_checked_google_zero_points(self):
        r = calculate(self.company, signals=self.signals)
        local = [f for f in r["factors"] if f["key"] == "local_presence"][0]
        self.assertEqual(local["points"], 0)

    def test_freshness_from_real_date(self):
        r = calculate(self.company, signals=self.signals)
        fr = [f for f in r["factors"] if f["key"] == "freshness"][0]
        self.assertGreater(fr["points"], 0)  # 2026-08-18 is very recent

    def test_no_fictitious_action(self):
        r = calculate(self.company, signals=self.signals)
        self.assertNotIn("CREATE_WEBSITE", r["action"])  # NOT_CHECKED ≠ NOT_FOUND
        self.assertNotIn("LOCAL_SEO", r["action"])       # NOT_CHECKED ≠ NOT_FOUND
        self.assertNotIn("SEO_SERVICE", r["action"])     # no WEAK_SEO signal

    def test_commercial_potential_null_zero(self):
        r = calculate(self.company, signals=self.signals)
        cp = [f for f in r["factors"] if f["key"] == "commercial_potential"][0]
        self.assertEqual(cp["points"], 0)

    def test_score_reproducible(self):
        r1 = calculate(self.company, signals=self.signals)
        r2 = calculate(self.company, signals=self.signals)
        self.assertEqual(r1["provenance_fingerprint"], r2["provenance_fingerprint"])
        self.assertEqual(r1["score"], r2["score"])


class NoEnrichmentTests(unittest.TestCase):
    """Tests 13-14: no external enrichment or fictional data."""

    def test_no_enrichment_executed(self):
        # The scoring result must not contain website/SEO/google enrichment data.
        company = {
            "creation_date": COMPANY["formation_date"],
            "website_status": "NOT_CHECKED",
            "google_status": "NOT_CHECKED",
        }
        r = calculate(company, signals=[])
        # website/SEO/google are NOT_CHECKED → 0 points
        for key in ("digital_gap", "seo_opportunity", "local_presence"):
            f = [x for x in r["factors"] if x["key"] == key][0]
            self.assertEqual(f["points"], 0)

    def test_no_fictional_emails_or_phones(self):
        blob = json.dumps(COMPANY) + json.dumps(RELATED_ENTITIES)
        for forbidden in ("@", "tel:", "phone", "email", "http://", "https://"):
            self.assertNotIn(forbidden, blob.lower())


class FixtureHonestyTests(unittest.TestCase):
    """Tests 15-16: fixture is never presented as real PDF integration."""

    def test_source_hash_not_fabricated(self):
        # The fixture metadata must NOT contain a fabricated file hash.
        blob = json.dumps(FIXTURE_METADATA)
        self.assertNotIn("sha256", blob.lower())
        self.assertNotIn("checksum", blob.lower())

    def test_extraction_method_not_fabricated(self):
        blob = json.dumps(FIXTURE_METADATA)
        self.assertNotIn("native_text", blob.lower())
        self.assertNotIn("ocr", blob.lower())


class RegressionTests(unittest.TestCase):
    """Tests 17-20: existing Step 7 behavior preserved."""

    def test_scoring_formula_unchanged(self):
        self.assertEqual(MODEL_VERSION, "nacelux-scoring-7.0")
        r = calculate({"creation_date": date.today().isoformat(), "website_status": "NOT_FOUND",
                        "seo_opportunity": 90, "google_status": "NOT_FOUND",
                        "decision_maker_status": "FOUND", "niche_attractiveness": 95,
                        "commercial_potential": 90})
        self.assertGreaterEqual(r["score"], 90)

    def test_fingerprint_deterministic(self):
        c = {"creation_date": "2026-08-18", "website_status": "NOT_CHECKED"}
        r1 = calculate(c, signals=[])
        r2 = calculate(c, signals=[])
        self.assertEqual(r1["provenance_fingerprint"], r2["provenance_fingerprint"])

    def test_natural_persons_still_extracted(self):
        people = rp.extract_people_facts("Gérant: Jean Dupont")
        self.assertTrue(any("Jean" in p["display_name"] for p in people))


class TenantIsolationTests(unittest.TestCase):
    """Test 18: tenant isolation remains active."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.tmp.close()
        os.environ["NACELUX_DB"] = cls.tmp.name
        import database as data
        data.init_db()
        cls.data = data

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("NACELUX_DB", None)
        Path(cls.tmp.name).unlink(missing_ok=True)

    def test_tenant_isolation_scoring(self):
        ts = self.data.now()
        with self.data.connect() as db:
            db.execute("INSERT OR IGNORE INTO organizations(id,name,slug,created_at) VALUES(?,?,?,?)",
                       ("org_t2", "T2", "t2", ts))
            db.execute("INSERT INTO companies(id,organization_id,company_name,creation_date,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                       ("comp_t2", "org_t2", "Tenant 2 Co", "2026-08-18", ts, ts))
        # Tenant 1 (demo org) should not see tenant 2's company
        leak = self.data.list_companies("org_demo_lux", {"search": "Tenant 2"})
        self.assertEqual(len(leak), 0)

    def test_append_only_history_preserved(self):
        with self.data.connect() as db:
            self.data.recalculate_all(db, "org_demo_lux")
        before = self.data.one("SELECT count(*) c FROM opportunity_score_history WHERE organization_id='org_demo_lux'")["c"]
        with self.data.connect() as db:
            self.data.recalculate_all(db, "org_demo_lux")
        after = self.data.one("SELECT count(*) c FROM opportunity_score_history WHERE organization_id='org_demo_lux'")["c"]
        self.assertGreaterEqual(after, before)


if __name__ == "__main__":
    unittest.main()
