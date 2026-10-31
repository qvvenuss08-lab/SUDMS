"""Project finance ledger: exact satang arithmetic and audit history."""
import json,io
from decimal import Decimal,InvalidOperation
from datetime import datetime,timedelta
from finance_groups import authority
from flask import request,jsonify,render_template,abort,send_file
DISBURSEMENTS=['จ่ายตรง','สำรองจ่าย','ทดรองจ่าย']
ITEM_TYPES=['จ่ายตรง','ว.119','จัดหารวมศูนย์','ค่าตอบแทน','ค่าเดินทางไปราชการ','ค่าอาหาร']
STAGES={'not_submitted':'ยังไม่ยื่นขออนุมัติ','submitted':'ยื่นขออนุมัติจัดแล้ว','union_approved':'องค์การนักศึกษาอนุมัติ','department_approved':'กองพัฒนานักศึกษา/กองการกีฬาอนุมัติ','affairs_approved':'ฝ่ายกิจการนักศึกษาอนุมัติ'}
CATEGORIES=['ค่าตอบแทน','ค่าใช้สอย','ค่าวัสดุ','ค่าใช้จ่ายเบ็ดเตล็ด','ค่าเดินทางไปราชการ']
BUDGET_FUNDS={'กีฬา':'131239 เงินอุดหนุนบำรุงกีฬาองค์การนักศึกษาและชมรมกีฬา','ทั่วไป':'131243 เงินอุดหนุนกิจกรรมองค์การนักศึกษาและชมรมกิจกรรม'}
ACTIVITY_FIELDS=['activity_no','title','format','target_group','participants','okr','sdgs','eggs_core','ksa_k','ksa_s','ksa_a','approach','eggs_sub','sub_ksa_k','sub_ksa_s','sub_ksa_a','sub_approach','period']
def active_budget_period(today,records):
    stamp=today.isoformat()
    matches=[]
    for row in records:
        periods=json.loads(row['periods'])
        if periods and periods[0]['start']<=stamp<=periods[-1]['end']:
            matches.append((row['fiscal_year'],row['budget_round']))
    if matches:return max(matches)
    return None

def define_finance_models(db,now):
    class FinanceProject(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        organization_id=db.Column(db.Integer,db.ForeignKey('organization.id'),nullable=False)
        created_by=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False)
        title=db.Column(db.String(500),nullable=False)
        fiscal_year=db.Column(db.Integer,nullable=False)
        budget_round=db.Column(db.Integer,nullable=False,default=1)
        advisor=db.Column(db.String(500),default='')
        activity_start=db.Column(db.String(10),default='')
        activity_end=db.Column(db.String(10),default='')
        participants=db.Column(db.Text,default='[]')
        budget_details=db.Column(db.Text,default='')
        rationale=db.Column(db.Text,default='')
        approval_stage=db.Column(db.String(40),nullable=False,default='not_submitted')
        department_authority=db.Column(db.String(100),default='')
        budget_category=db.Column(db.String(100),default='ทั่วไป')
        source_file=db.Column(db.String(500),default='')
        source_sheet=db.Column(db.String(180),default='')
        source_row=db.Column(db.Integer)
        source_data=db.Column(db.Text,default='{}')
        source_import_key=db.Column(db.String(100),index=True)
        source_proposed=db.Column(db.BigInteger,nullable=False,default=0)
        source_union_allocated=db.Column(db.BigInteger,nullable=False,default=0)
        source_council_allocated=db.Column(db.BigInteger,nullable=False,default=0)
        responsible=db.Column(db.String(5000),default='')
        location=db.Column(db.String(500),default='')
        objectives=db.Column(db.Text,default='')
        evaluation=db.Column(db.Text,default='')
        activities=db.Column(db.Text,default='[]')
        requests_budget=db.Column(db.Boolean,nullable=False,default=True)
        budget_received=db.Column(db.BigInteger,nullable=False,default=0)
        borrower=db.Column(db.String(180),default='')
        loan_contract=db.Column(db.String(180),default='')
        has_loan=db.Column(db.Boolean,nullable=False,default=False)
        loan_request_date=db.Column(db.Date)
        loan_due_date=db.Column(db.Date)
        loan_amount=db.Column(db.BigInteger,nullable=False,default=0)
        approval_document_number=db.Column(db.String(180),nullable=False,default='')
        disbursement_progress=db.Column(db.String(40),nullable=False,default='not_recorded')
        report_progress=db.Column(db.String(40),nullable=False,default='not_recorded')
        approval_number=db.Column(db.Integer)
        status=db.Column(db.String(20),nullable=False,default='draft')
        review_note=db.Column(db.String(2000),default='')
        reviewed_by=db.Column(db.Integer,db.ForeignKey('user.id'))
        submitted_at=db.Column(db.DateTime)
        reviewed_at=db.Column(db.DateTime)
        created_at=db.Column(db.DateTime,nullable=False,default=now)
        updated_at=db.Column(db.DateTime,nullable=False,default=now)
    class FinanceExpense(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        project_id=db.Column(db.Integer,db.ForeignKey('finance_project.id'),nullable=False,index=True)
        category=db.Column(db.String(60),nullable=False)
        item_no=db.Column(db.String(20),default='')
        description=db.Column(db.String(1000),nullable=False)
        planned=db.Column(db.BigInteger,nullable=False,default=0)
        actual=db.Column(db.BigInteger,nullable=False,default=0)
        disbursement=db.Column(db.String(40),default='')
        payment_status=db.Column(db.String(20),default='unpaid')
        item_type=db.Column(db.String(60),default='')
        union_allocated=db.Column(db.BigInteger)
        council_allocated=db.Column(db.BigInteger)
        union_reason=db.Column(db.Text,default='')
        council_reason=db.Column(db.Text,default='')
        source_cells=db.Column(db.Text,default='{}')
        payment_type=db.Column(db.String(180),default='')
        pr_number=db.Column(db.String(100),default='')
        payee=db.Column(db.String(180),default='')
        responsible=db.Column(db.String(180),default='')
        quantity=db.Column(db.String(30),default='')
        unit_price=db.Column(db.String(30),default='')
        multiplier=db.Column(db.String(30),default='')
    class FinanceAudit(db.Model):
        id=db.Column(db.Integer,primary_key=True)
        project_id=db.Column(db.Integer,db.ForeignKey('finance_project.id'),nullable=False,index=True)
        actor_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False)
        action=db.Column(db.String(40),nullable=False)
        changes=db.Column(db.Text,nullable=False)
        created_at=db.Column(db.DateTime,nullable=False,default=now)
    return FinanceProject,FinanceExpense,FinanceAudit

