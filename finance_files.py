"""Private, authenticated project attachments."""
import io,json,uuid,hashlib,zipfile
from pathlib import Path
from sqlalchemy import text
from flask import request,jsonify,abort,send_file
LIMIT=9*1024*1024
EXTENSIONS={'.pdf','.doc','.docx','.xls','.xlsx','.png','.jpg','.jpeg'}
def setup_project_files(app,db,Project,authenticated,current_user,now,lock,ValidationError,get_project,project_data,audit):
    folder=Path(app.config['UPLOAD_FOLDER']).parent/'project_uploads';folder.mkdir(parents=True,exist_ok=True)
    with app.app_context():
        db.session.execute(text('CREATE TABLE IF NOT EXISTS finance_attachment (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES finance_project(id), filename TEXT NOT NULL, storage_name TEXT NOT NULL UNIQUE, size INTEGER NOT NULL, sha256 TEXT NOT NULL, uploaded_by INTEGER NOT NULL REFERENCES user(id), created_at TEXT NOT NULL)'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS finance_attachment_project ON finance_attachment(project_id)'));db.session.commit()
    def listing(project_id):
        return [dict(id=r.id,filename=r.filename,size=r.size,created_at=r.created_at,url=f'/api/finance/projects/{project_id}/files/{r.id}') for r in db.session.execute(text('SELECT id,filename,size,created_at FROM finance_attachment WHERE project_id=:id ORDER BY id'),{'id':project_id})]
    def prepare(files):
        files=[f for f in files if f.filename]
        if len(files)>5:raise ValidationError('แนบไฟล์ได้ครั้งละไม่เกิน 5 ไฟล์')
        prepared=[];total=0
        for file in files:
            filename=file.filename.replace('\\','/').rsplit('/',1)[-1]
            if not filename or len(filename)>255 or any(ord(c)<32 for c in filename):raise ValidationError('ชื่อไฟล์ไม่ถูกต้อง')
            extension=Path(filename).suffix.lower()
            if extension not in EXTENSIONS:raise ValidationError('รองรับ PDF, Word, Excel และรูปภาพ PNG/JPG เท่านั้น')
            raw=file.read(LIMIT+1);total+=len(raw)
            if not raw or total>LIMIT:raise ValidationError('ไฟล์ต้องไม่ว่างและขนาดรวมไม่เกิน 9 MB')
            valid=True
            if extension=='.pdf':valid=raw.startswith(b'%PDF-')
            elif extension=='.png':valid=raw.startswith(b'\x89PNG\r\n\x1a\n')
            elif extension in ['.jpg','.jpeg']:valid=raw.startswith(b'\xff\xd8\xff')
            elif extension in ['.doc','.xls']:valid=raw.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1')
            else:
                try:
                    with zipfile.ZipFile(io.BytesIO(raw)) as archive:valid=('[Content_Types].xml' in archive.namelist() and ('word/document.xml' if extension=='.docx' else 'xl/workbook.xml') in archive.namelist())
                except (zipfile.BadZipFile,ValueError):valid=False
            if not valid:raise ValidationError('ชนิดไฟล์ไม่ตรงกับนามสกุล: '+filename)
            prepared.append((filename,extension,raw))
        return prepared
    def cleanup(paths):
        for path in paths:
            if path.resolve().parent==folder.resolve() and path.exists():path.unlink()
    def store(project,prepared):
        paths=[]
        try:
            for filename,extension,raw in prepared:
                storage=uuid.uuid4().hex+extension;path=folder/storage;paths.append(path)
                with path.open('xb') as stream:stream.write(raw)
                db.session.execute(text('INSERT INTO finance_attachment(project_id,filename,storage_name,size,sha256,uploaded_by,created_at) VALUES(:id,:filename,:storage,:size,:hash,:actor,:at)'),dict(id=project.id,filename=filename,storage=storage,size=len(raw),hash=hashlib.sha256(raw).hexdigest(),actor=current_user().id,at=now().isoformat()))
            return paths
        except Exception:cleanup(paths);raise
    @app.post('/api/finance/projects/<int:id>/files')
    @authenticated()
    def upload_project_files(id):
        lock();project=get_project(id,True)
        if project.status=='completed' and current_user().role!='admin':abort(403)
        prepared=prepare(request.files.getlist('files'))
        if not prepared:raise ValidationError('กรุณาเลือกไฟล์โครงการ')
        before=project_data(project,True);paths=[]
        try:
            paths=store(project,prepared);audit(project,'upload_files',before);db.session.commit()
        except Exception:db.session.rollback();cleanup(paths);raise
        return jsonify(project_data(project,True))
    @app.get('/api/finance/projects/<int:id>/files/<int:file_id>')
    @authenticated()
    def download_project_file(id,file_id):
        get_project(id)
        row=db.session.execute(text('SELECT filename,storage_name FROM finance_attachment WHERE id=:file AND project_id=:project'),dict(file=file_id,project=id)).first()
        if not row:abort(404)
        path=folder/row.storage_name
        if path.resolve().parent!=folder.resolve() or not path.is_file():abort(404)
        response=send_file(path,as_attachment=True,download_name=row.filename,mimetype='application/octet-stream');response.headers['X-Content-Type-Options']='nosniff';response.headers['Cache-Control']='private, no-store';return response
    return listing,prepare,store,cleanup
