import unittest,hashlib
import test_finance as fixtures
from sac_forms import SAC_FORM_CATEGORIES
class SacFormsTest(unittest.TestCase):
 setUp=fixtures.FinanceTest.setUp
 tearDown=fixtures.FinanceTest.tearDown
 login=fixtures.FinanceTest.login
 def test_catalog_and_all_downloads(self):
  self.assertEqual(len(SAC_FORM_CATEGORIES),6);items=[i for g in SAC_FORM_CATEGORIES for i in g['items']];self.assertEqual(len(items),62)
  count=0
  for item in items:
   for file in item['local_files']:
    response=self.c.get('/api/forms/sac/'+item['id']+'/'+file['format'].lower());self.assertEqual(response.status_code,200)
    self.assertEqual(hashlib.sha256(response.data).hexdigest(),file['sha256']);self.assertEqual(len(response.data),file['size']);self.assertIn('attachment',response.headers['Content-Disposition']);response.close();count+=1
  self.assertEqual(count,61);self.assertEqual(sum(not i['local_files'] for i in items),1)
 def test_forms_page_and_access(self):
  page=self.c.get('/?view=forms');self.assertEqual(page.status_code,200);text=page.get_data(as_text=True)
  self.assertIn('id="sac-forms"',text);self.assertIn('sac-forms-search',text);self.assertIn('sac-forms-category',text);self.assertIn('id="general-forms"',text);self.assertIn('id="english-forms"',text)
  self.assertEqual(text.count('class="sac-form-item"'),62)
  self.assertEqual(text.count('class="sac-form-category p-3"'),6)
  for category in SAC_FORM_CATEGORIES: self.assertIn(category['title'],text)
  self.assertEqual(self.c.get('/api/forms/sac/invalid/pdf').status_code,404)
  item=next(i for g in SAC_FORM_CATEGORIES for i in g['items'] if i['local_files'])
  with self.c.session_transaction() as s:s.clear()
  self.assertEqual(self.c.get('/api/forms/sac/'+item['id']+'/pdf').status_code,401)
