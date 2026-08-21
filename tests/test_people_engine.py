import os,sqlite3,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
import database
from people_engine import PeopleEngine,extract_official_people

TEXT='Gérant : Jean-Pierre Muller ; Administratrice: Marie Dupont. Le siège social reste à Luxembourg. manager: société exemple.'
class PeopleEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.NamedTemporaryFile(suffix='.db',delete=False);self.tmp.close();os.environ['SEARCH_PROVIDER']='none'
        def connect():db=sqlite3.connect(self.tmp.name);db.row_factory=sqlite3.Row;return db
        self.connect=connect
        with connect() as db:
            db.executescript(database.SCHEMA);db.execute("INSERT INTO organizations VALUES(?,?,?,?)",('org','Org','org','2026-01-01'));db.execute("INSERT INTO companies(id,organization_id,company_name,rcs_number,created_at,updated_at) VALUES(?,?,?,?,?,?)",('c','org','Example Sàrl','B123456','2026-01-01','2026-01-01'));db.execute("INSERT INTO resa_journals(id,organization_id,journal_key,source_url,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?)",('j','org','RESA-2026_1_1_0','https://www.lbr.lu/journal','2026-01-01','2026-01-01'));db.execute("INSERT INTO resa_entries(id,organization_id,journal_id,natural_key,row_index,rcs_number,row_text,source_url,content_hash,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",('e','org','j','n',1,'B123456','row','https://www.lbr.lu/journal','h','2026-01-01','2026-01-01'));db.execute("INSERT INTO resa_documents(id,organization_id,journal_id,entry_id,document_url,canonical_url,source_url,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?,?)",('d','org','j','e','https://www.lbr.lu/file.pdf','https://www.lbr.lu/file.pdf','https://www.lbr.lu/journal','2026-01-01','2026-01-01'));db.execute("INSERT INTO document_extractions(id,organization_id,document_id,storage_object_id,source_checksum,status,text_content,engine_version,started_at) VALUES(?,?,?,?,?,?,?,?,?)",('x','org','d','s','hash','SUCCESS',TEXT,'test','2026-01-01'))
    def tearDown(self):Path(self.tmp.name).unlink(missing_ok=True)
    def test_explicit_official_roles_only(self):
        people=extract_official_people(TEXT);self.assertEqual({x['name'] for x in people},{'Jean-Pierre Muller','Marie Dupont'});self.assertTrue(all(x['confidence']>=.9 for x in people))
    def test_engine_stores_provenance_and_no_unconfigured_profile_guess(self):
        result=PeopleEngine(self.connect).analyze('org','c');self.assertEqual(result['status'],'SUCCESS');self.assertEqual(result['official_people_found'],2);self.assertEqual(result['professional_profiles_found'],0);self.assertEqual(result['profile_search_status'],'NOT_CONFIGURED')
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM people WHERE source_type='OFFICIAL'").fetchone()[0],2);self.assertEqual(db.execute('SELECT count(*) FROM people_evidence').fetchone()[0],2)
    def test_privacy_request_sets_review_status(self):
        result=PeopleEngine(self.connect).analyze('org','c');pid=result['official_people'][0]['id'];request=PeopleEngine(self.connect).create_privacy_request('org',pid,'SUPPRESSION','case-1');self.assertEqual(request['status'],'OPEN')
        with self.connect() as db:self.assertEqual(db.execute('SELECT privacy_status FROM people WHERE id=?',(pid,)).fetchone()[0],'REVIEW_REQUIRED')

if __name__=='__main__':unittest.main()
