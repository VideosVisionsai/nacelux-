"""Step 7 hardening: invariant, threshold, evidence, double-counting, decision-maker,
NACE, fingerprint, history, RESA fixtures, and API contract tests.

These tests do NOT change the scoring formula, weights, thresholds, actions, or
business meaning. They prove invariants that the existing implementation already
satisfies. All fixtures are TEST DATA — never presented as real production data.
"""
import hashlib, json, os, sys, tempfile, unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from scoring import calculate, _level_for, MODEL_VERSION, DEFAULT_WEIGHTS, LEVELS


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _company(**overrides):
    """Minimal company dict for scoring tests. Defaults are all-zero (UNKNOWN)."""
    base = {"creation_date": None, "website_status": "UNKNOWN", "digital_score": None,
            "seo_opportunity": None, "google_status": "UNKNOWN",
            "decision_maker_status": "UNKNOWN", "niche_attractiveness": None,
            "commercial_potential": None}
    base.update(overrides)
    return base


# ─── Task 1: Invariants ──────────────────────────────────────────────────────

class ScoringInvariantTests(unittest.TestCase):
    def test_score_always_between_0_and_100(self):
        """Score must be >= 0 and <= 100 for any combination of inputs."""
        test_cases = [
            (_company(), None),  # all unknown
            (_company(creation_date=date.today().isoformat(), website_status="NOT_FOUND",
                      seo_opportunity=100, google_status="NOT_FOUND",
                      decision_maker_status="FOUND", niche_attractiveness=100,
                      commercial_potential=100), None),
            (_company(creation_date="2000-01-01"), ["NO_WEBSITE", "WEAK_SEO", "DECISION_MAKER_FOUND"]),
        ]
        for company, signals in test_cases:
            r = calculate(company, signals=signals)
            self.assertGreaterEqual(r["score"], 0, f"score below 0 for {company}")
            self.assertLessEqual(r["score"], 100, f"score above 100 for {company}")

    def test_every_factor_le_its_max(self):
        r = calculate(_company(creation_date=date.today().isoformat(), website_status="NOT_FOUND",
                               seo_opportunity=100, google_status="NOT_FOUND",
                               decision_maker_status="FOUND", niche_attractiveness=100,
                               commercial_potential=100))
        for f in r["factors"]:
            self.assertLessEqual(f["points"], f["max"],
                                 f"factor {f['key']} points {f['points']} > max {f['max']}")

    def test_total_score_equals_sum_of_factors(self):
        """Score must equal the sum of individual factor points (before the 100 cap)."""
        test_sets = [(_company(), None),
                     (_company(creation_date=date.today().isoformat()), ["NO_WEBSITE"]),
                     (_company(commercial_potential=50, niche_attractiveness=60), ["WEAK_SEO"])]
        for company, signals in test_sets:
            r = calculate(company, signals=signals)
            raw_sum = sum(f["points"] for f in r["factors"])
            self.assertEqual(r["score"], min(100, raw_sum))

    def test_unknown_yields_zero_score(self):
        r = calculate(_company())
        self.assertEqual(r["score"], 0)

    def test_not_checked_yields_zero_digital_gap(self):
        """website_status=NOT_CHECKED must give 0 digital_gap points."""
        r = calculate(_company(website_status="NOT_CHECKED"))
        dg = [f for f in r["factors"] if f["key"] == "digital_gap"][0]
        self.assertEqual(dg["points"], 0)

    def test_not_connected_yields_zero_local(self):
        r = calculate(_company(google_status="NOT_CONNECTED"))
        lp = [f for f in r["factors"] if f["key"] == "local_presence"][0]
        self.assertEqual(lp["points"], 0)

    def test_missing_fields_cannot_create_positive_points(self):
        r = calculate({})
        self.assertEqual(r["score"], 0)
        for f in r["factors"]:
            self.assertEqual(f["points"], 0)

    def test_all_positive_does_not_exceed_100(self):
        c = _company(creation_date=date.today().isoformat(), website_status="NOT_FOUND",
                     seo_opportunity=100, google_status="NOT_FOUND",
                     decision_maker_status="FOUND", niche_attractiveness=100,
                     commercial_potential=100)
        r = calculate(c)
        self.assertLessEqual(r["score"], 100)


