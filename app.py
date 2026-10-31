"""SUDMS — ระบบสารบรรณนักศึกษา มหาวิทยาลัยขอนแก่น"""
import os, io, json, secrets, hashlib, uuid, re, hmac, smtplib, ssl
from email.message import EmailMessage
from datetime import timedelta
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
import click
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import or_, text
from sqlalchemy.exc import IntegrityError
from organizations import ORGANIZATIONS, ORGANIZATION_CODES
from faculties import FACULTIES
from form_catalog import FORM_CATALOG
from sac_forms import SAC_FORM_CATEGORIES, SAC_FORM_ITEMS

db = SQLAlchemy()
BANGKOK = timezone(__import__('datetime').timedelta(hours=7))
def now(): return datetime.now(BANGKOK).replace(tzinfo=None)
def stamp(value): return value.isoformat(timespec='seconds') + '+07:00' if value else None

def plain_document_number(value):
    return re.sub(r'([0-9]+)/([0-9]{4})$',lambda match:str(int(match.group(1)))+'/'+match.group(2),value or '')

class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(180), unique=True, nullable=False)
    club_type = db.Column(db.String(20),nullable=False,default='other')
    code = db.Column(db.String(30), unique=True, nullable=True)  # ตัวย่อหน่วยงาน
    quota = db.Column(db.Integer, nullable=False, default=5)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False)
    student_id = db.Column(db.String(30), unique=True, nullable=True)  # รหัสนักศึกษา
    faculty = db.Column(db.String(180), nullable=True)  # คณะของนักศึกษา
    position = db.Column(db.String(120), nullable=True)  # ตำแหน่งในหน่วยงาน
    profile = db.Column(db.Text, nullable=True)  # ข้อมูลประวัติจากรายชื่อหน่วยงาน
    password_initialized = db.Column(db.Boolean, default=True, nullable=False)  # บัญชีนำเข้าตั้งรหัสผ่านครั้งแรกผ่าน OTP
    password_hash = db.Column(db.String(256), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    requested_org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=True)  # หน่วยงานที่ผู้สมัครแจ้ง
    organization = db.relationship(Organization, foreign_keys=[organization_id])
    requested_organization = db.relationship(Organization, foreign_keys=[requested_org_id])
    role = db.Column(db.String(20), default='user', nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)  # เวลาล็อกอินสำเร็จล่าสุด
    login_count = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=now)

class UserOrganization(db.Model):
    user_id=db.Column(db.Integer,db.ForeignKey('user.id'),primary_key=True)
    organization_id=db.Column(db.Integer,db.ForeignKey('organization.id'),primary_key=True)

# สมาชิกที่เคยได้รับเอกสารยังคงเข้าถึงประวัติได้หลังส่งต่อ
class DocumentAccess(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('document.id'), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('document_id','organization_id'),)

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(80), unique=True, nullable=False)
    direction = db.Column(db.String(20), nullable=False)
    category = db.Column(db.String(30), default='general', nullable=False)
    title = db.Column(db.String(300), nullable=False)
    sender = db.Column(db.String(180), nullable=False)
    recipient = db.Column(db.String(180), nullable=False)
    owner_org_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    current_org_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(30), default='pending', nullable=False)
    priority = db.Column(db.String(20), default='normal', nullable=False)
    send_details = db.Column(db.Text, nullable=True)  # ข้อมูลแบบฟอร์มหนังสือส่ง
    content = db.Column(db.Text, default='')
    digital_only = db.Column(db.Boolean, default=True, nullable=False)
    version = db.Column(db.String(20), default='v1.0', nullable=False)
    deleted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now, nullable=False)
    @property
    def display_number(self):
        number=json.loads(self.send_details or '{}').get('released_number',self.number)
        # ซ่อนคำว่า รับ. เฉพาะการแสดงผล ทะเบียนรับ/ส่งยังแยกชุดเลขภายใน
        return plain_document_number(number.replace('รับ.','',1) if self.direction=='received' else number)
    @property
    def source_number(self):
        details=json.loads(self.send_details or '{}')
        source=db.session.get(Document,details['source_document_id']) if details.get('source_document_id') else None
        return source.display_number if source else plain_document_number(details.get('source_number','')) if self.direction=='received' else self.display_number
    def to_dict(self):
        details=json.loads(self.send_details or '{}')
        if self.direction=='received':details['source_number']=self.source_number
        for key in ['released_number','restored_original_number']:
            if details.get(key):details[key]=plain_document_number(details[key])
        return {k:getattr(self,k) for k in ['id','number','direction','category','title','sender','recipient','status','priority','content','digital_only','version','deleted','owner_org_id','current_org_id']} | {'number':self.display_number,'source_number':self.source_number,'created_at':stamp(self.created_at),'updated_at':stamp(self.updated_at),'send_details':details}

# สถานะผู้รับแยกตามหน่วยงาน เอกสารฉบับเดียวส่งหลายหน่วยงานได้
class DocumentRecipient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('document.id'), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    status = db.Column(db.String(30), default='pending', nullable=False)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now, nullable=False)
    __table_args__ = (db.UniqueConstraint('document_id','organization_id'),)

class DocumentTracking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('document.id'), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    actor = db.relationship(User)
    action = db.Column(db.String(30), nullable=False)
    from_org = db.Column(db.String(180), nullable=False)
    to_org = db.Column(db.String(180), nullable=False)
    status = db.Column(db.String(30), nullable=False)
    note = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=now, nullable=False)

class DocumentAuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('document.id'), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    actor = db.relationship(User)
    event = db.Column(db.String(40), nullable=False)
    changes = db.Column(db.Text, nullable=False)
    version = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

class Attachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('document.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    storage_name = db.Column(db.String(80), unique=True, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    version = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

class NumberReservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(80), unique=True, nullable=False)
    direction = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=True)
    used_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    used_at = db.Column(db.DateTime, nullable=True)
    source = db.Column(db.String(20), default='reserved', nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

class UserApprovalLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action = db.Column(db.String(30), nullable=False)
    changes = db.Column(db.Text, nullable=True)  # ประวัติการจัดหน่วยงานก่อน/หลัง
    created_at = db.Column(db.DateTime, default=now, nullable=False)

# เก็บเฉพาะ hash ของ OTP มีอายุและจำนวนครั้งที่ลอง จำกัดการส่งซ้ำในฐานข้อมูล
# ทะเบียนรับของปลายทางแยกจากข้อมูลหนังสือส่งต้นฉบับ
class ReceivedRegistration(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    source_document_id=db.Column(db.Integer,db.ForeignKey('document.id'),nullable=False)
    organization_id=db.Column(db.Integer,db.ForeignKey('organization.id'),nullable=False)
    received_document_id=db.Column(db.Integer,db.ForeignKey('document.id'),nullable=False)
    registered_by=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False)
    created_at=db.Column(db.DateTime,default=now,nullable=False)
    __table_args__=(db.UniqueConstraint('source_document_id','organization_id'),)

class PersonalAssignment(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    document_id=db.Column(db.Integer,db.ForeignKey('document.id'),nullable=False)
    user_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False)
    assigned_by=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False)
    status=db.Column(db.String(20),default='pending',nullable=False)
    accepted_at=db.Column(db.DateTime,nullable=True)
    created_at=db.Column(db.DateTime,default=now,nullable=False)
    __table_args__=(db.UniqueConstraint('document_id','user_id'),)

