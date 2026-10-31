"""Evaluation coverage from project activities; no inferred assessment scores."""
import json,re
from pathlib import Path
from flask import request,jsonify,render_template,send_file,abort
OKRS=[8,9,10,12,72,77]
EGGS={**{f'E{i}':v for i,v in enumerate(['ความคิดสร้างสรรค์และนวัตกรรม','การจัดการ','การจัดการการเงินและบัญชี','ภาวะผู้นำ','การตลาดและการสร้างแบรนด์','การคิดเชิงออกแบบและการแก้ปัญหา'],1)},**{f'Gm{i}':v for i,v in enumerate(['การสื่อสาร','AI และการรู้ดิจิทัล','ความสามารถในการใช้ภาษาต่างประเทศ','แนวโน้มโลกและวัฒนธรรมสากล','การยอมรับความหลากหลาย'],1)},**{f'Go{i}':v for i,v in enumerate(['การเรียนรู้ตลอดชีวิต','การจัดการตนเองเพื่อการดูแลตนเอง','สุขภาพและความเป็นอยู่ที่ดี','บุคลิกภาพและมารยาททางสังคม','ความเข้าใจผู้อื่นและรับฟังอย่างตั้งใจ','ความยืดหยุ่นและการปรับตัว'],1)},**{f'S{i}':v for i,v in enumerate(['สิ่งแวดล้อมและการพัฒนาอย่างยั่งยืน','การอุทิศต่อสังคม','การทำงานร่วมกันและการสร้างเครือข่าย','คุณธรรมจริยธรรม','กฎหมาย กฎระเบียบ และความยุติธรรม'],1)}}
from finance import BUDGET_FUNDS
FUNDS={key:'หมวด '+BUDGET_FUNDS[key] for key in ['ทั่วไป','กีฬา']}
FUND_AMOUNTS={'ทั่วไป':dict(amount='1400000.00',amount_text='หนึ่งล้านสี่แสนบาทถ้วน'),'กีฬา':dict(amount='1500000.00',amount_text='หนึ่งล้านห้าแสนบาทถ้วน')}
GROUPS={'E':'Entrepreneurial · มีความคิดเชิงการประกอบการ','Gm':'Global-minded · มีมุมมองและความรู้ในระดับสากล','Go':'Growth-oriented · มุ่งเติบโตและพัฒนาอย่างต่อเนื่อง','S':'Sustainable-focused · ใส่ใจความยั่งยืน'}
def codes(value,kind):
    value=str(value or '').translate(str.maketrans('๐๑๒๓๔๕๖๗๘๙','0123456789'))
    if kind=='eggs':
        found=re.findall(r'(?i)(?<![a-z])(gm|go|e|s)\s*(\d+)(?!\d)',value)
        return {a.lower().capitalize()+str(int(b)) for a,b in found if a.lower().capitalize()+str(int(b)) in EGGS}
    return {int(n) for n in re.findall(r'(?<![\d.])\b(\d+)(?![\d.])',re.sub(r'(?i)OKRs?|SDGs?',' ',value))}
def summarize(projects,organization_names):
    total=len(projects);counts={'okr':{f'OKR{i}':0 for i in OKRS},'sdgs':{f'SDG{i}':0 for i in range(1,18)},'eggs':{k:0 for k in GROUPS},'eggs_skills':{k:0 for k in EGGS}}
    missing=dict(okr=0,sdgs=0,eggs=0);issues=[];rows=[];activities_total=0
    for project in projects:
        activities=json.loads(project.activities or '[]');activities_total+=len(activities);okr=set();sdgs=set();eggs=set()
        for activity in activities:
            raw_okr=codes(activity.get('okr'),'okr');raw_sdgs=codes(activity.get('sdgs'),'sdgs')
            okr.update(raw_okr&set(OKRS));sdgs.update(raw_sdgs&set(range(1,18)))
            for key in ['eggs_core','eggs_sub']:eggs.update(codes(activity.get(key),'eggs'))
            for kind,raw,valid in [('OKR',raw_okr,set(OKRS)),('SDG',raw_sdgs,set(range(1,18)))]:
                if raw-valid:issues.append(dict(project_id=project.id,title=project.title,note=kind+' นอกขอบเขต: '+', '.join(map(str,sorted(raw-valid)))))
            for key in ['okr','sdgs','eggs_core','eggs_sub']:
                raw=str(activity.get(key) or '').strip()
                if raw and raw not in ['-','–','ไม่ระบุ'] and not codes(raw,'eggs' if key.startswith('eggs') else key):issues.append(dict(project_id=project.id,title=project.title,note='อ่านรหัสไม่ได้: '+key+' = '+raw))
        groups={re.sub(r'\d+$','',k) for k in eggs}
        for kind,values in [('okr',okr),('sdgs',sdgs),('eggs',groups)]:
            if not values:missing[kind]+=1
        for n in okr:counts['okr'][f'OKR{n}']+=1
        for n in sdgs:counts['sdgs'][f'SDG{n}']+=1
        for n in eggs:counts['eggs_skills'][n]+=1
        for n in groups:counts['eggs'][n]+=1
        rows.append(dict(id=project.id,title=project.title,organization=organization_names.get(project.organization_id,''),category=FUNDS.get(project.budget_category,project.budget_category),requests_budget=project.requests_budget,activities=len(activities),okr=[f'OKR{n}' for n in sorted(okr)],sdgs=[f'SDG{n}' for n in sorted(sdgs)],eggs=sorted(eggs)))
    charts={kind:[dict(code=code,label=GROUPS.get(code,code) if kind=='eggs' else EGGS.get(code,code) if kind=='eggs_skills' else code,projects=count,percent=round(count*100/total,2) if total else 0) for code,count in values.items()] for kind,values in counts.items()}
    return dict(total_projects=total,total_activities=activities_total,no_budget_projects=sum(not p.requests_budget for p in projects),missing=missing,charts=charts,projects=rows,issues=issues)
def register_evaluation(app,db,Project,Organization,authenticated,now):
    @app.get('/evaluation')
    @authenticated()
    def evaluation_page():return render_template('evaluation.html',evaluation_year=now().year+543+(1 if now().month>=10 else 0))
    @app.get('/api/evaluation/summary')
    @authenticated()
    def evaluation_summary():
        try:
            year=int(request.args.get('year',now().year+543+(1 if now().month>=10 else 0)))
            if not 2500<=year<=2700:raise ValueError()
            cycle=request.args.get('round','')
            if cycle not in ['','1','2']:raise ValueError()
        except (ValueError,TypeError):return jsonify(error='ปีหรือรอบงบประมาณไม่ถูกต้อง'),400
        query=Project.query.filter_by(fiscal_year=year)
        if cycle:query=query.filter_by(budget_round=int(cycle))
        projects=query.order_by(Project.id).all();names={o.id:o.name for o in Organization.query.all()}
        return jsonify(year=year,budget_round=cycle,overall=summarize(projects,names),categories=[dict(category=key,label=label,**FUND_AMOUNTS[key],**summarize([p for p in projects if p.budget_category==key],names)) for key,label in FUNDS.items()])
    @app.get('/evaluation/documents/<key>')
    @authenticated()
    def evaluation_document(key):
        files={'eggs':'eggs-manual-march-2026.pdf','okr':'okr-dictionary-2569.pdf'}
        if key not in files:abort(404)
        return send_file(Path(app.root_path)/'resources/evaluation'/files[key],mimetype='application/pdf',as_attachment=True,download_name=files[key])