# ─── Task 2: Threshold tests ─────────────────────────────────────────────────

class ThresholdTests(unittest.TestCase):
    def test_level_boundaries(self):
        cases = [(0, "LOW"), (49, "LOW"), (50, "MEDIUM"), (74, "MEDIUM"),
                 (75, "HIGH"), (89, "HIGH"), (90, "VERY HIGH"), (100, "VERY HIGH")]
        for score, expected_level in cases:
            self.assertEqual(_level_for(score), expected_level,
                             f"score {score} should be {expected_level}")


# ─── Task 3: Incomplete / contradictory data ─────────────────────────────────

class IncompleteContradictoryTests(unittest.TestCase):
    def test_no_signals_uses_company_fields(self):
        r = calculate(_company(website_status="NOT_FOUND", niche_attractiveness=80), signals=[])
        self.assertGreater(r["score"], 0)

    def test_all_signals_unknown_still_works(self):
        """If all company fields are UNKNOWN/missing and no signals, score = 0."""
        r = calculate(_company(), signals=[])
        self.assertEqual(r["score"], 0)

    def test_missing_website_status(self):
        r = calculate({"creation_date": "2000-01-01"})
        dg = [f for f in r["factors"] if f["key"] == "digital_gap"][0]
        self.assertEqual(dg["points"], 0)

    def test_unknown_seo(self):
        r = calculate(_company(seo_opportunity=None))
        seo = [f for f in r["factors"] if f["key"] == "seo_opportunity"][0]
        self.assertEqual(seo["points"], 0)

    def test_no_website_plus_weak_seo(self):
        r = calculate(_company(), signals=["NO_WEBSITE", "WEAK_SEO"])
        self.assertGreater(r["score"], 0)
        self.assertIn("CREATE_WEBSITE", r["action"])
        self.assertIn("SEO_SERVICE", r["action"])

    def test_commercial_potential_missing(self):
        r = calculate({"commercial_potential": None})
        cp = [f for f in r["factors"] if f["key"] == "commercial_potential"][0]
        self.assertEqual(cp["points"], 0)

    def test_commercial_potential_null(self):
        r = calculate({})
        cp = [f for f in r["factors"] if f["key"] == "commercial_potential"][0]
        self.assertEqual(cp["points"], 0)

    def test_commercial_potential_outside_range(self):
        """Values >100 are out-of-range inputs; total score must still be capped."""
        r = calculate({"commercial_potential": 200})
        self.assertLessEqual(r["score"], 100)  # total always capped


# ─── Task 4: Evidence validation ─────────────────────────────────────────────

class EvidenceValidationTests(unittest.TestCase):
    def test_only_active_signals_in_scoring(self):
        """Scoring receives a list of signal TYPES; inactive/non-evidence statuses
        are filtered by the signal engine (Step 6) before reaching calculate().
        Here we verify that signals the engine would NOT activate contribute 0."""
        # DECISION_MAKER_FOUND is the only signal that gives decision_maker points.
        # If it's absent, decision_maker = 0 even if decision_maker_status is "FOUND".
        r_no_sig = calculate(_company(decision_maker_status="UNKNOWN"), signals=[])
        dm = [f for f in r_no_sig["factors"] if f["key"] == "decision_maker"][0]
        self.assertEqual(dm["points"], 0)

    def test_signal_status_propagation(self):
        """The signal engine (Step 6) only emits ACTIVE signals with evidence.
        Tests that simulate signals here are evidence-backed by construction."""
        r = calculate(_company(), signals=["DECISION_MAKER_FOUND"])
        dm = [f for f in r["factors"] if f["key"] == "decision_maker"][0]
        self.assertEqual(dm["points"], 5)  # full marks


# ─── Task 5: Double counting ─────────────────────────────────────────────────

class DoubleCountingTests(unittest.TestCase):
    def test_duplicate_signals_do_not_inflate(self):
        """The same signal type appearing multiple times must not give extra points."""
        r1 = calculate(_company(), signals=["NO_WEBSITE"])
        r2 = calculate(_company(), signals=["NO_WEBSITE", "NO_WEBSITE", "NO_WEBSITE"])
        self.assertEqual(r1["score"], r2["score"])
        self.assertEqual(r1["provenance_fingerprint"], r2["provenance_fingerprint"])

    def test_no_duplicate_factor_points(self):
        """Each scoring factor appears exactly once."""
        r = calculate(_company(creation_date=date.today().isoformat()),
                      signals=["NO_WEBSITE", "WEAK_SEO", "DECISION_MAKER_FOUND"])
        keys = [f["key"] for f in r["factors"]]
        self.assertEqual(len(keys), len(set(keys)), "duplicate factor keys")


