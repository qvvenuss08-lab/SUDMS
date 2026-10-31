import unittest,tempfile,sys,io,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,r'C:\คอมปี 2\SUDMS')
from app import create_app,db,User,Organization,FinanceProject,FinanceExpense,FinanceAudit
from werkzeug.security import generate_password_hash
from openpyxl import load_workbook
class FinanceTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.app=create_app({'TESTING':True,'SECRET_KEY':'test','SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(Path(self.tmp.name)/'db.sqlite'),'UPLOAD_FOLDER':str(Path(self.tmp.name)/'uploads')});self.ctx=self.app.app_context();self.ctx.push();orgs=Organization.query.order_by(Organization.id).all();self.a=orgs[0].id;self.b=orgs[1].id
  for name,oid,role in [('owner',self.a,'user'),('other',self.b,'user'),('admin',self.a,'admin')]:db.session.add(User(name=name,email=name+'@kkumail.com',student_id={'owner':'683050391-3','other':'683050392-3','admin':'683050393-3'}[name],organization_id=oid,status='approved',role=role,password_hash=generate_password_hash('Password123!')))
  db.session.commit();self.c=self.app.test_client();self.login('owner')
 def tearDown(self):db.session.remove();db.engine.dispose();self.ctx.pop();self.tmp.cleanup()
 def login(self,name):
  uid=User.query.filter_by(name=name).one().id
  with self.c.session_transaction() as s:s['user_id']=uid;s['csrf_token']='test'
 def post(self,path,data):return self.c.post(path,json=data,headers={'X-CSRF-Token':'test'})
 def data(self,budget=True,oid=None):return dict(title='โครงการทดสอบ',organization_id=oid or self.a,fiscal_year=2569,requests_budget=budget,budget_received='0',objectives='วัตถุประสงค์',evaluation='ประเมินความพึงพอใจ',responsible='ผู้รับผิดชอบ',location='มข.',activities=[dict(title='อ่านหนังสือ',okr='OKR10',sdgs='3',eggs_core='Go2',ksa_k='3',ksa_s='3',ksa_a='3',approach='Ap6')],loan_amount='0')
 def create(self,budget=True):
  response=self.post('/api/finance/projects',self.data(budget));self.assertEqual(response.status_code,201,response.json);return response.json['id']
 def expense(self):return dict(category='ค่าใช้สอย',item_no='1.1',description='ค่าอาหาร',planned='6000.10',actual='0',disbursement='จ่ายตรง',item_type='ว.119',payment_status='unpaid',quantity='60',unit_price='50',multiplier='2')
 def approve(self,id,amount='6000.10'):
  self.assertEqual(self.post(f'/api/finance/projects/{id}/submit',{}).status_code,200);self.login('admin');r=self.post(f'/api/finance/projects/{id}/review',dict(decision='approved',budget_received=amount,note='อนุมัติ'));self.assertEqual(r.status_code,200,r.json)
 def test_dashboard_project_counts_and_exact_money(self):
  id=self.create();r=self.post(f'/api/finance/projects/{id}/expenses',self.expense());self.assertEqual(r.status_code,200,r.json);self.approve(id);self.login('owner');self.create(False)
  data=self.c.get('/api/finance/dashboard?year=2569').json;self.assertEqual(data['total_projects'],2);self.assertEqual(data['budget_projects'],1);self.assertEqual(data['no_budget_projects'],1);self.assertEqual(data['submitted_projects'],1);self.assertEqual(data['approved_projects'],1);self.assertEqual(data['total_money'],'6000.10');self.assertEqual(data['planned'],'6000.10');self.assertEqual(next(o for o in data['organizations'] if o['id']==self.a)['share'],'100.00')
 def test_permissions_and_status_transitions(self):
  id=self.create();self.login('other');self.assertEqual(self.post(f'/api/finance/projects/{id}/expenses',self.expense()).status_code,403);self.assertEqual(self.post('/api/finance/projects',self.data(oid=self.a)).status_code,403);self.assertEqual(self.c.get(f'/api/finance/projects/{id}').status_code,200);self.login('owner');self.assertEqual(self.post(f'/api/finance/projects/{id}/review',dict(decision='approved')).status_code,403);self.assertEqual(self.post(f'/api/finance/projects/{id}/submit',{}).status_code,400)
  self.post(f'/api/finance/projects/{id}/expenses',self.expense());self.approve(id);self.login('owner');self.assertEqual(self.c.patch(f'/api/finance/projects/{id}',json=self.data(),headers={'X-CSRF-Token':'test'}).status_code,400);eid=FinanceExpense.query.filter_by(project_id=id).one().id;self.assertEqual(self.c.delete(f'/api/finance/projects/{id}/expenses/{eid}',json={},headers={'X-CSRF-Token':'test'}).status_code,400)
  data=self.expense();data.update(actual='5500.05',payment_status='paid');response=self.c.patch(f'/api/finance/projects/{id}/expenses/{eid}',json=data,headers={'X-CSRF-Token':'test'});self.assertEqual(response.status_code,200,response.json);self.assertEqual(response.json['difference'],'500.05');self.assertEqual(response.json['remaining'],'500.05');self.assertEqual(response.json['paid'],'5500.05');self.assertEqual(self.post(f'/api/finance/projects/{id}/complete',{}).status_code,200)
 def test_invalid_currency_csrf_and_audit(self):
  id=self.create()
  for value in ['-1','NaN','Infinity','1.001',True]:
   data=self.expense();data['planned']=value;self.assertEqual(self.post(f'/api/finance/projects/{id}/expenses',data).status_code,400)
  self.assertEqual(self.c.post('/api/finance/projects',json=self.data()).status_code,400)
  data=self.expense();data['actual']='1';self.assertEqual(self.post(f'/api/finance/projects/{id}/expenses',data).status_code,400)
  self.post(f'/api/finance/projects/{id}/expenses',self.expense());log=FinanceAudit.query.filter_by(project_id=id,action='add_expense').one();self.assertEqual(json.loads(log.changes)['after']['expenses'][0]['planned'],'6000.10')
 def test_export_formula_safety_and_pages(self):
  id=self.create(False);item=self.expense();item['description']='=HYPERLINK("bad")';self.post(f'/api/finance/projects/{id}/expenses',item)
  response=self.c.get(f'/api/finance/projects/{id}/export');self.assertEqual(response.status_code,200);wb=load_workbook(io.BytesIO(response.data));self.assertEqual(wb.active['C13'].data_type,'s');self.assertTrue(wb.active['C13'].value.startswith("'="));self.assertEqual(wb.active['D13'].value,6000.1)
  self.assertEqual(self.c.get('/finance').status_code,200);self.assertEqual(self.c.get(f'/finance/projects/{id}').status_code,200)
 def test_no_budget_approval_and_rejection(self):
  id=self.create(False);self.assertEqual(self.post(f'/api/finance/projects/{id}/submit',{}).status_code,200);self.login('admin');self.assertEqual(self.post(f'/api/finance/projects/{id}/review',dict(decision='approved',budget_received='1')).status_code,400);response=self.post(f'/api/finance/projects/{id}/review',dict(decision='rejected',note='แก้ไข'));self.assertEqual(response.status_code,200);self.login('owner');self.assertEqual(self.c.patch(f'/api/finance/projects/{id}',json=self.data(False),headers={'X-CSRF-Token':'test'}).status_code,200)
 def test_sequential_approvals_and_club_authority(self):
  id=self.create();self.post(f'/api/finance/projects/{id}/expenses',self.expense());self.approve(id)
  r=self.post(f'/api/finance/projects/{id}/approval-stage',dict(stage='affairs_approved'));self.assertEqual(r.status_code,400)
  r=self.post(f'/api/finance/projects/{id}/approval-stage',dict(stage='department_approved',note='เลขหนังสือ 1'));self.assertEqual(r.status_code,200,r.json)
  r=self.post(f'/api/finance/projects/{id}/approval-stage',dict(stage='affairs_approved'));self.assertEqual(r.status_code,200);self.assertEqual(r.json['approval_stage_label'],'ฝ่ายกิจการนักศึกษาอนุมัติ')
  self.login('owner');self.assertEqual(self.post(f'/api/finance/projects/{id}/approval-stage',dict(stage='affairs_approved')).status_code,403)
  self.login('admin');sports=Organization.query.filter_by(name='ชมรมฟุตบอล').one();r=self.post('/api/finance/projects',self.data(oid=sports.id));self.assertEqual(r.status_code,201);self.assertEqual(r.json['department_authority'],'กองการกีฬา');self.assertEqual(r.json['club_type'],'sports')
  general=Organization.query.filter_by(name='ชมรมถ่ายภาพ').one();r=self.post('/api/finance/projects',self.data(oid=general.id));self.assertEqual(r.json['department_authority'],'กองพัฒนานักศึกษาและศิษย์เก่าสัมพันธ์');self.assertEqual(r.json['club_type'],'general')
 def test_expense_required_choices_are_separate_from_payment_status(self):
  id=self.create()
  for method in ['จ่ายตรง','สำรองจ่าย','ทดรองจ่าย']:
   for kind in ['จัดหารวมศูนย์','ว.119','จ่ายตรง']:
    data=self.expense();data.update(disbursement=method,item_type=kind);r=self.post(f'/api/finance/projects/{id}/expenses',data);self.assertEqual(r.status_code,200,r.json);self.assertEqual(r.json['expenses'][-1]['payment_status'],'unpaid')
  data=self.expense();data['disbursement']='อื่น';self.assertEqual(self.post(f'/api/finance/projects/{id}/expenses',data).status_code,400)
  data=self.expense();data['item_type']='อื่น';self.assertEqual(self.post(f'/api/finance/projects/{id}/expenses',data).status_code,400)


 def test_annual_budget_and_project_registration_details(self):
  path='/api/finance/annual-budget?year=2570'
  self.assertEqual(self.c.put(path,json={'fund':'กีฬา','amount':'1000'},headers={'X-CSRF-Token':'test'}).status_code,403)
  self.login('admin')
  for fund,total in [('กีฬา','150000.25'),('ทั่วไป','200000.00')]:
   r=self.c.put(path,json={'fund':fund,'amount':total},headers={'X-CSRF-Token':'test'});self.assertEqual(r.status_code,200,r.json)
  self.assertEqual(self.c.get('/api/finance/annual-budget?year=2569').json['funds'][0]['amount'],'0.00')
  values=self.data();values.update(fiscal_year=2570,budget_category='กีฬา',budget_received='12000.50',advisor='ที่ปรึกษา',activity_start='2026-11-01',activity_end='2026-11-03',participants=[{'label':'นักศึกษา','count':500},{'label':'คณะดำเนินงาน','count':20}],budget_details='เงินอุดหนุนทั่วไป')
  r=self.post('/api/finance/projects',values);self.assertEqual(r.status_code,201,r.json);project=r.json
  self.assertEqual(project['participant_total'],520);self.assertEqual(project['advisor'],'ที่ปรึกษา');self.assertIn('131239',project['budget_fund_label'])
  annual=self.c.get(path).json['funds'][0];self.assertEqual(annual['allocated'],'12000.50');self.assertEqual(annual['remaining'],'137999.75')
  item=self.expense();item['category']='ค่าใช้จ่ายเบ็ดเตล็ด';self.assertEqual(self.post('/api/finance/projects/'+str(project['id'])+'/expenses',item).status_code,200)
  values['participants']=[{'label':'ผิด','count':-1}];self.assertEqual(self.post('/api/finance/projects',values).status_code,400)
  values['participants']=[];values['activity_end']='2026-10-01';self.assertEqual(self.post('/api/finance/projects',values).status_code,400)

 def test_budget_round_dates_amounts_filters_and_permissions(self):
  base='/api/finance/budget-round?year=2570&round='
  values={'fund':'กีฬา','amount':'100000.25','periods':[{'start':'2026-10-01','end':'2026-12-25'},{'start':'2027-01-01','end':'2027-03-20'}]}
  headers={'X-CSRF-Token':'test'}
  self.assertEqual(self.c.put(base+'1',json=values,headers=headers).status_code,403)
  self.login('admin');r=self.c.put(base+'1',json=values,headers=headers);self.assertEqual(r.status_code,200,r.json)
  self.assertEqual(r.json['funds'][0]['periods'][0]['end'],'2026-12-25')
  second={**values,'amount':'25000.50','periods':[{'start':'2027-04-01','end':'2027-06-22'},{'start':'2027-07-01','end':'2027-09-20'}]}
  self.assertEqual(self.c.put(base+'2',json=second,headers=headers).status_code,200)
  self.assertEqual(self.c.get(base+'1').json['funds'][0]['amount'],'100000.25')
  self.assertEqual(self.c.get('/api/finance/budget-round?year=2571&round=1').json['funds'][0]['configured'],False)
  for periods in [[{'start':'2027-04-01','end':'2027-03-01'},second['periods'][1]],[{'start':'2027-03-01','end':'2027-05-01'},second['periods'][1]],[{'start':'2027-04-01','end':'2027-06-22'},{'start':'2027-06-22','end':'2027-09-20'}]]:
   self.assertEqual(self.c.put(base+'2',json={**second,'periods':periods},headers=headers).status_code,400)
  self.assertEqual(self.c.get(base+'3').status_code,400)
  for cycle,total in [(1,'1000.25'),(2,'500.50')]:
   data=self.data();data.update(fiscal_year=2570,budget_round=cycle,budget_category='กีฬา',budget_received=total)
   r=self.post('/api/finance/projects',data);self.assertEqual(r.status_code,201,r.json);self.assertEqual(r.json['budget_period_label'],str(cycle)+'/2570')
   self.assertEqual(self.c.get('/api/finance/dashboard?year=2570&round='+str(cycle)).json['total_projects'],1)
   self.assertEqual(len(self.c.get('/api/finance/projects?year=2570&round='+str(cycle)).json['projects']),1)
  self.assertEqual(self.c.get(base+'1').json['funds'][0]['remaining'],'99000.00')
  self.assertEqual(self.c.get(base+'2').json['funds'][0]['remaining'],'24500.00')

 def test_current_period_uses_dates_and_fiscal_boundaries(self):
  from finance import active_budget_period
  from datetime import date
  for day,expected in [('2026-10-01',(2570,1)),('2027-03-31',(2570,1)),('2027-04-01',(2570,2)),('2027-09-30',(2570,2)),('2027-10-01',(2571,1))]:
   self.assertIsNone(active_budget_period(date.fromisoformat(day),[]))
  records=[dict(fiscal_year=2570,budget_round=1,periods=json.dumps([{'start':'2026-10-01','end':'2026-12-25'},{'start':'2027-01-01','end':'2027-04-05'}]))]
  self.assertEqual(active_budget_period(date(2027,4,3),records),(2570,1))
  response=self.c.get('/api/finance/current-budget');self.assertEqual(response.status_code,200)
  self.assertEqual(response.json['status'],'waiting');self.assertEqual(response.json['funds'],[])
  self.assertEqual(self.c.get('/finance').status_code,200)

 def test_single_round_waits_until_admin_configures_next(self):
  from datetime import date
  from finance import active_budget_period
  self.login('admin');headers={'X-CSRF-Token':'test'}
  data={'fund':'ทั่วไป','amount':'1400000','periods':[{'start':'2026-10-01','end':'2027-03-18'}]}
  response=self.c.put('/api/finance/budget-round?year=2570&round=1',json=data,headers=headers)
  self.assertEqual(response.status_code,200,response.json);self.assertEqual(len(response.json['funds'][1]['periods']),1)
  records=[{'fiscal_year':2570,'budget_round':1,'periods':json.dumps(data['periods'])}]
  self.assertEqual(active_budget_period(date(2027,3,18),records),(2570,1))
  self.assertIsNone(active_budget_period(date(2027,3,19),records))
  self.assertIsNone(active_budget_period(date(2027,10,1),records))
  page=self.c.get('/finance').get_data(as_text=True);self.assertIn('name="round_start"',page);self.assertNotIn('name="q2_start"',page)

 def test_project_loan_due_date_calculated_and_optional(self):
  data=self.data();data.update(has_loan=True,loan_contract='ยืม1/2570',borrower='ผู้ยืม',loan_amount='5000.25',loan_request_date='2028-02-01',loan_due_date='2099-01-01')
  response=self.post('/api/finance/projects',data);self.assertEqual(response.status_code,201,response.json);project=response.json
  self.assertEqual(project['loan_due_date'],'2028-03-02');self.assertTrue(project['has_loan'])
  data['loan_request_date']='2026-12-15';response=self.c.patch('/api/finance/projects/'+str(project['id']),json=data,headers={'X-CSRF-Token':'test'})
  self.assertEqual(response.status_code,200,response.json);self.assertEqual(response.json['loan_due_date'],'2027-01-14')
  for change in [{'borrower':''},{'loan_contract':''},{'loan_amount':'0'},{'loan_request_date':'2026-02-30'}]:
   self.assertEqual(self.post('/api/finance/projects',{**data,**change}).status_code,400)
  data['has_loan']=False;response=self.c.patch('/api/finance/projects/'+str(project['id']),json=data,headers={'X-CSRF-Token':'test'})
  self.assertEqual(response.status_code,200);self.assertFalse(response.json['has_loan']);self.assertEqual(response.json['loan_amount'],'0.00');self.assertEqual(response.json['loan_due_date'],'');self.assertEqual(response.json['loan_request_date'],'')
 def test_all_expense_categories_and_new_payment_types(self):
  id=self.create()
  categories=['ค่าตอบแทน','ค่าใช้สอย','ค่าวัสดุ','ค่าใช้จ่ายเบ็ดเตล็ด']
  for category in categories:
   for kind in ['จ่ายตรง','ว.119','จัดหารวมศูนย์','ค่าตอบแทน','ค่าเดินทางไปราชการ','ค่าอาหาร']:
    data=self.expense();data.update(category=category,item_type=kind,planned='100.25');response=self.post(f'/api/finance/projects/{id}/expenses',data);self.assertEqual(response.status_code,200,response.json)
  project=response.json;self.assertEqual(project['planned'],'2406.00')
  for c in project['category_totals']:
   if c['category'] in categories:self.assertEqual(c['planned'],'601.50')

 def test_inline_payee_permissions_and_preserves_money(self):
  id=self.create();response=self.post(f'/api/finance/projects/{id}/expenses',self.expense());expense=response.json['expenses'][0];path=f"/api/finance/projects/{id}/expenses/{expense['id']}/payee"
  headers={'X-CSRF-Token':'test'}
  self.assertEqual(self.c.patch(path,json={'payee':'ร้านค้า'}).status_code,400)
  self.login('other');self.assertEqual(self.c.patch(path,json={'payee':'ร้านค้า'},headers=headers).status_code,403)
  self.login('owner');response=self.c.patch(path,json={'payee':'ร้านตัวอย่าง','planned':'0'},headers=headers)
  self.assertEqual(response.status_code,200,response.json);self.assertEqual(response.json['expenses'][0]['payee'],'ร้านตัวอย่าง');self.assertEqual(response.json['expenses'][0]['planned'],expense['planned'])
  self.assertEqual(self.c.patch(path,json={'payee':'x'*181},headers=headers).status_code,400)
  self.assertEqual(self.c.patch(path.replace('/expenses/'+str(expense['id']),'/expenses/999999'),json={'payee':'ร้านค้า'},headers=headers).status_code,404)
  self.assertEqual(self.c.patch(path,json={'payee':''},headers=headers).json['expenses'][0]['payee'],'')

 def test_non_budget_projects_keep_evaluation_category(self):
  for category in ['กีฬา','ทั่วไป']:
   data=self.data(False);data.update(budget_category=category,evaluation='')
   response=self.post('/api/finance/projects',data);self.assertEqual(response.status_code,201,response.json)
   project=response.json;self.assertEqual(project['evaluation_category'],category);self.assertTrue(project['evaluation_required']);self.assertEqual(project['budget_received'],'0.00')
   self.assertEqual(self.post('/api/finance/projects/'+str(project['id'])+'/submit',{}).status_code,400)
   data['evaluation']='บันทึกการประเมินตามหมวด'
   response=self.c.patch('/api/finance/projects/'+str(project['id']),json=data,headers={'X-CSRF-Token':'test'});self.assertEqual(response.status_code,200)
   self.assertEqual(self.post('/api/finance/projects/'+str(project['id'])+'/submit',{}).status_code,200)
  summary=self.c.get('/api/finance/dashboard?year=2569').json
  for category in summary['evaluation_categories']:
   self.assertEqual(category['no_budget_projects'],1);self.assertEqual(category['recorded_evaluations'],1)
  self.assertEqual(summary['total_money'],'0.00')

 def test_multiple_target_groups_per_activity(self):
  data=self.data();data['activities'][0]['target_groups']=[{'label':'นักศึกษาทั่วไป','count':500},{'label':'คณะดำเนินงาน','count':20}]
  data['activities'].append({'title':'กิจกรรมสอง','target_groups':[{'label':'บุคลากร','count':10}]})
  response=self.post('/api/finance/projects',data);self.assertEqual(response.status_code,201,response.json)
  saved=self.c.get('/api/finance/projects/'+str(response.json['id'])).json
  self.assertEqual(saved['activities'][0]['participants'],'520');self.assertEqual(len(saved['activities'][0]['target_groups']),2);self.assertEqual(saved['activities'][1]['participants'],'10')
  self.assertIn('คณะดำเนินงาน (20 คน)',saved['activities'][0]['target_group'])
  data['activities'][0]['target_groups'][0]['count']=-1;self.assertEqual(self.post('/api/finance/projects',data).status_code,400)