def register_finance(app,db,Project,Expense,Audit,Organization,User,authenticated,current_user,now,lock,ValidationError):
    from sqlalchemy import inspect,text as sql_text
    with app.app_context():
        additions={'finance_project':{'disbursement_progress':"VARCHAR(40) NOT NULL DEFAULT 'not_recorded'",'report_progress':"VARCHAR(40) NOT NULL DEFAULT 'not_recorded'",'approval_document_number':"VARCHAR(180) NOT NULL DEFAULT ''",'approval_number':'INTEGER','has_loan':'BOOLEAN NOT NULL DEFAULT 0','loan_request_date':'DATE','budget_round':'INTEGER NOT NULL DEFAULT 1','advisor':"VARCHAR(500) DEFAULT ''",'activity_start':"VARCHAR(10) DEFAULT ''",'activity_end':"VARCHAR(10) DEFAULT ''",'participants':"TEXT DEFAULT '[]'",'budget_details':"TEXT DEFAULT ''",'rationale':"TEXT DEFAULT ''",'approval_stage':"VARCHAR(40) NOT NULL DEFAULT 'not_submitted'",'department_authority':"VARCHAR(100) DEFAULT ''",'budget_category':"VARCHAR(100) DEFAULT 'ทั่วไป'",'source_file':"VARCHAR(500) DEFAULT ''",'source_sheet':"VARCHAR(180) DEFAULT ''",'source_row':'INTEGER','source_data':"TEXT DEFAULT '{}'",'source_import_key':'VARCHAR(100)','source_proposed':'BIGINT NOT NULL DEFAULT 0','source_union_allocated':'BIGINT NOT NULL DEFAULT 0','source_council_allocated':'BIGINT NOT NULL DEFAULT 0'},'finance_expense':{'payment_status':"VARCHAR(20) DEFAULT 'unpaid'",'item_type':"VARCHAR(60) DEFAULT ''",'union_allocated':'BIGINT','council_allocated':'BIGINT','union_reason':"TEXT DEFAULT ''",'council_reason':"TEXT DEFAULT ''",'source_cells':"TEXT DEFAULT '{}'"}}
        for table,columns in additions.items():
            existing={column['name'] for column in inspect(db.engine).get_columns(table)}
            for name,definition in columns.items():
                if name not in existing:db.session.execute(sql_text(f'ALTER TABLE {table} ADD COLUMN {name} {definition}'))
        db.session.execute(sql_text("UPDATE finance_expense SET payment_status=disbursement,disbursement='' WHERE disbursement IN ('unpaid','requested','paid')"))
        # Preserve old approved records without inventing approvals from external offices.
        db.session.execute(sql_text("UPDATE finance_project SET approval_stage=CASE WHEN status='submitted' THEN 'submitted' ELSE 'union_approved' END WHERE source_import_key IS NULL AND approval_stage='not_submitted' AND status IN ('submitted','approved','completed')"))
        db.session.execute(sql_text('CREATE TABLE IF NOT EXISTS finance_annual_budget (fiscal_year INTEGER NOT NULL, fund TEXT NOT NULL, amount BIGINT NOT NULL DEFAULT 0, updated_by INTEGER, updated_at TEXT, PRIMARY KEY(fiscal_year,fund))'))
        db.session.execute(sql_text('CREATE TABLE IF NOT EXISTS finance_budget_round (fiscal_year INTEGER NOT NULL, budget_round INTEGER NOT NULL, fund TEXT NOT NULL, amount BIGINT NOT NULL DEFAULT 0, periods TEXT NOT NULL, updated_by INTEGER, updated_at TEXT, PRIMARY KEY(fiscal_year,budget_round,fund))'))
        db.session.commit()
    def money(value):
        try:
            if isinstance(value,bool):raise ValueError()
            amount=Decimal(str(value if value is not None else '0'))
            if not amount.is_finite() or amount<0 or amount>Decimal('9999999999.99') or amount.as_tuple().exponent<-2:raise ValueError()
            return int(amount*100)
        except (ValueError,InvalidOperation):raise ValidationError('จำนวนเงินต้องไม่ติดลบและมีทศนิยมไม่เกิน 2 ตำแหน่ง')
    def decimal(value):return format(Decimal(value or 0)/100,'.2f')
    def text(data,key,max_length=500,required=False):
        value=data.get(key,'')
        if not isinstance(value,str) or len(value)>max_length or (required and not value.strip()):raise ValidationError('ข้อมูล '+key+' ไม่ถูกต้องหรือยาวเกินกำหนด')
        return value.strip()
    def can_edit(project):return current_user().role=='admin' or current_user().organization_id==project.organization_id
    def get_project(id,edit=False):
        row=db.session.get(Project,id)
        if not row:abort(404)
        if edit and not can_edit(row):abort(403)
        return row
    def expense_data(row):return dict(id=row.id,category=row.category,item_no=row.item_no,description=row.description,planned=decimal(row.planned),actual=decimal(row.actual),difference=decimal(row.planned-row.actual),disbursement=row.disbursement,payment_status=row.payment_status,item_type=row.item_type,union_allocated=decimal(row.union_allocated) if row.union_allocated is not None else None,council_allocated=decimal(row.council_allocated) if row.council_allocated is not None else None,union_reason=row.union_reason,council_reason=row.council_reason,payment_type=row.payment_type,pr_number=row.pr_number,payee=row.payee,responsible=row.responsible,quantity=row.quantity,unit_price=row.unit_price,multiplier=row.multiplier)
    def project_authority(row):
        organization=db.session.get(Organization,row.organization_id)
        kind='sports' if organization.club_type=='sports' or (organization.club_type=='other' and row.budget_category=='กีฬา') else 'general'
        return authority(kind)
    def project_data(row,detail=False):
        items=Expense.query.filter_by(project_id=row.id).order_by(Expense.id).all();planned=sum(i.planned for i in items);actual=sum(i.actual for i in items);paid=sum(i.actual for i in items if i.payment_status=='paid');loan_paid=sum(i.actual for i in items if i.payment_status=='paid' and i.payment_type=='เงินยืม')
        organization=db.session.get(Organization,row.organization_id)
        result=dict(evaluation_category=row.budget_category,evaluation_category_label=BUDGET_FUNDS.get(row.budget_category,''),evaluation_required=True,has_loan=bool(row.has_loan or row.loan_amount),loan_request_date=row.loan_request_date.isoformat() if row.loan_request_date else '',budget_round=row.budget_round,budget_period_label=f'{row.budget_round}/{row.fiscal_year}',advisor=row.advisor,activity_start=row.activity_start,activity_end=row.activity_end,participants=json.loads(row.participants or '[]'),budget_details=row.budget_details,budget_fund_label=BUDGET_FUNDS.get(row.budget_category,''),participant_total=sum(i['count'] for i in json.loads(row.participants or '[]')),club_type=organization.club_type,id=row.id,organization_id=row.organization_id,organization=db.session.get(Organization,row.organization_id).name,title=row.title,fiscal_year=row.fiscal_year,responsible=row.responsible,location=row.location,objectives=row.objectives,rationale=row.rationale,evaluation=row.evaluation,disbursement_progress=row.disbursement_progress,report_progress=row.report_progress,approval_document_number=row.approval_document_number,approval_number=row.approval_number,approval_stage=row.approval_stage,approval_stage_label=project_authority(row)+'อนุมัติ' if row.approval_stage=='department_approved' else STAGES.get(row.approval_stage,row.approval_stage),department_authority=project_authority(row),budget_category=row.budget_category,source_file=row.source_file,source_sheet=row.source_sheet,source_row=row.source_row,source_proposed=decimal(row.source_proposed),source_union_allocated=decimal(row.source_union_allocated),source_council_allocated=decimal(row.source_council_allocated),activities=json.loads(row.activities or '[]'),requests_budget=row.requests_budget,budget_received=decimal(row.budget_received),planned=decimal(planned),actual=decimal(actual),difference=decimal(planned-actual),remaining=decimal(row.budget_received-actual),paid=decimal(paid),borrower=row.borrower,loan_contract=row.loan_contract,loan_due_date=row.loan_due_date.isoformat() if row.loan_due_date else '',loan_amount=decimal(row.loan_amount),loan_remaining=decimal(row.loan_amount-loan_paid),status=row.status,review_note=row.review_note,can_edit=can_edit(row),can_delete=current_user().role=='admin',created_at=row.created_at.isoformat(),updated_at=row.updated_at.isoformat())
        if detail:
            result['files']=list_project_files(row.id)
            result['source_details']=json.loads(row.source_data or '{}')
            result['expenses']=[expense_data(i) for i in items]
            result['category_totals']=[dict(category=category,planned=decimal(sum(i.planned for i in items if i.category==category)),actual=decimal(sum(i.actual for i in items if i.category==category))) for category in CATEGORIES]
            result['history']=[dict(action=a.action,actor=db.session.get(User,a.actor_id).name,created_at=a.created_at.isoformat()) for a in Audit.query.filter_by(project_id=row.id).order_by(Audit.id.desc()).limit(100)]
        return result
    def audit(row,action,before=None):
        row.updated_at=now();db.session.flush();db.session.add(Audit(project_id=row.id,actor_id=current_user().id,action=action,changes=json.dumps({'before':before,'after':project_data(row,True)},ensure_ascii=False)))
    def fiscal_year(raw):
        try:
            if isinstance(raw,bool) or str(raw)!=str(int(raw)):raise ValueError()
            year=int(raw)
        except (ValueError,TypeError):raise ValidationError('ปีงบประมาณต้องเป็นปี พ.ศ.')
        if not 2500<=year<=2700:raise ValidationError('ปีงบประมาณไม่ถูกต้อง')
        return year
    def round_number(raw):
        if isinstance(raw,bool) or str(raw) not in ['1','2']:raise ValidationError('รอบงบประมาณต้องเป็น 1 หรือ 2')
        return int(raw)
    def assign(row,data):
        row.title=text(data,'title',500,True);row.fiscal_year=fiscal_year(data.get('fiscal_year'));row.budget_round=round_number(data.get('budget_round',row.budget_round or 1))
        for key,length in [('responsible',5000),('location',500),('rationale',20000),('objectives',20000),('evaluation',10000),('borrower',180),('loan_contract',180)]:setattr(row,key,text(data,key,length))
        if not isinstance(data.get('requests_budget'),bool):raise ValidationError('กรุณาระบุว่าขอใช้งบประมาณหรือไม่')
        row.budget_category=text(data,'budget_category',100) or row.budget_category or 'ทั่วไป'
        if row.budget_category not in BUDGET_FUNDS:raise ValidationError('กรุณาเลือกหมวดงบประมาณ')
        if 'approval_document_number' in data:row.approval_document_number=text(data,'approval_document_number',180)
        number=data.get('approval_number',row.approval_number)
        if number in ['',None]:number=None
        else:
            if isinstance(number,bool) or not str(number).isascii() or not str(number).isdigit() or not 1<=int(number)<=999999:raise ValidationError('ลำดับการอนุมัติต้องเป็นจำนวนเต็ม 1–999999')
            number=int(number)
        if current_user().role!='admin' and number!=row.approval_number:abort(403)
        if number is not None:
            duplicate=Project.query.filter(Project.id!=row.id,Project.budget_category==row.budget_category,Project.fiscal_year==row.fiscal_year,Project.budget_round==row.budget_round,Project.approval_number==number).first()
            if duplicate:raise ValidationError('ลำดับการอนุมัตินี้มีแล้วในหมวด ปีงบประมาณ และรอบเดียวกัน')
        row.approval_number=number
        for key,limit in [('advisor',500),('budget_details',10000)]:setattr(row,key,text(data,key,limit))
        for key in ['activity_start','activity_end']:
            value=text(data,key,10)
            try:
                if value:datetime.strptime(value,'%Y-%m-%d')
            except ValueError:raise ValidationError('วันที่จัดกิจกรรมไม่ถูกต้อง')
            setattr(row,key,value)
        if row.activity_start and row.activity_end and row.activity_end<row.activity_start:raise ValidationError('วันสิ้นสุดต้องไม่ก่อนวันเริ่มกิจกรรม')
        groups=data.get('participants',[])
        if not isinstance(groups,list) or len(groups)>100:raise ValidationError('กลุ่มผู้เข้าร่วมไม่ถูกต้อง')
        cleaned_groups=[]
        for group in groups:
            if not isinstance(group,dict):raise ValidationError('กลุ่มผู้เข้าร่วมไม่ถูกต้อง')
            count=group.get('count')
            if isinstance(count,bool) or not str(count).isdigit() or not 0<=int(count)<=1000000:raise ValidationError('จำนวนผู้เข้าร่วมต้องเป็นจำนวนเต็มไม่ติดลบ')
            cleaned_groups.append({'label':text(group,'label',500,True),'count':int(count)})
        row.participants=json.dumps(cleaned_groups,ensure_ascii=False)
        row.department_authority=project_authority(row)
        row.requests_budget=data['requests_budget'];amount=money(data.get('budget_received',0))
        if current_user().role!='admin' and amount!=row.budget_received:raise ValidationError('งบประมาณที่ได้รับต้องให้แอดมินบันทึก')
        if not row.requests_budget and amount:raise ValidationError('โครงการไม่ขอใช้งบประมาณต้องไม่ระบุงบที่ได้รับ')
        row.budget_received=amount
        has_loan=data.get('has_loan',bool(row.has_loan or row.loan_amount))
        if not isinstance(has_loan,bool):raise ValidationError('กรุณาระบุว่ามีการยืมเงินหรือไม่')
        row.has_loan=has_loan
        if has_loan:
            row.borrower=text(data,'borrower',180,True);row.loan_contract=text(data,'loan_contract',180,True)
            row.loan_amount=money(data.get('loan_amount',0))
            if row.loan_amount<=0:raise ValidationError('จำนวนเงินยืมต้องมากกว่า 0')
            value=text(data,'loan_request_date',10,True)
            try:
                row.loan_request_date=datetime.strptime(value,'%Y-%m-%d').date()
                if row.loan_request_date.isoformat()!=value:raise ValueError()
                row.loan_due_date=row.loan_request_date+timedelta(days=30)
            except (ValueError,OverflowError):raise ValidationError('วันที่ขอรับเงินไม่ถูกต้อง')
        else:
            row.borrower='';row.loan_contract='';row.loan_amount=0;row.loan_request_date=None;row.loan_due_date=None
        activities=data.get('activities',[])
        if not isinstance(activities,list) or len(activities)>100:raise ValidationError('กิจกรรมต้องเป็นรายการ ไม่เกิน 100 รายการ')
        cleaned=[]
        for item in activities:
            if not isinstance(item,dict):raise ValidationError('กิจกรรมไม่ถูกต้อง')
            activity={key:text(item,key,1000) for key in ACTIVITY_FIELDS}
            if 'target_groups' in item:
                groups=item['target_groups']
                if not isinstance(groups,list) or len(groups)>100:raise ValidationError('กลุ่มเป้าหมายต่อกิจกรรมต้องไม่เกิน 100 กลุ่ม')
                targets=[]
                for group in groups:
                    if not isinstance(group,dict):raise ValidationError('กลุ่มเป้าหมายไม่ถูกต้อง')
                    label=text(group,'label',200,True);count=group.get('count')
                    if isinstance(count,bool) or not str(count).isdigit() or not 0<=int(count)<=1000000:raise ValidationError('จำนวนคนแต่ละกลุ่มต้องเป็นจำนวนเต็มไม่ติดลบ')
                    targets.append(dict(label=label,count=int(count)))
                activity['target_groups']=targets
                activity['target_group']='; '.join(g['label']+' ('+str(g['count'])+' คน)' for g in targets)
                activity['participants']=str(sum(g['count'] for g in targets))
            cleaned.append(activity)
        row.activities=json.dumps(cleaned,ensure_ascii=False)
    from finance_files import setup_project_files
    list_project_files,prepare_project_files,store_project_files,cleanup_project_files=setup_project_files(app,db,Project,authenticated,current_user,now,lock,ValidationError,get_project,project_data,audit)
    @app.route('/api/finance/annual-budget',methods=['GET','PUT'])
    @authenticated()
    def annual_budget():
        year=fiscal_year(request.args.get('year',str(now().year+543)))
        if request.method=='PUT':
            if current_user().role!='admin':abort(403)
            lock();data=request.get_json(silent=True) or {};fund=data.get('fund')
            if fund not in BUDGET_FUNDS:raise ValidationError('หมวดงบประมาณไม่ถูกต้อง')
            amount=money(data.get('amount'))
            db.session.execute(sql_text('INSERT INTO finance_annual_budget(fiscal_year,fund,amount,updated_by,updated_at) VALUES(:year,:fund,:amount,:actor,:at) ON CONFLICT(fiscal_year,fund) DO UPDATE SET amount=:amount,updated_by=:actor,updated_at=:at'),dict(year=year,fund=fund,amount=amount,actor=current_user().id,at=now().isoformat()));db.session.commit()
        rows={r.fund:r.amount for r in db.session.execute(sql_text('SELECT fund,amount FROM finance_annual_budget WHERE fiscal_year=:year'),{'year':year})}
        projects=Project.query.filter_by(fiscal_year=year).all()
        funds=[]
        for key,label in BUDGET_FUNDS.items():
            allocated=sum(p.budget_received for p in projects if p.budget_category==key)
            funds.append(dict(fund=key,label=label,amount=decimal(rows.get(key,0)),allocated=decimal(allocated),remaining=decimal(rows.get(key,0)-allocated)))
        return jsonify(year=year,funds=funds)
    @app.route('/api/finance/budget-round',methods=['GET','PUT'])
    @authenticated()
    def budget_round_config():
        year=fiscal_year(request.args.get('year',str(now().year+543)))
        cycle=round_number(request.args.get('round','1'))
        if request.method=='PUT':
            if current_user().role!='admin':abort(403)
            lock();data=request.get_json(silent=True) or {};fund=data.get('fund')
            if fund not in BUDGET_FUNDS:raise ValidationError('หมวดงบประมาณไม่ถูกต้อง')
            amount=money(data.get('amount'));periods=data.get('periods')
            if not isinstance(periods,list) or len(periods) not in [1,2]:raise ValidationError('กรุณาระบุวันเริ่มต้นและสิ้นสุดของรอบงบประมาณ')
            cleaned=[]
            for index,item in enumerate(periods):
                if not isinstance(item,dict):raise ValidationError('ข้อมูลไตรมาสไม่ถูกต้อง')
                start=text(item,'start',10,True);end=text(item,'end',10,True)
                try:
                    a=datetime.strptime(start,'%Y-%m-%d').date();b=datetime.strptime(end,'%Y-%m-%d').date()
                    if a.isoformat()!=start or b.isoformat()!=end:raise ValueError()
                except ValueError:raise ValidationError('วันที่ไตรมาสไม่ถูกต้อง')
                if b<a:raise ValidationError('วันสิ้นสุดไตรมาสต้องไม่ก่อนวันเริ่มต้น')
                if a<datetime(year-544,10,1).date() or b>datetime(year-543,9,30).date():raise ValidationError('วันที่ต้องอยู่ภายในปีงบประมาณที่เลือก')
                if cleaned and start<=cleaned[-1]['end']:raise ValidationError('ช่วงไตรมาสต้องเรียงลำดับและไม่ซ้อนกัน')
                cleaned.append(dict(start=start,end=end))
            other=db.session.execute(sql_text('SELECT periods FROM finance_budget_round WHERE fiscal_year=:year AND budget_round<>:cycle'),dict(year=year,cycle=cycle)).all()
            for saved in other:
                for period in json.loads(saved.periods):
                    if cleaned[0]['start']<=period['end'] and cleaned[-1]['end']>=period['start']:raise ValidationError('ช่วงรอบงบประมาณซ้อนกับอีกรอบในปีเดียวกัน')
            db.session.execute(sql_text('INSERT INTO finance_budget_round(fiscal_year,budget_round,fund,amount,periods,updated_by,updated_at) VALUES(:year,:cycle,:fund,:amount,:periods,:actor,:at) ON CONFLICT(fiscal_year,budget_round,fund) DO UPDATE SET amount=:amount,periods=:periods,updated_by=:actor,updated_at=:at'),dict(year=year,cycle=cycle,fund=fund,amount=amount,periods=json.dumps(cleaned),actor=current_user().id,at=now().isoformat()));db.session.commit()
        saved={r.fund:r for r in db.session.execute(sql_text('SELECT * FROM finance_budget_round WHERE fiscal_year=:year AND budget_round=:cycle'),dict(year=year,cycle=cycle))}
        projects=Project.query.filter_by(fiscal_year=year,budget_round=cycle).all();funds=[]
        for key,label in BUDGET_FUNDS.items():
            row=saved.get(key);total=row.amount if row else 0;allocated=sum(p.budget_received for p in projects if p.budget_category==key)
            funds.append(dict(fund=key,label=label,amount=decimal(total),allocated=decimal(allocated),remaining=decimal(total-allocated),configured=row is not None,periods=json.loads(row.periods) if row else []))
        return jsonify(year=year,budget_round=cycle,label=f'{cycle}/{year}',funds=funds)
    @app.get('/api/finance/current-budget')
    @authenticated()
    def current_budget():
        today=now().date();records=db.session.execute(sql_text('SELECT * FROM finance_budget_round')).mappings().all()
        active=active_budget_period(today,records);stamp=today.isoformat();funds=[]
        if active is None:return jsonify(year=None,budget_round=None,label='',as_of=stamp,status='waiting',funds=[])
        year,cycle=active
        for key,label in BUDGET_FUNDS.items():
            saved=next((r for r in records if r['fiscal_year']==year and r['budget_round']==cycle and r['fund']==key),None)
            periods=json.loads(saved['periods']) if saved else []
            if not periods or not periods[0]['start']<=stamp<=periods[-1]['end']:continue
            projects=Project.query.filter_by(fiscal_year=year,budget_round=cycle,budget_category=key).all()
            total=saved['amount'] if saved else 0;allocated=sum(p.budget_received for p in projects)
            funds.append(dict(fund=key,label=label,amount=decimal(total),allocated=decimal(allocated),remaining=decimal(total-allocated),configured=saved is not None,periods=periods))
        return jsonify(year=year,budget_round=cycle,label=f'{cycle}/{year}',as_of=stamp,status='active',funds=funds)
    from evaluation import register_evaluation
    register_evaluation(app,db,Project,Organization,authenticated,now)
    @app.get('/finance')
    @authenticated()
    def finance_page():
        records=db.session.execute(sql_text('SELECT * FROM finance_budget_round')).mappings().all()
        year,cycle=active_budget_period(now().date(),records) or (now().year+543+(1 if now().month>=10 else 0),1 if now().month>=10 or now().month<=3 else 2)
        return render_template('finance.html',finance_year=year,finance_round=cycle)
    @app.get('/finance/projects/<int:id>')
    @authenticated()
    def finance_project_page(id):return render_template('finance_project.html',project_id=get_project(id).id,categories=CATEGORIES)
    @app.get('/api/finance/dashboard')
    @authenticated()
    def finance_dashboard():
        year=fiscal_year(request.args.get('year',str(now().year+543+(1 if now().month>=10 else 0))))
        project_query=Project.query.filter_by(fiscal_year=year)
        if request.args.get('round'):project_query=project_query.filter_by(budget_round=round_number(request.args['round']))
        projects=project_query.all();items=Expense.query.filter(Expense.project_id.in_([p.id for p in projects])).all() if projects else []
        planned_by={};actual_by={}
        for item in items:planned_by[item.project_id]=planned_by.get(item.project_id,0)+item.planned;actual_by[item.project_id]=actual_by.get(item.project_id,0)+item.actual
        allocated=sum(p.budget_received for p in projects);planned=sum(planned_by.values());actual=sum(actual_by.values());orgs=[]
        for organization in Organization.query.order_by(Organization.id):
            group=[p for p in projects if p.organization_id==organization.id];total=sum(p.budget_received for p in group)
            orgs.append(dict(club_type=organization.club_type,department_authority=authority(organization.club_type),source_union_allocated=decimal(sum(p.source_union_allocated for p in group)),source_council_allocated=decimal(sum(p.source_council_allocated for p in group)),id=organization.id,name=organization.name,code=organization.code,total_projects=len(group),budget_projects=sum(p.requests_budget for p in group),no_budget_projects=sum(not p.requests_budget for p in group),submitted_projects=sum(p.submitted_at is not None for p in group),approved_projects=sum(p.status in ['approved','completed'] for p in group),allocated=decimal(total),planned=decimal(sum(planned_by.get(p.id,0) for p in group)),actual=decimal(sum(actual_by.get(p.id,0) for p in group)),share=format(Decimal(total)*100/allocated,'.2f') if allocated else '0.00'))
        return jsonify(evaluation_categories=[dict(category=key,label=label,total_projects=sum(p.budget_category==key for p in projects),no_budget_projects=sum(p.budget_category==key and not p.requests_budget for p in projects),recorded_evaluations=sum(p.budget_category==key and bool((p.evaluation or '').strip()) for p in projects)) for key,label in BUDGET_FUNDS.items()],source_union_total=decimal(sum(p.source_union_allocated for p in projects)),source_council_total=decimal(sum(p.source_council_allocated for p in projects)),year=year,total_projects=len(projects),budget_projects=sum(p.requests_budget for p in projects),no_budget_projects=sum(not p.requests_budget for p in projects),submitted_projects=sum(p.submitted_at is not None for p in projects),approved_projects=sum(p.status in ['approved','completed'] for p in projects),total_money=decimal(allocated),planned=decimal(planned),actual=decimal(actual),organizations=orgs)
    @app.get('/api/finance/projects')
    @authenticated()
    def finance_projects():
        query=Project.query
        if request.args.get('year'):query=query.filter_by(fiscal_year=fiscal_year(request.args['year']))
        if request.args.get('round'):query=query.filter_by(budget_round=round_number(request.args['round']))
        if request.args.get('organization_id'):
            try:oid=int(request.args['organization_id'])
            except ValueError:raise ValidationError('หน่วยงานไม่ถูกต้อง')
            query=query.filter_by(organization_id=oid)
        return jsonify(projects=[project_data(p) for p in query.order_by(Project.updated_at.desc()).all()])
    @app.post('/api/finance/projects')
    @authenticated()
    def create_project():
        lock();user=current_user()
        if request.is_json:data=request.get_json(silent=True) or {}
        else:
            try:data=json.loads(request.form.get('project','{}'))
            except (ValueError,TypeError):raise ValidationError('ข้อมูลโครงการไม่ถูกต้อง')
        if not isinstance(data,dict):raise ValidationError('ข้อมูลโครงการไม่ถูกต้อง')
        prepared=prepare_project_files(request.files.getlist('files'))
        try:oid=int(data.get('organization_id',user.organization_id))
        except (ValueError,TypeError):raise ValidationError('หน่วยงานไม่ถูกต้อง')
        if user.role!='admin' and oid!=user.organization_id:abort(403)
        if not db.session.get(Organization,oid):raise ValidationError('ไม่พบหน่วยงาน')
        row=Project(organization_id=oid,created_by=user.id,budget_received=0);assign(row,data);paths=[]
        try:
            db.session.add(row);db.session.flush();paths=store_project_files(row,prepared);audit(row,'create');db.session.commit()
        except Exception:db.session.rollback();cleanup_project_files(paths);raise
        return jsonify(project_data(row,True)),201
    @app.route('/api/finance/projects/<int:id>',methods=['GET','PATCH','DELETE'])
    @authenticated()
    def finance_project(id):
        if request.method=='GET':return jsonify(project_data(get_project(id),True))
        lock();row=get_project(id,True)
        if request.method=='DELETE':
            if current_user().role!='admin':abort(403)
            # Keep a standalone snapshot because project audit rows have a required FK.
            before=project_data(row,True)
            history=[dict(actor_id=a.actor_id,action=a.action,changes=a.changes,created_at=a.created_at.isoformat()) for a in Audit.query.filter_by(project_id=id).order_by(Audit.id)]
            db.session.execute(sql_text('CREATE TABLE IF NOT EXISTS finance_deleted_project (id INTEGER PRIMARY KEY, original_project_id INTEGER NOT NULL, deleted_by INTEGER NOT NULL, deleted_at TEXT NOT NULL, snapshot TEXT NOT NULL)'))
            db.session.execute(sql_text('INSERT INTO finance_deleted_project(original_project_id,deleted_by,deleted_at,snapshot) VALUES(:id,:actor,:at,:snapshot)'),dict(id=id,actor=current_user().id,at=now().isoformat(),snapshot=json.dumps(dict(project=before,history=history,attachments=[dict(a) for a in db.session.execute(sql_text('SELECT * FROM finance_attachment WHERE project_id=:id'),{'id':id}).mappings()]),ensure_ascii=False)))
            # Attachments remain private for recovery; no download route can access a deleted project.
            db.session.execute(sql_text('DELETE FROM finance_attachment WHERE project_id=:id'),{'id':id})
            Expense.query.filter_by(project_id=id).delete(synchronize_session=False)
            Audit.query.filter_by(project_id=id).delete(synchronize_session=False)
            db.session.delete(row);db.session.commit()
            return jsonify(deleted=True,id=id)
        if row.status not in ['draft','rejected'] and current_user().role!='admin':raise ValidationError('โครงการส่งอนุมัติแล้ว ไม่สามารถแก้รายละเอียดแผนได้')
        before=project_data(row,True);data=request.get_json(silent=True) or {};assign(row,data);audit(row,'edit_project',before);db.session.commit();return jsonify(project_data(row,True))
    @app.post('/api/finance/projects/<int:id>/submit')
    @authenticated()
    def submit_project(id):
        lock();row=get_project(id,True)
        if row.status not in ['draft','rejected']:raise ValidationError('โครงการนี้ส่งขออนุมัติแล้ว')
        if not row.objectives.strip() or not row.evaluation.strip():raise ValidationError('กรุณาระบุวัตถุประสงค์และแนวทางการประเมินก่อนส่งขออนุมัติ')
        if row.requests_budget and not Expense.query.filter(Expense.project_id==id,Expense.planned>0).first():raise ValidationError('โครงการขอใช้งบต้องมีแผนค่าใช้จ่ายก่อนส่งอนุมัติ')
        if Expense.query.filter_by(project_id=id).filter((~Expense.disbursement.in_(DISBURSEMENTS)) | (~Expense.item_type.in_(ITEM_TYPES))).first():raise ValidationError('กรุณาระบุการเบิกจ่ายและประเภทรายการให้ครบทุกค่าใช้จ่ายก่อนส่งอนุมัติ')
        before=project_data(row);row.status='submitted';row.approval_stage='submitted';row.submitted_at=now();audit(row,'submit',before);db.session.commit();return jsonify(project_data(row,True))
    @app.post('/api/finance/projects/<int:id>/review')
    @authenticated(admin=True)
    def review_project(id):
        lock();row=get_project(id);data=request.get_json(silent=True) or {}
        if row.status!='submitted' or data.get('decision') not in ['approved','rejected']:raise ValidationError('พิจารณาได้เฉพาะโครงการที่ส่งขออนุมัติ')
        before=project_data(row);row.review_note=text(data,'note',2000);amount=money(data.get('budget_received',0))
        if not row.requests_budget and amount:raise ValidationError('โครงการไม่ขอใช้งบต้องไม่มีงบจัดสรร')
        row.status=data['decision'];row.approval_stage='union_approved' if row.status=='approved' else 'submitted';row.budget_received=amount if row.status=='approved' else 0;row.reviewed_by=current_user().id;row.reviewed_at=now();audit(row,row.status,before);db.session.commit();return jsonify(project_data(row,True))
    @app.post('/api/finance/projects/<int:id>/approval-stage')
    @authenticated(admin=True)
    def advance_approval(id):
        lock();row=get_project(id);data=request.get_json(silent=True) or {};stage=data.get('stage')
        next_stage={'union_approved':'department_approved','department_approved':'affairs_approved'}.get(row.approval_stage)
        if row.status!='approved' or stage!=next_stage:raise ValidationError('ต้องบันทึกผลอนุมัติตามลำดับ องค์การนักศึกษา → กองพัฒนานักศึกษา/กองการกีฬา → ฝ่ายกิจการนักศึกษา')
        before=project_data(row,True);row.approval_stage=stage;row.review_note=text(data,'note',2000);row.reviewed_by=current_user().id;row.reviewed_at=now();audit(row,'approval_stage',before);db.session.commit();return jsonify(project_data(row,True))
    @app.patch('/api/finance/projects/<int:id>/progress')
    @authenticated()
    def update_project_progress(id):
        lock();row=get_project(id,True)
        if row.status not in ['approved','completed'] and current_user().role!='admin':raise ValidationError('บันทึกผลหลังจัดกิจกรรมได้เมื่อโครงการอนุมัติแล้ว')
        data=request.get_json(silent=True)
        allowed={'disbursement_progress':{'not_recorded','awaiting_disbursement','disbursed'},'report_progress':{'not_recorded','awaiting_report','report_submitted'}}
        if not isinstance(data,dict) or not data or set(data)-set(allowed):raise ValidationError('ข้อมูลความคืบหน้าไม่ถูกต้อง')
        for key,value in data.items():
            if not isinstance(value,str) or value not in allowed[key]:raise ValidationError('สถานะความคืบหน้าไม่ถูกต้อง')
        before=project_data(row,True)
        for key,value in data.items():setattr(row,key,value)
        audit(row,'update_progress',before);db.session.commit();return jsonify(project_data(row,True))
    @app.post('/api/finance/projects/<int:id>/complete')
    @authenticated()
    def complete_project(id):
        lock();row=get_project(id,True)
        if row.status!='approved':raise ValidationError('ปิดโครงการได้เฉพาะโครงการที่อนุมัติแล้ว')
        before=project_data(row);row.status='completed';audit(row,'complete',before);db.session.commit();return jsonify(project_data(row,True))
    def set_expense(row,data,project):
        category=text(data,'category',60)
        if category not in CATEGORIES:raise ValidationError('หมวดค่าใช้จ่ายไม่ถูกต้อง')
        planned=money(data.get('planned',0));actual=money(data.get('actual',0));description=text(data,'description',1000,True)
        if project.status in ['submitted','approved','completed'] and current_user().role!='admin':
            if row.id is None or row.planned!=planned or row.description!=description or row.category!=category:raise ValidationError('แผนที่ส่งอนุมัติแล้วแก้ไขได้เฉพาะแอดมิน ส่วนผู้รับผิดชอบบันทึกค่าใช้จ่ายจริงได้')
        if project.status=='completed' and current_user().role!='admin':raise ValidationError('โครงการปิดแล้ว แก้ไขได้เฉพาะแอดมิน')
        method=data.get('disbursement','');item_type=data.get('item_type','')
        if method not in DISBURSEMENTS or item_type not in ITEM_TYPES:raise ValidationError('กรุณาเลือกการเบิกจ่าย (จ่ายตรง/สำรองจ่าย/ทดรองจ่าย) และประเภทเบิกจ่ายที่กำหนด')
        state=data.get('payment_status','unpaid')
        if state not in ['unpaid','requested','paid']:raise ValidationError('สถานะเบิกจ่ายไม่ถูกต้อง')
        if project.status in ['draft','rejected','submitted'] and (actual or state=='paid'):raise ValidationError('ต้องอนุมัติโครงการก่อนบันทึกใช้จ่ายจริงหรือเบิกจ่ายแล้ว')
        row.category=category;row.planned=planned;row.actual=actual;row.description=description;row.disbursement=method;row.payment_status=state;row.item_type=item_type
        for key,length in [('item_no',20),('payment_type',180),('pr_number',100),('payee',180),('responsible',180),('quantity',30),('unit_price',30),('multiplier',30)]:setattr(row,key,text(data,key,length))
    @app.route('/api/finance/projects/<int:id>/expenses',methods=['POST'])
    @app.route('/api/finance/projects/<int:id>/expenses/<int:expense_id>',methods=['PATCH','DELETE'])
    @authenticated()
    def edit_expense(id,expense_id=None):
        lock();project=get_project(id,True);before=project_data(project,True)
        row=db.session.get(Expense,expense_id) if expense_id else Expense(project_id=id)
        if not row or row.project_id!=id:abort(404)
        if request.method=='DELETE':
            if project.status not in ['draft','rejected'] and current_user().role!='admin':raise ValidationError('ลบรายการแผนที่ส่งอนุมัติแล้วได้เฉพาะแอดมิน')
            db.session.delete(row);action='delete_expense'
        else:
            set_expense(row,request.get_json(silent=True) or {},project);db.session.add(row);action='edit_expense' if expense_id else 'add_expense'
        audit(project,action,before);db.session.commit();return jsonify(project_data(project,True))
    @app.patch('/api/finance/projects/<int:id>/expenses/<int:expense_id>/payee')
    @authenticated()
    def edit_expense_payee(id,expense_id):
        lock();project=get_project(id,True)
        if project.status=='completed' and current_user().role!='admin':abort(403)
        row=db.session.get(Expense,expense_id)
        if not row or row.project_id!=id:abort(404)
        before=project_data(project,True);data=request.get_json(silent=True) or {}
        row.payee=text(data,'payee',180);audit(project,'edit_expense',before);db.session.commit()
        return jsonify(project_data(project,True))
    @app.get('/api/finance/projects/<int:id>/export')
    @authenticated()
    def export_finance(id):
        from openpyxl import Workbook
        from openpyxl.styles import Font,PatternFill,Alignment
        row=get_project(id);data=project_data(row,True);wb=Workbook();sheet=wb.active;sheet.title='แผนค่าใช้จ่าย'
        def safe(value):return "'"+value if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@','\t','\r')) else value
        sheet.append([f'แบบสรุปค่าใช้จ่ายกิจกรรมตามแผนปฏิบัติการ ประจำปีงบประมาณ {row.fiscal_year}'])
        for label,value in [('หน่วยงาน',data['organization']),('โครงการ',row.title),('ผู้รับผิดชอบ',row.responsible),('สถานที่',row.location),('งบประมาณที่ได้รับ',float(data['budget_received'])),('ผู้ยืม',row.borrower),('สัญญาเงินยืม',row.loan_contract),('ครบกำหนด',data['loan_due_date']),('จำนวนเงินยืม',float(data['loan_amount']))]:sheet.append([label,safe(value)])
        sheet.append([]);sheet.append(['ที่','หมวด','รายการ','จำนวนเงิน/โครงการ','การเบิกจ่าย','ประเภทรายการ','สถานะการจ่ายเงิน','เลข PR','ผู้เหมาจ่าย/ผู้ออกบิล','ผู้รับผิดชอบ','ใช้จ่ายจริง','ส่วนต่าง','องค์การนักศึกษาจัดสรร','ส่วนต่างองค์การนักศึกษา','เหตุผลองค์การนักศึกษา','สภานักศึกษาจัดสรร','ส่วนต่างสภานักศึกษา','เหตุผลสภานักศึกษา'])
        for item in data['expenses']:
            union=float(item['union_allocated']) if item['union_allocated'] is not None else None;council=float(item['council_allocated']) if item['council_allocated'] is not None else None
            sheet.append([safe(item['item_no']),item['category'],safe(item['description']),float(item['planned']),item['disbursement'],item['item_type'],{'unpaid':'ยังไม่เบิก','requested':'ขอเบิกแล้ว','paid':'เบิกจ่ายแล้ว'}[item['payment_status']],safe(item['pr_number']),safe(item['payee']),safe(item['responsible']),float(item['actual']),float(item['difference']),union,union-float(item['planned']) if union is not None else None,safe(item['union_reason']),council,council-float(item['planned']) if council is not None else None,safe(item['council_reason'])])
        sheet.append(['รวม','','',float(data['planned']),'','','','','','',float(data['actual']),float(data['difference'])]);sheet.append(['งบคงเหลือ',float(data['remaining'])]);sheet.append(['เงินยืมคงเหลือ (ประเภทเงินยืม)',float(data['loan_remaining'])])
        for col in range(1,19):sheet.column_dimensions[__import__('openpyxl').utils.get_column_letter(col)].width=24
        sheet.column_dimensions['C'].width=70;sheet.column_dimensions['O'].width=45;sheet.column_dimensions['R'].width=45
        for cell in sheet[12]:cell.fill=PatternFill('solid',fgColor='A73B24');cell.font=Font(color='FFFFFF',bold=True)
        sheet.freeze_panes='D13';sheet.auto_filter.ref=f'A12:R{12+len(data["expenses"])}'
        for cells in sheet.iter_rows(min_row=13):
            for cell in cells:
                if isinstance(cell.value,(float,int)):cell.number_format='#,##0.00'
                cell.alignment=Alignment(vertical='top',wrap_text=True)
        info=wb.create_sheet('รายละเอียดโครงการ');info.append(['หมวดงบประมาณ',safe(data['budget_fund_label'])]);info.append(['มีการยืมเงิน', 'มี' if data['has_loan'] else 'ไม่มี']);info.append(['วันที่ขอรับเงิน',data['loan_request_date']]);info.append(['วันที่คืนเงินยืม (30 วัน)',data['loan_due_date']]);info.append(['ปีงบประมาณ',row.fiscal_year]);info.append(['รอบงบประมาณ',data['budget_period_label']]);info.append(['ที่ปรึกษาองค์กรกิจกรรม',safe(row.advisor)]);info.append(['วันที่เริ่มกิจกรรม',row.activity_start]);info.append(['วันที่สิ้นสุดกิจกรรม',row.activity_end]);info.append(['รายละเอียดงบประมาณ',safe(row.budget_details)]);info.append(['เป้าหมายผู้เข้าร่วมรวม',data['participant_total']]);
        for group in data['participants']:info.append([safe(group['label']),group['count']])
        info.append(['สถานะเบิกจ่ายหลังจัดกิจกรรม',{'not_recorded':'ยังไม่ระบุ','awaiting_disbursement':'ดำเนินการจัดกิจกรรมแล้วรอเบิกจ่าย','disbursed':'เบิกจ่ายแล้ว'}.get(row.disbursement_progress,'')]);info.append(['สถานะรายงานสรุปผล',{'not_recorded':'ยังไม่ระบุ','awaiting_report':'ดำเนินการจัดกิจกรรมเรียบร้อยแล้วรอส่งรายงานสรุปผลการดำเนินโครงการ','report_submitted':'ส่งรายงานสรุปผลการดำเนินโครงการเรียบร้อย'}.get(row.report_progress,'')]);info.append(['เลขหนังสือขออนุมัติจัดโครงการ',safe(row.approval_document_number)]);info.append(['ลำดับการอนุมัติ',row.approval_number or '']);info.append(['หลักการและเหตุผล',safe(row.rationale)]);info.append(['สถานะอนุมัติ',data['approval_stage_label']]);info.append(['วัตถุประสงค์',safe(row.objectives)]);info.append(['หมวดการประเมิน',safe(data['evaluation_category_label'])]);info.append(['การประเมินกิจกรรม',safe(row.evaluation)]);info.column_dimensions['A'].width=28;info.column_dimensions['B'].width=100
        activities=wb.create_sheet('กิจกรรม');activities.append(ACTIVITY_FIELDS)
        for activity in data['activities']:activities.append([safe(activity.get(key,'')) for key in ACTIVITY_FIELDS])
        output=io.BytesIO();wb.save(output);output.seek(0);return send_file(output,as_attachment=True,download_name=f'SUDMS-project-{id}.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