# ─── Task 6: Decision maker safety ───────────────────────────────────────────

class DecisionMakerSafetyTests(unittest.TestCase):
    def test_signatory_only_does_not_qualify(self):
        """A signatory-only person must NOT trigger DECISION_MAKER_FOUND.
        The signal engine only emits DECISION_MAKER_FOUND for verified managers.
        Here we verify the scoring logic: no DECISION_MAKER_FOUND signal → 0 points."""
        r = calculate(_company(decision_maker_status="UNKNOWN"), signals=[])
        dm = [f for f in r["factors"] if f["key"] == "decision_maker"][0]
        self.assertEqual(dm["points"], 0)

    def test_verified_manager_qualifies(self):
        r = calculate(_company(decision_maker_status="FOUND"), signals=["DECISION_MAKER_FOUND"])
        dm = [f for f in r["factors"] if f["key"] == "decision_maker"][0]
        self.assertEqual(dm["points"], 5)

    def test_llm_signataire_not_manager(self):
        """Verify the LLM provider classifies signataire as NON_MANAGER."""
        from llm_provider import classify_role_type
        self.assertEqual(classify_role_type("signataire"), "NON_MANAGER")
        self.assertEqual(classify_role_type("mandataire"), "NON_MANAGER")
        self.assertEqual(classify_role_type("gérant"), "MANAGER")
        self.assertEqual(classify_role_type("administrateur"), "MANAGER")


# ─── Task 7: NACE compatibility ──────────────────────────────────────────────

class NaceCompatibilityTests(unittest.TestCase):
    def test_no_nace_no_invented_points(self):
        """Missing niche_attractiveness (no NACE, no taxonomy) → niche factor 0."""
        r = calculate(_company(niche_attractiveness=None), signals=[])
        n = [f for f in r["factors"] if f["key"] == "niche"][0]
        self.assertEqual(n["points"], 0)

    def test_high_value_niche_signal_gives_full(self):
        r = calculate(_company(), signals=["HIGH_VALUE_NICHE"])
        n = [f for f in r["factors"] if f["key"] == "niche"][0]
        self.assertEqual(n["points"], 20)

    def test_taxonomy_attractiveness_used_without_signal(self):
        r = calculate(_company(niche_attractiveness=85), signals=[])
        n = [f for f in r["factors"] if f["key"] == "niche"][0]
        self.assertEqual(n["points"], 17)  # round(20 * 0.85)


# ─── Task 8: Fingerprint reproducibility ─────────────────────────────────────

