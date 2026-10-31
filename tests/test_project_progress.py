import unittest,json
import test_finance as fixtures
from app import db,FinanceProject,FinanceAudit
class ProgressTest(unittest.TestCase):
 setUp=fixtures.FinanceTest.setUp
 tearDown=fixtures.FinanceTest.tearDown
 login=fixtures.FinanceTest.login
 post=fixtures.FinanceTest.post
 data=fixtures.FinanceTest.data
 def test_progress_and_permissions(self):
  pid=self.post('/api/finance/projects',self.data(False)).json['id'];url=f'/api/finance/projects/{pid}/progress'
  def update(data):return self.c.patch(url,json=data,headers={'X-CSRF-Token':'test'})
  self.assertEqual(update({'report_progress':'awaiting_report'}).status_code,400)
  row=db.session.get(FinanceProject,pid);row.status='approved';db.session.commit()
  for payment in ['awaiting_disbursement','disbursed']:
   for report in ['awaiting_report','report_submitted']:
    response=update(dict(disbursement_progress=payment,report_progress=report));self.assertEqual(response.status_code,200,response.json);self.assertEqual(response.json['report_progress'],report);self.assertEqual(response.json['status'],'approved');self.assertEqual(response.json['actual'],'0.00')
  self.assertEqual(update({'report_progress':'invalid'}).status_code,400)
  self.assertEqual(update({'status':'completed'}).status_code,400)
  self.login('other');self.assertEqual(update({'report_progress':'awaiting_report'}).status_code,403)
  self.login('owner');row=db.session.get(FinanceProject,pid);row.status='completed';db.session.commit()
  self.assertEqual(update({'report_progress':'report_submitted'}).status_code,200)
  self.assertEqual(FinanceAudit.query.filter_by(project_id=pid,action='update_progress').count(),5)
  self.assertEqual(self.c.patch(url,json={'report_progress':'awaiting_report'}).status_code,400)
