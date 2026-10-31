import unittest
import test_finance as fixtures
from app import db,User,Organization,UserOrganization
class MembershipTest(unittest.TestCase):
 setUp=fixtures.FinanceTest.setUp
 tearDown=fixtures.FinanceTest.tearDown
 login=fixtures.FinanceTest.login
 post=fixtures.FinanceTest.post
 data=fixtures.FinanceTest.data
 def set_members(self,ids):
  uid=User.query.filter_by(name='owner').one().id
  return self.c.put(f'/api/admin/users/{uid}/organizations',json={'organization_ids':ids},headers={'X-CSRF-Token':'test'})
 def switch(self,oid,client=None):return (client or self.c).post('/workspace/organization',data={'organization_id':oid,'csrf_token':'test'})
 def test_switch_permissions_primary_and_revocation(self):
  owner=User.query.filter_by(name='owner').one();self.assertEqual(self.set_members([self.a,self.b]).status_code,403)
  self.login('admin');self.assertEqual(self.set_members([self.a,self.b]).status_code,200)
  row=next(u for u in self.c.get('/api/admin/users').json if u['id']==owner.id);self.assertEqual(set(row['organization_ids']),{self.a,self.b})
  self.login('owner');self.assertEqual(self.switch(self.b).status_code,302)
  page=self.c.get('/finance').get_data(as_text=True);self.assertIn(f'data-organization-id="{self.b}"',page)
  response=self.post('/api/finance/projects',self.data(oid=self.b));self.assertEqual(response.status_code,201,response.json)
  self.assertEqual(self.post('/api/finance/projects',self.data(oid=self.a)).status_code,403)
  self.assertEqual(db.session.get(User,owner.id).organization_id,self.a)
  self.assertIn('สลับองค์กรกิจกรรม',page)
  self.assertEqual(self.switch(99999).status_code,403)
  uid=owner.id;other_session=self.c
  admin=self.app.test_client()
  with admin.session_transaction() as session:session['user_id']=User.query.filter_by(name='admin').one().id;session['csrf_token']='test'
  self.assertEqual(admin.put(f'/api/admin/users/{uid}/organizations',json={'organization_ids':[self.a]},headers={'X-CSRF-Token':'test'}).status_code,200)
  page=self.c.get('/finance').get_data(as_text=True);self.assertIn(f'data-organization-id="{self.a}"',page)
  self.assertEqual(self.switch(self.b).status_code,403)
 def test_quota_invalid_and_csrf(self):
  self.login('admin');organization=db.session.get(Organization,self.b);organization.quota=1;db.session.commit()
  self.assertEqual(self.set_members([self.a,self.b]).status_code,400)
  self.assertEqual(self.set_members([self.b]).status_code,400)
  self.assertEqual(self.set_members([self.a,999999]).status_code,400)
  self.assertEqual(self.c.post('/workspace/organization',data={'organization_id':self.a}).status_code,400)