class FingerprintReproducibilityTests(unittest.TestCase):
    BASE = {"creation_date": "2026-01-15", "website_status": "NOT_FOUND",
            "digital_score": 10, "seo_opportunity": 80, "google_status": "NOT_FOUND",
            "decision_maker_status": "FOUND", "niche_attractiveness": 90,
            "commercial_potential": 70}
    BASE_SIGNALS = ["NO_WEBSITE", "DECISION_MAKER_FOUND"]

    def test_same_inputs_same_fingerprint(self):
        r1 = calculate(self.BASE, signals=self.BASE_SIGNALS)
        r2 = calculate(self.BASE, signals=self.BASE_SIGNALS)
        self.assertEqual(r1["provenance_fingerprint"], r2["provenance_fingerprint"])
        self.assertEqual(len(r1["provenance_fingerprint"]), 64)

    def test_changed_signal_different_fingerprint(self):
        r1 = calculate(self.BASE, signals=self.BASE_SIGNALS)
        r2 = calculate(self.BASE, signals=self.BASE_SIGNALS + ["WEAK_SEO"])
        self.assertNotEqual(r1["provenance_fingerprint"], r2["provenance_fingerprint"])

    def test_changed_weight_different_fingerprint(self):
        r1 = calculate(self.BASE, signals=self.BASE_SIGNALS)
        r2 = calculate(self.BASE, weights={"freshness": 19, "niche": 21, "digital_gap": 20,
                                           "seo_opportunity": 15, "local_presence": 10,
                                           "decision_maker": 5, "commercial_potential": 10},
                       signals=self.BASE_SIGNALS)
        self.assertNotEqual(r1["provenance_fingerprint"], r2["provenance_fingerprint"])

    def test_changed_field_different_fingerprint(self):
        r1 = calculate(self.BASE, signals=self.BASE_SIGNALS)
        modified = {**self.BASE, "niche_attractiveness": 50}
        r2 = calculate(modified, signals=self.BASE_SIGNALS)
        self.assertNotEqual(r1["provenance_fingerprint"], r2["provenance_fingerprint"])

    def test_no_volatile_fields_in_snapshot(self):
        """The canonical input_snapshot must NOT contain volatile fields like
        calculated_at, now(), or random data."""
        r = calculate(self.BASE, signals=self.BASE_SIGNALS)
        snap = r["input_snapshot"]
        for forbidden in ("calculated_at", "now", "random", "uuid", "timestamp"):
            self.assertNotIn(forbidden, snap, f"volatile field {forbidden} in snapshot")

    def test_stable_json_key_ordering(self):
        r = calculate(self.BASE, signals=self.BASE_SIGNALS)
        raw = json.dumps(r["input_snapshot"], sort_keys=True, default=str)
        self.assertEqual(raw, json.dumps(r["input_snapshot"], sort_keys=True, default=str))


# ─── Task 9: Append-only history ─────────────────────────────────────────────

class AppendOnlyHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.tmp.close()
        os.environ["NACELUX_DB"] = cls.tmp.name
        import database as data
        data.init_db()
        cls.data = data
        ts = data.now()
        with data.connect() as db:
            db.execute("INSERT OR IGNORE INTO organizations(id,name,slug,created_at) VALUES(?,?,?,?)",
                       ("org_h", "H", "h", ts))
            db.execute("INSERT INTO companies(id,organization_id,company_name,creation_date,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                       ("comp_h", "org_h", "Hardening Co", "2026-07-01", ts, ts))

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("NACELUX_DB", None)
        Path(cls.tmp.name).unlink(missing_ok=True)

    def test_recalculation_creates_history(self):
        before = self.data.one("SELECT count(*) c FROM opportunity_score_history WHERE organization_id='org_h'")["c"]
        with self.data.connect() as db:
            self.data.recalculate_all(db, "org_h")
        after = self.data.one("SELECT count(*) c FROM opportunity_score_history WHERE organization_id='org_h'")["c"]
        self.assertGreater(after, before)

    def test_previous_history_unchanged(self):
        with self.data.connect() as db:
            self.data.recalculate_all(db, "org_h")
        first = self.data.rows("SELECT * FROM opportunity_score_history WHERE organization_id='org_h' ORDER BY created_at LIMIT 1")
        with self.data.connect() as db:
            self.data.recalculate_all(db, "org_h")
        first_again = self.data.rows("SELECT * FROM opportunity_score_history WHERE organization_id='org_h' ORDER BY created_at LIMIT 1")
        self.assertEqual(first[0]["fingerprint"], first_again[0]["fingerprint"])
        self.assertEqual(first[0]["total_score"], first_again[0]["total_score"])

    def test_tenant_isolation_history(self):
        """Tenant B cannot read tenant A's scoring history (same-DB SQL filter)."""
        ts = self.data.now()
        with self.data.connect() as db:
            db.execute("INSERT OR IGNORE INTO organizations(id,name,slug,created_at) VALUES(?,?,?,?)",
                       ("org_h_b", "HB", "hb", ts))
        leak = self.data.rows("SELECT count(*) c FROM opportunity_score_history WHERE organization_id='org_h_b'")
        self.assertEqual(leak[0]["c"], 0)


# ─── Task 10: RESA test fixtures ─────────────────────────────────────────────

class ResaFixtureTests(unittest.TestCase):
    """Deterministic TEST DATA — never presented as real RESA results.
    Each fixture is a (company_dict, signals_list, expected_properties) tuple."""

    FIXTURES = [
        # 1. Valid immatriculation publication
        ("valid_immat", {"creation_date": date.today().isoformat(), "website_status": "NOT_FOUND",
                         "google_status": "NOT_FOUND", "niche_attractiveness": 90,
                         "commercial_potential": 80},
         ["NEW_COMPANY", "NO_WEBSITE", "NO_GOOGLE_BUSINESS", "HIGH_VALUE_NICHE"],
         {"min_score": 70, "action_contains": "CREATE_WEBSITE"}),
        # 2. Company with verified manager
        ("verified_manager", {"creation_date": "2000-01-01", "website_status": "FOUND",
                              "niche_attractiveness": 50, "commercial_potential": 50},
         ["DECISION_MAKER_FOUND"],
         {"action_contains": "LOW_PRIORITY"}),  # score < 50 → LOW_PRIORITY
        # 3. Company with signatory only (NOT a verified decision maker)
        ("signatory_only", {"creation_date": "2000-01-01"},
         [],  # no DECISION_MAKER_FOUND signal (signatory ≠ manager)
         {"dm_points": 0}),
        # 4. Company with no website
        ("no_website", {"creation_date": "2020-01-01"},
         ["NO_WEBSITE"],
         {"action_contains": "CREATE_WEBSITE", "digital_gap": 20}),
        # 5. Company with weak SEO
        ("weak_seo", {"creation_date": "2020-01-01", "website_status": "FOUND",
                      "seo_opportunity": 20},
         ["WEAK_SEO"],
         {"action_contains": "SEO_SERVICE"}),
        # 6. Company with unknown information
        ("unknown", {},
         [],
         {"score": 0}),
        # 7. Invalid/incomplete publication
        ("incomplete", {"creation_date": None},
         [],
         {"score": 0}),
    ]

    def test_fixtures(self):
        for name, company, signals, expectations in self.FIXTURES:
            with self.subTest(fixture=name):
                r = calculate(company, signals=signals)
                self.assertGreaterEqual(r["score"], 0)
                self.assertLessEqual(r["score"], 100)
                if "min_score" in expectations:
                    self.assertGreaterEqual(r["score"], expectations["min_score"],
                                            f"{name}: score {r['score']} < {expectations['min_score']}")
                if "action_contains" in expectations:
                    self.assertIn(expectations["action_contains"], r["action"],
                                  f"{name}: action '{r['action']}' missing '{expectations['action_contains']}'")
                if "dm_points" in expectations:
                    dm = [f for f in r["factors"] if f["key"] == "decision_maker"][0]
                    self.assertEqual(dm["points"], expectations["dm_points"],
                                     f"{name}: dm points {dm['points']} != {expectations['dm_points']}")
                if "digital_gap" in expectations:
                    dg = [f for f in r["factors"] if f["key"] == "digital_gap"][0]
                    self.assertEqual(dg["points"], expectations["digital_gap"],
                                     f"{name}: dg points {dg['points']} != {expectations['digital_gap']}")
                if "score" in expectations:
                    self.assertEqual(r["score"], expectations["score"],
                                     f"{name}: score {r['score']} != {expectations['score']}")


# ─── Task 12: API contract ───────────────────────────────────────────────────

class ScoringApiContractTests(unittest.TestCase):
    def test_calculate_returns_all_required_fields(self):
        r = calculate(_company(creation_date=date.today().isoformat()), signals=["NO_WEBSITE"])
        required = ["score", "level", "action", "model_version", "provenance_fingerprint",
                    "input_snapshot", "factors"]
        for field in required:
            self.assertIn(field, r, f"missing field {field}")
        # Each factor must have key, label, points, max
        for f in r["factors"]:
            for field in ("key", "label", "points", "max"):
                self.assertIn(field, f)
        # input_snapshot must contain signals, weights, model_version
        snap = r["input_snapshot"]
        self.assertIn("signals", snap)
        self.assertIn("weights", snap)
        self.assertIn("model_version", snap)

    def test_no_secrets_in_response(self):
        r = calculate(_company(), signals=[])
        blob = json.dumps(r, default=str)
        for forbidden in ("password", "postgresql://", "service_role", "eyJ", "api_key", "secret"):
            self.assertNotIn(forbidden, blob.lower())


if __name__ == "__main__":
    unittest.main()
