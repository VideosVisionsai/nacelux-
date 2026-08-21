import sqlite3,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
import database
from resa_connector import LBRResaConnector,parse_static_html,validate_url

URL='https://www.lbr.lu/mjrcs-web-front/publication-journal/RESA-2026_231_1_0'
HTML=(ROOT/'tests/fixtures/resa_journal_sample.html').read_text()

class ResaParserTests(unittest.TestCase):
    def test_rejects_non_public_or_api_urls(self):
        for url in ['https://evil.test/publication-journal/RESA-2026_1_1_0','https://www.lbr.lu/mjrcs-web-api/x','http://www.lbr.lu/mjrcs-web-front/publication-journal/RESA-2026_1_1_0']:
            with self.assertRaises(ValueError):validate_url(url)
    def test_extracts_all_rows_and_document_links(self):
        page=parse_static_html(URL,HTML)
        self.assertEqual(len(page.entries),2)
        self.assertEqual(page.entries[0].rcs_number,'B123456')
        self.assertEqual(page.entries[0].company_name,'Alpha Exemple Sàrl')
        self.assertEqual(page.entries[0].documents[0].document_type,'PDF')
        self.assertEqual(page.entries[1].documents[0].document_type,'PUBLIC_DOCUMENT_LINK')

class ResaStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.NamedTemporaryFile(suffix='.db',delete=False);self.tmp.close()
        def connect():
            db=sqlite3.connect(self.tmp.name);db.row_factory=sqlite3.Row;return db
        self.connect=connect
        with connect() as db:
            db.executescript(database.SCHEMA)
            db.execute("INSERT INTO organizations VALUES(?,?,?,?)",('org_test','Test','test','2026-01-01T00:00:00Z'))
        self.connector=LBRResaConnector(connect,enabled=True)
    def tearDown(self):Path(self.tmp.name).unlink(missing_ok=True)
    def test_idempotent_storage_and_change_status(self):
        page=parse_static_html(URL,HTML)
        self.connector._insert_run('run1','org_test',URL,'2026-01-01T00:00:00Z','ALLOWED')
        first=self.connector._store('org_test','run1',page)
        self.assertEqual(first['rows_detected'],2);self.assertEqual(first['documents_detected'],2);self.assertEqual(first['changes']['NEW'],2)
        self.connector._insert_run('run2','org_test',URL,'2026-01-02T00:00:00Z','ALLOWED')
        second=self.connector._store('org_test','run2',page)
        self.assertEqual(second['changes']['UNCHANGED'],2)
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM resa_entries').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT count(*) FROM resa_documents').fetchone()[0],2)

if __name__=='__main__':unittest.main()
