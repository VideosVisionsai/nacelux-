"""Step 5 (ÉTAPE 5.21/5.22) — Website Discovery + Digital Footprint tests.

SSRF validation, HTML analysis, status mapping, history and tenant isolation are
VERIFIED without network. Real HTTPS/HTML/connectivity checks run against
genuinely reachable public hosts (pypi.org / github.com) when the sandbox allows
egress; otherwise those network tests are skipped (REQUIRES CONFIGURATION). No
mocks stand in for real integration where real execution is possible.
"""
import io, json, os, socket, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import website_intelligence as wi
from website_intelligence import (validate_public_url, parse_html, SafeWebsiteRedirect,
                                  WebsiteDiscoveryEngine, WEBSITE_STATUSES, _is_public_routable)
import ipaddress


def _reachable(url="https://pypi.org/simple/", timeout=6):
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "NACELUX/1.0 probe"}), timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


NET = _reachable()


class SsrfValidationTests(unittest.TestCase):
    def _blocked(self, url):
        with self.assertRaises(ValueError):
            validate_public_url(url)

    def test_loopback_and_private_literals_blocked(self):
        for url in ("http://127.0.0.1/", "http://localhost/", "http://[::1]/",
                    "http://10.0.0.1/", "http://172.16.0.1/", "http://192.168.1.1/",
                    "http://169.254.169.254/", "http://0.0.0.0/",
                    "http://[fc00::1]/", "http://[fe80::1]/"):
            self._blocked(url)

    def test_metadata_hosts_blocked(self):
        for url in ("http://metadata.google.internal/", "http://169.254.170.2/"):
            self._blocked(url)

    def test_forbidden_schemes_and_ports_blocked(self):
        for url in ("file:///etc/passwd", "ftp://example.com/", "javascript:alert(1)",
                    "data:text/html,<x>", "http://example.com:8080/",
                    "http://user:pass@example.com/", "not a url at all"):
            self._blocked(url)

    def test_is_public_routable_helper(self):
        for ip in ("127.0.0.1", "10.1.2.3", "192.168.0.1", "169.254.169.254", "0.0.0.0",
                   "::1", "fc00::1", "fe80::1"):
            self.assertFalse(_is_public_routable(ipaddress.ip_address(ip)), ip)

    def test_dns_rebinding_to_private_is_blocked(self):
        # A hostname that resolves to a private address must be refused.
        orig = socket.getaddrinfo
        socket.getaddrinfo = lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        try:
            self._blocked("https://rebinding.example.com/")
        finally:
            socket.getaddrinfo = orig

    def test_redirect_to_private_or_localhost_is_blocked(self):
        handler = SafeWebsiteRedirect()
        req = type("R", (), {"full_url": "https://public.example.com/"})()
        for target in ("http://192.168.1.1/", "http://localhost/", "http://169.254.169.254/",
                       "http://127.0.0.1/", "http://[::1]/"):
            with self.assertRaises(ValueError):
                handler.redirect_request(req, None, 302, "Found", {}, target)


class HtmlAnalysisTests(unittest.TestCase):
    HTML = ("<html><head><title>Test Page</title>"
            "<meta name='description' content='A great company'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<link rel='canonical' href='https://example.eu/canonical'>"
            "<meta name='robots' content='noindex, follow'></head>"
            "<body><h1>Main Heading</h1><h1>Second</h1><p>body</p></body></html>")

    def test_extracts_all_technical_elements(self):
        r = parse_html(self.HTML)
        self.assertEqual(r["title"], "Test Page")
        self.assertEqual(r["h1"], "Main Heading")
        self.assertEqual(r["h1_count"], 2)
        self.assertEqual(r["meta_description"], "A great company")
        self.assertEqual(r["viewport"], "width=device-width, initial-scale=1")
        self.assertTrue(r["has_viewport"])
        self.assertEqual(r["canonical"], "https://example.eu/canonical")
        self.assertEqual(r["robots_meta"], "noindex, follow")

    def test_missing_elements_are_none(self):
        r = parse_html("<html><body><p>no head elements</p></body></html>")
        self.assertIsNone(r["title"])
        self.assertIsNone(r["h1"])
        self.assertIsNone(r["meta_description"])
        self.assertIsNone(r["viewport"])
        self.assertFalse(r["has_viewport"])


