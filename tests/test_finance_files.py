import unittest,io,json
from pathlib import Path
import test_finance as fixtures
from app import db,FinanceProject
from sqlalchemy import text
class FinanceFilesTest(unittest.TestCase):
 setUp=fixtures.FinanceTest.setUp
 tearDown=fixtures.FinanceTest.tearDown
 login=fixtures.FinanceTest.login
 post=fixtures.FinanceTest.post
 data=fixtures.FinanceTest.data
 def upload(self,path,values):return self.c.post(path,data=values,content_type='multipart/form-data',headers={'X-CSRF-Token':'test'})
 def test_create_with_files_download_and_more(self):
  raw=b'%PDF-1.4\nproject test'
  response=self.upload('/api/finance/projects',{'project':json.dumps(self.data()),'files':(io.BytesIO(raw),'โครงการ.pdf')})
  self.assertEqual(response.status_code,201,response.json);project=response.json;self.assertEqual(len(project['files']),1)
  file=project['files'][0];self.assertEqual(file['filename'],'โครงการ.pdf')
  download=self.c.get(file['url']);self.assertEqual(download.data,raw);self.assertIn('attachment',download.headers['Content-Disposition']);download.close()
  more=self.upload('/api/finance/projects/'+str(project['id'])+'/files',{'files':(io.BytesIO(raw),'เพิ่มเติม.pdf')});self.assertEqual(more.status_code,200,more.json);self.assertEqual(len(more.json['files']),2)
  self.assertEqual(self.c.get('/finance/projects/'+str(project['id'])).status_code,200)
 def test_bad_files_fail_before_project_created(self):
  for raw,name in [(b'not pdf','bad.pdf'),(b'code','bad.exe'),(b'','empty.pdf')]:
   response=self.upload('/api/finance/projects',{'project':json.dumps(self.data()),'files':(io.BytesIO(raw),name)});self.assertEqual(response.status_code,400,response.json)
  self.assertEqual(FinanceProject.query.count(),0)
  self.assertEqual(db.session.execute(text('SELECT count(*) FROM finance_attachment')).scalar(),0)
  self.assertFalse(list((Path(self.app.config['UPLOAD_FOLDER']).parent/'project_uploads').glob('*')))
 def test_upload_permissions_and_csrf(self):
  response=self.post('/api/finance/projects',self.data());id=response.json['id'];path=f'/api/finance/projects/{id}/files'
  self.login('other');self.assertEqual(self.upload(path,{'files':(io.BytesIO(b'%PDF-1.4'),'test.pdf')}).status_code,403)
  self.login('owner');self.assertEqual(self.c.post(path,data={'files':(io.BytesIO(b'%PDF-1.4'),'test.pdf')}).status_code,400)
  with self.c.session_transaction() as s:s.clear()
  self.assertEqual(self.c.get(f'/api/finance/projects/{id}/files/1').status_code,401)
