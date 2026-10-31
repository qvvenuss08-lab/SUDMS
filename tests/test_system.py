# ทดสอบพฤติกรรมสำคัญและสิทธิ์การเข้าถึงด้วยฐานข้อมูลชั่วคราว
import unittest, tempfile, io, zipfile
from pathlib import Path
from app import create_app, db, User, Organization, Document, DocumentTracking
from werkzeug.security import generate_password_hash

class SystemTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.app=create_app({'TESTING':True,'SECRET_KEY':'test','SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(Path(self.tmp.name)/'test.db'),'UPLOAD_FOLDER':str(Path(self.tmp.name)/'uploads')})
        self.ctx=self.app.app_context();self.ctx.push()
        self.orgs=Organization.query.order_by(Organization.id).all()
        self.a=self.orgs[0].id;self.b=self.orgs[1].id;self.c=self.orgs[2].id
        for name,oid,role in [('admin',self.a,'admin'),('one',self.a,'user'),('two',self.b,'user'),('other',self.c,'user')]:
            db.session.add(User(name=name,email=name+'@kkumail.com',student_id=f'68305039{len(db.session.new)}-3',organization_id=oid,role=role,status='approved',password_hash=generate_password_hash('Password123!')))
        db.session.commit();self.client=self.app.test_client();self.login('one')
    def tearDown(self):
        db.session.remove();db.engine.dispose();self.ctx.pop();self.tmp.cleanup()
    def login(self,name):
        user=User.query.filter_by(name=name).one()
        with self.client.session_transaction() as s: s.clear();s['user_id']=user.id;s['csrf_token']='test-csrf'
    def post(self,path,data): return self.client.post(path,json=data,headers={'X-CSRF-Token':'test-csrf'})
    def create(self,target=None):
        r=self.post('/api/documents/sent',{'title':'หนังสือทดสอบ','sender':'ต้นทาง','recipient_org_id':target or self.a})
        self.assertEqual(r.status_code,201,r.get_json());return r.json['id']
    def test_independent_number_series(self):
        # ทั้งห้าชุดเริ่มแยกกัน และคนในหน่วยงานเดียวกันใช้เลขต่อกัน
        categories=['general','order','regulation','rule','announcement']
        for category in categories:
            r=self.post('/api/numbers/sent/reserve',{'category':category})
            self.assertEqual(r.status_code,201,r.json)
            self.assertTrue(r.json['number'].split('/')[0].endswith('1'))
            doc=db.session.get(Document,r.json['document_id'])
            self.assertEqual(doc.category,category)
            r=self.client.patch('/api/documents/'+str(doc.id),json={'title':'ทดสอบร่าง','category':category,'send_details':{'document_type':category if category!='general' else 'memo','circular':False,'owner_name':'ผู้ทดสอบ','document_date':'2026-10-14'}},headers={'X-CSRF-Token':'test-csrf'})
            self.assertEqual(r.status_code,200,r.json)
        self.login('admin')
        r=self.post('/api/numbers/sent/reserve',{'category':'order'})
        self.assertEqual(r.status_code,201,r.json)
        self.assertTrue(r.json['number'].split('/')[0].endswith('2'))
        self.login('two')
        r=self.post('/api/numbers/sent/reserve',{'category':'order'})
        self.assertEqual(r.status_code,201,r.json)
        self.assertTrue(r.json['number'].split('/')[0].endswith('1'))
        self.assertEqual(self.post('/api/numbers/sent/reserve',{'category':'invalid'}).status_code,400)

    def test_legacy_zero_padding_and_origin_number_in_receive_detail(self):
        from app import now
        did=self.create(self.b);source=db.session.get(Document,did);year=str(now().year+543);code=db.session.get(Organization,self.a).code
        source.number=code+'ว.001/'+year;db.session.commit()
        self.assertEqual(source.display_number,code+'ว.1/'+year)
        self.login('two');response=self.post(f'/api/documents/{did}/receive-registration',{'salutation':'ผู้รับ','practice':'ดำเนินการ'})
        self.assertEqual(response.status_code,200,response.json)
        received=Document.query.filter_by(owner_org_id=self.b,direction='received').one();received.number=db.session.get(Organization,self.b).code+'รับ.010/'+year;db.session.commit()
        self.assertEqual(received.display_number,db.session.get(Organization,self.b).code+'10/'+year)
        self.assertEqual(received.to_dict()['send_details']['source_number'],code+'ว.1/'+year)
        page=self.client.get('/documents/'+str(received.id)).get_data(as_text=True)
        self.assertIn('เลขหนังสือส่งของหน่วยงานต้นทาง',page);self.assertIn(code+'ว.1/'+year,page);self.assertIn('เลขทะเบียนรับของหน่วยงาน',page)

    def test_received_separate_and_special_titles(self):
        year=str(__import__('datetime').datetime.now().year+543)
        code=db.session.get(Organization,self.a).code
        first=self.post('/api/numbers/sent/reserve',{}).json['number']
        received=self.post('/api/numbers/received/reserve',{}).json['number']
        self.assertEqual(first,code+'1/'+year)
        self.assertEqual(received,code+'รับ.1/'+year)
        circular=self.post('/api/numbers/sent/reserve',{'circular':True}).json['number']
        self.assertEqual(circular,code+'ว.2/'+year)
        owner=db.session.get(Organization,self.a).name
        for category,label in [('order','คำสั่ง'),('regulation','ระเบียบ'),('rule','ข้อบังคับ'),('announcement','ประกาศ')]:
            suffix=' ฉบับที่ ' if category=='announcement' else ' ที่ '
            name=owner+('มหาวิทยาลัยขอนแก่น' if category=='announcement' and owner=='องค์การนักศึกษา' else '')
            r=self.post('/api/documents/sent',{'title':'ทดสอบ','sender':owner,'category':category,'send_details':{'document_type':category,'document_date':'2026-10-14','owner_name':'เจ้าของเรื่อง'},'save_mode':'draft'})
            self.assertEqual(r.status_code,201,r.json)
            self.assertEqual(r.json['number'],label+name+suffix+'1/'+year)
            self.assertEqual(self.client.get('/documents/'+str(r.json['id'])+'?edit=1').status_code,200)
            bad=self.post('/api/documents/sent',{'title':'ทดสอบ','sender':owner,'category':category,'save_mode':'draft'})
            self.assertEqual(bad.status_code,400)

    def test_attachment_preview_and_special_detail(self):
        payload={'title':'คำสั่งทดสอบ','sender':'องค์การนักศึกษา','category':'order','save_mode':'draft','send_details':{'document_type':'order','owner_name':'ผู้ทดสอบ','document_date':'2026-10-14'}}
        created=self.post('/api/documents/sent',payload)
        self.assertEqual(created.status_code,201,created.json)
        did=created.json['id'];pdf=b'%PDF-1.4\n%%EOF'
        uploaded=self.client.post(f'/api/documents/{did}/attachments',data={'file':(io.BytesIO(pdf),'เอกสาร.pdf')},headers={'X-CSRF-Token':'test-csrf'})
        self.assertEqual(uploaded.status_code,201)
        aid=self.client.get(f'/api/documents/{did}/history').json['attachments'][0]['id']
        viewed=self.client.get(f'/api/attachments/{aid}/view')
        self.assertEqual(viewed.status_code,200);self.assertEqual(viewed.data,pdf)
        self.assertEqual(viewed.mimetype,'application/pdf')
        self.assertIn('inline',viewed.headers['Content-Disposition']);viewed.close()
        for url in [f'/documents/{did}',f'/documents/{did}?edit=1']:
            html=self.client.get(url).get_data(as_text=True)
            self.assertIn(f'/api/attachments/{aid}/view',html)
            self.assertIn(f'/api/attachments/{aid}/download',html)
        html=self.client.get(f'/documents/{did}').get_data(as_text=True)
        self.assertNotIn('id="detail-recipient"',html)
        self.login('other');self.assertEqual(self.client.get(f'/api/attachments/{aid}/view').status_code,404)
        self.login('one');self.assertEqual(self.client.get('/api/attachments/999999/view').status_code,404)

    def test_admin_manage_users(self):
        data={'name':'ผู้ใช้ใหม่','email':'added@kkumail.com','profile':{'phone':'0812345678'},'student_id':'683050399-3','faculty':'คณะศึกษาศาสตร์','organization_id':self.a,'role':'user'}
        self.assertEqual(self.post('/api/admin/users',data).status_code,403)
        self.login('admin');r=self.post('/api/admin/users',data);self.assertEqual(r.status_code,201,r.json)
        uid=r.json['id'];user=db.session.get(User,uid);self.assertFalse(user.password_initialized);self.assertEqual(user.status,'approved')
        self.assertEqual(self.post('/api/admin/users',data).status_code,400)
        r=self.client.patch(f'/api/admin/users/{uid}',json={'role':'admin','name':'แอดมินใหม่'},headers={'X-CSRF-Token':'test-csrf'})
        self.assertEqual(r.status_code,200,r.json);self.assertEqual(user.role,'admin')
        self.assertEqual(self.client.get('/admin').status_code,200)
        r=self.client.delete(f'/api/admin/users/{uid}',json={},headers={'X-CSRF-Token':'test-csrf'})
        self.assertEqual(r.status_code,200);self.assertEqual(user.status,'deleted')
        self.assertNotIn(uid,[u['id'] for u in self.client.get('/api/admin/users').json])
        aid=User.query.filter_by(name='admin').one().id
        self.assertEqual(self.client.delete(f'/api/admin/users/{aid}',json={},headers={'X-CSRF-Token':'test-csrf'}).status_code,400)
        self.assertEqual(self.client.patch(f'/api/admin/users/{aid}',json={'role':'user'},headers={'X-CSRF-Token':'test-csrf'}).status_code,400)
        with self.client.session_transaction() as session:session['user_id']=uid
        self.assertEqual(self.client.get('/api/admin/users').status_code,401)

    def test_delete_user_releases_identity_and_new_signup_waits_approval(self):
        from app import UserApprovalLog,DocumentTracking
        old=User.query.filter_by(name='one').one();uid=old.id;email=old.email;student=old.student_id;name=old.name;oid=old.organization_id
        did=self.create(self.b)
        history_count=DocumentTracking.query.filter_by(document_id=did).count()
        self.login('admin')
        response=self.client.delete(f'/api/admin/users/{uid}',json={},headers={'X-CSRF-Token':'test-csrf'})
        self.assertEqual(response.status_code,200)
        old=db.session.get(User,uid);self.assertEqual(old.status,'deleted');self.assertIsNone(old.student_id);self.assertNotEqual(old.email,email);self.assertIsNone(old.profile)
        self.assertEqual(db.session.get(Document,did).created_by,uid);self.assertEqual(DocumentTracking.query.filter_by(document_id=did).count(),history_count)
        import json
        log=UserApprovalLog.query.filter_by(user_id=uid,action='delete_user').one()
        snapshot=json.loads(log.changes)['before'];self.assertEqual(snapshot['email'],email);self.assertEqual(snapshot['student_id'],student);self.assertEqual(snapshot['name'],name)
        with self.client.session_transaction() as session:session['user_id']=uid
        self.assertEqual(self.client.get('/api/documents/all').status_code,401)
        signup=dict(email=email,student_id=student,name=name,faculty='คณะวิทยาศาสตร์',phone='0812345678',password='Password123!',organization_id=oid,csrf_token='test-csrf')
        response=self.client.post('/register',data=signup);self.assertIn('ส่งคำขอสมัครเรียบร้อย',response.get_data(as_text=True))
        new_user=User.query.filter_by(email=email).one();self.assertNotEqual(new_user.id,uid);self.assertEqual(new_user.status,'pending');self.assertEqual(new_user.role,'user');self.assertEqual(new_user.organization_id,oid)
        response=self.client.post('/login',data=dict(email=email,student_id=student,password='Password123!',csrf_token='test-csrf'));self.assertIn('ยังไม่ได้รับอนุมัติ',response.get_data(as_text=True))
        self.login('admin');response=self.post(f'/api/admin/users/{new_user.id}/approval',{'status':'approved','organization_id':oid});self.assertEqual(response.status_code,200,response.json)
        response=self.client.post('/login',data=dict(email=email,student_id=student,password='Password123!',csrf_token='test-csrf'));self.assertEqual(response.status_code,302)

    def test_deleted_user_cannot_be_reactivated_as_old_account(self):
        old=User.query.filter_by(name='one').one();uid=old.id
        self.login('admin');self.client.delete(f'/api/admin/users/{uid}',json={},headers={'X-CSRF-Token':'test-csrf'})
        self.assertEqual(self.post(f'/api/admin/users/{uid}/approval',{'status':'approved','organization_id':self.a}).status_code,404)
        self.assertEqual(self.client.patch(f'/api/admin/users/{uid}',json={'role':'admin'},headers={'X-CSRF-Token':'test-csrf'}).status_code,404)

    def test_cross_org_special_search_read_only(self):
        general=self.post('/api/documents/sent',{'title':'private memo','sender':'ต้นทาง','save_mode':'draft'}).json['id']
        published=[]
        for category in ['order','regulation','rule','announcement']:
            payload={'title':'public '+category,'sender':'ต้นทาง','category':category,'send_details':{'document_type':category,'owner_name':'ผู้ทดสอบ','document_date':'2026-10-14'}}
            r=self.post('/api/documents/sent',payload);self.assertEqual(r.status_code,201,r.json);published.append(r.json['id'])
        payload['save_mode']='draft';draft=self.post('/api/documents/sent',payload).json['id']
        self.login('other')
        found={d['id'] for d in self.client.get('/api/documents/all').json['items']}
        self.assertTrue(set(published)<=found);self.assertNotIn(general,found);self.assertNotIn(draft,found)
        for did in published:
            h=self.client.get(f'/api/documents/{did}/history');self.assertEqual(h.status_code,200);self.assertFalse(h.json['can_act'])
            self.assertEqual(self.client.patch(f'/api/documents/{did}',json={'title':'unauthorized'},headers={'X-CSRF-Token':'test-csrf'}).status_code,403)
        self.assertEqual(self.client.get(f'/api/documents/{draft}/history').status_code,404)

    def test_admin_delete_releases_tail_number(self):
        self.login('admin')
        first=self.create();second=self.create()
        old=db.session.get(Document,second).number
        self.assertEqual(self.post(f'/api/documents/{second}/trash',{}).status_code,200)
        self.assertEqual(db.session.get(Document,second).to_dict()['number'],old)
        replacement=self.create()
        self.assertEqual(db.session.get(Document,replacement).number,old)
        self.assertEqual(self.post(f'/api/documents/{second}/trash',{'restore':True}).status_code,200)
        self.assertNotEqual(db.session.get(Document,second).number,old)
        self.assertEqual(self.post(f'/api/documents/{replacement}/trash',{}).status_code,200)
        self.assertEqual(self.post(f'/api/documents/{second}/trash',{'restore':True}).status_code,200)
        self.assertEqual(self.post(f'/api/documents/{second}/trash',{}).status_code,200)
        self.assertEqual(self.post(f'/api/documents/{first}/trash',{}).status_code,200)
        new=self.create();self.assertTrue(db.session.get(Document,new).number.split('/')[0].endswith('1'))

    def test_receive_registration_personal_and_shared_files(self):
        from app import ReceivedRegistration,PersonalAssignment,Attachment
        r=self.post('/api/documents/sent',{'title':'incoming','sender':'ต้นทาง','recipient_org_id':self.b,'save_mode':'draft'});source=r.json['id'];source_number=db.session.get(Document,source).number
        pdf=b'%PDF-1.4\n%%EOF'
        upload=self.client.post(f'/api/documents/{source}/attachments',data={'file':(io.BytesIO(pdf),'incoming.pdf')},headers={'X-CSRF-Token':'test-csrf'})
        self.assertEqual(upload.status_code,201)
        self.assertEqual(self.post(f'/api/documents/{source}/action',{'action':'send'}).status_code,200)
        member=User(name='colleague',email='colleague@kkumail.com',organization_id=self.b,role='user',status='approved',password_hash='x');db.session.add(member);db.session.commit();mid=member.id
        outsider=User.query.filter_by(name='one').one().id
        self.login('two')
        self.assertEqual(self.post(f'/api/documents/{source}/receive-registration',{'assignee_id':outsider}).status_code,400)
        r=self.post(f'/api/documents/{source}/receive-registration',{'salutation':'หัวหน้าฝ่าย','practice':'ดำเนินการ','note':'ทดสอบ','assignee_id':mid})
        self.assertEqual(r.status_code,200,r.json);received=r.json['received_document_id']
        copy=db.session.get(Document,received);self.assertEqual(copy.direction,'received');self.assertTrue(copy.number.startswith(db.session.get(Organization,self.b).code+'รับ.'))
        self.assertEqual(db.session.get(Document,source).number,source_number)
        self.assertEqual(self.post(f'/api/documents/{source}/receive-registration',{}).status_code,400)
        self.assertNotIn(source,[d['id'] for d in self.client.get('/api/documents/all?inbox=1').json['items']])
        self.assertIn(received,[d['id'] for d in self.client.get('/api/documents/received').json['items']])
        self.assertEqual(self.client.get('/api/documents/all?workspace=personal').json['total'],0)
        self.login('colleague');self.assertIn(received,[d['id'] for d in self.client.get('/api/documents/all?workspace=personal').json['items']])
        history=self.client.get(f'/api/documents/{received}/history').json;self.assertEqual(len(history['attachments']),1)
        aid=history['attachments'][0]['id'];view=self.client.get(f'/api/attachments/{aid}/view');self.assertEqual(view.status_code,200);self.assertEqual(view.data,pdf);view.close()
        self.assertIn('incoming.pdf',self.client.get(f'/documents/{received}').get_data(as_text=True))
        self.login('other');self.assertEqual(self.client.get(f'/api/documents/{received}/history').status_code,404)
        self.assertEqual(self.post(f'/api/documents/{received}/assign',{'assignee_id':mid}).status_code,404)

    def test_add_organization_and_overview(self):
        data={'name':'หน่วยงานเพิ่มเติม','code':'ทด.'}
        self.assertEqual(self.post('/api/admin/organizations',data).status_code,403)
        self.login('admin');r=self.post('/api/admin/organizations',data);self.assertEqual(r.status_code,201,r.json);self.assertEqual(r.json['quota'],5)
        self.assertEqual(self.post('/api/admin/organizations',data).status_code,400)
        self.assertEqual(self.client.get('/admin/organizations').status_code,200)
        self.assertEqual(db.session.get(Organization,self.a).quota,21);self.assertEqual(db.session.get(Organization,self.b).quota,5)

    def test_edit_after_sending_and_tracking_filter(self):
        r=self.post('/api/documents/sent',{'title':'sent record','sender':'ต้นทาง','send_details':{'recipient_org_ids':[self.b,self.c]}})
        self.assertEqual(r.status_code,201,r.json);did=r.json['id'];number=r.json['number']
        self.assertEqual(self.client.get(f'/documents/{did}?edit=1').status_code,200)
        r=self.client.patch(f'/api/documents/{did}',json={'title':'แก้หลังส่ง','send_details':{'recipient_org_ids':[self.b,self.c],'note':'แก้ไขเพิ่มเติม'},'digital_only':True},headers={'X-CSRF-Token':'test-csrf'})
        self.assertEqual(r.status_code,200,r.json);self.assertEqual(r.json['number'],number)
        uploaded=self.client.post(f'/api/documents/{did}/attachments',data={'file':(io.BytesIO(b'%PDF-1.4\n%%EOF'),'new-version.pdf')},headers={'X-CSRF-Token':'test-csrf'})
        self.assertEqual(uploaded.status_code,201)
        name=db.session.get(Organization,self.b).name
        timeline=self.client.get(f'/api/documents/{did}/history?organization_id={self.b}').json['timeline']
        self.assertTrue(timeline);self.assertTrue(all(t['to_org']==name or t['action']!='send' and t['from_org']==name for t in timeline))
        self.login('two')
        self.assertEqual(self.client.get(f'/documents/{did}/edit').status_code,403)
        self.assertEqual(self.client.patch(f'/api/documents/{did}',json={'title':'ไม่อนุญาต'},headers={'X-CSRF-Token':'test-csrf'}).status_code,403)

    def test_meeting_read_only_and_sources(self):
        from unittest.mock import patch
        from meeting_service import BookingParser
        sample='<table><tbody><tr data-key="1"><td><a>ห้องประชุม A</a><br>ใช้งาน</td><td>09:00 - 10:00</td><td>ประชุมทดสอบ</td><td>5</td></tr></tbody></table>'
        parser=BookingParser();parser.feed(sample);self.assertEqual(parser.rows[0]['room'],'ห้องประชุม A')
        self.assertEqual(self.client.get('/meeting-rooms').status_code,200)
        fake={'events':[],'rooms':[],'failed_days':['2026-10-14'],'read_only':True}
        with patch('meeting_service.load_month',return_value=fake):
            result=self.client.get('/api/meeting-rooms?month=2026-10').json
            self.assertEqual(result['events'],fake['events']);self.assertEqual(result['failed_days'],fake['failed_days']);self.assertTrue(result['local_booking_enabled'])
        self.assertEqual(self.client.get('/api/meeting-rooms?month=wrong').status_code,400)
        self.assertEqual(self.post('/api/meeting-rooms',{}).status_code,405)

    def test_kku_email_and_phone_validation(self):
        data={'name':'เพิ่มใหม่','email':'valid@kkumail.com','phone':'0812345678','student_id':'683050388-3','faculty':'คณะศึกษาศาสตร์','password':'Password123!','organization_id':self.a,'csrf_token':'test-csrf'}
        for phone in ['', '081234567','08123456789','abcdefghij','1812345678']:
            invalid=data|{'phone':phone};r=self.client.post('/register',data=invalid)
            self.assertIsNone(User.query.filter_by(email=data['email']).first())
            self.assertIn('10 หลัก',r.get_data(as_text=True))
        invalid=data|{'email':'valid@gmail.com'};self.client.post('/register',data=invalid)
        self.assertIsNone(User.query.filter_by(email='valid@gmail.com').first())
        r=self.client.post('/register',data=data);self.assertEqual(r.status_code,200)
        import json
        self.assertEqual(json.loads(User.query.filter_by(email=data['email']).one().profile)['phone'],'0812345678')
        self.login('admin')
        create={'name':'เพิ่มโดยแอดมิน','email':'adminadded@kkumail.com','student_id':'683050377-3','faculty':'คณะศึกษาศาสตร์','organization_id':self.a,'profile':{'phone':'081234567'}}
        self.assertEqual(self.post('/api/admin/users',create).status_code,400)
        create['profile']['phone']='0812345678';r=self.post('/api/admin/users',create);self.assertEqual(r.status_code,201,r.json)
        uid=r.json['id']
        self.assertEqual(self.client.patch(f'/api/admin/users/{uid}',json={'email':'bad@gmail.com'},headers={'X-CSRF-Token':'test-csrf'}).status_code,400)
        self.assertEqual(self.client.patch(f'/api/admin/users/{uid}',json={'profile':{'phone':'123'}},headers={'X-CSRF-Token':'test-csrf'}).status_code,400)

    def test_sender_received_registry_stays_empty(self):
        source=self.create(self.b)
        self.assertEqual(self.client.get('/api/documents/received').json['total'],0)
        self.assertEqual(self.client.get('/api/documents/all?direction=received').json['total'],0)
        self.assertEqual(self.client.get('/api/dashboard').json['received'],0)
        self.assertEqual(self.post('/api/documents/received',{'title':'wrong form','sender':'ต้นทาง','recipient_org_id':self.b}).status_code,400)
        self.login('two')
        self.assertEqual(self.client.get('/api/documents/received').json['total'],0)
        r=self.post(f'/api/documents/{source}/receive-registration',{})
        self.assertEqual(r.status_code,200,r.json);received=r.json['received_document_id']
        self.assertEqual([d['id'] for d in self.client.get('/api/documents/received').json['items']],[received])
        self.assertEqual(self.client.get('/api/documents/sent').json['total'],0)
        self.login('one');self.assertEqual(self.client.get('/api/documents/received').json['total'],0)
        self.assertIn(source,[d['id'] for d in self.client.get('/api/documents/sent').json['items']])
        self.login('admin');self.assertEqual(self.client.get('/api/documents/received').json['total'],0)

    def test_manual_received_is_registered_not_inbox(self):
        r=self.post('/api/documents/received',{'title':'ลงรับเอง','sender':'หน่วยงานภายนอก','recipient_org_id':self.a})
        self.assertEqual(r.status_code,201,r.json);self.assertEqual(r.json['status'],'received')
        did=r.json['id'];self.assertIn(did,[d['id'] for d in self.client.get('/api/documents/received').json['items']])
        self.assertNotIn(did,[d['id'] for d in self.client.get('/api/documents/all?inbox=1').json['items']])
        sent=self.post('/api/documents/sent',{'title':'หนังสือส่งตนเอง','sender':'ต้นทาง','recipient_org_id':self.a}).json['id']
        self.assertNotIn(sent,[d['id'] for d in self.client.get('/api/documents/all?inbox=1').json['items']])
        self.assertEqual(self.post(f'/api/documents/{sent}/receive-registration',{}).status_code,400)

    def test_assignment_practice_and_note(self):
        from app import DocumentAuditLog
        did=self.create(self.b);member=User.query.filter_by(name='admin').one().id
        r=self.post(f'/api/documents/{did}/assign',{'assignee_id':member,'practice':'ตรวจสอบและดำเนินการ','note':'ส่งผลภายในวันศุกร์'})
        self.assertEqual(r.status_code,200,r.json)
        history=self.client.get(f'/api/documents/{did}/history').json
        self.assertEqual(history['assignments'][0]['practice'],'ตรวจสอบและดำเนินการ')
        self.assertEqual(history['assignments'][0]['note'],'ส่งผลภายในวันศุกร์')
        self.assertEqual(self.post(f'/api/documents/{did}/assign',{'assignee_id':member,'practice':'แก้คำสั่ง','note':''}).status_code,200)
        self.assertEqual(DocumentAuditLog.query.filter_by(document_id=did,event='assign').count(),2)
        self.assertEqual(self.client.get(f'/api/documents/{did}/history').json['assignments'][0]['practice'],'แก้คำสั่ง')
        self.assertEqual(self.post(f'/api/documents/{did}/assign',{'assignee_id':member,'practice':['invalid']}).status_code,400)
        html=self.client.get(f'/documents/{did}').get_data(as_text=True)
        self.assertIn('name="practice"',html);self.assertIn('name="note"',html)
        self.login('other');self.assertEqual(self.client.get(f'/api/documents/{did}/history').status_code,404)

    def test_personal_assignment_requires_acceptance(self):
        from app import PersonalAssignment
        did=self.create(self.b);uid=User.query.filter_by(name='admin').one().id
        self.assertEqual(self.post(f'/api/documents/{did}/assign',{'assignee_id':uid,'practice':'ดำเนินการ'}).status_code,200)
        self.assertEqual(self.post(f'/api/documents/{did}/personal-receive',{}).status_code,403)
        original=db.session.get(Document,did).to_dict()
        self.login('admin')
        inbox=self.client.get('/api/documents/all?workspace=personal&inbox=1').json
        self.assertEqual([d['id'] for d in inbox['items']],[did])
        self.assertEqual(self.client.get('/api/documents/received?workspace=personal').json['total'],0)
        self.assertEqual(self.client.get('/api/dashboard?workspace=personal').json['pending'],1)
        self.assertEqual(self.post(f'/api/documents/{did}/personal-receive',{'note':'รับทราบ'}).status_code,200)
        self.assertEqual(self.client.get('/api/documents/all?workspace=personal&inbox=1').json['total'],0)
        received=self.client.get('/api/documents/received?workspace=personal').json
        self.assertEqual([d['id'] for d in received['items']],[did]);self.assertEqual(received['items'][0]['status'],'received')
        self.assertEqual(db.session.get(Document,did).number,original['number'])
        self.assertEqual(db.session.get(Document,did).status,original['status'])
        self.assertEqual(self.post(f'/api/documents/{did}/personal-receive',{}).status_code,400)
        self.login('one');self.post(f'/api/documents/{did}/assign',{'assignee_id':uid})
        self.login('admin');self.assertEqual(self.client.get('/api/documents/received?workspace=personal').json['total'],0)
        self.assertEqual(self.client.get('/api/documents/all?workspace=personal&inbox=1').json['total'],1)

    def test_access_and_forward(self):
        id=self.create(self.b)
        self.assertEqual(self.post(f'/api/documents/{id}/action',{'action':'receive'}).status_code,403)
        self.login('other');self.assertEqual(self.client.get(f'/api/documents/{id}/history').status_code,404)
        self.login('two');self.assertEqual(self.post(f'/api/documents/{id}/action',{'action':'receive'}).status_code,200)
        self.assertEqual(self.post(f'/api/documents/{id}/action',{'action':'forward','recipient_org_id':self.c,'note':'ดำเนินการต่อ'}).status_code,200)
        self.assertEqual(self.post(f'/api/documents/{id}/action',{'action':'complete'}).status_code,403)
        self.login('other');self.assertEqual(self.post(f'/api/documents/{id}/action',{'action':'endorse','note':'เห็นชอบ'}).status_code,200)
        h=self.client.get(f'/api/documents/{id}/history').json;self.assertEqual(len(h['timeline']),5);self.assertEqual(len(h['audit']),5)
    def test_quota_and_admin_only(self):
        db.session.add_all([User(name='pending1',email='p1@test',password_hash='x',organization_id=self.b),User(name='pending2',email='p2@test',password_hash='x',organization_id=self.b)])
        db.session.commit();ids=[u.id for u in User.query.filter(User.name.like('pending%')).all()]
        self.assertEqual(self.client.get('/api/admin/users').status_code,403)
        self.login('admin')
        self.assertEqual(self.post(f'/api/admin/users/{ids[0]}/approval',{'status':'approved','organization_id':self.b}).status_code,200)
        db.session.add_all([User(name='quota'+str(i),email='quota'+str(i)+'@kkumail.com',organization_id=self.b,status='approved',password_hash='x') for i in range(3)]);db.session.commit()
        self.assertEqual(self.post(f'/api/admin/users/{ids[1]}/approval',{'status':'approved','organization_id':self.b}).status_code,400)
        self.assertEqual(Organization.query.filter_by(id=self.a).one().quota,21)
        self.assertEqual(len(self.orgs),54)
    def test_reservations_trash_csrf_and_validation(self):
        r=self.post('/api/numbers/received/reserve',{});n=r.json['number']
        payload={'title':'รับทดสอบ','sender':'ต้นทาง','recipient_org_id':self.a,'reservation_number':n}
        doc=self.post('/api/documents/received',payload);self.assertEqual(doc.status_code,201);self.assertEqual(doc.json['number'],n.replace('รับ.',''))
        self.assertEqual(self.post('/api/documents/received',payload).status_code,400)
        id=doc.json['id'];self.assertEqual(self.client.post(f'/api/documents/{id}/trash',json={}).status_code,400)
        self.assertEqual(self.post(f'/api/documents/{id}/trash',{}).status_code,200)
        self.assertEqual(self.client.get('/api/documents/all').json['total'],0)
        self.assertEqual(self.client.get('/api/documents/all?trash=1').json['total'],1)
        self.assertEqual(self.post(f'/api/documents/{id}/trash',{'restore':True}).status_code,200)
        self.assertEqual(self.client.get('/api/documents/all?from=bad').status_code,400)
    def test_versions_files_and_exports(self):
        id=self.create()
        for version in ['v1.0','v1.1']:
            r=self.client.post(f'/api/documents/{id}/attachments',data={'file':(io.BytesIO(b'%PDF-1.4\n%%EOF'),'ทดสอบ.pdf')},headers={'X-CSRF-Token':'test-csrf'})
            self.assertEqual(r.status_code,201,r.json);self.assertEqual(r.json['version'],version)
        history=self.client.get(f'/api/documents/{id}/history').json;self.assertEqual(len(history['attachments']),2)
        aid=history['attachments'][0]['id'];self.login('other');self.assertEqual(self.client.get(f'/api/attachments/{aid}/download').status_code,404)
        self.login('one');r=self.client.get('/api/reports/export');self.assertEqual(r.status_code,200);self.assertTrue(zipfile.is_zipfile(io.BytesIO(r.data)))
        for lang in ['general','english']:
            for fmt in ['pdf','docx']:
                r=self.client.get(f'/api/forms/{lang}/{fmt}');self.assertEqual(r.status_code,200)
                self.assertTrue(r.data.startswith(b'%PDF') if fmt=='pdf' else zipfile.is_zipfile(io.BytesIO(r.data)))
    def test_pages_and_registration(self):
        id=self.create()
        for url in ['/',f'/documents/{id}']:
            r=self.client.get(url);self.assertEqual(r.status_code,200);self.assertIn(b'SUDMS',r.data)
        self.login('admin');self.assertEqual(self.client.get('/admin').status_code,200)
        with self.client.session_transaction() as s: s.clear()
        self.assertEqual(self.client.get('/api/dashboard').status_code,401)
        self.client.get('/register')
        with self.client.session_transaction() as s: token=s['csrf_token']
        r=self.client.post('/register',data={'name':'สมาชิกใหม่','email':'new@kkumail.com','phone':'0812345678','student_id':'683050399-3','faculty':'คณะวิทยาศาสตร์','password':'Password123!','organization_id':self.b,'csrf_token':token})
        self.assertEqual(r.status_code,200);self.assertEqual(User.query.filter_by(email='new@kkumail.com').one().status,'pending')
        r=self.client.post('/login',data={'email':'new@kkumail.com','phone':'0812345678','student_id':'683050399-3','faculty':'คณะวิทยาศาสตร์','password':'Password123!','csrf_token':token});self.assertIn('ยังไม่ได้รับอนุมัติ',r.data.decode())
    def test_excel_formula_safe(self):
        from openpyxl import load_workbook
        self.post('/api/documents/received',{'title':'=1+1','sender':'ต้นทาง','recipient_org_id':self.a})
        r=self.client.get('/api/reports/export');w=load_workbook(io.BytesIO(r.data));self.assertEqual(w.active['B2'].data_type,'s');self.assertEqual(w.active['B2'].value,"'=1+1")

    def test_registration_requirements(self):
        data={'name':'ใหม่','email':'new@kkumail.com','phone':'0812345678','student_id':'683050399-3','faculty':'คณะวิทยาศาสตร์','password':'Password123!','organization_id':self.b,'csrf_token':'test-csrf'}
        for key in ['name','student_id','faculty']:
            invalid=data.copy();invalid[key]='';self.client.post('/register',data=invalid)
            self.assertIsNone(User.query.filter_by(email=data['email']).first())
        invalid=data.copy();invalid['email']='new@gmail.com';self.client.post('/register',data=invalid)
        self.assertIsNone(User.query.filter_by(email='new@gmail.com').first())
        self.client.post('/register',data=data);self.assertEqual(User.query.filter_by(email=data['email']).one().faculty,'คณะวิทยาศาสตร์')
    def test_reset_email_and_password(self):
        from unittest.mock import patch
        from app import PasswordReset
        import re
        user=User.query.filter_by(name='one').one();user.email='one@kkumail.com';db.session.commit()
        self.app.config.update(SMTP_HOST='smtp.test',SMTP_FROM='sender@test')
        with patch('app.smtplib.SMTP') as smtp, patch('app.ssl.create_default_context'):
            server=smtp.return_value.__enter__.return_value
            r=self.client.post('/forgot-password',data={'email':user.email,'csrf_token':'test-csrf'})
            self.assertEqual(r.status_code,302);self.assertTrue(server.starttls.called)
            code=re.search(r'\b\d{6}\b',server.send_message.call_args.args[0].get_content()).group()
        self.assertNotEqual(PasswordReset.query.one().code_hash,code)
        r=self.client.post('/forgot-password',data={'email':user.email,'csrf_token':'test-csrf'});self.assertIn('60 วินาที',r.data.decode())
        r=self.client.post('/reset-password',data={'code':code,'password':'NewPassword123!','confirm_password':'NewPassword123!','csrf_token':'test-csrf'})
        self.assertIn('เปลี่ยนรหัสผ่านสำเร็จ',r.data.decode());self.assertTrue(PasswordReset.query.one().consumed)
        with self.client.session_transaction() as session: token=session['csrf_token'];session['reset_key']=PasswordReset.query.one().email_digest
        r=self.client.post('/reset-password',data={'code':code,'password':'AnotherPassword123!','confirm_password':'AnotherPassword123!','csrf_token':token})
        self.assertIn('ถูกใช้แล้ว',r.data.decode())
        r=self.client.post('/login',data={'email':user.email,'student_id':user.student_id,'password':'NewPassword123!','csrf_token':token});self.assertEqual(r.status_code,302)
    def test_reset_unknown_expiry_and_attempts(self):
        from unittest.mock import patch
        from datetime import timedelta
        from app import PasswordReset,now
        self.app.config.update(SMTP_HOST='smtp.test',SMTP_FROM='sender@test')
        with patch('app.smtplib.SMTP') as smtp, patch('app.ssl.create_default_context'):
            r=self.client.post('/forgot-password',data={'email':'unknown@kkumail.com','csrf_token':'test-csrf'})
            self.assertEqual(r.status_code,200);self.assertIn('ไม่พบบัญชี',r.get_data(as_text=True));smtp.assert_not_called()
            user=User.query.filter_by(name='one').one()
            self.client.post('/forgot-password',data={'email':user.email,'csrf_token':'test-csrf'})
        for _ in range(5): self.client.post('/reset-password',data={'code':'123456','password':'Password123!','confirm_password':'Password123!','csrf_token':'test-csrf'})
        entry=PasswordReset.query.one();self.assertTrue(entry.consumed);self.assertEqual(entry.attempts,5)
        entry.consumed=False;entry.attempts=0;entry.expires_at=now()-timedelta(seconds=1);db.session.commit()
        r=self.client.post('/reset-password',data={'code':'123456','password':'Password123!','confirm_password':'Password123!','csrf_token':'test-csrf'});self.assertIn('หมดอายุ',r.data.decode())
        user=User.query.filter_by(name='one').one();user.email='one@kkumail.com';entry.issued_at=now()-timedelta(seconds=61);db.session.commit()
        with patch('app.smtplib.SMTP',side_effect=OSError('test')):
            r=self.client.post('/forgot-password',data={'email':user.email,'csrf_token':'test-csrf'});self.assertIn('ส่งอีเมลไม่สำเร็จ',r.data.decode())
        self.assertTrue(PasswordReset.query.filter_by(user_id=user.id).one().consumed)

    def test_first_login_sets_password_once_for_approved_imported_account(self):
        from app import UserApprovalLog,PasswordReset
        from werkzeug.security import check_password_hash
        user=User.query.filter_by(name='one').one();user.password_initialized=False;original=user.password_hash;db.session.commit()
        wrong=self.client.post('/login',data=dict(email=user.email,student_id='683050399-3',password='FirstPassword123!',csrf_token='test-csrf'))
        self.assertEqual(wrong.status_code,200);self.assertFalse(user.password_initialized);self.assertEqual(user.password_hash,original)
        short=self.client.post('/login',data=dict(email=user.email,student_id=user.student_id,password='short',csrf_token='test-csrf'))
        self.assertIn('10–128',short.get_data(as_text=True));self.assertFalse(user.password_initialized)
        response=self.client.post('/login',data=dict(email=user.email,student_id=user.student_id,password='FirstPassword123!',csrf_token='test-csrf'))
        self.assertEqual(response.status_code,302);self.assertTrue(user.password_initialized);self.assertTrue(check_password_hash(user.password_hash,'FirstPassword123!'))
        log=UserApprovalLog.query.filter_by(user_id=user.id,action='initialize_password').one();self.assertNotIn('FirstPassword123!',log.changes)
        saved_hash=user.password_hash
        with self.client.session_transaction() as session:token=session['csrf_token']
        response=self.client.post('/login',data=dict(email=user.email,student_id=user.student_id,password='DifferentPassword123!',csrf_token=token))
        self.assertEqual(response.status_code,200);self.assertEqual(user.password_hash,saved_hash)
        response=self.client.post('/login',data=dict(email=user.email,student_id=user.student_id,password='FirstPassword123!',csrf_token=token));self.assertEqual(response.status_code,302)
        self.assertEqual(UserApprovalLog.query.filter_by(user_id=user.id,action='initialize_password').count(),1)

    def test_pending_account_cannot_initialize_password(self):
        user=User.query.filter_by(name='one').one();user.password_initialized=False;user.status='pending';original=user.password_hash;db.session.commit()
        response=self.client.post('/login',data=dict(email=user.email,student_id=user.student_id,password='FirstPassword123!',csrf_token='test-csrf'))
        self.assertIn('ยังไม่ได้รับอนุมัติ',response.get_data(as_text=True));self.assertFalse(user.password_initialized);self.assertEqual(user.password_hash,original)

    def test_login_requires_matching_student_email_password(self):
        user=User.query.filter_by(name='one').one()
        for student in ['', '683050399-3']:
            r=self.client.post('/login',data={'email':user.email,'student_id':student,'password':'Password123!','csrf_token':'test-csrf'})
            self.assertEqual(r.status_code,200);self.assertIn('ไม่พบข้อมูลผู้ใช้งาน',r.get_data(as_text=True))
        r=self.client.post('/login',data={'email':user.email,'student_id':user.student_id,'password':'WrongPassword','csrf_token':'test-csrf'})
        self.assertIn('รหัสผ่านไม่ถูกต้อง',r.get_data(as_text=True))
        r=self.client.post('/login',data={'email':user.email,'student_id':user.student_id,'password':'Password123!','csrf_token':'test-csrf'})
        self.assertEqual(r.status_code,302)
        with self.client.session_transaction() as session:self.assertEqual(session['user_id'],user.id)

    def test_forgot_unknown_before_smtp_and_deleted_account(self):
        from unittest.mock import patch
        from app import PasswordReset
        self.app.config.update(SMTP_HOST='',SMTP_FROM='')
        with patch('app.smtplib.SMTP') as smtp:
            r=self.client.post('/forgot-password',data={'email':'unknown@kkumail.com','csrf_token':'test-csrf'})
            self.assertIn('ไม่พบบัญชี',r.get_data(as_text=True));self.assertEqual(PasswordReset.query.count(),0);smtp.assert_not_called()
        user=User.query.filter_by(name='other').one();user.status='deleted';db.session.commit()
        r=self.client.post('/forgot-password',data={'email':user.email,'csrf_token':'test-csrf'})
        self.assertIn('ไม่พบบัญชี',r.get_data(as_text=True))

    def test_admin_initial_password_allows_matching_login(self):
        self.login('admin')
        data={'name':'initial','email':'initial@kkumail.com','student_id':'683050388-3','faculty':'คณะวิทยาศาสตร์','organization_id':self.a,'role':'user','profile':{'phone':'0812345678'},'initial_password':'InitialPassword123!'}
        r=self.post('/api/admin/users',data);self.assertEqual(r.status_code,201,r.json)
        user=User.query.filter_by(email=data['email']).one();self.assertTrue(user.password_initialized)
        self.assertNotIn('initial_password',r.get_data(as_text=True));self.assertNotEqual(user.password_hash,data['initial_password'])
        r=self.client.post('/login',data={'email':data['email'],'student_id':data['student_id'],'password':data['initial_password'],'csrf_token':'test-csrf'})
        self.assertEqual(r.status_code,302)

    def test_phone_otp_without_sms_never_claims_verification(self):
        r=self.post('/api/auth/phone-otp/send',{'phone':'0812345678'});self.assertEqual(r.status_code,503);self.assertFalse(r.json['phone_verified'])
        self.assertEqual(self.post('/api/auth/phone-otp/send',{'phone':'123'}).status_code,400)
        self.assertEqual(self.client.post('/api/auth/phone-otp/send',json={'phone':'0812345678'}).status_code,400)
        self.assertIn('phone-otp-send',self.client.get('/register').get_data(as_text=True))

    def test_organization_assignment_and_numbering(self):
        from app import NumberReservation, UserApprovalLog, now
        pending=User(name='candidate',email='candidate@kkumail.com',password_hash=generate_password_hash('Password123!'),organization_id=self.b,requested_org_id=self.b,status='pending')
        db.session.add(pending);db.session.commit();uid=pending.id
        self.login('admin')
        self.assertEqual(self.post(f'/api/admin/users/{uid}/approval',{'status':'approved'}).status_code,400)
        self.assertEqual(self.post(f'/api/admin/users/{uid}/approval',{'status':'approved','organization_id':self.c}).status_code,200)
        self.assertEqual(db.session.get(User,uid).organization_id,self.c)
        self.assertEqual(db.session.get(User,uid).requested_org_id,self.b)
        self.assertIsNotNone(UserApprovalLog.query.filter_by(user_id=uid).one().changes)
        private=self.create(self.a)
        self.login('candidate')
        self.assertEqual(self.client.get(f'/api/documents/{private}/history').status_code,404)
        self.assertIn('กลุ่มเลือดสีอิฐ',self.client.get('/').data.decode())
        r=self.post('/api/numbers/sent/reserve',{});year=str(now().year+543)
        self.assertEqual(r.json['number'],'ลสอ.1/'+year)
        r=self.post('/api/numbers/received/reserve',{});self.assertEqual(r.json['number'],'ลสอ.รับ.1/'+year)
        self.assertEqual(self.post('/api/admin/users/1/approval',{'status':'approved','organization_id':self.a}).status_code,403)
        self.login('two');r=self.post('/api/numbers/sent/reserve',{});self.assertEqual(r.json['number'],'สน.มข.1/'+year)
        self.login('admin')
        self.assertEqual(self.post(f'/api/admin/users/{uid}/approval',{'status':'approved','organization_id':self.b}).status_code,200)
        self.login('candidate');self.assertEqual(self.client.get('/api/numbers/received').json,[])
        self.assertEqual(self.post('/api/documents/received',{'title':'old reservation','sender':'test','recipient_org_id':self.b,'reservation_number':'ลสอ.002/'+year}).status_code,400)

    def test_admin_directory_and_login_history(self):
        import json
        user=User.query.filter_by(name='one').one();user.profile=json.dumps({'phone':'0123456789','english_name':'TEST USER'});db.session.commit()
        self.assertEqual(self.client.get('/api/admin/users').status_code,403)
        r=self.client.post('/login',data={'email':user.email,'student_id':user.student_id,'password':'Password123!','csrf_token':'test-csrf'})
        self.assertEqual(r.status_code,302);self.assertEqual(user.login_count,1);self.assertIsNotNone(user.last_login_at)
        self.login('admin');r=self.client.get('/api/admin/users');self.assertEqual(r.status_code,200)
        row=next(u for u in r.json if u['name']=='one')
        self.assertEqual(row['profile']['phone'],'0123456789');self.assertEqual(row['login_count'],1)
        self.assertNotIn('password_hash',row)
        page=self.client.get('/admin');self.assertEqual(page.status_code,200);self.assertIn(b'organization-cards',page.data);self.assertIn(b'admin.js',page.data)

    def test_faculty_and_organization_dropdown(self):
        from faculties import FACULTIES
        from html.parser import HTMLParser
        class Options(HTMLParser):
            def __init__(self): super().__init__();self.select=None;self.faculties=[];self.organizations=[]
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if tag=='select': self.select=attrs.get('name')
                if tag=='option' and attrs.get('value'):
                    if self.select=='faculty': self.faculties.append(attrs['value'])
                    elif self.select=='organization_id': self.organizations.append(attrs['value'])
            def handle_endtag(self,tag):
                if tag=='select': self.select=None
        html=self.client.get('/register').data.decode();parser=Options();parser.feed(html)
        self.assertEqual(parser.faculties,FACULTIES);self.assertEqual(len(parser.faculties),22)
        self.assertEqual(len(parser.organizations),54);self.assertEqual(len(set(parser.organizations)),54)
        data={'name':'ทดสอบ','email':'college@kkumail.com','phone':'0812345678','student_id':'683050399-3','faculty':'คณะที่ไม่มีในรายการ','password':'Password123!','organization_id':self.b,'csrf_token':'test-csrf'}
        response=self.client.post('/register',data=data);self.assertIn('กรุณาเลือกคณะ/วิทยาลัย',response.data.decode())
        self.assertIsNone(User.query.filter_by(email=data['email']).first())
        data['faculty']='วิทยาลัยการคอมพิวเตอร์';self.client.post('/register',data=data)
        self.assertEqual(User.query.filter_by(email=data['email']).one().faculty,data['faculty'])

    def test_saved_organization_and_approval_history(self):
        target=User.query.filter_by(name='two').one();uid=target.id
        self.login('admin');admin=User.query.filter_by(name='admin').one()
        r=self.post(f'/api/admin/users/{uid}/approval',{'status':'approved','organization_id':self.b,'actor_name':'forged','created_at':'1900-01-01'})
        self.assertEqual(r.status_code,200)
        row=next(u for u in self.client.get('/api/admin/users').json if u['id']==uid)
        self.assertTrue(row['organization_saved']);self.assertEqual(row['approved_by'],admin.name);self.assertTrue(row['approved_at'].endswith('+07:00'))
        self.assertEqual(row['approval_history'][0]['actor_id'],admin.id)
        r=self.post(f'/api/admin/users/{uid}/approval',{'status':'approved','organization_id':self.c})
        self.assertEqual(r.status_code,200)
        row=next(u for u in self.client.get('/api/admin/users').json if u['id']==uid)
        self.assertTrue(row['organization_saved']);self.assertEqual(len(row['approval_history']),2)
        self.assertEqual(row['approval_history'][0]['previous_organization'],Organization.query.filter_by(id=self.b).one().name)
        self.assertEqual(row['approval_history'][0]['organization_id'],self.c)
        self.post(f'/api/admin/users/{uid}/approval',{'status':'suspended'})
        row=next(u for u in self.client.get('/api/admin/users').json if u['id']==uid)
        self.assertFalse(row['organization_saved']);self.assertEqual(row['approved_by'],admin.name)
        self.assertEqual(len(row['approval_history']),3)
        self.login('one');self.assertEqual(self.client.get('/api/admin/users').status_code,403)

    def test_sent_draft_is_private_until_send(self):
        details={'document_type':'memo','document_date':'2026-10-14','due_date':'2026-10-20','owner_name':'เจ้าของเรื่อง','recipient_scope':'internal','recipient_org_id':self.b,'recipient_name':'ประธาน','salutation':'ประธานสภา','practice':'พิจารณา','note':'ทดสอบ','circular':True,'paper_today':False}
        r=self.post('/api/documents/sent',{'title':'ร่างทดสอบ','sender':'องค์การนักศึกษา','save_mode':'draft','priority':'most_urgent','send_details':details})
        self.assertEqual(r.status_code,201,r.json);id=r.json['id'];self.assertEqual(r.json['status'],'draft')
        self.assertEqual(self.client.get(f'/documents/{id}').status_code,200)
        r=self.client.post(f'/api/documents/{id}/attachments',data={'file':(io.BytesIO(b'%PDF-1.4\n%%EOF'),'test.pdf')},headers={'X-CSRF-Token':'test-csrf'})
        self.assertEqual(r.status_code,201)
        self.login('two');self.assertEqual(self.client.get(f'/api/documents/{id}/history').status_code,404)
        self.assertEqual(self.client.get('/api/documents/all?inbox=1').json['total'],0)
        self.login('one')
        details['note']='แก้หมายเหตุ';r=self.client.patch(f'/api/documents/{id}',json={'title':'แก้ร่าง','send_details':details},headers={'X-CSRF-Token':'test-csrf'})
        self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(self.post(f'/api/documents/{id}/action',{'action':'receive'}).status_code,400)
        self.assertEqual(self.post(f'/api/documents/{id}/action',{'action':'send'}).status_code,200)
        self.assertEqual(self.post(f'/api/documents/{id}/action',{'action':'send'}).status_code,403)
        history=self.client.get(f'/api/documents/{id}/history').json
        self.assertEqual(history['document']['send_details']['note'],'แก้หมายเหตุ')
        self.assertTrue(any(a['event']=='edit' and a['actor']=='one' for a in history['audit']))
        self.assertTrue(any(a['event']=='send' and a['actor']=='one' for a in history['audit']))
        self.login('two');self.assertEqual(self.client.get(f'/api/documents/{id}/history').status_code,200)
        self.assertEqual(self.client.get('/api/documents/all?inbox=1').json['total'],1)
    def test_shared_reservations_manual_numbers_and_audit(self):
        from app import now
        year=str(now().year+543)
        reserved=self.post('/api/numbers/sent/reserve',{}).json['number']
        self.login('admin')
        self.assertIn(reserved,self.client.get('/api/numbers/sent').json)
        r=self.post('/api/documents/sent',{'title':'ใช้เลขเพื่อนร่วมงาน','sender':'ต้นทาง','save_mode':'draft','reservation_number':reserved,'send_details':{'recipient_scope':'internal','recipient_org_id':self.b}})
        self.assertEqual(r.status_code,201,r.json);id=r.json['id']
        history=self.client.get(f'/api/documents/{id}/history').json
        self.assertEqual(history['number_reservation']['reserved_by'],'one');self.assertEqual(history['number_reservation']['used_by'],'admin')
        self.login('one')
        edited=self.client.patch(f'/api/documents/{id}',json={'title':'แก้ไขโดยเพื่อนร่วมหน่วยงาน'},headers={'X-CSRF-Token':'test-csrf'})
        self.assertEqual(edited.status_code,200)
        self.assertEqual(self.post(f'/api/documents/{id}/action',{'action':'send'}).status_code,200)
        history=self.client.get(f'/api/documents/{id}/history').json
        self.assertTrue(any(a['event']=='edit' and a['actor']=='one' for a in history['audit']))
        self.assertTrue(any(a['event']=='send' and a['actor']=='one' for a in history['audit']))
        self.login('admin')
        number='อน.มข.050/'+year
        r=self.post('/api/documents/sent',{'title':'เลขเอง','sender':'ต้นทาง','save_mode':'draft','number':number})
        self.assertEqual(r.status_code,201,r.json)
        self.assertEqual(self.post('/api/numbers/sent/reserve',{}).json['number'],'อน.มข.51/'+year)
        for invalid in [number,'อน.มข.0050/'+year,'สน.มข.1/'+year]:
            self.assertEqual(self.post('/api/documents/sent',{'title':'เลขซ้ำ','sender':'ต้นทาง','save_mode':'draft','number':invalid}).status_code,400)
        self.login('two');self.assertNotIn(reserved,self.client.get('/api/numbers/sent').json)
        self.assertEqual(self.client.get('/api/numbers/sent/details?organization_id='+str(self.a)).status_code,403)
        self.assertEqual(self.post('/api/numbers/sent/reserve',{'organization_id':self.a}).status_code,403)
    def test_external_sent_and_send_validation(self):
        r=self.post('/api/documents/sent',{'title':'ภายนอก','sender':'ต้นทาง','save_mode':'draft','digital_only':False,'send_details':{'recipient_scope':'external','external_unit':'หน่วยงานภายนอก','paper_today':True,'document_date':'2026-10-14','due_date':'2026-10-20'}})
        self.assertEqual(r.status_code,201,r.json);id=r.json['id']
        r=self.post(f'/api/documents/{id}/action',{'action':'send'});self.assertEqual(r.status_code,200);self.assertEqual(r.json['status'],'sent_external')
        self.assertEqual(self.post(f'/api/documents/{id}/action',{'action':'send'}).status_code,400)
        for details in [{'document_date':'bad'},{'document_date':'2026-10-14','due_date':'2026-10-01'},{'paper_today':True}]:
            self.assertEqual(self.post('/api/documents/sent',{'title':'ผิด','sender':'ต้นทาง','save_mode':'draft','send_details':details}).status_code,400)
        r=self.post('/api/documents/sent',{'title':'ไม่มีผู้รับ','sender':'ต้นทาง','save_mode':'draft'})
        self.assertEqual(r.status_code,201);self.assertEqual(self.post(f"/api/documents/{r.json['id']}/action",{'action':'send'}).status_code,200)
        self.assertIn(b'sent-create-form',self.client.get('/?view=sent').data)

    def test_reserved_row_edit_and_send(self):
        r=self.post('/api/numbers/sent/reserve',{});self.assertEqual(r.status_code,201)
        id=r.json['document_id'];number=r.json['number']
        self.assertEqual(r.json['edit_url'],f'/documents/{id}?edit=1')
        items=self.client.get('/api/documents/sent').json['items'];self.assertEqual(len(items),1)
        self.assertEqual(items[0]['number'],number);self.assertTrue(items[0]['send_details']['reservation_only'])
        self.assertEqual(self.post(f'/api/documents/{id}/action',{'action':'send'}).status_code,400)
        html=self.client.get(f'/documents/{id}?edit=1').data.decode();self.assertIn('sent-create-form',html)
        self.login('other');self.assertEqual(self.client.get(f'/api/documents/{id}/history').status_code,404)
        self.login('admin')
        data={'title':'หนังสือจากเลขจอง','send_details':{'recipient_scope':'internal','recipient_org_id':self.b,'document_date':'2026-10-14','owner_name':'ผู้ทำเอกสาร','document_type':'memo'}}
        edited=self.client.patch(f'/api/documents/{id}',json=data,headers={'X-CSRF-Token':'test-csrf'})
        self.assertEqual(edited.status_code,200,edited.json)
        self.assertFalse(edited.json['send_details'].get('reservation_only',False))
        self.assertEqual(self.client.get('/api/documents/sent').json['total'],1)
        self.assertEqual(self.post(f'/api/documents/{id}/action',{'action':'send'}).status_code,200)
        h=self.client.get(f'/api/documents/{id}/history').json
        self.assertEqual(h['number_reservation']['reserved_by'],'one');self.assertEqual(h['number_reservation']['used_by'],'admin')
        self.assertTrue(any(a['event']=='reserve' and a['actor']=='one' for a in h['audit']))
        self.assertTrue(any(a['event']=='edit' and a['actor']=='admin' for a in h['audit']))
        self.assertTrue(any(a['event']=='send' and a['actor']=='admin' for a in h['audit']))
        self.assertEqual(h['document']['number'],number)

    def test_full_sent_editor_and_legacy_details(self):
        from unittest.mock import patch
        r=self.post('/api/numbers/sent/reserve',{});id=r.json['document_id'];number=r.json['number']
        for url in [f'/documents/{id}/edit',f'/documents/{id}?edit=1']:
            response=self.client.get(url);self.assertEqual(response.status_code,200)
            text=response.data.decode()
            self.assertIn('แก้ไขหนังสือส่ง',text);self.assertIn('name="owner_name"',text)
            self.assertIn('name="external_units[]"',text);self.assertIn('name="files"',text)
            self.assertIn('value="send"',text);self.assertIn('value="draft"',text)
            self.assertIn('name="salutation"',text)
        # ข้อมูลรุ่นเก่าที่ไม่มี key send_details ต้องไม่เกิด UndefinedError
        with patch.object(Document,'to_dict',return_value={}):
            response=self.client.get(f'/documents/{id}/edit');self.assertEqual(response.status_code,200)
        self.login('other');self.assertEqual(self.client.get(f'/documents/{id}/edit').status_code,404)
        self.login('one')
        payload={'title':'กรอกข้อมูลจากหน้าแก้ไข','send_details':{'document_type':'memo','document_date':'2026-10-14','owner_name':'one','recipient_scope':'internal','recipient_org_id':self.b,'salutation':'ประธาน'}}
        response=self.client.patch(f'/api/documents/{id}',json=payload,headers={'X-CSRF-Token':'test-csrf'})
        self.assertEqual(response.status_code,200);self.assertEqual(response.json['number'],number)
        self.assertEqual(self.post(f'/api/documents/{id}/action',{'action':'send'}).status_code,200)
        self.assertEqual(self.client.get('/api/documents/sent').json['total'],1)
        self.login('admin');self.assertEqual(self.client.get(f'/documents/{id}/edit').status_code,200)

    def test_optional_multiple_recipients_and_independent_inboxes(self):
        details={'recipient_org_ids':[self.b,self.c,self.b],'external_units':['ภายนอก '+str(i) for i in range(120)],'recipient_names':['ผู้รับหนึ่ง','ผู้รับสอง'],'personnel':'','practice':'','note':''}
        r=self.post('/api/documents/sent',{'title':'ส่งหลายหน่วยงาน','sender':'ต้นทาง','save_mode':'draft','send_details':details})
        self.assertEqual(r.status_code,201,r.json);id=r.json['id']
        self.assertEqual(len(r.json['send_details']['external_units']),120)
        self.assertEqual(len(r.json['send_details']['recipient_org_ids']),2)
        self.assertEqual(self.post(f'/api/documents/{id}/action',{'action':'send'}).status_code,200)
        self.login('two');self.assertEqual(self.client.get('/api/documents/all?inbox=1').json['total'],1)
        self.assertEqual(self.post(f'/api/documents/{id}/action',{'action':'receive'}).status_code,200)
        self.assertEqual(self.client.get('/api/documents/all?inbox=1').json['total'],0)
        self.assertEqual(self.post(f'/api/documents/{id}/action',{'action':'receive'}).status_code,400)
        self.assertEqual(self.post(f'/api/documents/{id}/action',{'action':'complete'}).status_code,200)
        self.login('other');self.assertEqual(self.client.get('/api/documents/all?inbox=1').json['total'],1)
        self.assertEqual(self.client.get('/api/dashboard').json['pending'],1)
        self.assertEqual(self.post(f'/api/documents/{id}/action',{'action':'receive'}).status_code,200)
        self.assertEqual(self.post(f'/api/documents/{id}/action',{'action':'complete'}).json['status'],'completed')
        self.login('admin');h=self.client.get(f'/api/documents/{id}/history').json;self.assertEqual(len(h['deliveries']),2)
        html=self.client.get(f'/documents/{id}').data.decode();self.assertNotIn('id="action-form"',html);self.assertNotIn('id="upload-form"',html)
        self.assertNotIn('เอกสารแนบและเวอร์ชัน',html)
    def test_circular_code_reservation_edit_and_sequence(self):
        from app import now
        year=str(now().year+543)
        booked=self.post('/api/numbers/sent/reserve',{}).json;id=booked['document_id']
        payload={'title':'หนังสือเวียน','number':booked['number'],'send_details':{'circular':True,'recipient_org_ids':[]}}
        response=self.client.patch(f'/api/documents/{id}',json=payload,headers={'X-CSRF-Token':'test-csrf'})
        self.assertEqual(response.status_code,200,response.json);self.assertEqual(response.json['number'],'อน.มข.ว.1/'+year)
        self.assertEqual(self.client.get(f'/documents/{id}?edit=1').status_code,200)
        self.assertEqual(self.post('/api/numbers/sent/reserve',{}).json['number'],'อน.มข.2/'+year)
        circular=self.post('/api/numbers/sent/reserve',{'circular':True}).json
        self.assertEqual(circular['number'],'อน.มข.ว.3/'+year)
        self.assertEqual(self.post(f'/api/documents/{id}/action',{'action':'send'}).json['status'],'sent_recorded')
        history=self.client.get(f'/api/documents/{id}/history').json;self.assertTrue(any(a['event']=='number_format' for a in history['audit']))
        normal=self.post('/api/numbers/sent/reserve',{}).json
        created=self.post('/api/documents/sent',{'title':'ใช้เลขจองเป็นเวียน','sender':'ต้นทาง','save_mode':'draft','reservation_number':normal['number'],'send_details':{'circular':True}})
        self.assertEqual(created.status_code,201,created.json);self.assertEqual(created.json['id'],normal['document_id'])
        self.assertEqual(created.json['number'],'อน.มข.ว.4/'+year)

if __name__=='__main__': unittest.main()

