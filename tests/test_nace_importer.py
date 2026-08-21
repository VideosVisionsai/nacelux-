import sys,unittest,zipfile
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from nace_importer import parse_rdf,format_raw_code,EXPECTED

class OfficialNaceImporterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        files=list((ROOT/'data/nace-imports').glob('NACE_Rev_2.1_*.zip'))
        if not files:raise unittest.SkipTest('Official Eurostat artifact not downloaded')
        cls.archive=files[0]
    def test_official_distribution_has_complete_hierarchy(self):
        with zipfile.ZipFile(self.archive) as z:parsed=parse_rdf(z.open('NACE_Rev_2.1.rdf'),('fr','de','en'))
        counts=Counter(x['level'] for x in parsed['items']);self.assertEqual(dict(counts),EXPECTED)
        self.assertEqual(len(parsed['labels']),1047*3)
        self.assertGreater(len(parsed['notes']),1000)
        self.assertGreater(len(parsed['correspondences']),1000)
        self.assertTrue(all(x['source_code'] and x['target_code'] for x in parsed['correspondences']))
    def test_rev2_raw_codes_are_formatted(self):
        self.assertEqual(format_raw_code('0111'),'01.11');self.assertEqual(format_raw_code('011'),'01.1');self.assertEqual(format_raw_code('01'),'01')

if __name__=='__main__':unittest.main()
