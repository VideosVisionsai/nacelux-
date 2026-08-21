"""Controlled LBR/RESA public journal connector.

No private or undocumented LBR API is called. Static HTML is attempted first;
Playwright is used only when the public page requires JavaScript. Captchas are
reported and never bypassed.
"""
from __future__ import annotations
import hashlib, json, os, re, time, urllib.error, urllib.parse, urllib.request, urllib.robotparser, uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
import config

LBR_ORIGIN='https://www.lbr.lu'
URL_RE=re.compile(r'^https://www\.lbr\.lu/mjrcs-web-front/publication-journal/(RESA-(\d{4})_([0-9]+)_([0-9]+)_([0-9]+))/?$')
RCS_RE=re.compile(r'(?<![A-Z0-9])([A-Z])\s*([0-9]{4,8})(?![0-9])',re.I)
LABELS={
 'company_name':[r'(?:dénomination|denomination|firmenname|company name)\s*[:\-]\s*([^|;\n]{2,160})'],
 'entry_type':[r'(?:type|nature|publication type)\s*[:\-]\s*([^|;\n]{2,100})'],
 'publication_number':[r'(?:publication|publication no\.?|n[o°]\s*de publication)\s*[:\-]\s*([A-Z0-9_./-]+)']}

def utcnow():return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def sha(value):return hashlib.sha256(value.encode('utf-8')).hexdigest()
def normalize_space(value):return re.sub(r'\s+',' ',value or '').strip()
def canonical_url(url):
    p=urllib.parse.urlsplit(url);query=urllib.parse.parse_qsl(p.query,keep_blank_values=True)
    # Preserve functional parameters but remove common analytics only.
    query=[x for x in query if not x[0].lower().startswith(('utm_','pk_'))]
    return urllib.parse.urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path,urllib.parse.urlencode(query),''))

def classify_document_url(url):
    parsed=urllib.parse.urlsplit(url);path=parsed.path.lower();query=dict(urllib.parse.parse_qsl(parsed.query))
    if path.endswith('.pdf') or str(query.get('format','')).lower()=='pdf' or str(query.get('type','')).lower()=='pdf':return 'PDF'
    return 'PUBLIC_DOCUMENT_LINK'

@dataclass
class DocumentLink:
    url:str;link_text:str='';row_index:int|None=None;document_type:str='PUBLIC_DOCUMENT_LINK'
@dataclass
class ParsedEntry:
    row_index:int;row_text:str;company_name:str|None=None;rcs_number:str|None=None
    entry_type:str|None=None;publication_number:str|None=None;documents:list[DocumentLink]=field(default_factory=list)
@dataclass
class JournalPage:
    journal_key:str;year:str;sequence_number:str;source_url:str;title:str='';html:str=''
    entries:list[ParsedEntry]=field(default_factory=list);documents:list[DocumentLink]=field(default_factory=list)
    fetch_method:str='HTTP';captcha_status:str='NOT_PRESENT';robots_status:str='ALLOWED'

class RowHTMLParser(HTMLParser):
    def __init__(self,base_url):
        super().__init__(convert_charrefs=True);self.base=base_url;self.depth=0;self.current=None;self.rows=[];self.all_docs=[];self.title=[];self.in_title=False
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs);tag=tag.lower()
        if tag=='title':self.in_title=True
        if tag=='tr':self.depth=1;self.current={'parts':[],'documents':[]}
        elif self.current:self.depth+=1
        if tag=='a' and attrs.get('href'):
            href=urllib.parse.urljoin(self.base,attrs['href']);link={'url':href,'text':''}
            if self._is_document(href):
                link['document_type']=classify_document_url(href);self.all_docs.append(link)
                if self.current:self.current['documents'].append(link)
    def handle_data(self,data):
        if self.in_title:self.title.append(data)
        if self.current:
            self.current['parts'].append(data)
            if self.current['documents']:self.current['documents'][-1]['text']+=data
    def handle_endtag(self,tag):
        tag=tag.lower()
        if tag=='title':self.in_title=False
        if self.current:
            if tag in ('td','th'):self.current['parts'].append(' | ')
            self.depth-=1
            if tag=='tr' or self.depth<=0:
                text=normalize_space(' '.join(self.current['parts']))
                if text:self.rows.append({'text':text,'documents':self.current['documents']})
                self.current=None;self.depth=0
    @staticmethod
    def _is_document(url):return urllib.parse.urlsplit(url).path.lower().endswith('.pdf') or 'document' in urllib.parse.urlsplit(url).path.lower()

