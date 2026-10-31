import unittest,json
from sqlalchemy import text
import test_finance as fixtures
from app import db,FinanceProject,FinanceExpense,FinanceAudit
class AdminActionsTest(fixtures.FinanceTest):
 def test_admin_edit_delete_every_stage(self):
  for status,stage in [('draft','not_submitted'),('submitted','submitted'),('rejected','submitted'),('approved','union_approved'),('approved','department_approved'),('approved','affairs_approved'),('completed','affairs_approved')]:
   self.login('owner');pid=self.create();self.post(f'/api/finance/projects/{pid}/expenses',self.expense())
   row=db.session.get(FinanceProject,pid);row.status=status;row.approval_stage=stage;db.session.commit()
   self.login('admin');data=self.c.get(f'/api/finance/projects/{pid}').json
   self.assertTrue(data['can_edit']);self.assertTrue(data['can_delete'])
   changed=self.data();changed['title']='แก้ไขโดยแอดมิน'
   response=self.c.patch(f'/api/finance/projects/{pid}',json=changed,headers={'X-CSRF-Token':'test'})
   self.assertEqual(response.status_code,200,response.json);self.assertEqual(response.json['status'],status)
   self.assertIn('finance-delete-project',self.c.get(f'/finance/projects/{pid}').get_data(as_text=True))
   self.assertEqual(self.c.delete(f'/api/finance/projects/{pid}',headers={'X-CSRF-Token':'test'}).status_code,200)
   self.assertEqual(self.c.get(f'/api/finance/projects/{pid}').status_code,404)
   self.assertEqual(FinanceExpense.query.filter_by(project_id=pid).count(),0)
   self.assertEqual(FinanceAudit.query.filter_by(project_id=pid).count(),0)
   saved=db.session.execute(text('SELECT snapshot FROM finance_deleted_project ORDER BY id DESC LIMIT 1')).scalar()
   self.assertEqual(json.loads(saved)['project']['title'],'แก้ไขโดยแอดมิน')
 def test_delete_requires_admin_and_csrf(self):
  pid=self.create()
  self.assertEqual(self.c.delete(f'/api/finance/projects/{pid}',headers={'X-CSRF-Token':'test'}).status_code,403)
  self.login('other');self.assertEqual(self.c.delete(f'/api/finance/projects/{pid}',headers={'X-CSRF-Token':'test'}).status_code,403)
  self.login('admin');self.assertEqual(self.c.delete(f'/api/finance/projects/{pid}').status_code,400)
  self.assertIsNotNone(db.session.get(FinanceProject,pid))
