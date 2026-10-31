"""อ่านข้อมูลห้องประชุมด้วย GET เท่านั้น ไม่ใช้บัญชีหรือสิทธิ์แก้ไขต้นทาง"""
import calendar, json, re, time, threading, subprocess, os
from datetime import date,datetime,timedelta,timezone
from html.parser import HTMLParser
from urllib.parse import urlencode
from urllib.request import urlopen,Request
from concurrent.futures import ThreadPoolExecutor

BOOKING_URL='https://igad.kku.ac.th/bookingplace/web/index.php'
_cache={};_lock=threading.Lock()
def fetch_text(url):
    try:
        with urlopen(Request(url,headers={'User-Agent':'SUDMS read-only room calendar'}),timeout=12) as response:
            return response.read(5000000).decode('utf-8','replace')
    except PermissionError:
        # รองรับ Windows ที่จำกัด socket ของ Python แต่ให้ curl อ่าน HTTPS ได้
        flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
        result=subprocess.run(['curl.exe' if os.name=='nt' else 'curl','--fail','--location','--max-time','12','--silent','--show-error',url],capture_output=True,timeout=15,creationflags=flags,check=True)
        return result.stdout.decode('utf-8','replace')

class BookingParser(HTMLParser):
    def __init__(self):
        super().__init__();self.rows=[];self.row=None;self.cell=None;self.link=False;self.room=''
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='tr' and attrs.get('data-key'):
            self.row={'id':attrs['data-key'],'cells':[]};self.room=''
        elif self.row is not None and tag=='td':self.cell=[]
        elif self.row is not None and tag=='a' and not self.row['cells']:self.link=True
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)
        if self.link:self.room+=data
    def handle_endtag(self,tag):
        if tag=='a':self.link=False
        if tag=='td' and self.row is not None and self.cell is not None:
            self.row['cells'].append(' '.join(''.join(self.cell).split()));self.cell=None
        if tag=='tr' and self.row is not None:
            if len(self.row['cells'])>=3:
                self.row['room']=' '.join(self.room.split());self.rows.append(self.row)
            self.row=None

def read_booking_day(day):
    try:
        html=fetch_text(BOOKING_URL+'?'+urlencode({'r':'landingpage/index','department':6,'dateselect':day,'datep':day,'per-page':1000}))
        if 'grid-view' not in html or r'yii\base\ErrorException' in html:raise ValueError('Invalid source response')
        parser=BookingParser();parser.feed(html);events=[]
        for row in parser.rows:
            room=row['room'] or row['cells'][0].replace('ใช้งาน','').strip()
            events.append({'id':'kku-'+day+'-'+row['id'],'date':day,'room':room,'title':row['cells'][2],'time':row['cells'][1],'source':'KKU','source_url':BOOKING_URL+'?'+urlencode({'r':'landingpage/index','department':6,'dateselect':day})})
        total=re.search(r'จาก\s*<b>([0-9,]+)</b>\s*ผลลัพธ์',html)
        complete=not total or int(total.group(1).replace(',',''))<=len(parser.rows)
        return {'date':day,'ok':complete,'events':events}
    except Exception:return {'date':day,'ok':False,'events':[]}

def load_month(month,refresh=False):
    year,number=map(int,month.split('-'));start=date(year,number,1);end=date(year+1,1,1) if number==12 else date(year,number+1,1)
    with _lock:
        cached=_cache.get(month)
        if cached and not refresh and time.time()-cached[0]<300:return cached[1]
    days=[(start+timedelta(days=i)).isoformat() for i in range((end-start).days)]
    with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(read_booking_day,days))
    events=[event for result in results for event in result['events']]
    result={'month':month,'events':events,'rooms':sorted({event['room'] for event in events}),'failed_days':[d['date'] for d in results if not d['ok']],'checked_at':datetime.now(timezone.utc).isoformat(),'read_only':True}
    with _lock:
        if len(_cache)>=6:_cache.pop(next(iter(_cache)))
        _cache[month]=(time.time(),result)
    return result
