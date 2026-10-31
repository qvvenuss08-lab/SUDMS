"""เริ่ม SUDMS บนพอร์ต 5056 พร้อมบันทึกข้อผิดพลาดเริ่มระบบ"""
from pathlib import Path
import threading
import traceback
import webbrowser
import socket
import time

ROOT = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:5056/?view=forms'

def open_browser():
    # เปิดแยกจากเซิร์ฟเวอร์: หาก browser ผิดพลาดหรือค้าง เว็บยังรับคำขอได้
    try:
        for attempt in range(50):
            try:
                with socket.create_connection(('127.0.0.1',5056),timeout=0.3): break
            except OSError: time.sleep(0.2)
        else:
            print('Server is not ready yet. Check the startup error in this window.',flush=True)
            return
        webbrowser.open(URL)
    except Exception:
        print('Browser could not open automatically. Open this URL manually: ' + URL, flush=True)

def main():
    print('SUDMS source: ' + str(ROOT), flush=True)
    try:
        from werkzeug.serving import run_simple, is_running_from_reloader
        import app as app_module
        from form_catalog import FORM_CATALOG
        app=app_module.app
        if Path(app_module.__file__).resolve() != ROOT/'app.py':
            raise RuntimeError('Wrong SUDMS source directory')
        adapter=app.url_map.bind('127.0.0.1:5056')
        edit_endpoint, _ = adapter.match('/documents/1/edit',method='GET')
        if edit_endpoint!='edit_sent_page': raise RuntimeError('Full document editor endpoint missing')
        for item in FORM_CATALOG:
            for fmt in ['pdf','docx']:
                endpoint, _ = adapter.match('/api/forms/files/'+item['id']+'/'+fmt,method='GET')
                if endpoint!='original_form': raise RuntimeError('Download endpoint mismatch')
                if not (ROOT/'form_files'/item['files'][fmt]['filename']).is_file():
                    raise RuntimeError('Missing form file: '+item['files'][fmt]['filename'])
        print(f'Verified: {len(FORM_CATALOG)} form types, {sum(len(item["files"]) for item in FORM_CATALOG)} files, all download endpoints ready.', flush=True)
        print('SUDMS URL: ' + URL, flush=True)
        print('Keep this window open. Restart the server after source changes.', flush=True)
        if not is_running_from_reloader():
            threading.Thread(target=open_browser, daemon=True).start()
        extra_files=[str(path) for path in (ROOT/'templates').rglob('*.html')]
        try:
            run_simple('127.0.0.1', 5056, app, threaded=True,
                       use_reloader=False, use_debugger=False, reloader_type='stat',
                       extra_files=extra_files)
        except KeyboardInterrupt:
            pass
        return 0
    except (Exception, SystemExit) as error:
        if isinstance(error, SystemExit) and error.code in (None, 0):
            return 0
        details = traceback.format_exc()
        folder = ROOT / 'instance'
        folder.mkdir(exist_ok=True)
        logfile = folder / 'latest-startup.log'
        logfile.write_text(details, encoding='utf-8')
        print(details, flush=True)
        print('Startup failed. Log: ' + str(logfile), flush=True)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