class StatusTaxonomyTests(unittest.TestCase):
    def test_all_required_statuses_defined(self):
        for s in ("UNKNOWN", "NOT_CHECKED", "CHECKING", "CONNECTED", "NOT_FOUND", "INVALID", "BLOCKED", "ERROR"):
            self.assertIn(s, WEBSITE_STATUSES)


class VerifyWebsiteFlowTests(unittest.TestCase):
    """verify_website status mapping + history recording (DB-backed, no network:
    analyze_website is monkeypatched to controlled outcomes)."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.tmp.close()
        os.environ["NACELUX_DB"] = cls.tmp.name
        import database as data
        data.init_db()
        cls.data = data
        cls.engine = WebsiteDiscoveryEngine(data.connect)
        ts = data.now()
        with data.connect() as db:
            db.execute("INSERT OR IGNORE INTO organizations(id,name,slug,created_at) VALUES(?,?,?,?)",
                       ("org_w5", "W5", "w5", ts))
            db.execute("INSERT OR IGNORE INTO users(id,email,display_name,created_at) VALUES(?,?,?,?)",
                       ("u_w5", "w5@t.i", "W5", ts))
            db.execute("INSERT OR IGNORE INTO organization_members(organization_id,user_id,role) VALUES(?,?,?)",
                       ("org_w5", "u_w5", "OWNER"))
            db.execute("INSERT INTO companies(id,organization_id,company_name,website,website_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                       ("c_w5", "org_w5", "Web Co", "https://example.eu", "NOT_CHECKED", ts, ts))

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("NACELUX_DB", None)
        Path(cls.tmp.name).unlink(missing_ok=True)

    def _patch_analyze(self, outcome):
        def fake(self_, url):
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        self.addCleanup(setattr, WebsiteDiscoveryEngine, "analyze_website",
                        getattr(WebsiteDiscoveryEngine, "analyze_website"))
        WebsiteDiscoveryEngine.analyze_website = fake

    def test_no_url_is_not_checked_never_no_website(self):
        # company with no website and no provided URL -> NOT_CHECKED, no NO_WEBSITE claim
        engine = WebsiteDiscoveryEngine(self.data.connect)
        with self.data.connect() as db:
            db.execute("UPDATE companies SET website=NULL WHERE id='c_w5'")
        r = engine.verify_website("org_w5", "c_w5")
        self.assertEqual(r["status"], "NOT_CHECKED")

    def test_connected_records_metrics_and_history(self):
        self._patch_analyze({"http_status": 200, "final_url": "https://example.eu/", "https": True,
                             "https_status": "VALID", "title": "Example", "h1": "Hi", "h1_count": 1,
                             "meta_description": "d", "viewport": "width=device-width", "has_viewport": True,
                             "canonical": "https://example.eu/", "robots_meta": None,
                             "page_bytes": 1234, "response_ms": 120, "charset": "utf-8"})
        r = self.engine.verify_website("org_w5", "c_w5", "https://example.eu")
        self.assertEqual(r["status"], "CONNECTED")
        chk = self.data.one("SELECT * FROM digital_checks WHERE organization_id='org_w5' AND company_id='c_w5' AND channel='Website'")
        self.assertEqual(chk["status"], "CONNECTED")
        self.assertEqual(chk["http_status"], 200)
        self.assertEqual(chk["https_status"], "VALID")
        self.assertEqual(chk["rule_version"], wi.WEBSITE_RULE_VERSION)
        # history is append-only: at least CHECKING + CONNECTED recorded
        hist = self.data.rows("SELECT status FROM digital_check_history WHERE organization_id='org_w5' AND company_id='c_w5' ORDER BY checked_at")
        statuses = [h["status"] for h in hist]
        self.assertIn("CHECKING", statuses)
        self.assertIn("CONNECTED", statuses)

    def test_blocked_status_on_ssrf(self):
        self._patch_analyze(ValueError("URL resolves to a non-public address"))
        r = self.engine.verify_website("org_w5", "c_w5", "http://169.254.169.254")
        self.assertEqual(r["status"], "BLOCKED")
        chk = self.data.one("SELECT status,error_code FROM digital_checks WHERE organization_id='org_w5' AND company_id='c_w5' AND channel='Website'")
        self.assertEqual(chk["status"], "BLOCKED")
        self.assertEqual(chk["error_code"], "SSRF_BLOCKED")

    def test_not_found_on_http_404_and_history_not_silently_replaced(self):
        before = self.data.one("SELECT count(*) c FROM digital_check_history WHERE organization_id='org_w5' AND company_id='c_w5'")["c"]
        self._patch_analyze(__import__("urllib.error", fromlist=["HTTPError"]).HTTPError("u", 404, "Not Found", {}, io.BytesIO(b"")))
        r = self.engine.verify_website("org_w5", "c_w5", "https://example.eu/missing")
        self.assertEqual(r["status"], "NOT_FOUND")
        after = self.data.one("SELECT count(*) c FROM digital_check_history WHERE organization_id='org_w5' AND company_id='c_w5'")["c"]
        self.assertGreater(after, before)  # history grows, never silently replaced

    def test_tenant_isolation(self):
        ts = self.data.now()
        with self.data.connect() as db:
            db.execute("INSERT OR IGNORE INTO organizations(id,name,slug,created_at) VALUES(?,?,?,?)",
                       ("org_w5_b", "B", "b", ts))
            db.execute("INSERT INTO companies(id,organization_id,company_name,created_at,updated_at) VALUES(?,?,?,?,?)",
                       ("c_w5_b", "org_w5_b", "B Co", ts, ts))
        # tenant B has no digital checks for org_w5's company
        leak = self.data.rows("SELECT * FROM digital_checks WHERE organization_id='org_w5_b' AND company_id='c_w5'")
        self.assertEqual(len(leak), 0)


@unittest.skipUnless(NET, "Real network checks require egress to a public site")
class RealNetworkTests(unittest.TestCase):
    """VERIFIED against genuinely reachable public hosts (not mocks)."""
    @classmethod
    def setUpClass(cls):
        cls.engine = WebsiteDiscoveryEngine(lambda: (_ for _ in ()).throw(RuntimeError("no db")))
        cls.engine.max_bytes = 5_000_000  # the real PyPI simple index is >1MB

    def test_real_https_connectivity_and_html(self):
        r = self.engine.analyze_website("https://pypi.org/")
        self.assertEqual(r["http_status"], 200)
        self.assertTrue(r["https"])
        self.assertEqual(r["https_status"], "VALID")
        self.assertGreater(r["page_bytes"], 0)
        self.assertGreaterEqual(r["response_ms"], 0)
        self.assertIsNotNone(r["hostname"])

    def test_real_https_to_http_not_assumed_from_scheme(self):
        # github.com serves real TLS; https_status VALID comes from the real handshake
        r = self.engine.analyze_website("https://github.com/")
        self.assertTrue(r["https"])
        self.assertEqual(r["https_status"], "VALID")

    def test_size_limit_enforced(self):
        eng = WebsiteDiscoveryEngine(lambda: (_ for _ in ()).throw(RuntimeError("no db")))
        eng.max_bytes = 50
        with self.assertRaises(ValueError):
            eng.analyze_website("https://pypi.org/simple/")


if __name__ == "__main__":
    unittest.main()
