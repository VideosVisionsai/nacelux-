import os,sqlite3,sys,tempfile,unittest
from datetime import date
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
import database
from seo_engine import SEOAuditEngine,BusinessSignalEngine,SeoHTMLParser

class SeoEngineTests(unittest.TestCase):
    def setUp(self):os.environ.pop('PAGESPEED_API_KEY',None);self.engine=SEOAuditEngine(lambda:None)
    def test_complete_page_scores_100(self):
        result={'final_url':'https://example.com/','response_ms':400,'size':100000,'html':{'title':'A complete and descriptive website title here','h1':['Primary heading'],'meta_description':'A useful description of this company and its professional services in Luxembourg for prospective business customers.','viewport':'width=device-width, initial-scale=1','robots':'index,follow','canonical':'https://example.com/'}}
        audit=self.engine._analyze(result);self.assertEqual(audit['seo_score'],100);self.assertEqual(audit['seo_opportunity'],0);self.assertEqual(audit['mobile_status'],'PASS')
    def test_missing_elements_create_opportunity(self):
        result={'final_url':'http://example.com/','response_ms':4000,'size':2000000,'html':{'title':'','h1':[],'meta_description':'','viewport':'','robots':'noindex','canonical':None}}
        audit=self.engine._analyze(result);self.assertLess(audit['seo_score'],30);self.assertGreater(audit['seo_opportunity'],70);self.assertGreaterEqual(len(audit['findings']),6)

class BusinessSignalsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.NamedTemporaryFile(suffix='.db',delete=False);self.tmp.close()
        def connect():db=sqlite3.connect(self.tmp.name);db.row_factory=sqlite3.Row;return db
        self.connect=connect
        with connect() as db:
            db.executescript(database.SCHEMA);db.execute("INSERT INTO organizations VALUES(?,?,?,?)",('org','Org','org','2026-01-01'));db.execute("INSERT INTO companies(id,organization_id,company_name,creation_date,website_status,google_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",('c','org','New Company',date.today().isoformat(),'NOT_FOUND','NOT_FOUND','2026-01-01','2026-01-01'));db.execute("INSERT INTO seo_audits(id,organization_id,company_id,status,seo_score,findings) VALUES(?,?,?,?,?,?)",('s','org','c','SUCCESS',20,'[]'));db.execute("INSERT INTO digital_checks(id,organization_id,company_id,channel,status,confidence,checked_at,details) VALUES(?,?,?,?,?,?,?,?)",('dw','org','c','Website','NOT_FOUND',1,'2026-01-01','{}'));db.execute("INSERT INTO digital_checks(id,organization_id,company_id,channel,status,confidence,checked_at,details) VALUES(?,?,?,?,?,?,?,?)",('dg','org','c','Google Business','NOT_FOUND',1,'2026-01-01','{}'))
    def tearDown(self):Path(self.tmp.name).unlink(missing_ok=True)
    def test_required_signals_are_evidence_backed_and_idempotent(self):
        engine=BusinessSignalEngine(self.connect);first=engine.detect('org','c');engine.detect('org','c');types={x['signal_type'] for x in first};self.assertTrue({'NEW_COMPANY','NO_WEBSITE','WEAK_SEO','NO_GOOGLE_BUSINESS'}<=types)
        with self.connect() as db:self.assertEqual(db.execute("SELECT count(*) FROM business_signals WHERE status='ACTIVE'").fetchone()[0],len(first))

if __name__=='__main__':unittest.main()
