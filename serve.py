"""Production WSGI launcher; persistent SQLite and files live in instance_path."""
import argparse,os,socket
from waitress import serve

def main():
    parser=argparse.ArgumentParser(description='SUDMS web server')
    parser.add_argument('--host',default=os.environ.get('SUDMS_HOST','0.0.0.0'))
    parser.add_argument('--port',type=int,default=int(os.environ.get('PORT',os.environ.get('SUDMS_PORT','5057'))))
    args=parser.parse_args()
    from app import app,db
    from sqlalchemy import text
    @app.get('/healthz')
    def health():
        try:
            db.session.execute(text('SELECT 1'));return {'status':'ok'},200
        except Exception:
            db.session.rollback();return {'status':'unavailable'},503
    addresses=sorted({item[4][0] for item in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET) if not item[4][0].startswith('127.')})
    print(f'SUDMS local: http://127.0.0.1:{args.port}/login',flush=True)
    if args.host=='0.0.0.0':
        for address in addresses:print(f'SUDMS LAN: http://{address}:{args.port}/login',flush=True)
    serve(app,host=args.host,port=args.port,threads=8,max_request_body_size=10*1024*1024,expose_tracebacks=False,url_scheme='https' if os.environ.get('SUDMS_HTTPS')=='1' else 'http')
if __name__=='__main__':main()
