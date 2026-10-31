import unittest,json
from app import FinanceAudit
import test_finance as fixtures
class ProjectDocumentNumberTest(unittest.TestCase):
 setUp=fixtures.FinanceTest.setUp
 tearDown=fixtures.FinanceTest.tearDown
 login=fixtures.FinanceTest.login
 post=fixtures.FinanceTest.post
 data=fixtures.FinanceTest.data
 def test_reference_persists_audit_and_permissions(self):
  data=self.data(False);data['approval_document_number']='อน.มข. 001/2570'
  response=self.post('/api/finance/projects',data);self.assertEqual(response.status_code,201,response.json);pid=response.json['id']
  self.assertEqual(self.c.get(f'/api/finance/projects/{pid}').json['approval_document_number'],data['approval_document_number'])
  self.assertEqual(self.post(f'/api/finance/projects/{pid}/submit',{}).status_code,200)
  self.login('admin');data['approval_document_number']='อน.มข. 002/2570'
  response=self.c.patch(f'/api/finance/projects/{pid}',json=data,headers={'X-CSRF-Token':'test'});self.assertEqual(response.status_code,200,response.json);self.assertEqual(response.json['status'],'submitted')
  audit=FinanceAudit.query.filter_by(project_id=pid,action='edit_project').one()
  self.assertEqual(json.loads(audit.changes)['after']['approval_document_number'],data['approval_document_number'])
  self.login('other');self.assertEqual(self.c.patch(f'/api/finance/projects/{pid}',json=data,headers={'X-CSRF-Token':'test'}).status_code,403)
  self.login('admin');data['approval_document_number']='x'*181
  self.assertEqual(self.c.patch(f'/api/finance/projects/{pid}',json=data,headers={'X-CSRF-Token':'test'}).status_code,400)
