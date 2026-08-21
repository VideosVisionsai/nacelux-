"""Safe website SEO audit; business signals are delegated to the dedicated engine."""
import json,os,re,time,urllib.parse,urllib.request
from html.parser import HTMLParser
from website_intelligence import validate_public_url,SafeWebsiteRedirect
from business_signals import BusinessSignalEngine
from datetime import datetime,timezone

def now():return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
class SeoHTMLParser(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.title=[];self.h1=[];self.in_title=False;self.in_h1=False;self.meta={};self.canonical=None
    def handle_starttag(self,tag,attrs):
        a={k.lower():(v or '') for k,v in attrs};tag=tag.lower()
        if tag=='title':self.in_title=True
        elif tag=='h1':self.in_h1=True;self.h1.append('')
        elif tag=='meta':
            key=(a.get('name') or a.get('property')).lower()
            if key:self.meta[key]=a.get('content','').strip()
        elif tag=='link' and 'canonical' in a.get('rel','').lower():self.canonical=a.get('href')
    def handle_endtag(self,tag):
        if tag.lower()=='title':self.in_title=False
        elif tag.lower()=='h1':self.in_h1=False
    def handle_data(self,data):
        if self.in_title:self.title.append(data)
        if self.in_h1 and self.h1:self.h1[-1]+=data
    def result(self):return {'title':re.sub(r'\s+',' ',' '.join(self.title)).strip(),'h1':[re.sub(r'\s+',' ',x).strip() for x in self.h1 if x.strip()],'meta_description':self.meta.get('description',''),'viewport':self.meta.get('viewport',''),'robots':self.meta.get('robots',''),'canonical':self.canonical}
class SEOAuditEngine:
    def __init__(self,db_connect):self.db_connect=db_connect;self.timeout=int(os.getenv('SEO_FETCH_TIMEOUT_SECONDS','15'));self.max_bytes=int(os.getenv('SEO_FETCH_MAX_BYTES','3000000'))
    def status(self):return {'status':'READY','checks':['HTTPS','Title','H1','Meta description','Mobile viewport','Performance'],'pagespeed':'READY' if os.getenv('PAGESPEED_API_KEY') else 'BASIC_SERVER_TIMING','policy':'Backend fetch with SSRF and redirect protection'}
    def audit(self,org,company_id):
        with self.db_connect() as db:row=db.execute('SELECT * FROM companies WHERE organization_id=? AND id=?',(org,company_id)).fetchone()
        if not row:return {'status':'NOT_FOUND','error_code':'COMPANY_NOT_FOUND'}
        c=dict(row);url=c.get('website');aid='seo_'+company_id
        if not url or c.get('website_status')!='FOUND':
            stamp=now()
            with self.db_connect() as db:db.execute("INSERT INTO seo_audits(id,organization_id,company_id,url,status,findings,checked_at,error_code,error_message) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(organization_id,company_id) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at,error_code=excluded.error_code,error_message=excluded.error_message",(aid,org,company_id,url,'NOT_APPLICABLE','[]',stamp,'NO_WEBSITE','No confirmed website to audit'))
            BusinessSignalEngine(self.db_connect).detect(org,company_id);return {'status':'NOT_APPLICABLE','error_code':'NO_WEBSITE','message':'No confirmed website to audit','seo_score':None,'seo_opportunity':None}
        try:
            fetched=self._fetch(url);a=self._analyze(fetched);stamp=now()
            values=(aid,org,company_id,url,'SUCCESS',a['seo_score'],a['seo_opportunity'],json.dumps(a['findings']),stamp,fetched['final_url'],fetched['status'],a['https_status'],a['title'],len(a['title']),len(a['h1']),a['h1'][0] if a['h1'] else None,a['meta_description'],len(a['meta_description']),a['mobile_status'],a['performance_score'],fetched['response_ms'],fetched['size'],a['canonical'],a['robots'],a['performance_method'],None,None)
            with self.db_connect() as db:
                db.execute("""INSERT INTO seo_audits(id,organization_id,company_id,url,status,seo_score,opportunity_score,findings,checked_at,final_url,http_status,https_status,title,title_length,h1_count,h1_text,meta_description,meta_length,mobile_status,performance_score,response_ms,page_size_bytes,canonical_url,robots_meta,audit_method,error_code,error_message) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(organization_id,company_id) DO UPDATE SET url=excluded.url,status=excluded.status,seo_score=excluded.seo_score,opportunity_score=excluded.opportunity_score,findings=excluded.findings,checked_at=excluded.checked_at,final_url=excluded.final_url,http_status=excluded.http_status,https_status=excluded.https_status,title=excluded.title,title_length=excluded.title_length,h1_count=excluded.h1_count,h1_text=excluded.h1_text,meta_description=excluded.meta_description,meta_length=excluded.meta_length,mobile_status=excluded.mobile_status,performance_score=excluded.performance_score,response_ms=excluded.response_ms,page_size_bytes=excluded.page_size_bytes,canonical_url=excluded.canonical_url,robots_meta=excluded.robots_meta,audit_method=excluded.audit_method,error_code=NULL,error_message=NULL""",values);db.execute('UPDATE companies SET seo_score=?,seo_opportunity=?,updated_at=? WHERE organization_id=? AND id=?',(a['seo_score'],a['seo_opportunity'],stamp,org,company_id))
            BusinessSignalEngine(self.db_connect).detect(org,company_id);return {'status':'SUCCESS','audit_id':aid,**a,'final_url':fetched['final_url'],'http_status':fetched['status'],'response_ms':fetched['response_ms'],'page_size_bytes':fetched['size']}
        except Exception as exc:
            with self.db_connect() as db:db.execute("INSERT INTO seo_audits(id,organization_id,company_id,url,status,findings,checked_at,error_code,error_message) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(organization_id,company_id) DO UPDATE SET status='FAILED',checked_at=excluded.checked_at,error_code=excluded.error_code,error_message=excluded.error_message",(aid,org,company_id,url,'FAILED','[]',now(),'SEO_FETCH_FAILED',str(exc)[:1000]))
            return {'status':'FAILED','audit_id':aid,'error_code':'SEO_FETCH_FAILED','message':str(exc)}
    def _fetch(self,url):
        validate_public_url(url);opener=urllib.request.build_opener(SafeWebsiteRedirect());req=urllib.request.Request(url,headers={'User-Agent':'NACELUX/1.0 SEO-audit','Accept':'text/html,application/xhtml+xml'});start=time.perf_counter()
        with opener.open(req,timeout=self.timeout) as response:
            ttfb=time.perf_counter();final=response.geturl();validate_public_url(final)
            if response.headers.get_content_type() not in ('text/html','application/xhtml+xml'):raise ValueError('Website response is not HTML')
            raw=response.read(self.max_bytes+1)
            if len(raw)>self.max_bytes:raise ValueError('Website page exceeds audit size limit')
            status=response.status;charset=response.headers.get_content_charset() or 'utf-8'
        parser=SeoHTMLParser();parser.feed(raw.decode(charset,'replace'));return {'final_url':final,'status':status,'html':parser.result(),'size':len(raw),'response_ms':round((time.perf_counter()-start)*1000),'ttfb_ms':round((ttfb-start)*1000)}
    def _performance(self,r):
        key=os.getenv('PAGESPEED_API_KEY','')
        if key:
            try:
                query=urllib.parse.urlencode({'url':r['final_url'],'strategy':'mobile','category':'performance','key':key})
                with urllib.request.urlopen('https://www.googleapis.com/pagespeedonline/v5/runPagespeed?'+query,timeout=45) as response:data=json.load(response)
                return round(data['lighthouseResult']['categories']['performance']['score']*100),'PAGESPEED_INSIGHTS'
            except Exception:pass
        score=100;ms=r['response_ms'];size=r['size'];score-=0 if ms<=800 else 15 if ms<=1500 else 30 if ms<=3000 else 50;score-=0 if size<=500000 else 10 if size<=1500000 else 25;return max(0,score),'BASIC_SERVER_TIMING'
    def _analyze(self,r):
        p=r['html'];score=0;findings=[];https=r['final_url'].startswith('https://');score+=15 if https else 0
        if not https:findings.append({'check':'HTTPS','severity':'HIGH','message':'Page is not served over HTTPS','points_lost':15})
        title=p['title'];pts=15 if 30<=len(title)<=60 else 10 if title else 0;score+=pts
        if pts<15:findings.append({'check':'TITLE','severity':'MEDIUM','message':'Title missing or outside the recommended 30–60 characters','points_lost':15-pts})
        h1=p['h1'];pts=15 if len(h1)==1 else 8 if h1 else 0;score+=pts
        if pts<15:findings.append({'check':'H1','severity':'MEDIUM','message':f'Expected one H1; found {len(h1)}','points_lost':15-pts})
        meta=p['meta_description'];pts=15 if 70<=len(meta)<=160 else 10 if meta else 0;score+=pts
        if pts<15:findings.append({'check':'META','severity':'MEDIUM','message':'Meta description missing or outside the recommended 70–160 characters','points_lost':15-pts})
        mobile='PASS' if 'width=device-width' in p['viewport'].lower().replace(' ','') else 'FAIL';score+=15 if mobile=='PASS' else 0
        if mobile!='PASS':findings.append({'check':'MOBILE','severity':'HIGH','message':'Responsive viewport declaration not detected','points_lost':15})
        perf,method=self._performance(r);pts=round(perf*.2);score+=pts
        if perf<70:findings.append({'check':'PERFORMANCE','severity':'HIGH' if perf<50 else 'MEDIUM','message':f'Performance score is {perf}/100 using {method}','points_lost':20-pts})
        indexable='noindex' not in p['robots'].lower();score+=5 if indexable else 0
        if not indexable:findings.append({'check':'INDEXABILITY','severity':'HIGH','message':'Meta robots contains noindex','points_lost':5})
        score=min(100,score);return {'seo_score':score,'seo_opportunity':100-score,'https_status':'PASS' if https else 'FAIL','title':title,'h1':h1,'meta_description':meta,'mobile_status':mobile,'performance_score':perf,'performance_method':method,'canonical':p['canonical'],'robots':p['robots'],'findings':findings}
