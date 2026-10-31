"""Open the current SUDMS server, or start it when unavailable."""
import os, threading, time, webbrowser
import requests
URL = 'http://127.0.0.1:5057'
def ready():
    try:
        session = requests.Session()
        session.trust_env = False
        return session.get(URL+'/healthz', timeout=2).json().get('status') == 'ok'
    except Exception:
        return False
def open_when_ready():
    for _ in range(100):
        if ready():
            webbrowser.open(URL+'/?view=forms')
            return
        time.sleep(.2)
if __name__ == '__main__':
    os.environ['SUDMS_HTTPS'] = '0'
    if ready():
        webbrowser.open(URL+'/?view=forms')
    else:
        threading.Thread(target=open_when_ready, daemon=True).start()
        from serve import main
        main()
