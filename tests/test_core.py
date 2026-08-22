import json, sqlite3, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from scoring import calculate

class OpportunityTests(unittest.TestCase):
    def test_unknown_values_do_not_earn_points(self):
        result=calculate({'creation_date':'2000-01-01','website_status':'UNKNOWN','digital_score':None,'seo_opportunity':None,'google_status':'UNKNOWN','decision_maker_status':'UNKNOWN','niche_attractiveness':0,'commercial_potential':0})
        self.assertEqual(result['score'],0)
        self.assertEqual(result['action'],'LOW_PRIORITY')

    def test_new_company_without_site_is_high_value(self):
        from datetime import date
        c={'creation_date':date.today().isoformat(),'website_status':'NOT_FOUND','digital_score':10,'seo_opportunity':90,'google_status':'NOT_FOUND','decision_maker_status':'FOUND','niche_attractiveness':95,'commercial_potential':90}
        result=calculate(c)
        self.assertGreaterEqual(result['score'],90)
        self.assertEqual(result['action'],'CREATE_WEBSITE')
        self.assertEqual(sum(x['points'] for x in result['factors']),result['score'])

    def test_weights_cap_score(self):
        c={'creation_date':'2026-08-20','website_status':'NOT_FOUND','seo_opportunity':100,'google_status':'NOT_FOUND','decision_maker_status':'FOUND','niche_attractiveness':100,'commercial_potential':100}
        self.assertLessEqual(calculate(c)['score'],100)

if __name__=='__main__': unittest.main()