def parse_entry(index,text,documents=None):
    text=normalize_space(text);rcs=None;m=RCS_RE.search(text)
    if m:rcs=(m.group(1)+m.group(2)).upper()
    values={}
    for key,patterns in LABELS.items():
        for pattern in patterns:
            found=re.search(pattern,text,re.I)
            if found:values[key]=normalize_space(found.group(1));break
    docs=[DocumentLink(canonical_url(d['url']),normalize_space(d.get('text')),index,d.get('document_type') or classify_document_url(d['url'])) for d in (documents or [])]
    return ParsedEntry(index,text,values.get('company_name'),rcs,values.get('entry_type'),values.get('publication_number'),docs)

def parse_static_html(url,html):
    match=validate_url(url);parser=RowHTMLParser(url);parser.feed(html)
    entries=[parse_entry(i+1,row['text'],row['documents']) for i,row in enumerate(parser.rows)]
    assigned={d.url for e in entries for d in e.documents}
    docs=[DocumentLink(canonical_url(d['url']),normalize_space(d.get('text')),None,d.get('document_type') or classify_document_url(d['url'])) for d in parser.all_docs if canonical_url(d['url']) not in assigned]
    lower=html.lower();captcha='REQUIRED' if 'friendlycaptcha' in lower or 'captcha resolution' in lower else 'NOT_PRESENT'
    return JournalPage(match.group(1),match.group(2),'_'.join(match.groups()[2:]),url,normalize_space(' '.join(parser.title)),html,entries,docs,'HTTP',captcha,'ALLOWED')

def validate_url(url):
    match=URL_RE.match(url)
    if not match:raise ValueError('Only canonical public LBR RESA journal URLs are accepted')
    return match

def check_robots(url,user_agent):
    validate_url(url);rp=urllib.robotparser.RobotFileParser();rp.set_url(LBR_ORIGIN+'/robots.txt')
    try:rp.read()
    except Exception:return 'UNAVAILABLE'
    return 'ALLOWED' if rp.can_fetch(user_agent,url) else 'DISALLOWED'

