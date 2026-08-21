import os,sqlite3,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
import database
from website_intelligence import WebsiteDiscoveryEngine,DigitalFootprintEngine,validate_public_url

class WebsiteIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.NamedTemporaryFile(suffix='.db',delete=False);self.tmp.close();os.environ['SEARCH_PROVIDER']='none';os.environ.pop('GOOGLE_PLACES_API_KEY',None)
        def connect():db=sqlite3.connect(self.tmp.name);db.row_factory=sqlite3.Row;return db
        self.connect=connect
        with connect() as db:
            db.executescript(database.SCHEMA);db.execute("INSERT INTO organizations VALUES(?,?,?,?)",('org','Org','org','2026-01-01'));db.execute("INSERT INTO companies(id,organization_id,company_name,rcs_number,municipality,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",('c','org','Alpha Digital Sàrl','B123456','Esch-sur-Alzette','2026-01-01','2026-01-01'))
    def tearDown(self):Path(self.tmp.name).unlink(missing_ok=True)
    def test_no_provider_never_claims_not_found(self):
        result=WebsiteDiscoveryEngine(self.connect).discover('org','c');self.assertEqual(result['status'],'NOT_CONFIGURED')
        with self.connect() as db:check=db.execute("SELECT status FROM digital_checks WHERE company_id='c' AND channel='Website'").fetchone();self.assertEqual(check[0],'NOT_CHECKED')
    def test_digital_channels_remain_not_checked_without_connectors(self):
        result=DigitalFootprintEngine(self.connect).analyze('org','c');self.assertEqual(result['website']['status'],'NOT_CONFIGURED');self.assertEqual(result['linkedin']['status'],'NOT_CHECKED');self.assertEqual(result['google_business']['status'],'NOT_CHECKED');self.assertEqual(result['facebook']['status'],'NOT_CHECKED')
    def test_candidate_scoring_is_explainable(self):
        engine=WebsiteDiscoveryEngine(self.connect);score,evidence=engine._score({'company_name':'Alpha Digital Sàrl','rcs_number':'B123456','municipality':'Esch-sur-Alzette'},'https://alpha-digital.lu/',{'title':'Alpha Digital','snippet':'Esch-sur-Alzette'}, {'title':'Alpha Digital Sàrl','text':'Alpha Digital Sàrl RCS B123456 Esch-sur-Alzette'})
        self.assertGreaterEqual(score,.9);self.assertTrue(evidence['rcs_match']);self.assertTrue(evidence['location_match'])
    def test_ssrf_private_address_is_rejected(self):
        with self.assertRaises(ValueError):validate_public_url('http://127.0.0.1/admin')

if __name__=='__main__':unittest.main()
