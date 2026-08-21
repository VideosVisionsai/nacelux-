import hashlib,os,sqlite3,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
import database
from pdf_extraction import PdfTextExtractionEngine,text_quality

class PdfExtractionTests(unittest.TestCase):
    def setUp(self):
        self.dbfile=tempfile.NamedTemporaryFile(suffix='.db',delete=False);self.dbfile.close();self.storage=tempfile.TemporaryDirectory();os.environ['LOCAL_DOCUMENT_STORAGE_DIR']=self.storage.name
        content=b'%PDF-1.4 fake test';checksum=hashlib.sha256(content).hexdigest();path=Path(self.storage.name)/'org/file.pdf';path.parent.mkdir();path.write_bytes(content)
        def connect():db=sqlite3.connect(self.dbfile.name);db.row_factory=sqlite3.Row;return db
        self.connect=connect
        with connect() as db:
            db.executescript(database.SCHEMA);db.execute("INSERT INTO organizations VALUES(?,?,?,?)",('org','Org','org','2026-01-01'))
            db.execute("INSERT INTO resa_journals(id,organization_id,journal_key,source_url,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?)",('j','org','RESA-2026_1_1_0','https://www.lbr.lu/','2026-01-01','2026-01-01'))
            db.execute("INSERT INTO storage_objects VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",('s','org','local','bucket','org/file.pdf',checksum,len(content),'application/pdf','file.pdf','https://www.lbr.lu/file.pdf',str(path),'2026-01-01','2026-01-01'))
            db.execute("INSERT INTO resa_documents(id,organization_id,journal_id,document_url,canonical_url,source_url,download_status,extraction_status,checksum,first_seen_at,last_seen_at,storage_object_id,storage_provider,storage_bucket,storage_key,mime_type,size_bytes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",('d','org','j','https://www.lbr.lu/file.pdf','https://www.lbr.lu/file.pdf','https://www.lbr.lu/','STORED','NOT_STARTED',checksum,'2026-01-01','2026-01-01','s','local','bucket','org/file.pdf','application/pdf',len(content)))
        self.engine=PdfTextExtractionEngine(connect)
    def tearDown(self):Path(self.dbfile.name).unlink(missing_ok=True);self.storage.cleanup()
    def test_native_text_then_selective_ocr(self):
        self.engine._native_pages=lambda path:[{'page_number':1,'text':'This is a native corporate publication. '*6},{'page_number':2,'text':''}]
        self.engine._ocr_page=lambda path,page:{'text':'Texte reconnu par OCR pour la deuxième page de la publication officielle. '*3,'confidence':.91}
        result=self.engine.extract_document('org','d')
        self.assertEqual(result['status'],'SUCCESS');self.assertEqual(result['method'],'MIXED');self.assertEqual(result['ocr_pages'],1)
        with self.connect() as db:
            rows=db.execute('SELECT extraction_method FROM document_page_extractions ORDER BY page_number').fetchall();self.assertEqual([r[0] for r in rows],['TEXT','OCR'])
            self.assertEqual(db.execute("SELECT extraction_status FROM resa_documents WHERE id='d'").fetchone()[0],'SUCCESS')
    def test_quality_rejects_empty_text(self):self.assertEqual(text_quality(''),0)

if __name__=='__main__':unittest.main()
