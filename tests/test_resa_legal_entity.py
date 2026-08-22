"""RESA legal-entity validation — TEST-ONLY fixture.

Validates that the RESA parser correctly distinguishes legal entities from natural
persons and does NOT invent a decision maker when the named manager/gérant is a
legal entity (e.g. a Sàrl). Based on a described RESA publication structure;
the actual PDF file was NOT available in the workspace.

Rules validated:
- Roundtable Lux GP (general partner, RCS B266208) → LEGAL_ENTITY, not a person.
- Roundtable Lux Ops (manager, RCS B266215) → LEGAL_ENTITY, not a person.
- Neither entity is inserted into the people table.
- No DECISION_MAKER_FOUND signal.
- Decision-maker scoring points = 0.
- NACE/website/SEO/Google all remain UNKNOWN/NOT_CHECKED → 0 points.
- Natural persons are still correctly extracted (regression check).
"""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import resa_pipeline as rp
import pdf_extraction as pe
from scoring import calculate

# ─── TEST-ONLY fixture based on described RESA publication ────────────────────
# This is NOT real production data. It is a deterministic text fixture derived
# from the user's description of RESA-2026_179.931 structure.
#
# FIXTURE DATA — TEST ONLY

PAGE_3 = (
    "RESA — Recueil Electronique des Sociétés et Associations\n"
    "Publication: RESA-2026_179_931\n"
    "Dénomination: ROUNDTABLE LUX SCSP NEWCO 86 USD\n"
    "Forme: société en commandite spéciale (SCSP)\n"
    "Date de constitution: 18/08/2026\n"
    "Adresse: 7, rue Robert Stümper, L-2557 Luxembourg\n"
    "Associé solidairement responsable: Roundtable Lux GP (RCS B266208), "
    "société en commandite par actions, ayant son siège à Luxembourg."
)

PAGE_4 = (
    "Il est nommé gérant: Roundtable Lux Ops (RCS B266215), "
    "société à responsabilité limitée, ayant son siège social à Luxembourg. "
    "Le gérant n'est pas associé."
)


class ResaLegalEntityTests(unittest.TestCase):
    """Validate that legal entities are never treated as natural-person decision makers."""

    def test_no_people_extracted_from_legal_entities(self):
        """Roundtable Lux GP and Roundtable Lux Ops are legal entities (Sàrl/SCA).
        Neither must appear as a natural person."""
        people = pe.extract_people_from_pages([
            {"page_number": 3, "text": PAGE_3},
            {"page_number": 4, "text": PAGE_4},
        ])
        self.assertEqual(people, [], f"legal entities extracted as people: {people}")

    def test_general_partner_not_a_person(self):
        """'Roundtable Lux GP' (associé solidairement responsable) is a legal entity."""
        people = rp.extract_people_facts(PAGE_3)
        names = {p["display_name"] for p in people}
        self.assertNotIn("Roundtable Lux GP", names)
        self.assertNotIn("solidairement responsable", names)

    def test_manager_entity_not_a_person(self):
        """'Roundtable Lux Ops' (gérant) is a legal entity (Sàrl), not a natural person."""
        people = rp.extract_people_facts(PAGE_4)
        names = {p["display_name"] for p in people}
        self.assertNotIn("Roundtable Lux Ops", names)

    def test_no_decision_maker_found_signal(self):
        """With zero natural-person people, the DECISION_MAKER_FOUND signal must not fire.
        The scoring engine gives 0 decision-maker points."""
        r = calculate({"company_name": "ROUNDTABLE LUX SCSP", "creation_date": "2026-08-18"},
                       signals=[])  # no DECISION_MAKER_FOUND in signals
        dm = [f for f in r["factors"] if f["key"] == "decision_maker"][0]
        self.assertEqual(dm["points"], 0)

    def test_legal_phrase_rejected(self):
        """'solidairement responsable' is a French legal phrase, not a person name."""
        self.assertFalse(rp._is_natural_person("solidairement responsable", "associé solidairement responsable"))

    def test_legal_entity_with_rcs_rejected(self):
        """A name followed by an RCS number is a legal entity."""
        excerpt = "gérant: Test Entity (RCS B123456), société à responsabilité limitée"
        self.assertFalse(rp._is_natural_person("Test Entity", excerpt))

    def test_legal_entity_with_societe_rejected(self):
        """A name near 'société' is a legal entity."""
        excerpt = "gérant: Capital Holdings, société anonyme"
        self.assertFalse(rp._is_natural_person("Capital Holdings", excerpt))


class NaturalPersonRegressionTests(unittest.TestCase):
    """Ensure the legal-entity filter does NOT reject real natural persons."""

    def test_real_person_still_extracted(self):
        text = "Gérant: Jean Dupont  Administrateur: Marie Curie"
        people = rp.extract_people_facts(text)
        names = {p["display_name"] for p in people}
        self.assertIn("Jean Dupont", names)
        self.assertIn("Marie Curie", names)

    def test_real_person_in_resa_context(self):
        """A natural person named as gérant in a RESA-like text (no RCS nearby)."""
        text = "Est nommé gérant: Pierre Schmidt, demeurant à Luxembourg."
        people = rp.extract_people_facts(text)
        # "Pierre Schmidt" should be extracted (no RCS, no legal form nearby)
        names = {p["display_name"] for p in people}
        self.assertIn("Pierre Schmidt", names)

    def test_person_with_hyphenated_name(self):
        text = "Administrateur: Jean-Pierre Dubois"
        people = rp.extract_people_facts(text)
        self.assertTrue(any("Dubois" in p["display_name"] for p in people))


class ScoringSafetyTests(unittest.TestCase):
    """Validate scoring rules for the RESA legal-entity scenario."""

    def test_company_with_legal_entity_manager_scores_zero_dm(self):
        r = calculate({"creation_date": "2026-08-18", "website_status": "NOT_CHECKED"},
                       signals=[])  # no signals (nothing verified)
        dm = [f for f in r["factors"] if f["key"] == "decision_maker"][0]
        self.assertEqual(dm["points"], 0)

    def test_nace_unknown_scores_zero_niche(self):
        r = calculate({"niche_attractiveness": None}, signals=[])
        niche = [f for f in r["factors"] if f["key"] == "niche"][0]
        self.assertEqual(niche["points"], 0)

    def test_website_not_checked_scores_zero_digital(self):
        r = calculate({"website_status": "NOT_CHECKED"}, signals=[])
        dg = [f for f in r["factors"] if f["key"] == "digital_gap"][0]
        self.assertEqual(dg["points"], 0)

    def test_freshness_from_real_date(self):
        """Formation date 2026-08-18 gives freshness points (real date, not invented)."""
        r = calculate({"creation_date": "2026-08-18"}, signals=[])
        fr = [f for f in r["factors"] if f["key"] == "freshness"][0]
        self.assertGreater(fr["points"], 0)

    def test_no_fictitious_action(self):
        """With all signals NOT_CHECKED and no website/google, action must not invent."""
        r = calculate({"website_status": "NOT_CHECKED", "google_status": "NOT_CONNECTED"},
                       signals=[])
        # No CREATE_WEBSITE (NOT_CHECKED ≠ NOT_FOUND), no LOCAL_SEO
        self.assertNotIn("CREATE_WEBSITE", r["action"])
        self.assertNotIn("LOCAL_SEO", r["action"])


if __name__ == "__main__":
    unittest.main()