class LBRResaConnector:
    _last_fetch_monotonic=0.0
    def __init__(self,db_connect,enabled=None):
        self.db_connect=db_connect;self.enabled=(os.getenv('LBR_RESA_ENABLED','false').lower() in ('1','true','yes')) if enabled is None else enabled
        self.user_agent=os.getenv('LBR_USER_AGENT','NACELUX/1.0 (controlled RESA reader)');self.timeout_ms=int(os.getenv('LBR_RESA_TIMEOUT_MS','45000'))
        self.min_interval=float(os.getenv('LBR_RESA_MIN_INTERVAL_SECONDS','8'));self.artifacts=Path(os.getenv('LBR_RESA_ARTIFACT_DIR',config.ROOT/'data'/'resa-artifacts'))
        self.artifact_provider=os.getenv('DOCUMENT_STORAGE_PROVIDER','supabase' if os.getenv('NACELUX_ENV','development').lower() in ('production','prod') else 'local').lower()
        self.storage_base=os.getenv('SUPABASE_URL','').rstrip('/')
        self.storage_key=os.getenv('SUPABASE_SERVICE_ROLE_KEY','')
        self.storage_bucket=os.getenv('SUPABASE_STORAGE_BUCKET','resa-documents')
    def status(self):
        try:import playwright.sync_api;browser='AVAILABLE'
        except ImportError:browser='NOT_INSTALLED'
        artifact_status='SUPABASE_STORAGE' if self.artifact_provider=='supabase' else 'LOCAL_DEVELOPMENT_ONLY'
        return {'key':'lbr_resa','name':'LBR / RESA','status':'READY' if self.enabled else 'DISABLED','base_url':LBR_ORIGIN,'browser':browser,'artifact_storage':artifact_status,'policy':'Public pages only; no undocumented API; captcha is never bypassed.'}
    def analyze(self,organization_id,url,allow_browser=True,headless=None):
        validate_url(url)
        if not self.enabled:return {'status':'DISABLED','error_code':'CONNECTOR_DISABLED','message':'Set LBR_RESA_ENABLED=true after compliance approval.'}
        run_id='resa_run_'+uuid.uuid4().hex;started=utcnow();robots=check_robots(url,self.user_agent)
        self._insert_run(run_id,organization_id,url,started,robots)
        if robots=='DISALLOWED':return self._fail(run_id,'ROBOTS_DISALLOWED','Public URL is disallowed by robots.txt',robots)
        try:
            wait=max(0,self.min_interval-(time.monotonic()-LBRResaConnector._last_fetch_monotonic))
            if wait:time.sleep(wait)
            page=self._http_fetch(url,robots);LBRResaConnector._last_fetch_monotonic=time.monotonic()
            if allow_browser and (not page.entries or page.captcha_status=='REQUIRED'):
                page=self._browser_fetch(url,robots,headless)
            if page.captcha_status=='REQUIRED' and not page.entries:
                self._save_artifact(run_id,page,organization_id)
                return self._fail(run_id,'CAPTCHA_REQUIRED','LBR requested interactive captcha resolution; no bypass was attempted.',robots,page.fetch_method,'REQUIRED',page)
            if not page.entries:
                self._save_artifact(run_id,page,organization_id)
                return self._fail(run_id,'STRUCTURE_NOT_DETECTED','The public page rendered no recognizable publication rows; nothing was stored as a successful journal analysis.',robots,page.fetch_method,page.captcha_status,page)
            result=self._store(organization_id,run_id,page);self._save_artifact(run_id,page,organization_id);return result
        except Exception as exc:
            code='PLAYWRIGHT_UNAVAILABLE' if 'playwright' in str(exc).lower() else 'FETCH_ERROR'
            return self._fail(run_id,code,str(exc),robots)
    def _http_fetch(self,url,robots):
        req=urllib.request.Request(url,headers={'User-Agent':self.user_agent,'Accept':'text/html,application/xhtml+xml'})
        with urllib.request.urlopen(req,timeout=self.timeout_ms/1000) as response:
            final=response.geturl();validate_url(final);html=response.read(8_000_000).decode(response.headers.get_content_charset() or 'utf-8','replace')
        page=parse_static_html(url,html);page.robots_status=robots;return page
    def _browser_fetch(self,url,robots,headless=None):
        try:from playwright.sync_api import sync_playwright
        except ImportError as exc:raise RuntimeError('Playwright is required for this JavaScript-rendered public page') from exc
        headless=(os.getenv('LBR_RESA_HEADLESS','true').lower() in ('1','true','yes')) if headless is None else headless
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=headless);context=browser.new_context(user_agent=self.user_agent,locale='fr-LU');page=context.new_page()
            page.goto(url,wait_until='domcontentloaded',timeout=self.timeout_ms)
            try:page.wait_for_load_state('networkidle',timeout=min(self.timeout_ms,15000))
            except Exception:pass
            # Friendly Captcha may resolve itself. We wait but never click, solve, or call its service directly.
            captcha=page.locator('text=/Captcha Resolution|Friendly Captcha/i')
            if captcha.count():
                try:captcha.first.wait_for(state='hidden',timeout=min(self.timeout_ms,20000))
                except Exception:pass
            captcha_present=page.locator('.frc-captcha, .frc-i-agent, iframe[src*="frcapi"], iframe[src*="friendlycaptcha"]').count()>0
            extracted=page.evaluate("""() => {
              const clean=s=>(s||'').replace(/\\s+/g,' ').trim();
              const isDoc=a=>{const h=(a.href||'').toLowerCase();return h.endsWith('.pdf')||/\\/document(?:\\/|$)/.test(h)};
              const selectors=['tbody tr','[role="row"]','mat-row','.table-row','.publication-item'];
              let rows=[];for(const sel of selectors){rows=[...document.querySelectorAll(sel)].filter(x=>clean(x.innerText));if(rows.length)break}
              const parsed=rows.map((row,i)=>({index:i+1,text:clean(row.innerText),documents:[...row.querySelectorAll('a[href]')].filter(isDoc).map(a=>({url:a.href,text:clean(a.innerText||a.title)}))}));
              const all=[...document.querySelectorAll('a[href]')].filter(isDoc).map(a=>({url:a.href,text:clean(a.innerText||a.title)}));
              return {title:document.title,html:document.documentElement.outerHTML,rows:parsed,documents:all,captcha:/Captcha Resolution|Friendly Captcha/i.test(document.body.innerText)};
            }""")
            browser.close()
        match=validate_url(url);entries=[parse_entry(r['index'],r['text'],r['documents']) for r in extracted['rows']]
        assigned={d.url for e in entries for d in e.documents};docs=[DocumentLink(canonical_url(d['url']),normalize_space(d.get('text')),None,d.get('document_type') or classify_document_url(d['url'])) for d in extracted['documents'] if canonical_url(d['url']) not in assigned]
        captcha_status='REQUIRED' if captcha_present and not entries else ('RESOLVED' if captcha_present else 'NOT_PRESENT')
        return JournalPage(match.group(1),match.group(2),'_'.join(match.groups()[2:]),url,extracted['title'],extracted['html'],entries,docs,'PLAYWRIGHT',captcha_status,robots)
    def _insert_run(self,rid,org,url,started,robots):
        with self.db_connect() as db:db.execute("INSERT INTO resa_sync_runs(id,organization_id,source_url,status,started_at,robots_status,metadata) VALUES(?,?,?,?,?,?,?)",(rid,org,url,'RUNNING',started,robots,'{}'))
    def _fail(self,rid,code,message,robots,method=None,captcha=None,page=None):
        finished=utcnow();snapshot=sha(page.html) if page else None
        with self.db_connect() as db:db.execute("UPDATE resa_sync_runs SET status=?,fetch_method=?,finished_at=?,robots_status=?,captcha_status=?,error_code=?,error_message=?,snapshot_hash=? WHERE id=?",('BLOCKED' if code in ('CAPTCHA_REQUIRED','ROBOTS_DISALLOWED') else 'FAILED',method,finished,robots,captcha,code,message,snapshot,rid))
        return {'run_id':rid,'status':'BLOCKED' if code in ('CAPTCHA_REQUIRED','ROBOTS_DISALLOWED') else 'FAILED','error_code':code,'message':message,'robots_status':robots,'captcha_status':captcha}
    def _store(self,org,rid,page):
        now=utcnow();journal_id='resa_journal_'+sha(org+'|'+page.journal_key)[:24];snapshot=sha(page.html);stats={'NEW':0,'UPDATED':0,'UNCHANGED':0,'DUPLICATE':0};seen=set();seen_content=set();doc_count=0
        with self.db_connect() as db:
            db.execute("INSERT INTO resa_journals(id,organization_id,journal_key,sequence_number,source_url,first_seen_at,last_seen_at,content_hash) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(organization_id,journal_key) DO UPDATE SET last_seen_at=excluded.last_seen_at,content_hash=excluded.content_hash,source_url=excluded.source_url",(journal_id,org,page.journal_key,page.sequence_number,page.source_url,now,now,snapshot))
            for entry in page.entries:
                content_hash=sha(entry.row_text+'|'+'|'.join(sorted(d.url for d in entry.documents)))
                identity=('publication:'+entry.publication_number) if entry.publication_number else f'row:{entry.row_index}:{entry.rcs_number or ""}'
                natural=sha(identity)
                if natural in seen or content_hash in seen_content:stats['DUPLICATE']+=1;continue
                seen.add(natural);seen_content.add(content_hash);existing=db.execute("SELECT id,content_hash FROM resa_entries WHERE organization_id=? AND journal_id=? AND natural_key=?",(org,journal_id,natural)).fetchone();status='NEW' if not existing else ('UNCHANGED' if existing['content_hash']==content_hash else 'UPDATED');stats[status]+=1;entry_id=existing['id'] if existing else 'resa_entry_'+sha(org+'|'+journal_id+'|'+natural)[:24]
                if existing:db.execute("UPDATE resa_entries SET row_index=?,publication_number=?,entry_type=?,company_name=?,rcs_number=?,row_text=?,change_status=?,content_hash=?,last_seen_at=? WHERE id=?",(entry.row_index,entry.publication_number,entry.entry_type,entry.company_name,entry.rcs_number,entry.row_text,status,content_hash,now,entry_id))
                else:db.execute("INSERT INTO resa_entries VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(entry_id,org,journal_id,natural,entry.row_index,entry.publication_number,entry.entry_type,entry.company_name,entry.rcs_number,entry.row_text,page.source_url,status,content_hash,now,now))
                for document in entry.documents:doc_count+=1;self._store_doc(db,org,journal_id,entry_id,page.source_url,document,now)
            for document in page.documents:doc_count+=1;self._store_doc(db,org,journal_id,None,page.source_url,document,now)
            db.execute("UPDATE resa_sync_runs SET journal_id=?,status='SUCCESS',fetch_method=?,finished_at=?,rows_detected=?,documents_detected=?,new_entries=?,updated_entries=?,unchanged_entries=?,duplicate_entries=?,captcha_status=?,snapshot_hash=?,metadata=? WHERE id=?",(journal_id,page.fetch_method,now,len(page.entries),doc_count,stats['NEW'],stats['UPDATED'],stats['UNCHANGED'],stats['DUPLICATE'],page.captcha_status,snapshot,json.dumps({'title':page.title,'journal_key':page.journal_key}),rid))
        return {'run_id':rid,'journal_id':journal_id,'status':'SUCCESS','fetch_method':page.fetch_method,'rows_detected':len(page.entries),'documents_detected':doc_count,'changes':stats,'captcha_status':page.captcha_status,'robots_status':page.robots_status}
    def _store_doc(self,db,org,journal,entry,source,document,now):
        url=canonical_url(document.url);existing=db.execute("SELECT id FROM resa_documents WHERE organization_id=? AND canonical_url=?",(org,url)).fetchone()
        if existing:db.execute("UPDATE resa_documents SET last_seen_at=?,entry_id=COALESCE(entry_id,?) WHERE id=?",(now,entry,existing['id']));return 0
        did='resa_doc_'+sha(org+'|'+url)[:24];db.execute("INSERT INTO resa_documents(id,organization_id,journal_id,entry_id,document_url,canonical_url,document_type,link_text,source_url,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(did,org,journal,entry,url,url,document.document_type,document.link_text,source,now,now));return 1
    def _save_artifact(self,rid,page,organization_id=None):
        summary={'url':page.source_url,'method':page.fetch_method,'captcha':page.captcha_status,'rows':len(page.entries),'documents':len(page.documents)+sum(len(e.documents) for e in page.entries),'snapshot_hash':sha(page.html)}
        files=((f'{rid}.html',page.html.encode('utf-8'),'text/html; charset=utf-8'),(f'{rid}.json',json.dumps(summary,indent=2).encode('utf-8'),'application/json'))
        if os.getenv('NACELUX_ENV','development').lower() in ('production','prod'):
            if self.artifact_provider!='supabase' or not self.storage_base or not self.storage_key or not self.storage_bucket:
                raise RuntimeError('Supabase Storage is required for RESA artifacts in production')
            prefix=f"{organization_id or 'system'}/resa-artifacts"
            for filename,body,mime in files:
                object_key=f'{prefix}/{filename}'
                url=f"{self.storage_base}/storage/v1/object/{urllib.parse.quote(self.storage_bucket,safe='')}/{urllib.parse.quote(object_key,safe='/')}"
                request=urllib.request.Request(url,data=body,method='POST',headers={'Authorization':'Bearer '+self.storage_key,'apikey':self.storage_key,'Content-Type':mime,'x-upsert':'true'})
                try:
                    with urllib.request.urlopen(request,timeout=30) as response:
                        if response.status not in (200,201): raise RuntimeError(f'Artifact storage returned HTTP {response.status}')
                except urllib.error.HTTPError as exc:
                    raise RuntimeError(f'Artifact storage failed with HTTP {exc.code}') from exc
            return
        self.artifacts.mkdir(parents=True,exist_ok=True)
        (self.artifacts/files[0][0]).write_bytes(files[0][1])
        (self.artifacts/files[1][0]).write_bytes(files[1][1])