class PasswordReset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email_digest = db.Column(db.String(64), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    code_hash = db.Column(db.String(64), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    issued_at = db.Column(db.DateTime, nullable=True)
    window_at = db.Column(db.DateTime, nullable=True)
    send_count = db.Column(db.Integer, default=0, nullable=False)
    attempts = db.Column(db.Integer, default=0, nullable=False)
    consumed = db.Column(db.Boolean, default=False, nullable=False)

class RoomBooking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    requester_name = db.Column(db.String(120), nullable=False)
    activity = db.Column(db.String(500), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id'))
    email = db.Column(db.String(180), nullable=False)
    phone = db.Column(db.String(10), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    reviewed_at = db.Column(db.DateTime)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    review_note = db.Column(db.String(2000), default='')
    memo_name = db.Column(db.String(255))
    memo_storage = db.Column(db.String(80))
    email_status = db.Column(db.String(20), nullable=False, default='pending')
    email_sent_at = db.Column(db.DateTime)
    calendar_status = db.Column(db.String(20), nullable=False, default='local')
    calendar_event_ids = db.Column(db.Text, default='[]')

def archive_user_identity(user):
    snapshot={'name':user.name,'email':user.email,'student_id':user.student_id,'faculty':user.faculty,'position':user.position,'profile':user.profile,'role':user.role,'status':user.status,'organization_id':user.organization_id,'requested_org_id':user.requested_org_id}
    user.name=f'ผู้ใช้งานที่ลบ #{user.id}'
    user.email=f'deleted-{user.id}-{uuid.uuid4().hex}@invalid.local'
    user.student_id=None;user.faculty=None;user.position=None;user.profile=None;user.requested_org_id=None
    user.status='deleted';user.role='user';user.password_initialized=False
    user.password_hash=generate_password_hash(secrets.token_urlsafe(32))
    return snapshot

from finance import define_finance_models
FinanceProject, FinanceExpense, FinanceAudit = define_finance_models(db, now)

class ValidationError(Exception): pass

def create_app(test_config=None):
    instance_override=os.environ.get('SUDMS_INSTANCE_PATH')
    app = Flask(__name__, instance_relative_config=True, **({'instance_path':str(Path(instance_override).resolve())} if instance_override else {}))
    Path(app.instance_path).mkdir(exist_ok=True, parents=True)
    error_path=Path(app.instance_path)/'app-errors.log'
    if not any(getattr(handler,'baseFilename',None)==str(error_path) for handler in app.logger.handlers):
        handler=RotatingFileHandler(error_path,maxBytes=1024*1024,backupCount=2,encoding='utf-8')
        handler.setLevel(logging.ERROR)
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        app.logger.addHandler(handler)
    # เก็บกุญแจ session แยกจาก source และใช้ซ้ำเมื่อ restart
    keyfile=Path(app.instance_path)/'secret.key'
    if not keyfile.exists(): keyfile.write_text(secrets.token_hex(32))
    app.config.update(SECRET_KEY=os.environ.get('SUDMS_SECRET_KEY') or keyfile.read_text(),
        SQLALCHEMY_DATABASE_URI='sqlite:///'+str(Path(app.instance_path)/'sudms.db'),
        TEMPLATES_AUTO_RELOAD=True, SQLALCHEMY_TRACK_MODIFICATIONS=False, MAX_CONTENT_LENGTH=10*1024*1024,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('SUDMS_HTTPS')=='1', UPLOAD_FOLDER=str(Path(app.instance_path)/'uploads'))
    if test_config: app.config.update(test_config)
    # ค่า SMTP อยู่ใน instance ที่ไม่ถูกบรรจุใน ZIP หรือ Git
    smtp_path=Path(app.instance_path)/'smtp.json'
    smtp=json.loads(smtp_path.read_text(encoding='utf-8-sig')) if smtp_path.exists() else {}
    for key in ['HOST','PORT','USERNAME','PASSWORD','FROM','SECURITY']:
        app.config['SMTP_'+key]=os.environ.get('SUDMS_SMTP_'+key,smtp.get(key,''))
    db.init_app(app)
    Path(app.config['UPLOAD_FOLDER']).mkdir(exist_ok=True,parents=True)
    with app.app_context():
        db.create_all()
        from sqlalchemy import inspect
        if 'club_type' not in {c['name'] for c in inspect(db.engine).get_columns('organization')}:db.session.execute(text("ALTER TABLE organization ADD COLUMN club_type VARCHAR(20) NOT NULL DEFAULT 'other'"));db.session.commit()
        # Release old deleted-account identities while preserving their history rows.
        for deleted_user in User.query.filter_by(status='deleted').all():
            if not deleted_user.email.endswith('@invalid.local') or deleted_user.student_id:
                previous_deletion=UserApprovalLog.query.filter_by(user_id=deleted_user.id,action='delete_user').order_by(UserApprovalLog.id.desc()).first()
                snapshot=archive_user_identity(deleted_user)
                if previous_deletion:
                    changes=json.loads(previous_deletion.changes or '{}');changes['archived_identity']=snapshot;changes['identity_released_at']=stamp(now());previous_deletion.changes=json.dumps(changes,ensure_ascii=False)
                else:
                    db.session.add(UserApprovalLog(user_id=deleted_user.id,actor_id=deleted_user.id,action='delete_user',changes=json.dumps({'before':snapshot,'source':'release_deleted_identity','actor_name':'ระบบ (ย้ายข้อมูลบัญชีที่ลบเดิม)','after':{'status':'deleted'}},ensure_ascii=False)))
                for reset in PasswordReset.query.filter_by(user_id=deleted_user.id).all():reset.consumed=True
        db.session.commit()
        # เพิ่มสถานะให้ข้อมูลมอบหมายเดิมโดยไม่ลบประวัติ
        from sqlalchemy import inspect
        assignment_columns={column['name'] for column in inspect(db.engine).get_columns('personal_assignment')}
        if 'status' not in assignment_columns: db.session.execute(text("ALTER TABLE personal_assignment ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'pending'"))
        if 'accepted_at' not in assignment_columns: db.session.execute(text("ALTER TABLE personal_assignment ADD COLUMN accepted_at DATETIME"))
        db.session.commit()
        for name in ORGANIZATIONS:
            if not Organization.query.filter_by(name=name).first(): db.session.add(Organization(name=name,code=ORGANIZATION_CODES[name],quota=21 if name=='องค์การนักศึกษา' else 5))
        from finance_groups import GENERAL_CLUBS, SPORTS_CLUBS, club_type
        for name,code in [('ชมรม KKU DANCE CLUB','ชดค.'),('ชมรมซอฟท์บอล','ชซบ.')]:
            if not Organization.query.filter_by(name=name).first():db.session.add(Organization(name=name,code=code,quota=5))
        db.session.flush()
        for organization in Organization.query.all():
            organization.quota=21 if organization.name=='องค์การนักศึกษา' else 5
            organization.club_type=club_type(organization.name)
        db.session.commit()

    def validate_phone(value):
        # ตรวจรูปแบบเท่านั้น ยังไม่มีการยืนยัน OTP ทาง SMS
        if not isinstance(value,str): raise ValidationError('เบอร์โทรต้องเป็นตัวเลข 10 หลัก')
        phone=re.sub(r'[\s\-\u200b]+','',value)
        if not re.fullmatch(r'0[0-9]{9}',phone): raise ValidationError('กรุณาระบุเบอร์โทร 10 หลัก เริ่มต้นด้วย 0')
        return phone
    def membership_ids(user):
        user=getattr(user,'_user',user)
        return sorted({user.organization_id}|{m.organization_id for m in UserOrganization.query.filter_by(user_id=user.id)})
    def member_filter(oid):
        return or_(User.organization_id==oid,User.id.in_(db.session.query(UserOrganization.user_id).filter_by(organization_id=oid)))
    class WorkspaceUser:
        # Workspace is request/session-local; never overwrite the account's primary organization.
        def __init__(self,user,oid):object.__setattr__(self,'_user',user);object.__setattr__(self,'_oid',oid)
        @property
        def organization_id(self):return self._oid
        @property
        def organization(self):return db.session.get(Organization,self._oid)
        def __getattr__(self,key):return getattr(self._user,key)
        def __setattr__(self,key,value):setattr(self._user,key,value)
    def current_user():
        user=db.session.get(User,session.get('user_id')) if session.get('user_id') else None
        if not user:return None
        oid=session.get('active_organization_id',user.organization_id)
        if oid not in membership_ids(user):oid=user.organization_id
        return WorkspaceUser(user,oid)

    def authenticated(admin=False):
        def decorate(fn):
            @wraps(fn)
            def wrapper(*args,**kwargs):
                user=current_user()
                if not user or user.status!='approved':
                    if request.path.startswith('/api/'): return jsonify(error='กรุณาเข้าสู่ระบบด้วยบัญชีที่อนุมัติแล้ว'),401
                    return redirect(url_for('login'))
                if admin and user.role!='admin': abort(403)
                return fn(*args,**kwargs)
            return wrapper
        return decorate
    @app.before_request
    def csrf_check():
        if request.method in ['POST','PUT','PATCH','DELETE']:
            token=request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
            if not token or not secrets.compare_digest(token,session.get('csrf_token','')): abort(400,description='CSRF token ไม่ถูกต้อง กรุณาโหลดหน้าใหม่')
    @app.context_processor
    def context():
        session.setdefault('csrf_token',secrets.token_hex(32))
        return dict(user=current_user(),csrf_token=session['csrf_token'],book_year=now().year+543,staff_names=[u.name for u in User.query.filter(member_filter(current_user().organization_id)).filter_by(status="approved").all()] if current_user() else [],faculties=FACULTIES,form_catalog=FORM_CATALOG,sac_form_categories=SAC_FORM_CATEGORIES,member_organizations=Organization.query.filter(Organization.id.in_(membership_ids(current_user()))).order_by(Organization.id).all() if current_user() else [],organizations=Organization.query.order_by(Organization.id).all())
    @app.errorhandler(ValidationError)
    def invalid(e):
        db.session.rollback()
        return jsonify(error=str(e)),400
    @app.errorhandler(IntegrityError)
    def conflict(e):
        db.session.rollback()
        return jsonify(error='ข้อมูลซ้ำ กรุณาลองใหม่'),409
    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def http_error(e):
        if request.path.startswith('/api/'): return jsonify(error=e.description),e.code
        if e.code==404: app.logger.error('HTTP 404 path=%s endpoint=%s',request.path,request.endpoint)
        return render_template('error.html',message=e.description),e.code
    def body():
        data=request.get_json(silent=True)
        if not isinstance(data,dict): raise ValidationError('ต้องส่งข้อมูลแบบ JSON object')
        return data
    def field(data,key,limit=300):
        value=data.get(key,'')
        if not isinstance(value,str) or not value.strip() or len(value)>limit: raise ValidationError('ข้อมูล '+key+' ไม่ถูกต้อง')
        return value.strip()
    def org(value):
        try: result=db.session.get(Organization,int(value))
        except (ValueError,TypeError): result=None
        if not result: raise ValidationError('กรุณาเลือกหน่วยงานที่มีอยู่ในระบบ')
        return result
    def scope():
        user=current_user()
        q=Document.query
        if user.role!='admin': q=q.filter(or_(Document.owner_org_id==user.organization_id,Document.id.in_(db.session.query(DocumentAccess.document_id).filter_by(organization_id=user.organization_id)),db.and_(Document.direction=='sent',Document.category.in_(['order','regulation','rule','announcement']),Document.status.notin_(['draft']),Document.deleted==False)))
        return q
    def get_document(id): return scope().filter_by(id=id).first_or_404()
    def can_edit_document(doc):
        return not doc.deleted and (current_user().role=='admin' or doc.owner_org_id==current_user().organization_id)
    def editable(doc):
        if doc.deleted: abort(403)
        if can_edit_document(doc): return
        if doc.direction=='sent' and doc.status!='draft': abort(403)
        writable(doc)
    def writable(doc):
        user=current_user()
        if user.role!='admin':
            recipients=DocumentRecipient.query.filter_by(document_id=doc.id).all()
            mine=next((r for r in recipients if r.organization_id==user.organization_id),None)
            if recipients:
                if not mine or mine.status in ['forwarded','completed']: abort(403,description='ไม่มีสิทธิ์ดำเนินการในส่วนของหน่วยงานนี้')
            elif user.organization_id!=doc.current_org_id: abort(403,description='หน่วยงานผู้ถือเอกสารปัจจุบันเท่านั้นที่ดำเนินการได้')
        if doc.deleted: raise ValidationError('กรุณากู้คืนเอกสารก่อนดำเนินการ')
    def audit(doc,event,changes):
        db.session.add(DocumentAuditLog(document_id=doc.id,actor_id=current_user().id,event=event,changes=json.dumps(changes,ensure_ascii=False),version=doc.version))
    def tracking(doc,action,note='',target=None,status=None):
        user=current_user()
        db.session.add(DocumentTracking(document_id=doc.id,actor_id=user.id,action=action,from_org=user.organization.name,to_org=target.name if target else user.organization.name,status=status or doc.status,note=note))
    # BEGIN IMMEDIATE ทำให้การอนุมัติโควตาและการออกเลขเป็นธุรกรรมเรียงลำดับ
    def lock():
        db.session.rollback()
        db.session.execute(text('BEGIN IMMEDIATE'))
    def number_base(organization,category='general',direction='sent'):
        # ทะเบียนรับแยกจากส่ง ส่วนหนังสือส่งปกติ/เวียนใช้ลำดับร่วมกัน
        labels={'order':'คำสั่ง','regulation':'ระเบียบ','rule':'ข้อบังคับ','announcement':'ประกาศ'}
        if category=='general': return organization.code+('รับ.' if direction=='received' else '')
        if category not in labels: raise ValidationError('ประเภททะเบียนไม่ถูกต้อง')
        name=organization.name
        if category=='announcement':
            if name=='องค์การนักศึกษา': name+='มหาวิทยาลัยขอนแก่น'
            return 'ประกาศ'+name+' ฉบับที่ '
        return labels[category]+name+' ที่ '
    def release_deleted_number(doc):
        details=json.loads(doc.send_details or '{}')
        if details.get('released_number'): return
        original=doc.number
        reservation=NumberReservation.query.filter_by(number=original).first()
        archived='trash:'+str(doc.id)+':'+original
        details['released_number']=original
        doc.send_details=json.dumps(details,ensure_ascii=False);doc.number=archived
        if reservation: reservation.number=archived
        audit(doc,'release_number',{'number':original,'reason':'แอดมินลบเอกสารและคืนเลขทะเบียน'})
        db.session.flush()
    def allocate(direction,organization_id=None,circular=False,category='general'):
        user=current_user();organization=org(organization_id) if organization_id else user.organization
        if not organization.code: raise ValidationError('หน่วยงานยังไม่มีตัวย่อ กรุณาติดต่อแอดมิน')
        # คืนเลขที่แอดมินเคยลบก่อนเพิ่มฟังก์ชันนี้ด้วย
        for deleted in Document.query.filter_by(owner_org_id=organization.id,direction=direction,deleted=True).all():
            last=DocumentAuditLog.query.filter_by(document_id=deleted.id,event='trash').order_by(DocumentAuditLog.id.desc()).first()
            if last and last.actor and last.actor.role=='admin': release_deleted_number(deleted)
        base=number_base(organization,category,direction)
        prefix=base+('ว.' if circular and direction=='sent' and category=='general' else '')
        year=str(now().year+543)
        numbers=[row[0] for row in db.session.query(NumberReservation.number).filter_by(organization_id=organization.id,direction=direction).all()]
        # รวมเลขเก่าในทะเบียนเดียวกันเพื่อไม่ย้อนลำดับหลังปรับรูปแบบ
        numbers += [d.number for d in Document.query.filter_by(owner_org_id=organization.id,direction=direction,category=category,deleted=False).all()]
        values=[]
        patterns=[re.compile(re.escape(base)+r'(?:ว\.)?([0-9]+)/'+year)]
        old_labels={'general':'','order':'คำสั่ง.','regulation':'ระเบียบ.','rule':'ข้อบังคับ.','announcement':'ประกาศ.'}
        if category!='general': patterns.append(re.compile(re.escape(organization.code+old_labels[category])+r'(?:ว\.)?([0-9]+)/'+year))
        elif direction=='received': patterns.append(re.compile(re.escape(organization.code)+r'(?:ว\.)?([0-9]+)/'+year))
        for number in numbers:
            for pattern in patterns:
                match=pattern.fullmatch(number)
                if match: values.append(int(match.group(1)));break
        digits=str(max(values+[0])+1)
        number=prefix+digits+'/'+year
        reservation=NumberReservation(number=number,direction=direction,user_id=user.id,organization_id=organization.id)
        db.session.add(reservation)
        return reservation
    def filters(q):
        if request.args.get('direction') in ['received','sent']: q=q.filter(Document.owner_org_id==current_user().organization_id)
        personal=request.args.get('workspace')=='personal'
        if personal:
            assigned=db.session.query(PersonalAssignment.document_id).filter_by(user_id=current_user().id)
            if request.args.get('status') in ['pending','received']: assigned=assigned.filter_by(status=request.args['status'])
            q=q.filter(Document.id.in_(assigned))
        search=request.args.get('q','').strip()
        if search: q=q.filter(or_(Document.title.contains(search,autoescape=True),Document.number.contains(search,autoescape=True),Document.sender.contains(search,autoescape=True)))
        for key in ['status','category','direction','priority']:
            if request.args.get(key) and not (personal and key in ['direction','status']): q=q.filter(getattr(Document,key)==request.args[key])
        for key in ['from','to']:
            if request.args.get(key):
                try: date=datetime.strptime(request.args[key],'%Y-%m-%d')
                except ValueError: raise ValidationError('รูปแบบวันที่ไม่ถูกต้อง')
                q=q.filter(Document.created_at>=date) if key=='from' else q.filter(Document.created_at<date+__import__('datetime').timedelta(days=1))
        return q

    @app.route('/login',methods=['GET','POST'])
    def login():
        error=None
        if request.method=='POST':
            email=request.form.get('email','').strip().lower()
            student=request.form.get('student_id','').strip()
            password=request.form.get('password','')
            user=User.query.filter_by(email=email,student_id=student).first() if re.fullmatch(r'[a-z0-9._%+\-]+@kkumail\.com',email) and re.fullmatch(r'[0-9]{9}-[0-9]',student) else None
            if not user or user.status=='deleted': error='ไม่พบข้อมูลผู้ใช้งานที่ตรงกับอีเมลและรหัสนักศึกษา'
            elif user.status!='approved': error='บัญชียังไม่ได้รับอนุมัติ หรือถูกระงับ กรุณาติดต่อเลขานุการองค์การนักศึกษา'
            else:
                # Serialize first-password claims and recheck identity/status after acquiring the lock.
                user_id=user.id
                lock();user=db.session.get(User,user_id)
                if not user or user.email!=email or user.student_id!=student or user.status!='approved':
                    error='ไม่พบข้อมูลผู้ใช้งานที่ได้รับอนุมัติ';db.session.rollback()
                elif not user.password_initialized:
                    if not 10<=len(password)<=128:
                        error='การตั้งรหัสผ่านครั้งแรกต้องมี 10–128 ตัวอักษร';db.session.rollback()
                    else:
                        user.password_hash=generate_password_hash(password);user.password_initialized=True
                        for reset in PasswordReset.query.filter_by(user_id=user.id).all():reset.consumed=True
                        db.session.add(UserApprovalLog(user_id=user.id,actor_id=user.id,action='initialize_password',changes=json.dumps({'source':'first_login','actor_name':user.name,'password_initialized':True},ensure_ascii=False)))
                elif not check_password_hash(user.password_hash,password):
                    error='รหัสผ่านไม่ถูกต้อง กรุณาตรวจสอบหรือกดลืมรหัสผ่าน';db.session.rollback()
                if not error:
                    user.last_login_at=now();user.login_count=(user.login_count or 0)+1;db.session.commit()
                    session.clear();session['user_id']=user.id;session['csrf_token']=secrets.token_hex(32)
                    return redirect(url_for('index'))
        return render_template('auth.html',mode='login',error=error)
    @app.post('/api/auth/phone-otp/send')
    def send_phone_otp():
        data=request.get_json(silent=True) or {}
        validate_phone(data.get('phone',''))
        return jsonify(error='ยังไม่มีผู้ให้บริการ SMS จึงยังส่ง OTP ยืนยันเบอร์จริงไม่ได้ กรุณาติดต่อผู้ดูแลระบบ',phone_verified=False),503

    @app.route('/register',methods=['GET','POST'])
    def register():
        error=None
        if request.method=='POST':
            try:
                email=request.form.get('email','').strip().lower();name=request.form.get('name','').strip();password=request.form.get('password','')
                organization=org(request.form.get('organization_id'))
                student_id=request.form.get('student_id','').strip();faculty=request.form.get('faculty','').strip()
                if not name or len(name)>120: raise ValidationError('กรุณากรอกชื่อ–นามสกุล')
                if faculty not in FACULTIES: raise ValidationError('กรุณาเลือกคณะ/วิทยาลัยจากรายการที่กำหนด')
                if not re.fullmatch(r'[0-9]{9}-[0-9]',student_id): raise ValidationError('รหัสนักศึกษาต้องเป็นตัวเลข 9 หลัก ตามด้วยขีดและตัวเลข 1 หลัก (xxxxxxxxx-x)')
                if not re.fullmatch(r'[a-z0-9._%+\-]+@kkumail\.com',email) or len(email)>180: raise ValidationError('ใช้อีเมล @kkumail.com เท่านั้น')
                phone=validate_phone(request.form.get('phone',''))
                if len(password)<10 or len(password)>128: raise ValidationError('รหัสผ่านต้องมี 10–128 ตัวอักษร')
                if User.query.filter_by(student_id=student_id).first(): raise ValidationError('รหัสนักศึกษานี้ลงทะเบียนแล้ว')
                if User.query.filter_by(email=email).first(): raise ValidationError('อีเมลนี้ลงทะเบียนแล้ว')
                db.session.add(User(name=name,email=email,student_id=student_id,faculty=faculty,requested_org_id=organization.id,profile=json.dumps({'phone':phone,'phone_verified':False},ensure_ascii=False),password_hash=generate_password_hash(password),organization_id=organization.id))
                db.session.commit()
                return render_template('auth.html',mode='success')
            except (ValidationError,IntegrityError) as e:
                db.session.rollback();error=str(e) if isinstance(e,ValidationError) else 'อีเมลนี้ลงทะเบียนแล้ว'
        return render_template('auth.html',mode='register',error=error)
    def digest(value):
        return hmac.new(app.secret_key.encode(),value.encode(),hashlib.sha256).hexdigest()
    def send_reset_email(email,code):
        config=app.config
        message=EmailMessage();message['Subject']='SUDMS: รหัสยืนยันการเปลี่ยนรหัสผ่าน'
        message['From']=config['SMTP_FROM'];message['To']=email
        message.set_content('รหัสยืนยันของคุณคือ '+code+'\nรหัสมีอายุ 10 นาที ใช้ได้ครั้งเดียว\nหากคุณไม่ได้ร้องขอ กรุณาไม่เปิดเผยรหัสนี้และไม่ต้องดำเนินการใด ๆ')
        security=config['SMTP_SECURITY'] or 'starttls'
        port=int(config['SMTP_PORT'] or (465 if security=='ssl' else 587))
        if security not in ['ssl','starttls']: raise ValueError('SMTP ต้องใช้ ssl หรือ starttls')
        factory=smtplib.SMTP_SSL if security=='ssl' else smtplib.SMTP
        kwargs={'context':ssl.create_default_context()} if security=='ssl' else {}
        with factory(config['SMTP_HOST'],port,timeout=20,**kwargs) as server:
            if security=='starttls': server.ehlo();server.starttls(context=ssl.create_default_context());server.ehlo()
            if config['SMTP_USERNAME']: server.login(config['SMTP_USERNAME'],config['SMTP_PASSWORD'])
            server.send_message(message)

    @app.route('/forgot-password',methods=['GET','POST'])
    def forgot_password():
        error=None
        if request.method=='POST':
            email=request.form.get('email','').strip().lower()
            if not re.fullmatch(r'[a-z0-9._%+\-]+@kkumail\.com',email) or len(email)>180:
                error='กรุณากรอกอีเมล @kkumail.com'
            elif not User.query.filter(User.email==email,User.status!='deleted').first():
                session.pop('reset_key',None)
                error='ไม่พบบัญชีผู้ใช้งานที่ลงทะเบียนด้วย KKU-Mail นี้ กรุณาตรวจสอบอีเมลหรือสมัครใช้งาน'
            elif not User.query.filter_by(email=email,status='approved').first():
                session.pop('reset_key',None)
                error='บัญชีนี้ยังไม่ได้รับอนุมัติ หรือถูกระงับ กรุณาติดต่อผู้ดูแลระบบ'
            elif not app.config['SMTP_HOST'] or not app.config['SMTP_FROM']:
                error='ยังไม่ได้ตั้งค่าระบบส่งอีเมล กรุณาติดต่อผู้ดูแลระบบ'
            else:
                lock();key=digest(email);entry=PasswordReset.query.filter_by(email_digest=key).first();time=now()
                if entry and entry.issued_at and (time-entry.issued_at).total_seconds()<60:
                    error='กรุณารออย่างน้อย 60 วินาทีก่อนขอรหัสใหม่';db.session.rollback()
                elif entry and entry.window_at and time-entry.window_at<timedelta(hours=1) and entry.send_count>=5:
                    error='ขอรหัสเกินกำหนด กรุณาลองใหม่ในอีก 1 ชั่วโมง';db.session.rollback()
                else:
                    if not entry: entry=PasswordReset(email_digest=key,send_count=0);db.session.add(entry)
                    if not entry.window_at or time-entry.window_at>=timedelta(hours=1): entry.window_at=time;entry.send_count=0
                    user=User.query.filter_by(email=email,status='approved').first();code=f'{secrets.randbelow(1000000):06d}'
                    entry.user_id=user.id if user else None;entry.code_hash=digest(key+':'+code)
                    entry.issued_at=time;entry.expires_at=time+timedelta(minutes=10);entry.attempts=0;entry.consumed=False;entry.send_count+=1
                    db.session.commit()
                    try:
                        if user: send_reset_email(email,code)
                    except (OSError,smtplib.SMTPException,ValueError):
                        # ไม่พิมพ์ OTP หรือรหัส SMTP ลง log และยกเลิก OTP ที่ส่งไม่สำเร็จ
                        entry.consumed=True;db.session.commit();error='ส่งอีเมลไม่สำเร็จ กรุณาติดต่อผู้ดูแลระบบหรือลองใหม่ภายหลัง'
                    if not error:
                        session['reset_key']=key
                        return redirect(url_for('reset_password'))
        return render_template('auth.html',mode='forgot',error=error)

    @app.route('/reset-password',methods=['GET','POST'])
    def reset_password():
        if not session.get('reset_key'): return redirect(url_for('forgot_password'))
        error=None
        if request.method=='POST':
            code=request.form.get('code','').strip();password=request.form.get('password','');confirm=request.form.get('confirm_password','')
            if not 10<=len(password)<=128 or password!=confirm:
                error='รหัสผ่านต้องมี 10–128 ตัวอักษร และตรงกับช่องยืนยัน'
            else:
                lock();entry=PasswordReset.query.filter_by(email_digest=session['reset_key']).first()
                if not entry or entry.consumed or not entry.expires_at or entry.expires_at<=now() or entry.attempts>=5:
                    error='รหัสหมดอายุหรือถูกใช้แล้ว กรุณาขอรหัสใหม่';db.session.rollback()
                else:
                    entry.attempts+=1
                    valid=bool(re.fullmatch(r'\d{6}',code)) and hmac.compare_digest(entry.code_hash,digest(entry.email_digest+':'+code))
                    user=db.session.get(User,entry.user_id) if entry.user_id else None
                    if not valid or not user or user.status!='approved':
                        if entry.attempts>=5: entry.consumed=True
                        db.session.commit();error='รหัสยืนยันไม่ถูกต้อง (ลองได้ไม่เกิน 5 ครั้ง)'
                    else:
                        user.password_hash=generate_password_hash(password);user.password_initialized=True;entry.consumed=True;db.session.commit()
                        session.clear();session['csrf_token']=secrets.token_hex(32)
                        return render_template('auth.html',mode='reset_success')
        return render_template('auth.html',mode='reset',error=error)

    @app.post('/logout')
    def logout(): session.clear();return redirect(url_for('login'))
    @app.get('/')
    @authenticated()
    def index(): return render_template('index.html')
    def document_files(doc):
        details=json.loads(doc.send_details or '{}')
        source_id=details.get('source_document_id')
        ids=[doc.id]
        if source_id:
            get_document(source_id)
            ids.append(source_id)
        return Attachment.query.filter(Attachment.document_id.in_(ids)).order_by(Attachment.id.desc()).all()
    @app.get('/documents/<int:id>')
    @authenticated()
    def detail(id):
        doc=get_document(id)
        if request.args.get('edit')=='1' and doc.direction=='sent':
            if not can_edit_document(doc): abort(403)
            return render_template('sent_edit.html',doc=doc,draft_doc=doc,attached_files=document_files(doc))
        return render_template('doc_detail.html',doc=doc,attached_files=document_files(doc))
    @app.get('/documents/<int:id>/edit')
    @authenticated()
    def edit_sent_page(id):
        doc=get_document(id)
        if not can_edit_document(doc): abort(403)
        if doc.direction!='sent': abort(400,description='ใช้ฟอร์มนี้กับหนังสือส่ง')
        return render_template('sent_edit.html',doc=doc,draft_doc=doc,attached_files=document_files(doc))

    @app.get('/admin')
    @authenticated(admin=True)
    def admin(): return render_template('admin.html')
    @app.get('/api/organizations')
    @authenticated()
    def list_orgs(): return jsonify([{'id':x.id,'name':x.name,'quota':x.quota,'code':x.code} for x in Organization.query.all()])
    @app.get('/api/organizations/members')
    @authenticated()
    def organization_members():
        return jsonify([{'id':u.id,'name':u.name,'position':u.position} for u in User.query.filter(member_filter(current_user().organization_id)).filter_by(status='approved').order_by(User.name).all()])
    @app.post('/api/admin/organizations')
    @authenticated(admin=True)
    def add_organization():
        data=body();lock();name=field(data,'name',180);code=field(data,'code',30)
        if not code.endswith('.'): code+='.'
        if not re.fullmatch(r'[A-Za-zก-๙.]+',code): raise ValidationError('ตัวย่อต้องเป็นตัวอักษรและจุด')
        if Organization.query.filter(or_(Organization.name==name,Organization.code==code)).first(): raise ValidationError('ชื่อหรือตัวย่อหน่วยงานซ้ำ')
        item=Organization(name=name,code=code,quota=5);db.session.add(item);db.session.commit()
        return jsonify(id=item.id,name=item.name,code=item.code,quota=5),201
    @app.get('/api/dashboard')
    @authenticated()
    def dashboard():
        q=filters(scope().filter_by(deleted=False))
        if request.args.get('workspace')=='personal':
            received=q.filter(Document.id.in_(db.session.query(PersonalAssignment.document_id).filter_by(user_id=current_user().id,status='received'))).count()
            return jsonify(total=q.count(),pending=pending_inbox(q).count(),received=received,sent=0,completed=0)
        return jsonify(total=q.count(),pending=pending_inbox(q).count(),received=q.filter_by(direction='received',owner_org_id=current_user().organization_id).count(),sent=q.filter_by(direction='sent',owner_org_id=current_user().organization_id).count(),completed=q.filter_by(status='completed').count())
    def validate_send_details(details,digital_only):
        if not isinstance(details,dict): raise ValidationError('ข้อมูลหนังสือส่งต้องเป็น object')
        result={}
        for key in ['document_type','document_date','due_date','owner_name','recipient_name','recipient_scope','internal_unit','external_unit','personnel','salutation','practice','note']:
            value=details.get(key,'')
            if not isinstance(value,str) or len(value)>(5000 if key in ['note','practice'] else 300): raise ValidationError('ข้อมูล '+key+' ไม่ถูกต้อง')
            result[key]=value.strip()
        result['document_type']=result['document_type'] or 'general'
        if result['document_type'] not in ['memo','external','certificate','sealed','minutes','authorization','order','regulation','rule','announcement','general']: raise ValidationError('ประเภทหนังสือไม่ถูกต้อง')
        for key in ['circular','paper_today']:
            if not isinstance(details.get(key,False),bool): raise ValidationError(key+' ต้องเป็น boolean')
            result[key]=details.get(key,False)
        if digital_only and result['paper_today']: raise ValidationError('DIGITAL เท่านั้น ไม่สามารถระบุส่งกระดาษวันนี้ได้')
        for key in ['document_date','due_date']:
            if result[key]:
                try: datetime.strptime(result[key],'%Y-%m-%d')
                except ValueError: raise ValidationError('วันที่ไม่ถูกต้อง')
        if result['due_date'] and result['document_date'] and result['due_date']<result['document_date']: raise ValidationError('วันครบกำหนดต้องไม่ก่อนวันที่หนังสือ')
        ids=details.get('recipient_org_ids',[])
        if not isinstance(ids,list): raise ValidationError('รายชื่อหน่วยงานต้องเป็นรายการ')
        if details.get('recipient_org_id'): ids=ids+[details['recipient_org_id']]
        result['recipient_org_ids']=list(dict.fromkeys(org(value).id for value in ids))
        for key,legacy in [('internal_units','internal_unit'),('external_units','external_unit'),('recipient_names','recipient_name')]:
            values=details.get(key,[])
            if not isinstance(values,list): raise ValidationError(key+' ต้องเป็นรายการ')
            if not values and result.get(legacy): values=[result[legacy]]
            if any(not isinstance(value,str) or len(value)>300 for value in values): raise ValidationError('ข้อมูล '+key+' ไม่ถูกต้อง')
            result[key]=list(dict.fromkeys(value.strip() for value in values if value.strip()))
        # ทุกช่องผู้รับไม่บังคับ และส่งภายใน/ภายนอกร่วมกันได้ ไม่มีเพดานจำนวนรายการ
        has_internal=bool(result['recipient_org_ids'] or result['internal_units'])
        has_external=bool(result['external_units'])
        result['recipient_scope']='mixed' if has_internal and has_external else 'external' if has_external else 'internal'
        result['recipient_org_names']=[org(oid).name for oid in result['recipient_org_ids']]
        result['recipient_org_id']=result['recipient_org_ids'][0] if result['recipient_org_ids'] else None
        result['external_unit']=result['external_units'][0] if result['external_units'] else ''
        result['recipient_name']=result['recipient_names'][0] if result['recipient_names'] else ''
        return result
    def require_recipient(details,target_id):
        # ผู้ใช้สามารถไม่ระบุผู้รับได้ตามรูปแบบการบันทึกหนังสือส่ง
        return
    def recipient_summary(details):
        names=[org(oid).name for oid in details.get('recipient_org_ids',[])]
        names=list(dict.fromkeys(names+details.get('internal_units',[])+details.get('external_units',[])))
        if not names: names=details.get('recipient_names',[])
        if not names: return 'ไม่ระบุผู้รับ'
        value=', '.join(names)
        return value if len(value)<=180 else names[0][:120]+' และอีก '+str(len(names)-1)+' รายการ'
    def add_recipients(doc,details):
        for oid in details.get('recipient_org_ids',[]):
            if not DocumentRecipient.query.filter_by(document_id=doc.id,organization_id=oid).first(): db.session.add(DocumentRecipient(document_id=doc.id,organization_id=oid))
            if not DocumentAccess.query.filter_by(document_id=doc.id,organization_id=oid).first(): db.session.add(DocumentAccess(document_id=doc.id,organization_id=oid))
    def pending_inbox(q):
        oid=current_user().organization_id
        if request.args.get('workspace')=='personal': return q.filter(Document.id.in_(db.session.query(PersonalAssignment.document_id).filter_by(user_id=current_user().id,status='pending')))
        waiting=db.session.query(DocumentRecipient.document_id).filter_by(organization_id=oid,status='pending')
        legacy=db.session.query(DocumentRecipient.document_id)
        return q.filter(Document.direction=='sent',Document.owner_org_id!=oid).filter(or_(Document.id.in_(waiting),db.and_(Document.current_org_id==oid,Document.status=='pending',~Document.id.in_(legacy))))
    def refresh_delivery_status(doc):
        rows=DocumentRecipient.query.filter_by(document_id=doc.id).all()
        active=[row for row in rows if row.status!='forwarded']
        if active:
            states={row.status for row in active}
            doc.status='pending' if 'pending' in states else 'in_progress' if 'in_progress' in states else 'received' if 'received' in states else 'completed'
            next_row=next((row for row in active if row.status!='completed'),active[0])
            doc.current_org_id=next_row.organization_id

    def circular_number(number,organization,circular,category='general',direction='sent'):
        base=number_base(organization,category,direction)
        # รักษาเลขเอกสารเดิมก่อนแยกชุดทะเบียน ไม่เปลี่ยนเลขย้อนหลัง
        if not number.startswith(base):
            legacy={'general':'','order':'คำสั่ง.','regulation':'ระเบียบ.','rule':'ข้อบังคับ.','announcement':'ประกาศ.'}
            old_base=organization.code+legacy.get(category,'')
            base=old_base if number.startswith(old_base) else organization.code
        match=re.fullmatch(re.escape(base)+r'(?:ว\.)?([0-9]+)/([0-9]{4})',number)
        if not match: raise ValidationError('รูปแบบเลขหนังสือไม่ถูกต้อง')
        digits=str(int(match.group(1)))
        return base+('ว.' if circular and category=='general' and direction=='sent' else '')+digits+'/'+match.group(2)
    def change_circular_number(doc,circular):
        owner=org(doc.owner_org_id);desired=circular_number(doc.number,owner,circular,doc.category)
        if desired==doc.number: return
        if Document.query.filter_by(number=desired).first() or NumberReservation.query.filter_by(number=desired).first(): raise ValidationError('เลขหนังสือเวียน/ปกตินี้ถูกใช้หรือจองแล้ว')
        before=doc.number
        reservation=NumberReservation.query.filter_by(number=before).first()
        if reservation: reservation.number=desired
        doc.number=desired
        audit(doc,'number_format',{'before':before,'after':desired,'circular':circular})

    def choose_number(direction,data,user,organization_id=None):
        number_org=org(organization_id) if organization_id else user.organization
        category=data.get('category','general') if direction=='sent' else 'general'
        base=number_base(number_org,category,direction)
        number=data.get('number','') or data.get('reservation_number','')
        if not isinstance(number,str): raise ValidationError('เลขหนังสือไม่ถูกต้อง')
        number=number.strip()
        if data.get('number') and data.get('reservation_number') and data['number']!=data['reservation_number']: raise ValidationError('เลือกเลขจองหรือกรอกเลขเองอย่างใดอย่างหนึ่ง')
        if not number:
            reservation=allocate(direction,organization_id,circular=direction=='sent' and data.get('send_details',{}).get('circular',False),category=category);reservation.source='auto';return reservation
        expected=re.escape(base)+r'(?:ว\.)?([0-9]+)/'+str(now().year+543)
        match=re.fullmatch(expected,number)
        if not match or int(match.group(1))<1 or len(number)>300: raise ValidationError('เลขหนังสือต้องตรงกับประเภททะเบียน ตามด้วยเลขลำดับ / ปี พ.ศ. ปัจจุบัน')
        circular=direction=='sent' and data.get('send_details',{}).get('circular',False)
        number=circular_number(number,number_org,'ว.' in number[len(base):],category,direction)
        desired=circular_number(number,number_org,circular,category,direction)
        reservation=NumberReservation.query.filter_by(number=number).first()
        if reservation:
            if reservation.used or reservation.organization_id!=number_org.id or reservation.direction!=direction: raise ValidationError('เลขหนังสือถูกใช้แล้วหรือไม่ตรงกับหน่วยงาน/ประเภททะเบียน')
            if desired!=number:
                if NumberReservation.query.filter_by(number=desired).first(): raise ValidationError('เลขหนังสือนี้ถูกใช้หรือจองแล้ว')
                existing=Document.query.filter_by(number=number).first()
                if existing:
                    if existing.deleted or existing.status!='draft' or not json.loads(existing.send_details or '{}').get('reservation_only'): raise ValidationError('เลขจองมีเอกสารแล้ว')
                    change_circular_number(existing,circular)
                else: reservation.number=desired
            return reservation
        if data.get('reservation_number'): raise ValidationError('ไม่พบเลขที่จองไว้')
        opposite=circular_number(desired,number_org,not circular,category,direction)
        if NumberReservation.query.filter_by(number=opposite).first(): raise ValidationError('เลขลำดับนี้ถูกใช้หรือจองแล้ว')
        reservation=NumberReservation(number=desired,direction=direction,user_id=user.id,organization_id=number_org.id,source='manual')
        db.session.add(reservation);return reservation

    @app.route('/api/documents/<direction>',methods=['GET','POST'])
    @authenticated()
    def documents(direction):
        if direction not in ['received','sent','all']: abort(404)
        if request.method=='GET':
            q=scope().filter_by(deleted=request.args.get('trash')=='1')
            personal=request.args.get('workspace')=='personal'
            if personal and direction=='received': q=q.filter(Document.id.in_(db.session.query(PersonalAssignment.document_id).filter_by(user_id=current_user().id,status='received')))
            elif direction!='all': q=q.filter_by(direction=direction,owner_org_id=current_user().organization_id)
            if request.args.get('inbox')=='1': q=pending_inbox(q)
            q=filters(q)
            try: page=max(1,int(request.args.get('page',1)))
            except ValueError: raise ValidationError('เลขหน้าไม่ถูกต้อง')
            result=q.order_by(Document.created_at.desc(),Document.id.desc()).paginate(page=page,per_page=15,error_out=False)
            items=[]
            for doc in result.items:
                value=doc.to_dict()
                if personal:
                    assignment=PersonalAssignment.query.filter_by(document_id=doc.id,user_id=current_user().id).first()
                    if assignment:
                        value['status']=assignment.status;value['assignment_status']=assignment.status
                        if direction=='received': value['direction']='received'
                items.append(value)
            return jsonify(items=items,total=result.total,pages=result.pages,page=page)
        if direction=='all': abort(405)
        data=body();title=field(data,'title');sender=field(data,'sender',180)
        category=data.get('category','general');priority=data.get('priority','normal')
        if category not in ['general','order','regulation','rule','announcement'] or priority not in ['normal','urgent','very_urgent','most_urgent']: raise ValidationError('ประเภทหรือความเร่งด่วนไม่ถูกต้อง')
        content=data.get('content','')
        if not isinstance(content,str) or len(content)>20000: raise ValidationError('รายละเอียดไม่ถูกต้อง')
        if not isinstance(data.get('digital_only',True),bool): raise ValidationError('digital_only ต้องเป็น boolean')
        mode=data.get('save_mode','send')
        if mode not in ['draft','send'] or (direction=='received' and mode=='draft'): raise ValidationError('โหมดบันทึกไม่ถูกต้อง')
        details=validate_send_details(data.get('send_details',{}),data.get('digital_only',True)) if direction=='sent' else {}
        recipient_id=details.get('recipient_org_id') or data.get('recipient_org_id')
        if direction=='received':
            target=org(recipient_id)
            if target.id!=current_user().organization_id: raise ValidationError('ลงทะเบียนรับได้เฉพาะหน่วยงานของตนเอง กรุณาใช้หนังสือส่งเพื่อส่งไปหน่วยงานอื่น')
            target_id=target.id;target_name=target.name
        else:
            target=org(recipient_id) if recipient_id else None
            if target and target.id not in details['recipient_org_ids']: details['recipient_org_ids'].insert(0,target.id)
            details=validate_send_details(details,data.get('digital_only',True))
            target_id=target.id if target else None
            target_name=recipient_summary(details)
            if mode=='send': require_recipient(details,target_id)
            if target: details['recipient_org_id']=target.id
        if category!='general' and direction=='sent':
            if not details.get('owner_name') or not details.get('document_date'): raise ValidationError('กรุณาระบุเจ้าของเรื่องและวันที่หนังสือ')
            if details.get('circular'): raise ValidationError('ทะเบียนประเภทนี้ไม่ใช้รหัสเวียน')
        lock();user=current_user()
        reservation=choose_number(direction,data,user)
        reservation.used=True;reservation.used_by=user.id;reservation.used_at=now()
        draft=direction=='sent' and mode=='draft'
        state='received' if direction=='received' else 'draft' if draft else ('pending' if target_id else 'sent_external' if details.get('recipient_scope')=='external' else 'sent_recorded')
        values=dict(direction=direction,title=title,sender=sender,recipient=target_name,owner_org_id=user.organization_id,current_org_id=user.organization_id if draft or not target_id else target_id,category=category,priority=priority,content=content,digital_only=data.get('digital_only',True),status=state,send_details=json.dumps(details,ensure_ascii=False) if direction=='sent' else None)
        doc=Document.query.filter_by(number=reservation.number).first()
        if doc:
            if direction!='sent' or doc.deleted or doc.status!='draft' or doc.owner_org_id!=user.organization_id or not json.loads(doc.send_details or '{}').get('reservation_only'): raise ValidationError('เลขหนังสือนี้มีเอกสารแล้ว กรุณาเปิดแก้ไขจากรายการเดิม')
            for key,value in values.items(): setattr(doc,key,value)
        else:
            doc=Document(number=reservation.number,created_by=user.id,**values);db.session.add(doc)
        db.session.flush()
        access={user.organization_id}
        if not draft and target_id: access.add(target_id)
        if direction=='sent' and not draft: add_recipients(doc,details)
        for oid in access:
            if not DocumentAccess.query.filter_by(document_id=doc.id,organization_id=oid).first(): db.session.add(DocumentAccess(document_id=doc.id,organization_id=oid))
        tracking(doc,'draft' if draft else 'create','บันทึกร่างรอส่ง' if draft else 'ลงทะเบียนหนังสือ',db.session.get(Organization,user.organization_id if draft else target_id) if target_id or draft else None)
        audit(doc,'draft' if draft else 'create',{'document':doc.to_dict(),'number_reserved_by':db.session.get(User,reservation.user_id).name,'number_used_by':user.name})
        if direction=='sent' and not draft:
            
            for oid in details.get('recipient_org_ids',[]) or [None]: tracking(doc,'send','บันทึกและส่งหนังสือ',db.session.get(Organization,oid) if oid else None)
            audit(doc,'send',{'recipient':target_name,'actor':user.name,'delivery_mode':'digital' if doc.digital_only else 'paper'})
        db.session.commit();return jsonify(doc.to_dict()),201
    @app.post('/api/numbers/<direction>/reserve')
    @authenticated()
    def reserve(direction):
        if direction not in ['received','sent']: abort(404)
        data=body();lock();oid=current_user().organization_id
        if data.get('organization_id'):
            requested=org(data['organization_id']).id
            if requested!=oid and current_user().role!='admin': abort(403)
            oid=requested
        if not isinstance(data.get('circular',False),bool): raise ValidationError('circular ต้องเป็น boolean')
        category=data.get('category','general') if direction=='sent' else 'general'
        number_base(org(oid),category)
        r=allocate(direction,oid,circular=data.get('circular',False),category=category)
        document_id=None
        if direction=='sent':
            db.session.flush();user=current_user();owner=org(oid)
            details={'reservation_only':True,'circular':data.get('circular',False),'reserved_by':user.name,'document_type':'memo' if category=='general' else category,'document_date':now().date().isoformat(),'owner_name':user.name,'recipient_scope':'internal'}
            doc=Document(number=r.number,direction='sent',category=category,title='จอง ('+user.name+')',sender=owner.name,recipient='—',owner_org_id=oid,current_org_id=oid,created_by=user.id,status='draft',send_details=json.dumps(details,ensure_ascii=False),digital_only=True)
            db.session.add(doc);db.session.flush();document_id=doc.id
            db.session.add(DocumentAccess(document_id=doc.id,organization_id=oid))
            tracking(doc,'reserve','จองเลขหนังสือส่ง',owner)
            audit(doc,'reserve',{'number':r.number,'reserved_by':user.name,'reserved_at':stamp(r.created_at)})
        db.session.commit();return jsonify(number=r.number,document_id=document_id,edit_url='/documents/'+str(document_id)+'?edit=1' if document_id else None),201
    @app.get('/api/numbers/<direction>')
    @authenticated()
    def reserved(direction): return jsonify([r.number for r in NumberReservation.query.filter_by(direction=direction,organization_id=current_user().organization_id,used=False).all()])
    @app.get('/api/numbers/<direction>/details')
    @authenticated()
    def reservation_details(direction):
        if direction not in ['received','sent']: abort(404)
        oid=current_user().organization_id
        if request.args.get('organization_id'):
            requested=org(request.args['organization_id']).id
            if requested!=oid and current_user().role!='admin': abort(403)
            oid=requested
        reservations=NumberReservation.query.filter_by(direction=direction,organization_id=oid).order_by(NumberReservation.id.desc()).all()
        reserved_documents={d.number:d.id for d in Document.query.filter(Document.number.in_([r.number for r in reservations]),Document.deleted==False).all()}
        people={u.id:u.name for u in User.query.filter(User.id.in_({r.user_id for r in reservations}|{r.used_by for r in reservations if r.used_by})).all()}
        return jsonify([{'number':r.number,'category':next((d.category for d in Document.query.filter_by(number=r.number).all()),'general'),'reserved_by':people.get(r.user_id),'reserved_at':stamp(r.created_at),'used':r.used,'used_by':people.get(r.used_by),'used_at':stamp(r.used_at),'source':r.source,'document_id':reserved_documents.get(r.number),'edit_url':'/documents/'+str(reserved_documents[r.number])+'?edit=1' if r.number in reserved_documents else None} for r in reservations])
    @app.get('/api/documents/<int:id>/history')
    @authenticated()
    def history(id):
        doc=get_document(id)
        reservation=NumberReservation.query.filter_by(number=doc.number).first()
        number_history={'number':doc.display_number,'reserved_by':db.session.get(User,reservation.user_id).name,'reserved_at':stamp(reservation.created_at),'used_by':db.session.get(User,reservation.used_by).name if reservation.used_by else None,'source':reservation.source} if reservation else None
        recipients=DocumentRecipient.query.filter_by(document_id=id).all()
        timeline_query=DocumentTracking.query.filter_by(document_id=id)
        selected=request.args.get('organization_id')
        if selected:
            organization=org(selected)
            if organization.id not in {r.organization_id for r in recipients}|{doc.owner_org_id}: abort(404)
            timeline_query=timeline_query.filter(or_(DocumentTracking.to_org==organization.name,db.and_(DocumentTracking.from_org==organization.name,DocumentTracking.action!='send')))
        mine=next((r for r in recipients if r.organization_id==current_user().organization_id and r.status not in ['forwarded','completed']),None)
        assignments=[]
        if current_user().role=='admin' or doc.owner_org_id==current_user().organization_id:
            latest={}
            for entry in DocumentAuditLog.query.filter_by(document_id=id,event='assign').order_by(DocumentAuditLog.id.desc()).all():
                details=json.loads(entry.changes)
                uid=details.get('assigned_to_id')
                if uid not in latest:
                    assignment=PersonalAssignment.query.filter_by(document_id=id,user_id=uid).first()
                    latest[uid]={'status':assignment.status if assignment else 'pending','accepted_at':stamp(assignment.accepted_at) if assignment else None,'name':details.get('assigned_to',''),'practice':details.get('practice',''),'note':details.get('note',''),'assigned_by':entry.actor.name,'assigned_at':stamp(entry.created_at)}
            assignments=list(latest.values())
        return jsonify(assignments=assignments,deliveries=[{'organization_id':r.organization_id,'organization':org(r.organization_id).name,'status':r.status,'updated_at':stamp(r.updated_at)} for r in recipients],number_reservation=number_history,document=doc.to_dict(),can_edit=can_edit_document(doc),can_act=not doc.deleted and (current_user().role=='admin' or bool(mine) or (not recipients and current_user().organization_id==doc.current_org_id)),
            timeline=[{'id':t.id,'actor':t.actor.name,'action':t.action,'from_org':t.from_org,'to_org':t.to_org,'status':t.status,'note':t.note,'created_at':stamp(t.created_at)} for t in timeline_query.order_by(DocumentTracking.id)],
            audit=[{'id':a.id,'actor':a.actor.name,'event':a.event,'changes':json.loads(a.changes),'version':a.version,'created_at':stamp(a.created_at)} for a in DocumentAuditLog.query.filter_by(document_id=id).order_by(DocumentAuditLog.id.desc())],
            attachments=[{'id':a.id,'filename':a.filename,'version':a.version,'sha256':a.sha256,'created_at':stamp(a.created_at)} for a in document_files(doc)])
    def assign_person(doc,user_id,practice='',note=''):
        if not user_id: return
        if not isinstance(practice,str) or not isinstance(note,str) or len(practice)>5000 or len(note)>5000: raise ValidationError('การปฏิบัติและหมายเหตุแต่ละช่องต้องไม่เกิน 5,000 ตัวอักษร')
        try: member=db.session.get(User,int(user_id))
        except (ValueError,TypeError): member=None
        if not member or member.status!='approved' or current_user().organization_id not in membership_ids(member): raise ValidationError('เลือกบุคคลที่ใช้งานในหน่วยงานของตนเองเท่านั้น')
        assignment=PersonalAssignment.query.filter_by(document_id=doc.id,user_id=member.id).first()
        if not assignment:
            db.session.add(PersonalAssignment(document_id=doc.id,user_id=member.id,assigned_by=current_user().id,status='pending'))
        else:
            assignment.status='pending';assignment.accepted_at=None;assignment.assigned_by=current_user().id;assignment.created_at=now()
        # บันทึกทุกครั้ง รวมถึงมอบหมายซ้ำพร้อมคำสั่งใหม่ โดยไม่ทับประวัติเดิม
        audit(doc,'assign',{'assigned_to':member.name,'assigned_to_id':member.id,'practice':practice.strip(),'note':note.strip()})
    def register_received_document(source,data):
        user=current_user();oid=user.organization_id
        if ReceivedRegistration.query.filter_by(source_document_id=source.id,organization_id=oid).first(): raise ValidationError('หน่วยงานนี้ลงทะเบียนรับเอกสารแล้ว')
        recipient=DocumentRecipient.query.filter_by(document_id=source.id,organization_id=oid,status='pending').first()
        if source.direction!='sent' or source.owner_org_id==oid: raise ValidationError('ลงทะเบียนรับได้เฉพาะหนังสือที่หน่วยงานอื่นส่งเข้ามา')
        if not recipient and not (source.current_org_id==oid and source.status=='pending'): abort(403)
        details={'source_document_id':source.id,'source_number':source.display_number,'source_sender':source.sender}
        for key in ['salutation','practice','note']:
            value=data.get(key,'')
            if not isinstance(value,str) or len(value)>5000: raise ValidationError('ข้อมูลรับเอกสารไม่ถูกต้อง')
            details[key]=value
        reservation=allocate('received',oid)
        copy=Document(number=reservation.number,direction='received',category='general',title=source.title,sender=source.sender,recipient=user.organization.name,owner_org_id=oid,current_org_id=oid,created_by=user.id,status='received',priority=source.priority,content=source.content,digital_only=source.digital_only,send_details=json.dumps(details,ensure_ascii=False))
        db.session.add(copy);db.session.flush()
        reservation.used=True;reservation.used_by=user.id;reservation.used_at=now()
        db.session.add(DocumentAccess(document_id=copy.id,organization_id=oid))
        db.session.add(ReceivedRegistration(source_document_id=source.id,organization_id=oid,received_document_id=copy.id,registered_by=user.id))
        assign_person(copy,data.get('assignee_id'),data.get('practice',''),data.get('note',''))
        tracking(copy,'receive','ลงทะเบียนรับจาก '+source.display_number,user.organization)
        audit(copy,'register_receive',{'source_id':source.id,'source_number':source.display_number,'receive_number':copy.number,'registered_by':user.name})
        return copy
    @app.post('/api/documents/<int:id>/receive-registration')
    @authenticated()
    def receive_registration(id):
        return action(id,body() | {'action':'receive'})
    @app.post('/api/documents/<int:id>/personal-receive')
    @authenticated()
    def receive_personal_assignment(id):
        data=body();lock();doc=get_document(id)
        if doc.deleted: abort(403)
        assignment=PersonalAssignment.query.filter_by(document_id=id,user_id=current_user().id).first()
        if not assignment: abort(403)
        if assignment.status!='pending': raise ValidationError('รับงานนี้แล้ว')
        values={}
        for key in ['practice','note']:
            value=data.get(key,'')
            if not isinstance(value,str) or len(value)>5000: raise ValidationError('ข้อความต้องไม่เกิน 5,000 ตัวอักษร')
            values[key]=value.strip()
        assignment.status='received';assignment.accepted_at=now()
        audit(doc,'personal_receive',values|{'received_by':current_user().name,'user_id':current_user().id})
        db.session.commit();return jsonify(received_document_id=doc.id,status='received')
    @app.post('/api/documents/<int:id>/assign')
    @authenticated()
    def assign_document(id):
        data=body();lock();doc=get_document(id)
        if doc.owner_org_id!=current_user().organization_id or doc.deleted: abort(403)
        if not data.get('assignee_id'): raise ValidationError('กรุณาเลือกผู้รับผิดชอบ')
        assign_person(doc,data['assignee_id'],data.get('practice',''),data.get('note',''));db.session.commit();return jsonify(ok=True)
    @app.post('/api/documents/<int:id>/action')
    @authenticated()
    def action(id,data_override=None):
        data=data_override if data_override is not None else body();lock();doc=get_document(id);writable(doc)
        act=data.get('action');note=data.get('note','')
        if not isinstance(note,str) or len(note)>5000: raise ValidationError('ข้อความยาวเกินกำหนด')
        if act not in ['receive','forward','instruct','endorse','complete','send']: raise ValidationError('การดำเนินการไม่ถูกต้อง')
        if doc.status=='draft' and act!='send': raise ValidationError('ร่างหนังสือต้องส่งก่อนดำเนินการอื่น')
        if act=='send' and (doc.direction!='sent' or doc.status!='draft'): raise ValidationError('ส่งได้เฉพาะร่างหนังสือส่ง')
        if doc.status=='completed': raise ValidationError('เอกสารดำเนินการเสร็จแล้ว')
        recipient=DocumentRecipient.query.filter_by(document_id=id,organization_id=current_user().organization_id).first()
        if not recipient and current_user().role=='admin': recipient=DocumentRecipient.query.filter_by(document_id=id,organization_id=doc.current_org_id).first()
        if act=='receive' and (recipient.status if recipient else doc.status)!='pending': raise ValidationError('หน่วยงานนี้รับหนังสือแล้ว')
        if act in ['instruct','endorse'] and not note.strip(): raise ValidationError('กรุณากรอกคำสั่งหรือการเกษียณหนังสือ')
        target=None;old=doc.to_dict();received_copy=None
        if act=='receive': received_copy=register_received_document(doc,data)
        if act=='send':
            details=validate_send_details(json.loads(doc.send_details or '{}'),doc.digital_only)
            if json.loads(doc.send_details or '{}').get('reservation_only'): raise ValidationError('กรุณาเปิดแก้ไขและกรอกข้อมูลหนังสือก่อนส่ง')
            ids=details['recipient_org_ids'];target=org(ids[0]) if ids else None
            doc.current_org_id=target.id if target else doc.owner_org_id
            doc.recipient=recipient_summary(details)
            doc.status='pending' if ids else 'sent_external' if details['external_units'] else 'sent_recorded'
            doc.send_details=json.dumps(details,ensure_ascii=False)
            add_recipients(doc,details)
        elif act=='forward':
            target=org(data.get('recipient_org_id'))
            if target.id==(recipient.organization_id if recipient else doc.current_org_id): raise ValidationError('กรุณาเลือกหน่วยงานอื่น')
            if recipient: recipient.status='forwarded';recipient.updated_at=now()
            if DocumentRecipient.query.filter_by(document_id=id).first():
                if not DocumentRecipient.query.filter_by(document_id=id,organization_id=target.id).first(): db.session.add(DocumentRecipient(document_id=id,organization_id=target.id))
            doc.current_org_id=target.id;doc.status='pending'
            if not DocumentAccess.query.filter_by(document_id=id,organization_id=target.id).first(): db.session.add(DocumentAccess(document_id=id,organization_id=target.id))
        else:
            state={'receive':'received','instruct':'in_progress','endorse':'in_progress','complete':'completed'}[act]
            if recipient: recipient.status=state;recipient.updated_at=now()
            doc.status=state
        if act!='send' and DocumentRecipient.query.filter_by(document_id=id).first(): refresh_delivery_status(doc)
        doc.updated_at=now()
        if act=='send':
            for oid in details['recipient_org_ids'] or [None]: tracking(doc,act,note,org(oid) if oid else None)
        else: tracking(doc,act,note,target,status=recipient.status if recipient else None)
        audit(doc,act,{'before':old,'after':doc.to_dict(),'note':note});db.session.commit()
        return jsonify(doc.to_dict() | ({'received_document_id':received_copy.id} if received_copy else {}))
    @app.patch('/api/documents/<int:id>')
    @authenticated()
    def edit(id):
        data=body();lock();doc=get_document(id);editable(doc);old=doc.to_dict()
        for key in ['title','sender','content']:
            if key in data:
                value=data[key]
                if not isinstance(value,str) or len(value)>(20000 if key=='content' else 180 if key=='sender' else 300) or (key!='content' and not value.strip()): raise ValidationError('ข้อมูล '+key+' ไม่ถูกต้อง')
                setattr(doc,key,value.strip())
        if 'send_details' in data:
            if doc.direction!='sent': raise ValidationError('ข้อมูลการส่งใช้กับหนังสือส่งเท่านั้น')
            details=validate_send_details(data['send_details'],data.get('digital_only',doc.digital_only))
            if doc.category!='general' and (not details.get('owner_name') or not details.get('document_date')): raise ValidationError('กรุณาระบุเจ้าของเรื่องและวันที่หนังสือ')
            if doc.status!='draft':
                previous=json.loads(doc.send_details or '{}')
                if details['circular']!=previous.get('circular',False) or set(details['recipient_org_ids'])!=set(previous.get('recipient_org_ids',[])): raise ValidationError('หนังสือที่ส่งแล้วแก้ข้อมูลได้ แต่เปลี่ยนเลขเวียนหรือหน่วยงานที่จัดส่งแล้วไม่ได้')
            change_circular_number(doc,details['circular'])
            doc.send_details=json.dumps(details,ensure_ascii=False)
            doc.recipient=recipient_summary(details)
        if 'digital_only' in data:
            if not isinstance(data['digital_only'],bool): raise ValidationError('digital_only ต้องเป็น boolean')
            if doc.status!='draft' and data['digital_only']!=doc.digital_only: raise ValidationError('เปลี่ยนวิธีส่งได้เฉพาะร่าง')
            if 'send_details' not in data and doc.direction=='sent': validate_send_details(json.loads(doc.send_details or '{}'),data['digital_only'])
            doc.digital_only=data['digital_only']
        for key,allowed in [('priority',['normal','urgent','very_urgent','most_urgent']),('category',['general','order','regulation','rule','announcement'])]:
            if key in data:
                if data[key] not in allowed: raise ValidationError('ข้อมูล '+key+' ไม่ถูกต้อง')
                if key=='category' and data[key]!=doc.category: raise ValidationError('เลขทะเบียนนี้อยู่ในประเภทเดิม กรุณาจองเลขใหม่ในประเภทที่ต้องการ')
                setattr(doc,key,data[key])
        if data.get('number') or data.get('reservation_number'):
            requested_number=circular_number(data.get('number') or data.get('reservation_number'),org(doc.owner_org_id),json.loads(doc.send_details or '{}').get('circular',False),doc.category)
        else: requested_number=doc.number
        if requested_number!=doc.number:
            if doc.status!='draft': raise ValidationError('เปลี่ยนเลขหนังสือได้เฉพาะร่าง')
            reservation=choose_number('sent',data,current_user(),doc.owner_org_id)
            if Document.query.filter_by(number=reservation.number).first(): raise ValidationError('เลขจองนี้มีร่างแล้ว กรุณาเปิดร่างนั้นจากทะเบียน')
            old_reservation=NumberReservation.query.filter_by(number=doc.number).first()
            if old_reservation and not old_reservation.used: old_reservation.used=True;old_reservation.used_by=current_user().id;old_reservation.used_at=now()
            reservation.used=True;reservation.used_by=current_user().id;reservation.used_at=now();doc.number=reservation.number
        if doc.direction=='sent' and 'send_details' in data:
            reservation=NumberReservation.query.filter_by(number=doc.number).first()
            if reservation and not reservation.used: reservation.used=True;reservation.used_by=current_user().id;reservation.used_at=now()
        doc.updated_at=now();audit(doc,'edit',{'before':old,'after':doc.to_dict()});db.session.commit();return jsonify(doc.to_dict())
    @app.post('/api/documents/<int:id>/trash')
    @authenticated()
    def trash(id):
        data=body();lock();doc=get_document(id)
        if current_user().role!='admin' and doc.current_org_id!=current_user().organization_id: abort(403)
        restore=data.get('restore',False)
        if not isinstance(restore,bool): raise ValidationError('restore ต้องเป็น boolean')
        if restore:
            details=json.loads(doc.send_details or '{}');original=details.get('released_number')
            if original:
                base=original.split('/')[0].replace('ว.','');year=original.split('/')[-1]
                conflicts=Document.query.filter(Document.id!=doc.id,Document.deleted==False).all()
                reservations=NumberReservation.query.filter(NumberReservation.number!=doc.number).all()
                if any(n.split('/')[0].replace('ว.','')==base and n.split('/')[-1]==year for n in [d.number for d in conflicts]+[r.number for r in reservations] if '/' in n):
                    fresh=allocate(doc.direction,doc.owner_org_id,details.get('circular',False),doc.category)
                    fresh.used=True;fresh.used_by=current_user().id;fresh.used_at=now()
                    details['restored_original_number']=original
                    original=fresh.number
                    audit(doc,'restore_renumber',{'old_number':details['released_number'],'new_number':original})
                reservation=NumberReservation.query.filter_by(number=doc.number).first()
                if reservation and not details.get('restored_original_number'): reservation.number=original
                doc.number=original;details.pop('released_number');doc.send_details=json.dumps(details,ensure_ascii=False)
        else:
            doc.deleted=True
            if current_user().role=='admin': release_deleted_number(doc)
        doc.deleted=not restore;doc.updated_at=now();audit(doc,'restore' if restore else 'trash',{'deleted':doc.deleted});db.session.commit();return jsonify(ok=True)
    @app.post('/api/documents/<int:id>/attachments')
    @authenticated()
    def upload(id):
        lock();doc=get_document(id);editable(doc);file=request.files.get('file')
        if not file or not file.filename: raise ValidationError('กรุณาเลือกไฟล์')
        name=Path(file.filename.replace('\\','/')).name
        if len(name)>255 or Path(name).suffix.lower() not in ['.pdf','.docx']: raise ValidationError('รองรับ PDF และ DOCX เท่านั้น')
        raw=file.read()
        if not raw or (name.lower().endswith('.pdf') and not raw.startswith(b'%PDF-')): raise ValidationError('ไฟล์ PDF ไม่ถูกต้อง')
        if name.lower().endswith('.docx'):
            import zipfile
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    if 'word/document.xml' not in z.namelist(): raise ValueError()
            except (zipfile.BadZipFile,ValueError): raise ValidationError('ไฟล์ DOCX ไม่ถูกต้อง')
        minor=Attachment.query.filter_by(document_id=id).count();doc.version='v1.'+str(minor);doc.updated_at=now()
        storage=uuid.uuid4().hex+Path(name).suffix.lower();path=Path(app.config['UPLOAD_FOLDER'])/storage
        path.write_bytes(raw)
        try:
            attachment=Attachment(document_id=id,filename=name,storage_name=storage,sha256=hashlib.sha256(raw).hexdigest(),version=doc.version)
            db.session.add(attachment);audit(doc,'upload',{'filename':name,'sha256':attachment.sha256});db.session.commit()
        except Exception:
            path.unlink(missing_ok=True);db.session.rollback();raise
        return jsonify(version=doc.version),201
    @app.get('/api/attachments/<int:id>/download')
    @authenticated()
    def download(id):
        a=db.session.get(Attachment,id)
        if not a: abort(404)
        get_document(a.document_id)
        return send_file(Path(app.config['UPLOAD_FOLDER'])/a.storage_name,as_attachment=True,download_name=a.filename)
    @app.get('/api/attachments/<int:id>/view')
    @authenticated()
    def view_attachment(id):
        # ตรวจสิทธิ์เช่นเดียวกับดาวน์โหลด ไม่เปิดไฟล์ข้ามหน่วยงาน
        attachment=db.session.get(Attachment,id)
        if not attachment: abort(404)
        get_document(attachment.document_id)
        path=Path(app.config['UPLOAD_FOLDER'])/attachment.storage_name
        if not path.is_file(): abort(404,description='ไม่พบไฟล์แนบในระบบ')
        is_pdf=attachment.filename.lower().endswith('.pdf')
        response=send_file(path,as_attachment=not is_pdf,download_name=attachment.filename,
            mimetype='application/pdf' if is_pdf else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        response.headers['X-Content-Type-Options']='nosniff'
        return response
    @app.get('/api/reports/export')
    @authenticated()
    def export():
        import pandas as pd
        q=scope().filter_by(deleted=request.args.get('trash')=='1')
        if request.args.get('inbox')=='1': q=pending_inbox(q)
        rows=[d.to_dict() for d in filters(q).order_by(Document.id).all()]
        columns={'number':'เลขทะเบียน','title':'เรื่อง','direction':'ประเภท','sender':'จาก','recipient':'ถึง','status':'สถานะ','priority':'ความเร่งด่วน','version':'เวอร์ชัน','created_at':'วันเวลาลงทะเบียน'}
        # ป้องกันสูตร Excel ที่ซ่อนในข้อความผู้ใช้
        safe=lambda v: "'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v
        data=[{label:safe(row[key]) for key,label in columns.items()} for row in rows]
        output=io.BytesIO()
        with pd.ExcelWriter(output,engine='openpyxl') as writer:
            pd.DataFrame(data,columns=list(columns.values())).to_excel(writer,index=False,sheet_name='SUDMS')
            sheet=writer.sheets['SUDMS'];sheet.freeze_panes='A2';sheet.auto_filter.ref=sheet.dimensions
            for col in sheet.columns: sheet.column_dimensions[col[0].column_letter].width=26
        output.seek(0);return send_file(output,as_attachment=True,download_name='SUDMS-report.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    @app.get('/meeting-rooms')
    @authenticated()
    def meeting_rooms():
        from meeting_service import BOOKING_URL
        return render_template('meeting_rooms.html',booking_url=BOOKING_URL+'?r=landingpage%2Findex&department=6')
    @app.get('/api/meeting-rooms')
    @authenticated()
    def meeting_rooms_data():
        month=request.args.get('month',now().strftime('%Y-%m'))
        if not re.fullmatch(r'20[0-9]{2}-(?:0[1-9]|1[0-2])',month): raise ValidationError('เดือนต้องเป็น YYYY-MM')
        from meeting_service import load_month
        return jsonify(app.extensions['room_booking_calendar'](load_month(month),month))
    @app.get('/admin/organizations')
    @authenticated(admin=True)
    def organization_overview():
        rows=[{'organization':o,'approved':User.query.filter(member_filter(o.id)).filter_by(status='approved').count(),'total':User.query.filter(member_filter(o.id),User.status!='deleted').count()} for o in Organization.query.order_by(Organization.id).all()]
        return render_template('org_overview.html',organization_summary=rows)
    @app.get('/api/admin/users')
    @authenticated(admin=True)
    def users():
        # รวม log และชื่อผู้อนุมัติในคำขอเดียว ไม่รับชื่อ/เวลาผู้อนุมัติจาก browser
        history_by_user={}
        logs=UserApprovalLog.query.order_by(UserApprovalLog.id.desc()).all()
        names={u.id:u.name for u in User.query.all()}
        org_names={o.id:o.name for o in Organization.query.all()}
        for log in logs:
            changes=json.loads(log.changes or '{}')
            before=changes.get('before',{})
            after=changes.get('after',{})
            oid=after.get('organization_id',changes.get('organization_id'))
            history_by_user.setdefault(log.user_id,[]).append({
                'id':log.id,'action':log.action,'actor_id':log.actor_id,
                'actor_name':changes.get('actor_name') or names.get(log.actor_id,'ไม่พบข้อมูลผู้อนุมัติ'),
                'created_at':stamp(log.created_at),'organization_id':oid,
                'organization_name':changes.get('organization_name') or org_names.get(oid),
                'previous_organization':changes.get('previous_organization') or org_names.get(before.get('organization_id')),
                'source':changes.get('source'),'changes':changes})
        rows=[{'id':u.id,'name':u.name,'email':u.email,'student_id':u.student_id,'faculty':u.faculty,'position':u.position,'profile':json.loads(u.profile or '{}'),'password_initialized':u.password_initialized,'last_login_at':stamp(u.last_login_at),'login_count':u.login_count,'created_at':stamp(u.created_at),'organization_id':u.organization_id,'requested_organization':u.requested_organization.name if u.requested_organization else u.organization.name,'organization':u.organization.name,'status':u.status,'role':u.role} for u in User.query.filter(User.status!='deleted').order_by(User.created_at.desc())]
        for row in rows:
            history=history_by_user.get(row['id'],[])
            approvals=[h for h in history if h['action'] in ['approved','roster_import']]
            row['approval_history']=history
            row['approved_by']=approvals[0]['actor_name'] if approvals else None
            row['approved_at']=approvals[0]['created_at'] if approvals else None
            latest=history[0] if history else None
            row['organization_saved']=bool(row['status']=='approved' and latest and latest['action']=='approved' and latest['organization_id']==row['organization_id'])
        for row in rows:
            account=db.session.get(User,row['id']);row['organization_ids']=membership_ids(account);row['organizations']=[dict(id=o.id,name=o.name) for o in Organization.query.filter(Organization.id.in_(row['organization_ids'])).all()]
        return jsonify(rows)
    @app.route('/api/admin/users',methods=['POST'])
    @app.route('/api/admin/users/<int:id>',methods=['PATCH','DELETE'])
    @authenticated(admin=True)
    def manage_user(id=None):
        data=body();lock();actor=current_user()
        user=db.session.get(User,id) if id else None
        if id and (not user or user.status=='deleted'): abort(404)
        before={'name':user.name,'email':user.email,'role':user.role,'status':user.status,'organization_id':user.organization_id} if user else {}
        if request.method=='DELETE':
            if user.id==actor.id: raise ValidationError('ไม่สามารถลบบัญชีของตนเอง')
            if user.role=='admin' and User.query.filter_by(role='admin',status='approved').count()<=1: raise ValidationError('ต้องเหลือแอดมินอย่างน้อย 1 คน')
            # Keep the identity row for historical foreign keys, but release login identifiers.
            before=archive_user_identity(user)
            for entry in PasswordReset.query.filter_by(user_id=user.id).all(): entry.consumed=True
            event='delete_user'
        else:
            name=data.get('name',user.name if user else '')
            raw_email=data.get('email',user.email if user else '')
            if not isinstance(raw_email,str): raise ValidationError('อีเมลไม่ถูกต้อง')
            email=raw_email.strip().lower()
            student=data.get('student_id',user.student_id if user else '')
            faculty=data.get('faculty',user.faculty if user else '')
            position=data.get('position',user.position if user else '') or ''
            role=data.get('role',user.role if user else 'user')
            if not isinstance(name,str) or not name.strip() or len(name)>120: raise ValidationError('กรุณาระบุชื่อ–นามสกุล')
            if not re.fullmatch(r'[a-z0-9._%+\-]+@kkumail\.com',email) or len(email)>180: raise ValidationError('ใช้อีเมล @kkumail.com เท่านั้น')
            if not isinstance(student,str) or not re.fullmatch(r'[0-9]{9}-[0-9]',student): raise ValidationError('รหัสนักศึกษาไม่ถูกต้อง')
            if faculty not in FACULTIES: raise ValidationError('กรุณาเลือกคณะ/วิทยาลัย')
            if not isinstance(position,str) or len(position)>120 or role not in ['user','admin']: raise ValidationError('ตำแหน่งหรือสิทธิ์ไม่ถูกต้อง')
            if User.query.filter(User.id!=(id or 0),or_(User.email==email,User.student_id==student)).first(): raise ValidationError('อีเมลหรือรหัสนักศึกษานี้มีอยู่แล้ว')
            target=org(data.get('organization_id',user.organization_id if user else None))
            if not user or user.status=='approved':
                count=User.query.filter(member_filter(target.id)).filter_by(status='approved').filter(User.id!=(id or 0)).count()
                if count>=target.quota: raise ValidationError('ผู้ใช้งานครบโควตาหน่วยงานแล้ว')
            if user and user.role=='admin' and role!='admin' and user.status=='approved' and User.query.filter_by(role='admin',status='approved').count()<=1: raise ValidationError('ต้องเหลือแอดมินอย่างน้อย 1 คน')
            if role=='admin' and user and user.status!='approved': raise ValidationError('ต้องอนุมัติบัญชีก่อนแต่งตั้งแอดมิน')
            initial_password=data.get('initial_password','')
            if not isinstance(initial_password,str) or (initial_password and not 10<=len(initial_password)<=128): raise ValidationError('รหัสผ่านเริ่มต้นต้องมี 10–128 ตัวอักษร')
            if user and initial_password: raise ValidationError('รหัสผ่านเริ่มต้นใช้ได้เฉพาะตอนเพิ่มบัญชีใหม่')
            if not user:
                user=User(status='approved',password_initialized=bool(initial_password),password_hash=generate_password_hash(initial_password or secrets.token_urlsafe(32)))
                db.session.add(user)
            elif email!=user.email:
                user.password_initialized=False;user.password_hash=generate_password_hash(secrets.token_urlsafe(32))
                for entry in PasswordReset.query.filter_by(user_id=user.id).all(): entry.consumed=True
            user.name=name.strip();user.email=email;user.student_id=student;user.faculty=faculty;user.position=position;user.role=role;user.organization_id=target.id
            profile=data.get('profile',json.loads(user.profile or '{}'))
            if not isinstance(profile,dict): raise ValidationError('ข้อมูลประวัติไม่ถูกต้อง')
            allowed=['english_name','major','nickname_th','nickname_en','phone','year_column_1','year_column_2']
            profile=dict(profile)
            profile['phone']=validate_phone(profile.get('phone',''))
            for key in ['year_column_1','year_column_2']:
                if isinstance(profile.get(key),int): profile[key]=str(profile[key])
            if any(not isinstance(profile.get(k,''),str) or len(profile.get(k,''))>300 for k in allowed): raise ValidationError('ข้อมูลประวัติยาวเกินกำหนด')
            user.profile=json.dumps({k:profile.get(k,'') for k in allowed},ensure_ascii=False)
            event='edit_user' if id else 'create_user'
        db.session.flush()
        changes={'before':before,'after':{'name':user.name,'email':user.email,'role':user.role,'status':user.status,'organization_id':user.organization_id},'actor_name':actor.name}
        db.session.add(UserApprovalLog(actor_id=actor.id,user_id=user.id,action=event,changes=json.dumps(changes,ensure_ascii=False)))
        db.session.commit()
        return jsonify(id=user.id,status=user.status,role=user.role),201 if not id else 200
    @app.post('/api/admin/users/<int:id>/approval')
    @authenticated(admin=True)
    def approve(id):
        data=body();lock();user=db.session.get(User,id)
        if not user or user.status=='deleted': abort(404)
        if user.role=='admin': raise ValidationError('ไม่สามารถแก้ไขสถานะผู้ดูแลระบบผ่านหน้านี้')
        status=data.get('status')
        if status not in ['approved','rejected','suspended']: raise ValidationError('สถานะไม่ถูกต้อง')
        before={'organization_id':user.organization_id,'status':user.status}
        previous_organization=user.organization.name
        if status=='approved':
            target=org(data.get('organization_id'))
            count=User.query.filter(member_filter(target.id)).filter_by(status='approved').filter(User.id!=user.id).count()
            if count>=target.quota: raise ValidationError('ผู้ใช้งานครบโควตา '+str(target.quota)+' คนแล้ว')
            for membership in UserOrganization.query.filter_by(user_id=user.id):
                extra=db.session.get(Organization,membership.organization_id)
                if User.query.filter(member_filter(extra.id),User.status=='approved',User.id!=user.id).count()>=extra.quota:raise ValidationError('ผู้ใช้งานครบโควตา: '+extra.name)
            user.organization_id=target.id
        user.status=status
        changes={'before':before,'after':{'organization_id':user.organization_id,'status':status},'actor_name':current_user().name,'previous_organization':previous_organization,'organization_name':db.session.get(Organization,user.organization_id).name}
        db.session.add(UserApprovalLog(actor_id=current_user().id,user_id=id,action=status,changes=json.dumps(changes,ensure_ascii=False)))
        db.session.commit();return jsonify(ok=True)
    @app.post('/workspace/organization')
    @authenticated()
    def switch_organization():
        try:oid=int(request.form.get('organization_id',''))
        except (TypeError,ValueError):abort(400)
        account=db.session.get(User,current_user().id)
        if oid not in membership_ids(account):abort(403)
        session['active_organization_id']=oid
        return redirect('/')
    @app.put('/api/admin/users/<int:id>/organizations')
    @authenticated(admin=True)
    def update_memberships(id):
        lock();account=db.session.get(User,id)
        if not account or account.status=='deleted':abort(404)
        data=body();ids=data.get('organization_ids')
        if not isinstance(ids,list) or not ids or any(type(i)!=int for i in ids):raise ValidationError('กรุณาเลือกองค์กรกิจกรรม')
        ids=set(ids)
        if account.organization_id not in ids:raise ValidationError('ต้องคงองค์กรหลักไว้ หากต้องการเปลี่ยนให้แก้ไของค์กรหลักก่อน')
        if Organization.query.filter(Organization.id.in_(ids)).count()!=len(ids):raise ValidationError('ไม่พบองค์กรกิจกรรมที่เลือก')
        before=membership_ids(account)
        if account.status=='approved':
            for oid in ids:
                organization=db.session.get(Organization,oid)
                if User.query.filter(member_filter(oid),User.status=='approved',User.id!=id).count()>=organization.quota:raise ValidationError('สมาชิกครบโควตา: '+organization.name)
        UserOrganization.query.filter_by(user_id=id).delete(synchronize_session=False)
        for oid in ids-{account.organization_id}:db.session.add(UserOrganization(user_id=id,organization_id=oid))
        db.session.add(UserApprovalLog(actor_id=current_user().id,user_id=id,action='memberships',changes=json.dumps({'before':{'organization_ids':before},'after':{'organization_ids':sorted(ids)},'actor_name':current_user().name},ensure_ascii=False)))
        db.session.commit();return jsonify(organization_ids=sorted(ids))
    @app.get('/api/admin/quotas')
    @authenticated(admin=True)
    def quotas(): return jsonify([{'name':o.name,'quota':o.quota,'approved':User.query.filter(member_filter(o.id)).filter_by(status='approved').count()} for o in Organization.query.all()])
    @app.get('/api/forms/sac/<slug>/<format>')
    @authenticated()
    def sac_original_form(slug,format):
        item=SAC_FORM_ITEMS.get(slug)
        if not item:abort(404)
        file=next((entry for entry in item['local_files'] if entry['format'].lower()==format),None)
        if not file:abort(404)
        path=Path(app.root_path)/'form_files'/'sac'/file['filename']
        if not path.is_file():abort(404)
        response=send_file(path,as_attachment=True,download_name=item['title']+'.'+format)
        response.headers['X-Content-Type-Options']='nosniff'
        return response
    @app.get('/api/forms/files/<slug>/<format>')
    @authenticated()
    def original_form(slug,format):
        item=next((item for item in FORM_CATALOG if item['id']==slug),None)
        if not item or format not in ['pdf','docx']: abort(404)
        file=item['files'][format]
        path=Path(app.root_path)/'form_files'/file['filename']
        if not path.is_file(): abort(404,description='ไม่พบไฟล์แบบฟอร์มที่ต้องการ')
        mimetype='application/pdf' if format=='pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        return send_file(path,as_attachment=True,download_name=file['filename'],mimetype=mimetype)

    @app.get('/api/forms/<language>/<format>')
    @authenticated()
    def forms(language,format):
        if language not in ['general','english'] or format not in ['pdf','docx']: abort(404)
        # แบบฟอร์มตั้งต้นเพื่อปรับใช้ ไม่ใช่แบบฟอร์มทางการที่รับรองโดยมหาวิทยาลัย
        if format=='docx':
            from docx import Document as Word
            from docx.shared import Pt
            doc=Word();doc.styles['Normal'].font.name='Tahoma';doc.styles['Normal'].font.size=Pt(14)
            lines=['บันทึกข้อความ','ส่วนราชการ ........................................................','ที่ ........................ วันที่ ........................','เรื่อง ................................................................','เรียน ................................................................','...........................................................................','ลงชื่อ ........................................................','ตำแหน่ง ....................................................'] if language=='general' else ['OFFICIAL MEMORANDUM','Department: ____________________','Reference: __________ Date: __________','Subject: _________________________','To: _____________________________','________________________________','Signature: _______________________','Position: ________________________']
            for line in lines: doc.add_paragraph(line)
            output=io.BytesIO();doc.save(output)
        else:
            from reportlab.pdfgen import canvas
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'tahoma.ttf'
            if language=='general' and not font.exists(): raise ValidationError('ไม่พบฟอนต์ไทย Tahoma กรุณาดาวน์โหลด Word หรือกำหนดฟอนต์ไทยในโค้ด')
            fontname='Helvetica'
            if font.exists(): pdfmetrics.registerFont(TTFont('Thai',str(font)));fontname='Thai'
            output=io.BytesIO();c=canvas.Canvas(output);c.setFont(fontname,15)
            lines=['บันทึกข้อความ','ส่วนราชการ ........................................................','ที่ ........................ วันที่ ........................','เรื่อง ................................................................','เรียน ................................................................','...........................................................................','ลงชื่อ ........................................................','ตำแหน่ง ....................................................'] if language=='general' else ['OFFICIAL MEMORANDUM','Department: ____________________','Reference: __________ Date: __________','Subject: _________________________','To: _____________________________','________________________________','Signature: _______________________','Position: ________________________']
            for i,line in enumerate(lines): c.drawString(65,770-i*65,line)
            c.save()
        output.seek(0);return send_file(output,as_attachment=True,download_name='SUDMS-template-'+language+'.'+format)
    @app.cli.command('init-admin')
    @click.option('--email',prompt='Admin email')
    @click.option('--name',default='เลขานุการองค์การนักศึกษา',prompt='Admin name')
    @click.option('--student-id',prompt='Student ID (683050391-3)')
    @click.password_option(confirmation_prompt=True)
    def init_admin(email,name,student_id,password):
        """สร้างแอดมินคนแรกโดยไม่มีรหัสผ่านสำเร็จรูป"""
        if len(password)<10 or not re.fullmatch(r'[a-z0-9._%+\-]+@kkumail\.com',email.strip().lower()): raise click.ClickException('ใช้รหัสผ่านอย่างน้อย 10 ตัวอักษรและอีเมล @kkumail.com')
        if not re.fullmatch(r'[0-9]{9}-[0-9]',student_id): raise click.ClickException('รหัสนักศึกษาต้องเป็นตัวเลข 9 หลัก ตามด้วยขีดและตัวเลข 1 หลัก (xxxxxxxxx-x)')
        if User.query.filter_by(role='admin').first(): raise click.ClickException('มีแอดมินแล้ว')
        organization=Organization.query.filter_by(name='องค์การนักศึกษา').one()
        lock()
        if User.query.filter_by(role='admin').first() or User.query.filter_by(email=email.lower()).first(): raise click.ClickException('บัญชีหรือแอดมินมีอยู่แล้ว')
        db.session.add(User(name=name,email=email.strip().lower(),student_id=student_id,password_hash=generate_password_hash(password),organization_id=organization.id,role='admin',status='approved'));db.session.commit();click.echo('สร้างผู้ดูแลระบบสำเร็จ')
    from room_booking import register_room_booking
    register_room_booking(app, db, RoomBooking, User, Organization, authenticated, current_user, now, lock, ValidationError)
    from reporting import register_reporting
    register_reporting(app,db,Document,DocumentTracking,DocumentAuditLog,PersonalAssignment,RoomBooking,Organization,User,authenticated,current_user,now)
    from finance import register_finance
    register_finance(app, db, FinanceProject, FinanceExpense, FinanceAudit, Organization, User, authenticated, current_user, now, lock, ValidationError)
    return app

app=create_app()
if __name__=='__main__': app.run(host='127.0.0.1',port=5000,debug=False)
