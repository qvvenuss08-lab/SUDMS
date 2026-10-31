"""Read-only document flow and room usage reports, scoped by organization."""
import json
from collections import Counter,defaultdict
from datetime import datetime,timedelta
from flask import request,jsonify,render_template,abort

def register_reporting(app,db,Document,Tracking,Audit,Assignment,Booking,Organization,User,authenticated,current_user,now):
    def period():
        today=now().date()
        try:
            start=datetime.strptime(request.args.get('start',f'{today.year}-01-01'),'%Y-%m-%d').date()
            end=datetime.strptime(request.args.get('end',f'{today.year}-12-31'),'%Y-%m-%d').date()
            grain=request.args.get('grain','month')
            if end<start or (end-start).days>1830 or grain not in ['day','month','year']:raise ValueError()
        except (TypeError,ValueError):abort(400,description='ช่วงวันที่ไม่ถูกต้อง เลือกได้ไม่เกิน 5 ปี')
        return start,end,grain
    def bucket(day,grain):return day.isoformat() if grain=='day' else day.strftime('%Y-%m') if grain=='month' else str(day.year)
    def calendar_keys(start,end,grain):
        keys=[];day=start
        while day<=end:
            key=bucket(day,grain)
            if not keys or keys[-1]!=key:keys.append(key)
            day+=timedelta(days=1)
        return keys
    def scope():
        user=current_user();raw=request.args.get('organization_id','')
        if user.role!='admin':
            if raw and raw!=str(user.organization_id):abort(403)
            return user.organization_id
        if not raw:return None
        try:oid=int(raw)
        except ValueError:abort(400)
        if not db.session.get(Organization,oid):abort(404)
        return oid
    def defaults():
        today=now().date();return dict(report_start=f'{today.year}-01-01',report_end=f'{today.year}-12-31')
    @app.get('/reports/documents')
    @authenticated()
    def document_report_page():return render_template('reports.html',report_kind='documents',**defaults())
    @app.get('/reports/rooms')
    @authenticated(admin=True)
    def room_report_page():return render_template('reports.html',report_kind='rooms',**defaults())
    @app.get('/api/reports/documents')
    @authenticated()
    def document_report():
        start,end,grain=period();oid=scope();orgs={o.id:o.name for o in Organization.query.all()};byname={name:id for id,name in orgs.items()}
        docs={d.id:d for d in Document.query.all()};users={u.id:u for u in User.query.all()};flows=Counter();incoming=Counter();outgoing=Counter();people=Counter();names={};series=defaultdict(Counter);rows=[];seen_out=set();seen_in=set();assigned_docs=set()
        trails=Tracking.query.filter(Tracking.action.in_(['send','forward']),Tracking.created_at>=datetime.combine(start,datetime.min.time()),Tracking.created_at<datetime.combine(end+timedelta(days=1),datetime.min.time())).order_by(Tracking.id).all()
        for entry in trails:
            doc=docs.get(entry.document_id)
            if not doc:continue
            source=byname.get(entry.from_org);target=byname.get(entry.to_org);target_name=entry.to_org
            if source==target:
                details=json.loads(doc.send_details or '{}')
                if details.get('recipient_scope')!='external':continue
                target=None;target_name=doc.recipient or 'หน่วยงานภายนอก'
            if oid is not None and source!=oid and target!=oid:continue
            sent=oid is None or source==oid;received=oid is None or target==oid
            key=bucket(entry.created_at.date(),grain)
            if sent:outgoing[target_name]+=1;series[key]['sent']+=1;seen_out.add(doc.id)
            if received:incoming[entry.from_org]+=1;series[key]['incoming']+=1;seen_in.add(doc.id)
            flows[(entry.from_org,target_name)]+=1
            rows.append(dict(document_id=doc.id,number=doc.display_number,title=doc.title,from_org=entry.from_org,to_org=target_name,action=entry.action,created_at=entry.created_at.isoformat()))
        # Manual incoming records have no send event; received copies are counted from original transmissions.
        for doc in docs.values():
            if doc.direction!='received' or json.loads(doc.send_details or '{}').get('source_document_id') or not start<=doc.created_at.date()<=end:continue
            if oid is not None and doc.owner_org_id!=oid:continue
            incoming[doc.sender]+=1;seen_in.add(doc.id);series[bucket(doc.created_at.date(),grain)]['incoming']+=1
            rows.append(dict(document_id=doc.id,number=doc.display_number,title=doc.title,from_org=doc.sender,to_org=orgs.get(doc.owner_org_id,''),action='manual_receive',created_at=doc.created_at.isoformat()))
        entries=Audit.query.filter(Audit.event=='assign',Audit.created_at>=datetime.combine(start,datetime.min.time()),Audit.created_at<datetime.combine(end+timedelta(days=1),datetime.min.time())).all()
        for entry in entries:
            doc=docs.get(entry.document_id)
            if not doc or (oid is not None and doc.owner_org_id!=oid):continue
            change=json.loads(entry.changes or '{}');uid=change.get('assigned_to_id');name=change.get('assigned_to','ไม่ระบุชื่อ');key=(doc.owner_org_id,str(uid) if uid is not None else name)
            people[key]+=1;names[key]=name;assigned_docs.add(doc.id);series[bucket(entry.created_at.date(),grain)]['assigned']+=1
        return jsonify(start=start.isoformat(),end=end.isoformat(),grain=grain,organization_id=oid,scope_label=orgs.get(oid,'ทุกหน่วยงาน'),totals=dict(sent=sum(outgoing.values()),incoming=sum(incoming.values()),sent_documents=len(seen_out),incoming_documents=len(seen_in),assignments=sum(people.values()),assigned_documents=len(assigned_docs)),series=[dict(period=k,sent=series[k]['sent'],incoming=series[k]['incoming'],assigned=series[k]['assigned']) for k in calendar_keys(start,end,grain)],outgoing=[dict(name=k,count=v) for k,v in outgoing.most_common()],incoming=[dict(name=k,count=v) for k,v in incoming.most_common()],flows=[dict(from_org=k[0],to_org=k[1],count=v) for k,v in flows.most_common()],assignees=[dict(name=names[k],organization=orgs.get(k[0],''),count=v) for k,v in people.most_common()],documents=sorted(rows,key=lambda r:r['created_at'],reverse=True))
    @app.get('/api/reports/rooms')
    @authenticated(admin=True)
    def room_report():
        start,end,grain=period();oid=scope();orgs={o.id:o.name for o in Organization.query.all()};query=Booking.query.filter(Booking.start_date<=end,Booking.end_date>=start)
        if oid is not None:query=query.filter_by(organization_id=oid)
        bookings=query.order_by(Booking.start_date).all();statuses=Counter();series=defaultdict(Counter);monthly=Counter();people={};units={};rows=[]
        for row in bookings:
            statuses[row.status]+=1;unit=orgs.get(row.organization_id,'ส่วนตัว / ไม่ระบุหน่วยงาน');person_key=row.requester_id;organization_key=row.organization_id
            person=people.setdefault(person_key,dict(name=row.requester_name,requests=0,approved=0,hours=0));organization=units.setdefault(organization_key,dict(name=unit,requests=0,approved=0,hours=0));person['requests']+=1;organization['requests']+=1
            begin=datetime.strptime(row.start_time,'%H:%M');finish=datetime.strptime(row.end_time,'%H:%M');minutes=int((finish-begin).total_seconds()/60);minutes_total=0;day=max(start,row.start_date);days=0
            if row.status=='approved':person['approved']+=1;organization['approved']+=1
            while day<=min(end,row.end_date):
                key=bucket(day,grain);series[key]['requested_days']+=1;days+=1
                if row.status=='approved':series[key]['approved_days']+=1;series[key]['minutes']+=minutes;monthly[day.strftime('%Y-%m')]+=minutes;minutes_total+=minutes
                day+=timedelta(days=1)
            person['hours']+=minutes_total/60;organization['hours']+=minutes_total/60
            rows.append(dict(id=row.id,name=row.requester_name,organization=unit,activity=row.activity,start_date=row.start_date.isoformat(),end_date=row.end_date.isoformat(),start_time=row.start_time,end_time=row.end_time,status=row.status,days_in_period=days,approved_hours=round(minutes_total/60,2)))
        peak=max(monthly.values(),default=0)
        return jsonify(start=start.isoformat(),end=end.isoformat(),grain=grain,scope_label=orgs.get(oid,'ทุกหน่วยงาน'),totals=dict(requests=len(bookings),requesters=len(people),organizations=len(units),approved=statuses['approved'],pending=statuses['pending'],rejected=statuses['rejected'],approved_hours=round(sum(monthly.values())/60,2)),peak_months=[k for k,v in sorted(monthly.items()) if v==peak and peak>0],series=[dict(period=k,requested_days=series[k]['requested_days'],approved_days=series[k]['approved_days'],approved_hours=round(series[k]['minutes']/60,2)) for k in calendar_keys(start,end,grain)],months=[dict(month=k,hours=round(v/60,2)) for k,v in sorted(monthly.items())],people=sorted(people.values(),key=lambda r:(-r['hours'],-r['requests'])),organizations=sorted(units.values(),key=lambda r:(-r['hours'],-r['requests'])),bookings=rows)
