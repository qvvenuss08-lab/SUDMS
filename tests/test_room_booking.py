import unittest,tempfile,io,sys
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch,MagicMock
sys.path.insert(0,r'C:\คอมปี 2\SUDMS')
from app import create_app,db,User,Organization,RoomBooking,now
from werkzeug.security import generate_password_hash
from room_booking import ROOM_NAME
class BookingTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.app=create_app({'TESTING':True,'SECRET_KEY':'test','SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(Path(self.tmp.name)/'db.sqlite'),'UPLOAD_FOLDER':str(Path(self.tmp.name)/'uploads')});self.ctx=self.app.app_context();self.ctx.push()
  oid=Organization.query.first().id
  for name,role in [('requester','user'),('other','user'),('admin','admin')]:db.session.add(User(name=name,email=name+'@kkumail.com',organization_id=oid,role=role,status='approved',password_hash=generate_password_hash('Password123!')))
  db.session.commit();self.c=self.app.test_client();self.login('requester');self.day=now().date()+timedelta(days=30)
  self.mock=patch('meeting_service.load_month',return_value={'events':[],'rooms':[],'failed_days':[]});self.source=self.mock.start()
 def tearDown(self):self.mock.stop();db.session.remove();db.engine.dispose();self.ctx.pop();self.tmp.cleanup()
 def login(self,name):
  uid=User.query.filter_by(name=name).one().id
  with self.c.session_transaction() as s:s.clear();s['user_id']=uid;s['csrf_token']='test'
 def payload(self,days=1):return dict(requester_name='ผู้ทดสอบ',activity='ทดสอบใช้ห้อง',email='requester@kkumail.com',phone='0812345678',start_date=str(self.day),end_date=str(self.day+timedelta(days=days-1)),start_time='09:00',end_time='10:00')
 def create(self,days=1,memo=False):
  data=self.payload(days)
  if memo:data['memo']=(io.BytesIO(b'%PDF-1.4\n test'), 'request.pdf')
  return self.c.post('/api/room-bookings',data=data,headers={'X-CSRF-Token':'test'})
 def review(self,id,decision='approved'):return self.c.post(f'/api/room-bookings/{id}/review',json=dict(decision=decision),headers={'X-CSRF-Token':'test'})
 def test_pending_then_approved_calendar_email_retry(self):
  r=self.create();self.assertEqual(r.status_code,201,r.json);id=r.json['id'];self.assertEqual(r.json['status'],'pending')
  self.login('admin');self.app.config.update(SMTP_HOST='',SMTP_FROM='');r=self.review(id);self.assertEqual(r.status_code,200,r.json);self.assertEqual(r.json['email_status'],'failed')
  events=self.app.extensions['room_booking_calendar']({'events':[],'rooms':[]},self.day.strftime('%Y-%m'))['events'];self.assertEqual(len(events),1);self.assertEqual(events[0]['room'],ROOM_NAME)
  self.app.config.update(SMTP_HOST='smtp.test',SMTP_FROM='no-reply@test',SMTP_PORT='587',SMTP_USERNAME='',SMTP_SECURITY='starttls')
  with patch('room_booking.smtplib.SMTP') as smtp:
   r=self.c.post(f'/api/room-bookings/{id}/email-retry',json={},headers={'X-CSRF-Token':'test'});self.assertEqual(r.json['email_status'],'sent');smtp.return_value.__enter__.return_value.send_message.assert_called_once()
 def test_more_than_three_days_requires_valid_memo(self):
  self.assertEqual(self.create(4).status_code,400);r=self.create(4,True);self.assertEqual(r.status_code,201,r.json);id=r.json['id'];self.login('other');self.assertEqual(self.c.get(f'/api/room-bookings/{id}/memo').status_code,403);self.assertEqual(len(self.c.get('/api/room-bookings').json['bookings']),0)
 def test_overlapping_pending_can_only_approve_one(self):
  first=self.create().json['id'];second=self.create().json['id'];self.login('admin');self.app.config.update(SMTP_HOST='');self.assertEqual(self.review(first).status_code,200);self.assertEqual(self.review(second).status_code,409);self.login('requester');self.assertEqual(self.create().status_code,409)
 def test_permissions_and_csrf(self):
  id=self.create().json['id'];self.assertEqual(self.review(id).status_code,403);self.assertEqual(self.c.post('/api/room-bookings',data=self.payload()).status_code,400)
 def test_sources_fail_closed_and_event_overlap(self):
  self.source.return_value=dict(events=[],rooms=[],failed_days=[str(self.day)]);self.assertEqual(self.create().status_code,409)
  self.source.return_value=dict(events=[dict(date=str(self.day),room=ROOM_NAME,time='09:30 - 11:00',source='KKU')],rooms=[ROOM_NAME],failed_days=[]);self.assertEqual(self.create().status_code,409)
  self.source.return_value['events'][0]['time']='10:00 - 11:00';self.assertEqual(self.create().status_code,201)
 def test_validation_and_three_days_without_file(self):
  self.assertEqual(self.create(3).status_code,201)
  for changes in [dict(phone='123'),dict(email='test@gmail.com'),dict(end_time='08:00'),dict(organization_id='999999')]:
   data=self.payload();data.update(changes);r=self.c.post('/api/room-bookings',data=data,headers={'X-CSRF-Token':'test'});self.assertEqual(r.status_code,400,r.json)
 def test_room_page_slots_and_reject(self):
  page=self.c.get('/meeting-rooms');self.assertEqual(page.status_code,200);self.assertIn(b'room-booking-form',page.data)
  slots=self.c.get('/api/room-bookings/slots?date='+str(self.day));self.assertEqual(slots.status_code,200);self.assertTrue(slots.json['slots'][0]['available'])
  id=self.create().json['id'];self.login('admin');self.assertEqual(self.review(id,'rejected').json['status'],'rejected')
if __name__=='__main__':unittest.main()
