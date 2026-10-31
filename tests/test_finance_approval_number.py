import unittest
import test_finance as fixtures
class ApprovalNumberTest(unittest.TestCase):
 setUp=fixtures.FinanceTest.setUp
 tearDown=fixtures.FinanceTest.tearDown
 login=fixtures.FinanceTest.login
 post=fixtures.FinanceTest.post
 data=fixtures.FinanceTest.data
 def test_separate_number_and_permissions(self):
  self.login('admin');data=self.data();data.update(approval_number='1',budget_category='ทั่วไป')
  first=self.post('/api/finance/projects',data);self.assertEqual(first.status_code,201,first.json)
  self.assertEqual(first.json['approval_number'],1)
  self.assertEqual(self.post('/api/finance/projects',data).status_code,400)
  data['budget_category']='กีฬา';self.assertEqual(self.post('/api/finance/projects',data).status_code,201)
  data['budget_round']=2;self.assertEqual(self.post('/api/finance/projects',data).status_code,201)
  self.login('owner');data['approval_number']=2
  self.assertEqual(self.c.patch('/api/finance/projects/'+str(first.json['id']),json=data,headers={'X-CSRF-Token':'test'}).status_code,403)
  self.login('admin')
  for value in [-1,0,'1.5',True]:
   data['approval_number']=value;self.assertEqual(self.post('/api/finance/projects',data).status_code,400)
