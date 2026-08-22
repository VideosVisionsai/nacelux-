"""Step 6 (ÉTAPE 6) — Business Signals: evidence-backed, no signal without proof.

UNKNOWN != NOT_CHECKED != NOT_CONNECTED; NOT_CONFIGURED != NOT_FOUND. A missing
or unchecked value never produces a positive/negative signal. Verified on an
isolated SQLite DB with clearly-labeled synthetic fixtures (never production).
"""
import json, os, sys, tempfile, unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import database
from business_signals import BusinessSignalEngine


class SignalFixture(unittest.TestCase):
    ORG = "o"

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()

        def connect():
            db = __import__("sqlite3").connect(self.tmp.name)
            db.row_factory = __import__("sqlite3").Row
            db.execute("PRAGMA foreign_keys=ON")
            return db
        self.connect = connect
        with connect() as db:
            db.executescript(database.SCHEMA)
            db.execute("INSERT INTO organizations VALUES(?,?,?,?)", ("o", "O", "o", "2026-01-01"))

    def tearDown(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    def _company(self, cid="c", name="Co", creation=None, attractiveness=None, is_demo=0, source_status=None, website_status="NOT_CHECKED"):
        with self.connect() as db:
            db.execute("INSERT INTO companies(id,organization_id,company_name,creation_date,website_status,niche_attractiveness,is_demo,source_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (cid, "o", name, creation, website_status, attractiveness, is_demo, source_status, "2026-01-01", "2026-01-01"))

    def _discovery(self, cid, status="SUCCESS", selected=None, error=None):
        with self.connect() as db:
            db.execute("INSERT INTO website_discovery_runs(id,organization_id,company_id,status,provider,query_text,started_at,candidates_found,selected_candidate_id,error_code) VALUES(?,?,?,?,?,?,?, ?,?,?)",
                       ("run_" + cid, "o", cid, status, "test", "q", "2026-01-01", 0 if not selected else 1, selected, error))

    def _check(self, cid, channel, status, details=None, provider=None, https_status=None):
        with self.connect() as db:
            db.execute("INSERT INTO digital_checks(id,organization_id,company_id,channel,status,confidence,checked_at,details,source_provider,https_status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       ("chk_" + cid + channel.replace(" ", "_"), "o", cid, channel, status, 1.0, "2026-01-01", json.dumps(details or {}), provider, https_status))

    def _seo(self, cid, score=20, findings=None):
        with self.connect() as db:
            db.execute("INSERT INTO seo_audits(id,organization_id,company_id,status,seo_score,opportunity_score,findings,checked_at) VALUES(?,?,?,?,?,?,?,?)",
                       ("seo_" + cid, "o", cid, "SUCCESS", score, 100 - score, json.dumps(findings or [{"check": "HTTPS", "severity": "HIGH", "message": "no https", "points_lost": 15}]), "2026-01-01"))

    def _person(self, cid, source_type="OFFICIAL", confidence=0.9, privacy="ACTIVE"):
        with self.connect() as db:
            db.execute("INSERT INTO people(id,organization_id,display_name,company_id,source_type,match_status,confidence,privacy_status,is_demo,created_at,name_normalized) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       ("p_" + cid, "o", "Director " + cid, cid, source_type, "CONFIRMED", confidence, privacy, 0, "2026-01-01", "dir" + cid))

    def _signals(self, cid):
        eng = BusinessSignalEngine(self.connect)
        res = eng.refresh("o", cid)
        return {s["signal_type"]: s for s in res["signals"]}, res


class PositiveSignalsTests(SignalFixture):
    def test_new_company_and_recent_incorporation(self):
        self._company(creation=date.today().isoformat())
        sigs, _ = self._signals("c")
        self.assertIn("NEW_COMPANY", sigs)
        self.assertIn("RECENT_INCORPORATION", sigs)

    def test_no_website_only_from_completed_discovery(self):
        self._company(website_status="NOT_CHECKED")
        self._discovery("c", status="SUCCESS", selected=None)
        sigs, _ = self._signals("c")
        self.assertIn("NO_WEBSITE", sigs)
        self.assertEqual(sigs["NO_WEBSITE"]["data_quality"], "VERIFIED")

    def test_weak_website_factor_based(self):
        self._company(website_status="FOUND")
        self._check("c", "Website", "CONNECTED", details={"title": None, "h1": None, "has_viewport": False, "canonical": None}, https_status="NOT_HTTPS")
        sigs, _ = self._signals("c")
        self.assertIn("WEAK_WEBSITE", sigs)
        self.assertIn("HTTPS", sigs["WEAK_WEBSITE"]["value"]["factors"])

    def test_weak_seo_lists_findings(self):
        self._company(website_status="FOUND")
        self._seo("c", score=20, findings=[{"check": "META", "severity": "MEDIUM", "message": "missing", "points_lost": 15}])
        sigs, _ = self._signals("c")
        self.assertIn("WEAK_SEO", sigs)
        self.assertIn("META", sigs["WEAK_SEO"]["explanation"])

    def test_no_google_business_from_places_not_found(self):
        self._company()
        self._check("c", "Google Business", "NOT_FOUND", provider="google_places")
        sigs, _ = self._signals("c")
        self.assertIn("NO_GOOGLE_BUSINESS", sigs)

    def test_decision_maker_found_official(self):
        self._company()
        self._person("c", source_type="OFFICIAL", confidence=0.9)
        sigs, _ = self._signals("c")
        self.assertIn("DECISION_MAKER_FOUND", sigs)
        self.assertEqual(sigs["DECISION_MAKER_FOUND"]["data_quality"], "VERIFIED")

    def test_high_value_niche_from_taxonomy(self):
        self._company(attractiveness=90)
        sigs, _ = self._signals("c")
        self.assertIn("HIGH_VALUE_NICHE", sigs)


class NegativeGuardrailTests(SignalFixture):
    def _none(self, types):
        sigs, _ = self._signals("c")
        for t in types:
            self.assertNotIn(t, sigs, f"{t} should not be produced from missing/unchecked data")

    def test_unknown_creation_date_no_freshness_signal(self):
        self._company(creation=None)
        self._none(["NEW_COMPANY", "RECENT_INCORPORATION"])

    def test_no_website_case_A_discovery_not_run(self):
        self._company(website_status="NOT_CHECKED")  # no discovery run
        self._none(["NO_WEBSITE"])

    def test_no_website_case_B_not_configured(self):
        self._company(cid="c", website_status="NOT_CHECKED")
        self._discovery("c", status="NOT_CONFIGURED", error="SEARCH_PROVIDER_NOT_CONFIGURED")
        sigs, _ = self._signals("c")
        self.assertNotIn("NO_WEBSITE", sigs)  # NOT_CONFIGURED != NOT_FOUND

    def test_no_website_case_C_error(self):
        self._company(cid="c")
        self._discovery("c", status="FAILED")
        self._assert_none_for("c", ["NO_WEBSITE"])

    def test_no_website_case_D_blocked(self):
        self._company(cid="c")
        self._check("c", "Website", "BLOCKED")  # verify blocked, no completed discovery
        self._assert_none_for("c", ["NO_WEBSITE"])

    def _assert_none_for(self, cid, types):
        sigs, _ = self._signals(cid)
        for t in types:
            self.assertNotIn(t, sigs)

    def test_no_website_not_configured_not_found(self):
        self._company(); self._discovery("c", status="NOT_CONFIGURED", error="SEARCH_PROVIDER_NOT_CONFIGURED")
        sigs, _ = self._signals("c")
        self.assertNotIn("NO_WEBSITE", sigs)  # NOT_CONFIGURED != NOT_FOUND

    def test_no_google_business_when_not_connected_or_not_checked(self):
        self._company(); self._check("c", "Google Business", "NOT_CHECKED", provider="google_places")
        sigs, _ = self._signals("c"); self.assertNotIn("NO_GOOGLE_BUSINESS", sigs)
        self.setUp(); self._company(cid="c2"); self._check("c2", "Google Business", "NOT_FOUND", provider=None)
        sigs, _ = self._signals("c2"); self.assertNotIn("NO_GOOGLE_BUSINESS", sigs)  # not a places check

    def test_decision_maker_not_inferred_or_private(self):
        self._company(); self._person("c", source_type="OFFICIAL", confidence=0.5)  # below threshold
        sigs, _ = self._signals("c"); self.assertNotIn("DECISION_MAKER_FOUND", sigs)
        self.setUp(); self._company(cid="c2"); self._person("c2", source_type="INFERRED", confidence=0.9)
        sigs, _ = self._signals("c2"); self.assertNotIn("DECISION_MAKER_FOUND", sigs)  # not official

    def test_high_value_niche_null_no_invented_classification(self):
        self._company(attractiveness=None)
        sigs, _ = self._signals("c"); self.assertNotIn("HIGH_VALUE_NICHE", sigs)

    def test_weak_website_not_checked_metric_not_counted(self):
        self._company(website_status="FOUND")
        self._check("c", "Website", "CONNECTED", details={"title": "Has title", "h1": "Has h1", "has_viewport": True, "canonical": "x"}, https_status="VALID")
        sigs, _ = self._signals("c"); self.assertNotIn("WEAK_WEBSITE", sigs)  # nothing weak


class IdempotenceAndHistoryTests(SignalFixture):
    def test_fingerprint_is_deterministic(self):
        self._company(creation=date.today().isoformat())
        eng = BusinessSignalEngine(self.connect)
        s1 = {x["signal_type"]: x for x in eng.refresh("o", "c")["signals"]}
        fp1 = s1["NEW_COMPANY"]["evidence"]["fingerprint"]
        self.assertEqual(len(fp1), 64)
        s2 = {x["signal_type"]: x for x in eng.refresh("o", "c")["signals"]}
        self.assertEqual(s2["NEW_COMPANY"]["evidence"]["fingerprint"], fp1)  # same inputs -> same fingerprint

    def test_idempotent_refresh_no_duplicates(self):
        self._company(creation=date.today().isoformat())
        eng = BusinessSignalEngine(self.connect)
        eng.refresh("o", "c"); eng.refresh("o", "c")
        with self.connect() as db:
            n = db.execute("SELECT count(*) FROM business_signals WHERE organization_id='o' AND company_id='c'").fetchone()[0]
        self.assertEqual(n, len({x["signal_type"] for x in eng.refresh("o", "c")["signals"]}))  # no dup rows

    def test_activation_and_deactivation_history_preserved(self):
        self._company(website_status="NOT_CHECKED")
        self._discovery("c", status="SUCCESS", selected=None)
        eng = BusinessSignalEngine(self.connect)
        eng.refresh("o", "c")
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM business_signals WHERE signal_type='NO_WEBSITE'").fetchone()[0], "ACTIVE")
        # evidence changes -> deactivate, history (the INACTIVE row) is kept, not deleted
        with self.connect() as db:
            db.execute("UPDATE website_discovery_runs SET selected_candidate_id='found' WHERE id='run_c'")
        res = eng.refresh("o", "c")
        self.assertEqual(res["deactivated"], 1)
        with self.connect() as db:
            row = db.execute("SELECT status FROM business_signals WHERE signal_type='NO_WEBSITE'").fetchone()
            self.assertEqual(row[0], "INACTIVE")  # history retained as INACTIVE


class TenantAndSecretTests(SignalFixture):
    def test_tenant_isolation(self):
        with self.connect() as db:
            db.execute("INSERT INTO organizations VALUES(?,?,?,?)", ("o2", "O2", "o2", "2026-01-01"))
            db.execute("INSERT INTO companies(id,organization_id,company_name,creation_date,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                       ("c2", "o2", "Other", date.today().isoformat(), "2026-01-01", "2026-01-01"))
        self._company(creation=date.today().isoformat())
        BusinessSignalEngine(self.connect).refresh("o", "c")
        with self.connect() as db:
            leak = db.execute("SELECT count(*) FROM business_signals WHERE organization_id='o2'").fetchone()[0]
        self.assertEqual(leak, 0)

    def test_no_secrets_in_signal_payload(self):
        self._company(creation=date.today().isoformat())
        eng = BusinessSignalEngine(self.connect)
        sigs = eng.refresh("o", "c")["signals"]
        blob = json.dumps(sigs, default=str)
        for forbidden in ("password", "postgresql://", "service_role", "eyJ", "supabase"):
            self.assertNotIn(forbidden, blob.lower())


if __name__ == "__main__":
    unittest.main()
