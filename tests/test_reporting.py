import unittest,json
from datetime import datetime,date
import test_finance as fixtures
from app import db,User,Organization,Document,DocumentTracking,DocumentAuditLog,RoomBooking
class ReportingTest(unittest.TestCase):
 setUp=fixtures.FinanceTest.setUp
 tearDown=fixtures.FinanceTest.tearDown
 login=fixtures.FinanceTest.login
 def seed_documents(self):
  owner=User.query.filter_by(name='owner').one();other=User.query.filter_by(name='other').one();a=db.session.get(Organization,self.a).name;b=db.session.get(Organization,self.b).name
  doc=Document(number='ทดสอบ1',direction='sent',title='เอกสารทดสอบ',sender=a,recipient=b,owner_org_id=self.a,current_org_id=self.b,created_by=owner.id,status='pending',created_at=datetime(2026,2,1));db.session.add(doc);db.session.flush()
  db.session.add(DocumentTracking(document_id=doc.id,actor_id=owner.id,action='send',from_org=a,to_org=b,status='pending',created_at=datetime(2026,2,1,9)))
  db.session.add(DocumentAuditLog(document_id=doc.id,actor_id=owner.id,event='assign',version='v1',changes=json.dumps({'assigned_to_id':owner.id,'assigned_to':'ผู้รับงานเดิม'}),created_at=datetime(2026,2,2)))
  db.session.add(DocumentAuditLog(document_id=doc.id,actor_id=owner.id,event='assign',version='v1',changes=json.dumps({'assigned_to_id':owner.id,'assigned_to':'ผู้รับงานเดิม'}),created_at=datetime(2026,2,3)))
  db.session.commit()
 def test_document_scope_and_daily_monthly_yearly(self):
  self.seed_documents();url='/api/reports/documents?start=2026-01-01&end=2026-12-31'
  response=self.c.get(url);self.assertEqual(response.status_code,200);data=response.json
  self.assertEqual(data['totals']['sent'],1);self.assertEqual(data['totals']['incoming'],0);self.assertEqual(data['totals']['assignments'],2);self.assertEqual(data['assignees'][0]['count'],2)
  self.assertEqual(self.c.get(url+'&organization_id='+str(self.b)).status_code,403)
  self.login('other');data=self.c.get(url).json;self.assertEqual(data['totals']['incoming'],1);self.assertEqual(data['totals']['sent'],0);self.assertEqual(data['assignees'],[])
  self.login('admin');self.assertEqual(self.c.get(url).json['totals']['sent'],1)
  for grain,size in [('day',365),('month',12),('year',1)]:self.assertEqual(len(self.c.get(url+'&grain='+grain).json['series']),size)
  self.assertEqual(self.c.get('/reports/documents').status_code,200)
  self.assertEqual(self.c.get(url+'&grain=bad').status_code,400)
 def test_rooms_admin_only_clips_dates_and_peak(self):
  owner=User.query.filter_by(name='owner').one()
  for status,start,end in [('approved',date(2026,1,31),date(2026,2,2)),('pending',date(2026,2,3),date(2026,2,3))]:
   db.session.add(RoomBooking(requester_id=owner.id,requester_name='ผู้ขอจอง',organization_id=self.a,email='owner@kkumail.com',phone='0891234567',activity='กิจกรรม',start_date=start,end_date=end,start_time='09:00',end_time='11:00',status=status))
  db.session.commit();url='/api/reports/rooms?start=2026-02-01&end=2026-02-28&grain=month'
  self.assertEqual(self.c.get(url).status_code,403);self.assertEqual(self.c.get('/reports/rooms').status_code,403)
  self.login('admin');response=self.c.get(url);self.assertEqual(response.status_code,200);data=response.json
  self.assertEqual(data['totals']['requests'],2);self.assertEqual(data['totals']['approved_hours'],4);self.assertEqual(data['peak_months'],['2026-02']);self.assertEqual(data['people'][0]['hours'],4);self.assertEqual(data['series'][0]['approved_days'],2)
  self.assertNotIn('email',data['bookings'][0]);self.assertEqual(self.c.get('/reports/rooms').status_code,200)
  self.assertEqual(self.c.get(url+'&organization_id='+str(self.b)).json['totals']['requests'],0)
 def test_empty_and_anonymous(self):
  self.assertEqual(self.c.get('/api/reports/documents').json['totals']['sent'],0)
  self.login('admin');self.assertEqual(self.c.get('/api/reports/rooms').json['peak_months'],[])
  with self.c.session_transaction() as session:session.clear()
  self.assertEqual(self.c.get('/reports/documents').status_code,302)
  self.assertEqual(self.c.get('/api/reports/documents').status_code,401)
