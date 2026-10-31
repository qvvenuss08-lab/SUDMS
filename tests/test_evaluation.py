import unittest,json
import test_finance as fixtures
from evaluation import codes
class EvaluationTest(unittest.TestCase):
 setUp=fixtures.FinanceTest.setUp
 tearDown=fixtures.FinanceTest.tearDown
 login=fixtures.FinanceTest.login
 post=fixtures.FinanceTest.post
 data=fixtures.FinanceTest.data
 def test_parser(self):
  self.assertEqual(codes('OKR8, OKR 9 / 10;72,77','okr'),{8,9,10,72,77})
  self.assertEqual(codes('E1, gm2, Go 3;S5 / go3','eggs'),{'E1','Gm2','Go3','S5'})
  self.assertEqual(codes('SDGs 3, SDG17','sdgs'),{3,17})
 def test_aggregate_dedup_category_nonbudget_and_missing(self):
  values=self.data(False);values.update(budget_category='กีฬา',activities=[{'title':'หนึ่ง','okr':'OKR8, OKR10','sdgs':'3,17','eggs_core':'Go2','eggs_sub':'Go2, E1'},{'title':'สอง','okr':'OKR8','sdgs':'3','eggs_core':'Go2'}])
  self.assertEqual(self.post('/api/finance/projects',values).status_code,201)
  values=self.data(False);values.update(budget_category='ทั่วไป',activities=[]);self.assertEqual(self.post('/api/finance/projects',values).status_code,201)
  values=self.data();values.update(fiscal_year=2570);self.assertEqual(self.post('/api/finance/projects',values).status_code,201)
  response=self.c.get('/api/evaluation/summary?year=2569&round=1');self.assertEqual(response.status_code,200);overall=response.json['overall']
  self.assertEqual(overall['total_projects'],2);self.assertEqual(overall['total_activities'],2);self.assertEqual(overall['no_budget_projects'],2)
  okr={r['code']:r for r in overall['charts']['okr']};self.assertEqual(okr['OKR8']['projects'],1);self.assertEqual(okr['OKR8']['percent'],50)
  self.assertEqual(overall['missing']['eggs'],1)
  sport=next(c for c in response.json['categories'] if c['category']=='กีฬา');self.assertEqual(sport['charts']['eggs'][2]['projects'],1)
  self.assertEqual(self.c.get('/api/evaluation/summary?year=2569&round=2').json['overall']['total_projects'],0)
  self.assertEqual(self.c.get('/api/evaluation/summary?year=invalid').status_code,400)
 def test_authenticated_documents_and_page(self):
  self.assertEqual(self.c.get('/evaluation').status_code,200)
  for key in ['eggs','okr']:
   response=self.c.get('/evaluation/documents/'+key);self.assertEqual(response.status_code,200);self.assertEqual(response.mimetype,'application/pdf');self.assertTrue(response.data.startswith(b'%PDF'));self.assertIn('attachment',response.headers['Content-Disposition']);response.close()
  self.assertEqual(self.c.get('/evaluation/documents/invalid').status_code,404)
  with self.c.session_transaction() as session:session.clear()
  self.assertEqual(self.c.get('/evaluation').status_code,302)
  self.assertNotEqual(self.c.get('/evaluation/documents/eggs').status_code,200)
