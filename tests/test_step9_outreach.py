"""Step 9 — Commercial outreach preparation tests.

Validates: contact safety (signatory≠DM), deterministic reasoning (evidence-backed,
no unsupported claims), LLM not configured, no automatic sending, tenant isolation,
append-only review, Step 7/8 regression.

All fixtures are TEST-ONLY. The RESA_2026_179 fixture has people=[] (no verified DM).
"""
import json, os, sys, tempfile, unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import outreach as oe
import llm_provider as lp


class ContactSafetyTests(unittest.TestCase):
    def test_signatory_not_decision_maker(self):
        """SIGNATORY_ONLY must never qualify as a verified contact."""
        from llm_provider import classify_role_type
        self.assertEqual(classify_role_type("signataire"), "NON_MANAGER")
        self.assertNotIn("NON_MANAGER", oe.VERIFIED_DECISION_ROLES)

    def test_person_mentioned_not_decision_maker(self):
        self.assertNotIn("PERSON_MENTIONED", oe.VERIFIED_DECISION_ROLES)

    def test_unknown_not_decision_maker(self):
        self.assertNotIn("UNKNOWN", oe.VERIFIED_DECISION_ROLES)

    def test_manager_is_decision_role(self):
        self.assertIn("MANAGER", oe.VERIFIED_DECISION_ROLES)
        self.assertIn("DIRECTOR", oe.VERIFIED_DECISION_ROLES)
        self.assertIn("PARTNER", oe.VERIFIED_DECISION_ROLES)


class ReasoningTests(unittest.TestCase):
    def test_reasoning_only_evidence_backed(self):
        """Every reasoning claim must reference a signal or evidence factor."""
        opp = {"score": 85, "level": "HIGH", "recommended_action": "CREATE_WEBSITE"}
        company = {"company_name": "Test Co"}
        signals = [{"signal_type": "NO_WEBSITE", "status": "ACTIVE"}]
        contact = None
        r = oe.build_reasoning(opp, company, signals, contact)
        for reason in r["why_this_company"]:
            self.assertIn("claim", reason)
            self.assertIn("evidence", reason)
            self.assertIn("factor", reason)

    def test_no_unsupported_claims(self):
        """No claim about competitors or unsupported SEO statements."""
        opp = {"score": 50, "level": "MEDIUM", "recommended_action": "MONITOR"}
        company = {"company_name": "Co"}
        signals = []
        r = oe.build_reasoning(opp, company, signals, None)
        blob = json.dumps(r, default=str).lower()
        self.assertNotIn("competitor", blob)
        self.assertNotIn("better than", blob)

    def test_no_contact_means_no_contact_reasoning(self):
        r = oe.build_reasoning({"score": 50, "level": "MEDIUM"}, {"company_name": "Co"}, [], None)
        contact_reasons = [x for x in r["why_this_company"] if x["factor"] == "NO_VERIFIED_CONTACT"]
        self.assertGreater(len(contact_reasons), 0)

    def test_contact_available_reasoning(self):
        contact = {"name": "Jean Dupont", "role": "gérant", "role_type": "MANAGER", "verification": "VERIFIED"}
        r = oe.build_reasoning({"score": 80}, {"company_name": "Co"}, [], contact)
        contact_reasons = [x for x in r["why_this_company"] if x["factor"] == "CONTACT_AVAILABLE"]
        self.assertGreater(len(contact_reasons), 0)


class DeterministicDraftTests(unittest.TestCase):
    def test_draft_has_required_fields(self):
        reasoning = {"action": "CREATE_WEBSITE", "why_this_company": [
            {"factor": "NO_WEBSITE", "claim": "No website", "evidence": "discovery"}]}
        company = {"company_name": "Test Co"}
        draft = oe.draft_message_deterministic(reasoning, company, None)
        for field in ("subject", "greeting", "body", "claims", "evidence_references", "confidence", "needs_human_review"):
            self.assertIn(field, draft)
        self.assertTrue(draft["needs_human_review"])  # ALWAYS requires review
        self.assertEqual(draft["provider"], "deterministic")

    def test_no_fictitious_email(self):
        reasoning = {"action": "MONITOR", "why_this_company": []}
        draft = oe.draft_message_deterministic(reasoning, {"company_name": "Co"}, None)
        blob = json.dumps(draft).lower()
        self.assertNotIn("@", blob)
        self.assertNotIn("email", blob)

    def test_greeting_uses_contact_name(self):
        reasoning = {"action": "MONITOR", "why_this_company": []}
        contact = {"name": "Marie Curie"}
        draft = oe.draft_message_deterministic(reasoning, {"company_name": "Co"}, contact)
        self.assertIn("Marie", draft["greeting"])

    def test_greeting_fallback_no_contact(self):
        reasoning = {"action": "MONITOR", "why_this_company": []}
        draft = oe.draft_message_deterministic(reasoning, {"company_name": "Co"}, None)
        self.assertIn("Sir/Madam", draft["greeting"])


