import os,sqlite3,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
import database
from document_storage import ResaPdfStoragePipeline,validate_document_url

class PdfStorageTests(unittest.TestCase):
    def setUp(self):
        self.dbfile=tempfile.NamedTemporaryFile(suffix='.db',delete=False);self.dbfile.close();self.storage=tempfile.TemporaryDirectory()
        os.environ['DOCUMENT_STORAGE_PROVIDER']='local';os.environ['LOCAL_DOCUMENT_STORAGE_DIR']=self.storage.name
        def connect():
            db=sqlite3.connect(self.dbfile.name);db.row_factory=sqlite3.Row;return db
        self.connect=connect
        with connect() as db:
            db.executescript(database.SCHEMA);db.execute("INSERT INTO organizations VALUES(?,?,?,?)",('org_test','Test','test','2026-01-01T00:00:00Z'))
            db.execute("INSERT INTO resa_journals(id,organization_id,journal_key,source_url,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?)",('j1','org_test','RESA-2026_1_1_0','https://www.lbr.lu/mjrcs-web-front/publication-journal/RESA-2026_1_1_0','2026-01-01','2026-01-01'))
            for i in (1,2):db.execute("INSERT INTO resa_documents(id,organization_id,journal_id,document_url,canonical_url,source_url,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?)",(f'd{i}','org_test','j1',f'https://www.lbr.lu/public/doc{i}.pdf',f'https://www.lbr.lu/public/doc{i}.pdf','https://www.lbr.lu/','2026-01-01','2026-01-01'))
        self.pdf=tempfile.NamedTemporaryFile(suffix='.pdf',delete=False);self.pdf.write(b'%PDF-1.4\n% test fixture\n%%EOF');self.pdf.close()
        self.pipe=ResaPdfStoragePipeline(connect);self.pipe._download=lambda url:(self._copy(),{'checksum':'a'*64,'size_bytes':29,'http_status':200,'mime_type':'application/pdf'})
    def _copy(self):
        f=tempfile.NamedTemporaryFile(suffix='.part',delete=False);f.write(Path(self.pdf.name).read_bytes());f.close();return f.name
    def tearDown(self):Path(self.dbfile.name).unlink(missing_ok=True);Path(self.pdf.name).unlink(missing_ok=True);self.storage.cleanup()
    def test_rejects_unapproved_hosts(self):
        with self.assertRaises(ValueError):validate_document_url('https://evil.example/file.pdf')
    def test_store_and_checksum_deduplicate(self):
        first=self.pipe.store_document('org_test','d1');second=self.pipe.store_document('org_test','d2')
        self.assertEqual(first['status'],'STORED');self.assertEqual(second['status'],'DUPLICATE')
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM storage_objects').fetchone()[0],1)
            self.assertEqual(db.execute("SELECT download_status FROM resa_documents WHERE id='d2'").fetchone()[0],'DUPLICATE')

if __name__=='__main__':unittest.main()
