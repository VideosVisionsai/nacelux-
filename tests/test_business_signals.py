import sqlite3,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
import database
from business_signals import BusinessSignalEngine
class SignalGuardrailTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.NamedTemporaryFile(suffix='.db',delete=False);self.tmp.close()
  def connect():db=sqlite3.connect(self.tmp.name);db.row_factory=sqlite3.Row;return db
  self.connect=connect
  with connect() as db:db.executescript(database.SCHEMA);db.execute("INSERT INTO organizations VALUES(?,?,?,?)",('o','O','o','2026-01-01'));db.execute("INSERT INTO companies(id,organization_id,company_name,website_status,google_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",('c','o','Old Company','NOT_FOUND','NOT_FOUND','2020-01-01','2020-01-01'))
 def tearDown(self):Path(self.tmp.name).unlink(missing_ok=True)
 def test_company_status_without_completed_check_creates_no_negative_signal(self):
  result=BusinessSignalEngine(self.connect).refresh('o','c');types={x['signal_type'] for x in result['signals']};self.assertNotIn('NO_WEBSITE',types);self.assertNotIn('NO_GOOGLE_BUSINESS',types)
 def test_signal_is_deactivated_when_evidence_changes(self):
  with self.connect() as db:db.execute("INSERT INTO digital_checks(id,organization_id,company_id,channel,status,confidence,checked_at,details) VALUES(?,?,?,?,?,?,?,?)",('d','o','c','Website','NOT_FOUND',1,'2026-01-01','{}'))
  engine=BusinessSignalEngine(self.connect);self.assertIn('NO_WEBSITE',{x['signal_type'] for x in engine.refresh('o','c')['signals']})
  with self.connect() as db:db.execute("UPDATE digital_checks SET status='FOUND' WHERE id='d'")
  result=engine.refresh('o','c');self.assertEqual(result['deactivated'],1)
  with self.connect() as db:self.assertEqual(db.execute("SELECT status FROM business_signals WHERE signal_type='NO_WEBSITE'").fetchone()[0],'INACTIVE')
if __name__=='__main__':unittest.main()