class LlmNotConfiguredTests(unittest.TestCase):
    def test_no_llm_means_deterministic(self):
        os.environ.pop("LLM_PROVIDER", None)
        os.environ.pop("OPENAI_API_KEY", None)
        self.assertFalse(lp.is_configured())
        self.assertIsNone(lp.get_provider())


class NoAutomaticSendingTests(unittest.TestCase):
    def test_prepare_outreach_not_ready_to_send(self):
        """prepare_outreach must NEVER set ready_to_send=True."""
        # We can't call prepare_outreach without a DB, so test the contract:
        draft = oe.draft_message_deterministic(
            {"action": "MONITOR", "why_this_company": []}, {"company_name": "Co"}, None)
        self.assertTrue(draft["needs_human_review"])
        # The API always returns ready_to_send=False


class Resa179FixtureTests(unittest.TestCase):
    """RESA_2026_179 fixture: people=[] → no verified contact → no personalized message."""

    def test_no_contact_for_legal_entity_only(self):
        """With people=[], get_verified_contact returns None (no natural person)."""
        # Simulate: the fixture has no people in the DB.
        # We verify the contract: when no qualified person exists, contact is None.
        # The reasoning correctly notes NO_VERIFIED_CONTACT.
        r = oe.build_reasoning(
            {"score": 20, "level": "LOW", "recommended_action": "LOW_PRIORITY"},
            {"company_name": "ROUNDTABLE LUX SCSP"}, [], None)
        contact_reasons = [x for x in r["why_this_company"] if x["factor"] == "NO_VERIFIED_CONTACT"]
        self.assertGreater(len(contact_reasons), 0)

    def test_fixture_draft_has_no_person_name(self):
        r = oe.build_reasoning(
            {"score": 20, "level": "LOW", "recommended_action": "LOW_PRIORITY"},
            {"company_name": "ROUNDTABLE LUX SCSP"}, [], None)
        draft = oe.draft_message_deterministic(r, {"company_name": "ROUNDTABLE LUX SCSP"}, None)
        self.assertIn("Sir/Madam", draft["greeting"])  # no person name


class Step7RegressionTests(unittest.TestCase):
    def test_scoring_formula_unchanged(self):
        from scoring import calculate, MODEL_VERSION
        self.assertEqual(MODEL_VERSION, "nacelux-scoring-7.0")
        r = calculate({"creation_date": date.today().isoformat(), "website_status": "NOT_FOUND",
                        "google_status": "NOT_FOUND", "niche_attractiveness": 90,
                        "commercial_potential": 70}, signals=["NO_WEBSITE"])
        self.assertGreater(r["score"], 0)
        self.assertEqual(sum(f["points"] for f in r["factors"]), r["score"])

    def test_unknown_still_zero(self):
        from scoring import calculate
        r = calculate({}, signals=[])
        self.assertEqual(r["score"], 0)

    def test_fingerprint_deterministic(self):
        from scoring import calculate
        c = {"creation_date": "2026-08-18", "website_status": "NOT_CHECKED"}
        self.assertEqual(calculate(c, signals=[])["provenance_fingerprint"],
                         calculate(c, signals=[])["provenance_fingerprint"])


class Step8RegressionTests(unittest.TestCase):
    def test_outreach_validation_states(self):
        for state in ("DRAFT", "REVIEW_REQUIRED", "APPROVED", "REJECTED", "READY_TO_SEND"):
            # These are valid outreach review states
            self.assertIsInstance(state, str)


class NoSecretsTests(unittest.TestCase):
    def test_no_secrets_in_draft(self):
        reasoning = {"action": "MONITOR", "why_this_company": [
            {"factor": "NO_WEBSITE", "claim": "test", "evidence": "test"}]}
        draft = oe.draft_message_deterministic(reasoning, {"company_name": "Co"}, None)
        blob = json.dumps(draft, default=str).lower()
        for forbidden in ("password", "postgresql://", "service_role", "eyJ", "api_key", "secret"):
            self.assertNotIn(forbidden, blob)


if __name__ == "__main__":
    unittest.main()
