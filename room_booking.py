"""Room requests, the SUDMS web calendar, and SMTP notifications."""
import io, re, uuid, zipfile, smtplib, ssl
from pathlib import Path
from datetime import datetime, timedelta
from email.message import EmailMessage
from flask import request, jsonify, abort, send_file

ROOM_NAME = 'ห้องประชุมองค์กรกิจกรรมนักศึกษา ชั้น 3 อาคารองค์กรกิจกรรมนักศึกษา (ห้องดำ)'

def register_room_booking(app, db, Booking, User, Organization, authenticated, current_user, now, lock, ValidationError):
    folder=Path(app.config['UPLOAD_FOLDER']).parent/'room_booking_uploads'
    folder.mkdir(parents=True,exist_ok=True)
    def serial(row,private=True):
        organization=db.session.get(Organization,row.organization_id) if row.organization_id else None
        result=dict(id=row.id,room=ROOM_NAME,requester_name=row.requester_name,activity=row.activity,organization=organization.name if organization else 'ส่วนตัว',start_date=row.start_date.isoformat(),end_date=row.end_date.isoformat(),start_time=row.start_time,end_time=row.end_time,days=(row.end_date-row.start_date).days+1,status=row.status,review_note=row.review_note,email_status=row.email_status,calendar_status='local',has_memo=bool(row.memo_storage),created_at=row.created_at.isoformat()+'+07:00')
        if private:result.update(email=row.email,phone=row.phone)
        return result
    def parse_period(values):
        try:
            start=datetime.strptime(values.get('start_date',''),'%Y-%m-%d').date()
            end=datetime.strptime(values.get('end_date','') or values.get('start_date',''),'%Y-%m-%d').date()
            begin=values.get('start_time','');finish=values.get('end_time','')
            for value in [begin,finish]:
                if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',value):raise ValueError()
        except (ValueError,TypeError):raise ValidationError('กรุณาระบุวันที่และเวลาให้ถูกต้อง')
        if start<now().date():raise ValidationError('ไม่สามารถจองวันที่ผ่านมาแล้ว')
        if end<start or (end-start).days>=31:raise ValidationError('วันที่สิ้นสุดต้องไม่ก่อนวันเริ่ม และจองได้ครั้งละไม่เกิน 31 วัน')
        if begin>=finish:raise ValidationError('เวลาสิ้นสุดต้องหลังเวลาเริ่ม (ใช้ช่วงเวลาเดียวกันทุกวัน)')
        if start==now().date() and begin<=now().strftime('%H:%M'):raise ValidationError('เวลาเริ่มต้องยังไม่ผ่านไป')
        return start,end,begin,finish
    def days_between(start,end):
        return [start+timedelta(days=i) for i in range((end-start).days+1)]
    def same_room(value):
        normalized=re.sub(r'\s+','',value or '')
        return normalized==re.sub(r'\s+','',ROOM_NAME) or 'ห้องดำ' in normalized
    def external_check(start,end,begin,finish,fresh=False,exclude_booking_id=None):
        from meeting_service import load_month
        datasets={day.strftime('%Y-%m'):load_month(day.strftime('%Y-%m'),refresh=fresh) for day in {d.replace(day=1) for d in days_between(start,end)}}
        issues=[]
        for day in days_between(start,end):
            data=datasets[day.strftime('%Y-%m')];iso=day.isoformat()
            if iso in data['failed_days']:
                issues.append({'date':iso,'reason':'อ่านปฏิทินต้นทางได้ไม่ครบ จึงยังยืนยันเวลาว่างไม่ได้'});continue
            for event in data['events']:
                if event['date']!=iso:continue
                if exclude_booking_id is not None and str(event.get('sudms_booking_id') or '')==str(exclude_booking_id):continue
                if not same_room(event.get('room')):continue
                times=re.findall(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',event.get('time',''))
                if len(times)<2 or (begin<times[1] and finish>times[0]):issues.append({'date':iso,'reason':'ชนกับรายการต้นทาง: '+event.get('time','ไม่ระบุเวลา')})
        return issues
    def local_conflicts(start,end,begin,finish,exclude=None):
        query=Booking.query.filter(Booking.status.in_(['pending','approved']),Booking.start_date<=end,Booking.end_date>=start,Booking.start_time<finish,Booking.end_time>begin)
        if exclude is not None:query=query.filter(Booking.id!=exclude)
        return query.count()>0
    @app.get('/api/room-bookings/availability')
    @authenticated()
    def room_availability():
        start,end,begin,finish=parse_period(request.args)
        issues=external_check(start,end,begin,finish)
        if local_conflicts(start,end,begin,finish):issues.append({'reason':'มีคำขอหรือรายการจองใน SUDMS ใช้ช่วงเวลานี้แล้ว'})
        return jsonify(available=not issues,issues=issues,room=ROOM_NAME)
    @app.get('/api/room-bookings/slots')
    @authenticated()
    def room_slots():
        try:
            day=datetime.strptime(request.args.get('date',''),'%Y-%m-%d').date()
            end_day=datetime.strptime(request.args.get('end_date') or request.args.get('date',''),'%Y-%m-%d').date()
            duration=int(request.args.get('duration','30'))
        except (ValueError,TypeError):raise ValidationError('วันที่หรือระยะเวลาไม่ถูกต้อง')
        if day<now().date():raise ValidationError('ไม่สามารถเลือกวันที่ผ่านมาแล้ว')
        if end_day<day or (end_day-day).days>=31:raise ValidationError('วันที่สิ้นสุดต้องไม่ก่อนวันเริ่ม และจองได้ครั้งละไม่เกิน 31 วัน')
        if duration<30 or duration>720 or duration%30:raise ValidationError('ระยะเวลาจองต้องเป็นช่วงละ 30 นาที และไม่เกิน 12 ชั่วโมง')
        slots=[]
        for minutes in range(0,24*60-duration+1,30):
            finish_minutes=minutes+duration
            if finish_minutes>=24*60:continue
            begin=f'{minutes//60:02d}:{minutes%60:02d}';finish=f'{finish_minutes//60:02d}:{finish_minutes%60:02d}'
            if day==now().date() and begin<=now().strftime('%H:%M'):continue
            issues=external_check(day,end_day,begin,finish)
            slots.append(dict(start=begin,end=finish,available=not issues and not local_conflicts(day,end_day,begin,finish)))
        return jsonify(slots=slots,room=ROOM_NAME)
    @app.get('/api/room-bookings')
    @authenticated()
    def room_booking_list():
        user=current_user();query=Booking.query
        if user.role!='admin':query=query.filter_by(requester_id=user.id)
        rows=query.order_by(Booking.created_at.desc()).limit(300).all()
        return jsonify(bookings=[serial(row) for row in rows],room=ROOM_NAME,smtp_ready=bool(app.config.get('SMTP_HOST') and app.config.get('SMTP_FROM')))
    @app.post('/api/room-bookings')
    @authenticated()
    def request_booking():
        values=request.form;start,end,begin,finish=parse_period(values)
        name=values.get('requester_name','').strip();activity=values.get('activity','').strip();email=values.get('email','').strip().lower();phone=values.get('phone','').strip()
        if not name or len(name)>120 or not activity or len(activity)>500:raise ValidationError('กรุณาระบุชื่อผู้จองและกิจกรรม (ชื่อไม่เกิน 120 และกิจกรรมไม่เกิน 500 ตัวอักษร)')
        if not re.fullmatch(r'[a-z0-9._%+\-]+@kkumail\.com',email) or len(email)>180:raise ValidationError('อีเมลต้องเป็น KKU-Mail @kkumail.com เท่านั้น')
        if not re.fullmatch(r'0[0-9]{9}',phone):raise ValidationError('เบอร์โทรต้องเป็นตัวเลข 10 หลัก เริ่มด้วย 0')
        oid=values.get('organization_id','')
        if oid:
            try:oid=int(oid)
            except ValueError:raise ValidationError('หน่วยงานไม่ถูกต้อง')
            if not db.session.get(Organization,oid):raise ValidationError('ไม่พบหน่วยงาน')
        else:oid=None
        memo=request.files.get('memo');has_file=bool(memo and memo.filename)
        if (end-start).days+1>3 and not has_file:raise ValidationError('จองเกิน 3 วัน ต้องแนบบันทึกข้อความขอใช้ห้อง (PDF หรือ DOCX)')
        blob=None;filename=None;storage=None
        if has_file:
            filename=Path(memo.filename.replace('\\','/')).name
            if len(filename)>255:raise ValidationError('ชื่อไฟล์ยาวเกินไป')
            extension=Path(filename).suffix.lower();blob=memo.read(10*1024*1024+1)
            if len(blob)>10*1024*1024:raise ValidationError('ไฟล์แนบต้องไม่เกิน 10 MB')
            valid=extension=='.pdf' and blob.startswith(b'%PDF-')
            if extension=='.docx':
                try:
                    with zipfile.ZipFile(io.BytesIO(blob)) as archive:valid='[Content_Types].xml' in archive.namelist() and 'word/document.xml' in archive.namelist()
                except zipfile.BadZipFile:valid=False
            if not valid:raise ValidationError('ไฟล์แนบต้องเป็น PDF หรือ DOCX ที่ถูกต้อง')
            storage=uuid.uuid4().hex+extension
        issues=external_check(start,end,begin,finish)
        if issues:return jsonify(error='ช่วงเวลานี้ยังไม่ว่างหรือข้อมูลต้นทางไม่ครบ กรุณาตรวจตารางอีกครั้ง',issues=issues),409
        requester_id=current_user().id
        lock()
        if local_conflicts(start,end,begin,finish):db.session.rollback();return jsonify(error='มีคำขอหรือรายการจองใช้ช่วงเวลานี้แล้ว'),409
        row=Booking(requester_id=requester_id,requester_name=name,activity=activity,organization_id=oid,email=email,phone=phone,start_date=start,end_date=end,start_time=begin,end_time=finish,memo_name=filename,memo_storage=storage,calendar_status='local')
        try:
            if storage:(folder/storage).write_bytes(blob)
            db.session.add(row);db.session.commit()
        except Exception:
            db.session.rollback()
            if storage:(folder/storage).unlink(missing_ok=True)
            raise
        return jsonify(serial(row)),201
    def send_notification(row):
        config=app.config
        if not config.get('SMTP_HOST') or not config.get('SMTP_FROM'):raise ValueError('SMTP not configured')
        message=EmailMessage();message['Subject']='SUDMS: อนุมัติการขอใช้ห้องประชุมแล้ว';message['From']=config['SMTP_FROM'];message['To']=row.email
        message.set_content(f'เรียน {row.requester_name}\nคำขอเลขที่ {row.id} ได้รับอนุมัติแล้ว\nสถานที่: {ROOM_NAME}\nกิจกรรม: {row.activity}\nวันที่: {row.start_date} ถึง {row.end_date}\nเวลา: {row.start_time}–{row.end_time} น. ของทุกวันที่จอง\nหมายเหตุ: {row.review_note or "—"}\nตรวจสถานะได้ที่เมนูปฏิทินห้องประชุมใน SUDMS')
        security=config.get('SMTP_SECURITY') or 'starttls'
        if security not in ['ssl','starttls']:raise ValueError('Invalid SMTP security')
        port=int(config.get('SMTP_PORT') or (465 if security=='ssl' else 587));factory=smtplib.SMTP_SSL if security=='ssl' else smtplib.SMTP
        kwargs={'context':ssl.create_default_context()} if security=='ssl' else {}
        with factory(config['SMTP_HOST'],port,timeout=20,**kwargs) as server:
            if security=='starttls':server.ehlo();server.starttls(context=ssl.create_default_context());server.ehlo()
            if config.get('SMTP_USERNAME'):server.login(config['SMTP_USERNAME'],config['SMTP_PASSWORD'])
            server.send_message(message)
    def notify(row):
        try:send_notification(row);row.email_status='sent';row.email_sent_at=now()
        except (OSError,smtplib.SMTPException,ValueError):row.email_status='failed';app.logger.warning('Room approval email not sent for request %s',row.id)
        db.session.commit()
    @app.post('/api/room-bookings/<int:booking_id>/review')
    @authenticated(admin=True)
    def review_booking(booking_id):
        values=request.get_json(silent=True) or {};decision=values.get('decision');note=values.get('note','')
        if decision not in ['approved','rejected'] or not isinstance(note,str) or len(note)>2000:raise ValidationError('ผลพิจารณาหรือหมายเหตุไม่ถูกต้อง')
        row=db.session.get(Booking,booking_id)
        if not row:abort(404)
        if row.status!='pending':return jsonify(error='คำขอนี้พิจารณาแล้ว'),409
        reviewer_id=current_user().id
        if decision=='approved':
            parse_period(dict(start_date=row.start_date.isoformat(),end_date=row.end_date.isoformat(),start_time=row.start_time,end_time=row.end_time))
            issues=external_check(row.start_date,row.end_date,row.start_time,row.end_time,fresh=True,exclude_booking_id=row.id)
            if issues:return jsonify(error='ยังอนุมัติไม่ได้: เวลาชนหรืออ่านข้อมูลต้นทางไม่ครบ',issues=issues),409
        lock();row=db.session.get(Booking,booking_id)
        if row.status!='pending':db.session.rollback();return jsonify(error='คำขอนี้พิจารณาแล้ว'),409
        if decision=='approved' and local_conflicts(row.start_date,row.end_date,row.start_time,row.end_time,row.id):db.session.rollback();return jsonify(error='มีคำขอหรือรายการจองอื่นใช้ช่วงเวลานี้แล้ว'),409
        row.status=decision;row.review_note=note.strip();row.reviewer_id=reviewer_id;row.reviewed_at=now()
        row.email_status='pending' if decision=='approved' else 'not_required'
        db.session.commit()
        row.calendar_status='local'
        db.session.commit()
        if decision=='approved':notify(row)
        return jsonify(serial(row))
    @app.post('/api/room-bookings/<int:booking_id>/email-retry')
    @authenticated(admin=True)
    def retry_email(booking_id):
        lock();row=db.session.get(Booking,booking_id)
        if not row:abort(404)
        if row.status!='approved':raise ValidationError('ส่งอีเมลได้เฉพาะคำขอที่อนุมัติแล้ว')
        if row.email_status=='sent':db.session.rollback();return jsonify(serial(row))
        notify(row);return jsonify(serial(row))
    @app.get('/api/room-bookings/<int:booking_id>/memo')
    @authenticated()
    def booking_memo(booking_id):
        row=db.session.get(Booking,booking_id)
        if not row:abort(404)
        if current_user().role!='admin' and row.requester_id!=current_user().id:abort(403)
        if not row.memo_storage:abort(404)
        return send_file(folder/row.memo_storage,as_attachment=True,download_name=row.memo_name)
    def append_calendar(data,month):
        result=dict(data);events=list(data['events']);year,number=map(int,month.split('-'));first=datetime(year,number,1).date();last=(first.replace(day=28)+timedelta(days=4)).replace(day=1)-timedelta(days=1)
        rows=Booking.query.filter(Booking.status.in_(['pending','approved']),Booking.start_date<=last,Booking.end_date>=first).all()
        for row in rows:
            for day in days_between(max(first,row.start_date),min(last,row.end_date)):
                label='รออนุมัติ' if row.status=='pending' else 'อนุมัติแล้ว'
                events.append(dict(id=f'sudms-booking-{row.id}-{day}',date=day.isoformat(),room=ROOM_NAME,title=row.activity,time=row.start_time+' - '+row.end_time,source='SUDMS · '+label,source_url='/meeting-rooms#room-booking-section'))
        result.update(events=events,rooms=sorted(set(data['rooms']+[ROOM_NAME])),local_booking_enabled=True)
        return result
    app.extensions['room_booking_calendar']=append_calendar
