"""Website discovery and public digital-footprint checks via documented APIs.
No search-result pages or protected social profiles are scraped.
"""
from __future__ import annotations
import hashlib, html, ipaddress, json, os, re, socket, time, unicodedata, urllib.error, urllib.parse, urllib.request, uuid
from datetime import datetime, timezone
from html.parser import HTMLParser

SOCIAL_HOSTS={'linkedin.com','www.linkedin.com','facebook.com','www.facebook.com','instagram.com','www.instagram.com','youtube.com','www.youtube.com'}
EXCLUDED_WEBSITE_HOSTS=SOCIAL_HOSTS|{'google.com','www.google.com','editus.lu','www.editus.lu','yellow.lu','www.yellow.lu'}
def now():return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def norm(value):return re.sub(r'[^a-z0-9]+',' ',unicodedata.normalize('NFKD',value or '').encode('ascii','ignore').decode().lower()).strip()
def company_tokens(name):
    stop={'sarl','sa','s','asbl','se','sc','sicav','luxembourg','holding','group'}
    return {x for x in norm(name).split() if len(x)>2 and x not in stop}
def canonical(url):
    p=urllib.parse.urlsplit(url if '://' in url else 'https://'+url);path=p.path or '/';return urllib.parse.urlunsplit((p.scheme.lower(),(p.hostname or '').lower(),path.rstrip('/') or '/','',''))
WEBSITE_STATUSES=('NOT_CHECKED','UNKNOWN','CHECKING','CONNECTED','NOT_FOUND','INVALID','BLOCKED','ERROR')
WEBSITE_RULE_VERSION='2.1.0'
NACELUX_UA=os.getenv('WEBSITE_USER_AGENT','NACELUX/1.0 (+https://nacelux.eu; website-verification)')
# Cloud metadata / link-local endpoints that must never be fetched.
METADATA_HOSTS=('169.254.169.254','metadata.google.internal','metadata','169.254.170.2')

def _is_public_routable(ip):
    """A destination is allowed only if it is a globally routable, non-special
    address. This single positive check covers private, loopback, link-local,
    reserved, multicast, unspecified, and all other non-global ranges."""
    return ip.is_global and not (ip.is_private or ip.is_loopback or ip.is_link_local
                                 or ip.is_reserved or ip.is_multicast or ip.is_unspecified)

def validate_public_url(url):
    """Strict SSRF guard. Parses the URL, allows only http/https on standard
    ports with no credentials, refuses metadata hosts, resolves DNS and rejects
    ANY resolved address that is not globally routable. All IPs are checked so a
    hostname that resolves to one public + one private address is still refused."""
    try:
        p = urllib.parse.urlsplit(url)
    except Exception:
        raise ValueError('Malformed URL')
    if p.scheme not in ('http', 'https'):
        raise ValueError('Only http/https schemes are allowed')
    if not p.hostname:
        raise ValueError('URL has no hostname')
    if p.username or p.password:
        raise ValueError('Credentials in URL are not allowed')
    if p.port not in (None, 80, 443):
        raise ValueError('Only ports 80 and 443 are allowed')
    host = p.hostname.lower()
    if host in METADATA_HOSTS:
        raise ValueError('Metadata endpoint is blocked')
    try:
        literal = ipaddress.ip_address(host)
        if not _is_public_routable(literal):
            raise ValueError('URL host is not a public address')
    except ValueError:
        if host == 'localhost':
            raise ValueError('localhost is blocked')
    port = p.port or (443 if p.scheme == 'https' else 80)
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise ValueError('DNS resolution failed')
    if not addresses:
        raise ValueError('DNS resolution returned no address')
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not _is_public_routable(ip):
            raise ValueError('URL resolves to a non-public address')
    return url

class SafeWebsiteRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):validate_public_url(urllib.parse.urljoin(req.full_url,newurl));return super().redirect_request(req,fp,code,msg,headers,newurl)
class PageText(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[];self.title=[];self.in_title=False
    def handle_starttag(self,tag,attrs):
        if tag.lower()=='title':self.in_title=True
    def handle_endtag(self,tag):
        if tag.lower()=='title':self.in_title=False
    def handle_data(self,data):
        self.parts.append(data)
        if self.in_title:self.title.append(data)

class WebsiteHTMLAnalyzer(HTMLParser):
    """Passive extraction of on-page technical elements for the digital footprint.
    No scripts/styles execute; this only parses received HTML."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title=[]; self._in_title=False
        self._h1_parts=None; self.h1s=[]
        self.meta_description=None; self.viewport=None; self.canonical=None; self.robots=None
    def handle_starttag(self, tag, attrs):
        t=tag.lower(); d=dict(attrs)
        if t=='title': self._in_title=True
        elif t=='h1': self._h1_parts=[]
        elif t=='meta':
            name=(d.get('name') or d.get('property') or '').lower(); content=d.get('content')
            if content:
                if name=='description': self.meta_description=content
                elif name=='viewport': self.viewport=content
                elif name=='robots': self.robots=content
        elif t=='link' and (d.get('rel') or '').lower()=='canonical' and d.get('href'):
            self.canonical=d['href']
    def handle_endtag(self, tag):
        t=tag.lower()
        if t=='title': self._in_title=False
        elif t=='h1' and self._h1_parts is not None:
            txt=' '.join(self._h1_parts).strip()
            if txt: self.h1s.append(txt)
            self._h1_parts=None
    def handle_data(self, data):
        if self._in_title: self.title.append(data)
        elif self._h1_parts is not None: self._h1_parts.append(data)

def parse_html(html_text):
    a=WebsiteHTMLAnalyzer()
    try:
        a.feed(html_text or ''); a.close()
    except Exception:
        pass
    title=' '.join(a.title).strip() or None
    h1=a.h1s[0] if a.h1s else None
    return {'title':title,'title_length':len(title or ''),'h1':h1,'h1_count':len(a.h1s),
            'meta_description':a.meta_description,'meta_length':len(a.meta_description or ''),
            'viewport':a.viewport,'has_viewport':bool(a.viewport),
            'canonical':a.canonical,'robots_meta':a.robots}

class SearchProvider:
    name='none'
    def configured(self):return False
    def search(self,query,count=10):raise RuntimeError('Search provider is not configured')
class BraveSearch(SearchProvider):
    name='brave'
    def __init__(self):self.key=os.getenv('BRAVE_SEARCH_API_KEY','')
    def configured(self):return bool(self.key)
    def search(self,query,count=10):
        url='https://api.search.brave.com/res/v1/web/search?'+urllib.parse.urlencode({'q':query,'count':min(count,20),'country':'lu','search_lang':'fr'})
        req=urllib.request.Request(url,headers={'Accept':'application/json','X-Subscription-Token':self.key})
        with urllib.request.urlopen(req,timeout=15) as response:data=json.load(response)
        return [{'url':x.get('url'),'title':x.get('title',''),'snippet':x.get('description','')} for x in data.get('web',{}).get('results',[]) if x.get('url')]
class GoogleCustomSearch(SearchProvider):
    name='google_custom_search'
    def __init__(self):self.key=os.getenv('GOOGLE_CUSTOM_SEARCH_API_KEY','');self.cx=os.getenv('GOOGLE_CUSTOM_SEARCH_CX','')
    def configured(self):return bool(self.key and self.cx)
    def search(self,query,count=10):
        url='https://www.googleapis.com/customsearch/v1?'+urllib.parse.urlencode({'key':self.key,'cx':self.cx,'q':query,'num':min(count,10)})
        with urllib.request.urlopen(url,timeout=15) as response:data=json.load(response)
        return [{'url':x.get('link'),'title':x.get('title',''),'snippet':x.get('snippet','')} for x in data.get('items',[]) if x.get('link')]
def search_provider():
    name=os.getenv('SEARCH_PROVIDER','none').lower();provider=BraveSearch() if name=='brave' else GoogleCustomSearch() if name in ('google','google_custom_search') else SearchProvider()
    return provider

class WebsiteDiscoveryEngine:
    def __init__(self,db_connect):self.db_connect=db_connect;self.threshold=float(os.getenv('WEBSITE_DISCOVERY_MIN_CONFIDENCE','.72'));self.timeout=int(os.getenv('WEBSITE_FETCH_TIMEOUT_SECONDS','10'));self.max_bytes=int(os.getenv('WEBSITE_FETCH_MAX_BYTES','1000000'))
    def status(self):
        provider=search_provider();return {'status':'READY' if provider.configured() else 'NOT_CONFIGURED','provider':provider.name,'minimum_confidence':self.threshold,'policy':'Documented search API; candidate website verification; SSRF protection.'}
    def discover(self,organization_id,company_id):
        with self.db_connect() as db:
            row=db.execute('SELECT * FROM companies WHERE organization_id=? AND id=?',(organization_id,company_id)).fetchone()
        if not row:return {'status':'NOT_FOUND','error_code':'COMPANY_NOT_FOUND'}
        company=dict(row);provider=search_provider();run='web_run_'+uuid.uuid4().hex;query=f'"{company["company_name"]}" Luxembourg {company.get("municipality") or ""}'.strip();started=now()
        with self.db_connect() as db:db.execute("INSERT INTO website_discovery_runs(id,organization_id,company_id,status,provider,query_text,started_at,metadata) VALUES(?,?,?,?,?,?,?,?)",(run,organization_id,company_id,'RUNNING',provider.name,query,started,'{}'))
        if company.get('website'):
            try:
                known=canonical(company['website']);page=self._fetch(known);score,evidence=self._score(company,known,{'title':'','snippet':''},page)
                if score>=self.threshold:
                    candidate={'url':known,'canonical_url':known,'domain':urllib.parse.urlsplit(known).hostname,'title':page.get('title'),'snippet':'','confidence':score,'evidence':{**evidence,'existing_company_field':True},'match_status':'CONFIRMED' if score>=.88 else 'PROBABLE'};self._store_candidate(organization_id,company_id,run,candidate,'existing_company_field');cid='web_candidate_'+hashlib.sha256((organization_id+'|'+company_id+'|'+known).encode()).hexdigest()[:24]
                    with self.db_connect() as db:db.execute("UPDATE website_discovery_runs SET status='SUCCESS',completed_at=?,candidates_found=1,selected_candidate_id=? WHERE id=?",(now(),cid,run))
                    self._check(organization_id,company_id,'Website','FOUND',known,score,'existing_company_field',None,candidate['evidence']);return {'status':'FOUND','run_id':run,'website_url':known,'confidence':score,'discovery_source':'existing_company_field','evidence':candidate['evidence'],'candidates_found':1}
            except Exception:pass
        if not provider.configured():
            self._finish_run(run,'NOT_CONFIGURED',error_code='SEARCH_PROVIDER_NOT_CONFIGURED',error='Configure Brave Search or Google Programmable Search.');self._check(organization_id,company_id,'Website','NOT_CHECKED',None,None,provider.name,'SEARCH_PROVIDER_NOT_CONFIGURED',{'query':query});return {'status':'NOT_CONFIGURED','run_id':run,'message':'Search provider is not configured; Website was not marked NOT_FOUND.'}
        try:results=provider.search(query,10)
        except Exception as exc:
            self._finish_run(run,'FAILED',error_code='SEARCH_API_ERROR',error=str(exc));self._check(organization_id,company_id,'Website','UNKNOWN',None,None,provider.name,'SEARCH_API_ERROR',{'query':query});return {'status':'FAILED','run_id':run,'message':str(exc)}
        candidates=[]
        for result in results:
            try:
                url=canonical(result['url']);host=urllib.parse.urlsplit(url).hostname
                if host in EXCLUDED_WEBSITE_HOSTS:continue
                page=self._fetch(url);score,evidence=self._score(company,url,result,page)
                candidate={**result,'url':url,'canonical_url':url,'domain':host,'confidence':score,'evidence':evidence,'match_status':'CONFIRMED' if score>=.88 else 'PROBABLE' if score>=self.threshold else 'POSSIBLE'};candidates.append(candidate);self._store_candidate(organization_id,company_id,run,candidate,provider.name)
            except Exception:continue
        candidates.sort(key=lambda x:x['confidence'],reverse=True);selected=candidates[0] if candidates and candidates[0]['confidence']>=self.threshold else None;completed=now()
        if selected:
            cid='web_candidate_'+hashlib.sha256((organization_id+'|'+company_id+'|'+selected['canonical_url']).encode()).hexdigest()[:24]
            with self.db_connect() as db:
                db.execute("UPDATE website_discovery_runs SET status='SUCCESS',completed_at=?,candidates_found=?,selected_candidate_id=? WHERE id=?",(completed,len(candidates),cid,run));db.execute("UPDATE companies SET website=?,website_status='FOUND',updated_at=? WHERE organization_id=? AND id=?",(selected['url'],completed,organization_id,company_id))
            self._check(organization_id,company_id,'Website','FOUND',selected['url'],selected['confidence'],provider.name,None,selected['evidence']);return {'status':'FOUND','run_id':run,'website_url':selected['url'],'confidence':selected['confidence'],'discovery_source':provider.name,'evidence':selected['evidence'],'candidates_found':len(candidates)}
        self._finish_run(run,'SUCCESS',len(candidates));self._check(organization_id,company_id,'Website','NOT_FOUND',None,1.0,provider.name,None,{'query':query,'results_evaluated':len(results)});return {'status':'NOT_FOUND','run_id':run,'confidence':1.0,'discovery_source':provider.name,'candidates_found':len(candidates)}
    def _fetch(self,url):
        validate_public_url(url);req=urllib.request.Request(url,headers={'User-Agent':'NACELUX/1.0 website-verification','Accept':'text/html,application/xhtml+xml'});opener=urllib.request.build_opener(SafeWebsiteRedirect())
        with opener.open(req,timeout=self.timeout) as response:
            ctype=response.headers.get_content_type()
            if ctype not in ('text/html','application/xhtml+xml'):raise ValueError('Candidate is not HTML')
            raw=response.read(self.max_bytes+1)
            if len(raw)>self.max_bytes:raise ValueError('Candidate page exceeds limit')
            parser=PageText();parser.feed(raw.decode(response.headers.get_content_charset() or 'utf-8','replace'));return {'title':' '.join(parser.title).strip(),'text':re.sub(r'\s+',' ',' '.join(parser.parts)).strip()[:200000]}
    def analyze_website(self, url):
        """Fetch a candidate URL (full SSRF guard, redirect revalidation, bounded
        size, timeout) and return the technical on-page analysis. Raises on any
        safety/validation/connectivity problem so the caller maps a status."""
        validate_public_url(url)
        start = time.monotonic()
        opener = urllib.request.build_opener(SafeWebsiteRedirect())
        req = urllib.request.Request(url, headers={'User-Agent': NACELUX_UA, 'Accept': 'text/html,application/xhtml+xml,*/*;q=0.1'})
        with opener.open(req, timeout=self.timeout) as response:
            final_url = response.geturl()
            validate_public_url(final_url)
            http_status = getattr(response, 'status', 200)
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or 'utf-8'
            raw = response.read(self.max_bytes + 1)
            page_bytes = len(raw)
            if page_bytes > self.max_bytes:
                raise ValueError('Candidate page exceeds size limit')
            response_ms = int((time.monotonic() - start) * 1000)
            analysis = parse_html(raw.decode(charset, 'replace'))
            final_scheme = urllib.parse.urlsplit(final_url).scheme.lower()
            return {**analysis, 'http_status': http_status, 'final_url': final_url,
                    'hostname': urllib.parse.urlsplit(final_url).hostname, 'https': final_scheme == 'https',
                    'https_status': 'VALID' if final_scheme == 'https' else 'NOT_HTTPS',
                    'content_type': content_type, 'charset': charset,
                    'page_bytes': page_bytes, 'response_ms': response_ms}
    @staticmethod
    def _classify_value_error(message):
        low = message.lower()
        if any(k in low for k in ('non-public', 'metadata', 'localhost', 'not a public', 'resolves to')):
            return 'BLOCKED', 'SSRF_BLOCKED'
        if 'dns' in low or 'name or service' in low or 'no address' in low:
            return 'NOT_FOUND', 'DNS_FAILURE'
        return 'INVALID', 'INVALID_URL'
    def verify_website(self, organization_id, company_id, url=None):
        """Verify a company website and record a CONNECTED/NOT_FOUND/INVALID/
        BLOCKED/ERROR observation with technical metrics + history. The URL is
        chosen server-side: the company's known website, or an explicitly provided
        candidate (untrusted -> full SSRF). NEVER invents a URL from the name."""
        with self.db_connect() as db:
            row = db.execute('SELECT * FROM companies WHERE organization_id=? AND id=?', (organization_id, company_id)).fetchone()
        if not row:
            return {'status': 'NOT_FOUND', 'error_code': 'COMPANY_NOT_FOUND'}
        company = dict(row)
        candidate = canonical(url) if url else (canonical(company['website']) if company.get('website') else None)
        if not candidate:
            self._record_check(organization_id, company_id, 'Website', 'NOT_CHECKED', None,
                               explanation='No website URL known; verify cannot claim NO_WEBSITE.',
                               rule_version=WEBSITE_RULE_VERSION)
            return {'status': 'NOT_CHECKED', 'message': 'No website URL available to verify.'}
        self._record_check(organization_id, company_id, 'Website', 'CHECKING', candidate, rule_version=WEBSITE_RULE_VERSION)
        try:
            result = self.analyze_website(candidate)
        except ValueError as exc:
            status, code = self._classify_value_error(str(exc))
            self._record_check(organization_id, company_id, 'Website', status, candidate,
                               error_code=code, explanation=str(exc), rule_version=WEBSITE_RULE_VERSION)
            return {'status': status, 'url': candidate, 'error_code': code, 'message': str(exc)}
        except urllib.error.HTTPError as exc:
            status = 'NOT_FOUND' if exc.code in (404, 410) else 'ERROR'
            self._record_check(organization_id, company_id, 'Website', status, candidate,
                               metrics={'http_status': exc.code}, explanation=f'HTTP {exc.code}', rule_version=WEBSITE_RULE_VERSION)
            return {'status': status, 'url': candidate, 'http_status': exc.code}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = str(exc)
            status, code = self._classify_value_error(reason)
            self._record_check(organization_id, company_id, 'Website', status, candidate,
                               error_code=code, explanation=reason[:300], rule_version=WEBSITE_RULE_VERSION)
            return {'status': status, 'url': candidate, 'message': reason[:300]}
        status = 'CONNECTED' if 200 <= result['http_status'] < 400 else 'ERROR'
        self._record_check(organization_id, company_id, 'Website', status, candidate,
                           metrics=result, value=result.get('title'), rule_version=WEBSITE_RULE_VERSION)
        with self.db_connect() as db:
            db.execute("UPDATE companies SET website=?,website_status=?,updated_at=? WHERE organization_id=? AND id=?",
                       (result['final_url'], status, now(), organization_id, company_id))
        return {'status': status, 'url': candidate,
                **{k: result[k] for k in ('http_status', 'final_url', 'https', 'https_status', 'title', 'h1', 'h1_count', 'meta_description', 'viewport', 'has_viewport', 'canonical', 'robots_meta', 'page_bytes', 'response_ms', 'charset')}}
    def _record_check(self, org, company, channel, status, url=None, *, metrics=None, error_code=None,
                      explanation=None, value=None, confidence=None, source_provider='website_verification',
                      rule_version=None):
        metrics = metrics or {}
        check_id = 'digital_' + hashlib.sha256((org + '|' + company + '|' + channel).encode()).hexdigest()[:24]
        cols = ['id', 'organization_id', 'company_id', 'channel', 'status', 'source_url', 'confidence', 'checked_at',
                'details', 'source_provider', 'evidence', 'error_code', 'check_method', 'http_status', 'response_ms',
                'page_bytes', 'https_status', 'final_url', 'value', 'explanation', 'rule_version']
        vals = [check_id, org, company, channel, status, url, confidence, now(), json.dumps(metrics),
                source_provider, json.dumps(metrics), error_code, 'WEBSITE_VERIFICATION',
                metrics.get('http_status'), metrics.get('response_ms'), metrics.get('page_bytes'),
                metrics.get('https_status'), metrics.get('final_url'), value or metrics.get('title'),
                explanation, rule_version]
        updates = ','.join(f"{c}=excluded.{c}" for c in cols if c not in ('id', 'organization_id', 'company_id', 'channel'))
        ph = ','.join(['?'] * len(cols))
        hid = 'dch_' + uuid.uuid4().hex[:24]
        hcols = ['id', 'organization_id', 'company_id', 'channel', 'status', 'source_url', 'http_status',
                 'response_ms', 'page_bytes', 'https_status', 'final_url', 'checked_at', 'details', 'rule_version']
        hvals = [hid, org, company, channel, status, url, metrics.get('http_status'), metrics.get('response_ms'),
                 metrics.get('page_bytes'), metrics.get('https_status'), metrics.get('final_url'), now(),
                 json.dumps(metrics), rule_version]
        with self.db_connect() as db:
            db.execute(f"INSERT INTO digital_checks({','.join(cols)}) VALUES({ph}) ON CONFLICT(organization_id,company_id,channel) DO UPDATE SET {updates}", vals)
            db.execute(f"INSERT INTO digital_check_history({','.join(hcols)}) VALUES({','.join(['?']*len(hcols))})", hvals)
    def _score(self,c,url,result,page):
        tokens=company_tokens(c['company_name']);hay=norm(' '.join([result.get('title',''),result.get('snippet',''),page.get('title',''),page.get('text','')[:10000]]));domain=norm(urllib.parse.urlsplit(url).hostname or '').replace('www ','');matched=sorted(t for t in tokens if t in hay);domain_matches=sorted(t for t in tokens if t in domain);score=0
        if tokens:score+=.4*len(matched)/len(tokens)+.2*len(domain_matches)/len(tokens)
        exact=norm(c['company_name']) in hay
        if exact:score+=.2
        if c.get('rcs_number') and norm(c['rcs_number']) in hay:score+=.15
        if c.get('municipality') and norm(c['municipality']) in hay:score+=.05
        return round(min(score,1),3),{'matched_name_tokens':matched,'domain_tokens':domain_matches,'exact_name':exact,'rcs_match':bool(c.get('rcs_number') and norm(c['rcs_number']) in hay),'location_match':bool(c.get('municipality') and norm(c['municipality']) in hay),'page_title':page.get('title')}
    def _store_candidate(self,org,company,run,c,provider):
        cid='web_candidate_'+hashlib.sha256((org+'|'+company+'|'+c['canonical_url']).encode()).hexdigest()[:24]
        with self.db_connect() as db:db.execute("INSERT INTO website_candidates(id,organization_id,company_id,run_id,url,canonical_url,domain,title,snippet,confidence,match_status,evidence,discovery_source,checked_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(organization_id,company_id,canonical_url) DO UPDATE SET run_id=excluded.run_id,title=excluded.title,snippet=excluded.snippet,confidence=excluded.confidence,match_status=excluded.match_status,evidence=excluded.evidence,checked_at=excluded.checked_at",(cid,org,company,run,c['url'],c['canonical_url'],c['domain'],c.get('title'),c.get('snippet'),c['confidence'],c['match_status'],json.dumps(c['evidence']),provider,now()))
    def _finish_run(self,run,status,candidates=0,error_code=None,error=None):
        with self.db_connect() as db:db.execute("UPDATE website_discovery_runs SET status=?,completed_at=?,candidates_found=?,error_code=?,error_message=? WHERE id=?",(status,now(),candidates,error_code,error,run))
    def _check(self,org,company,channel,status,url,confidence,provider,error,evidence):
        check_id='digital_'+hashlib.sha256((org+'|'+company+'|'+channel).encode()).hexdigest()[:24]
        with self.db_connect() as db:db.execute("INSERT INTO digital_checks(id,organization_id,company_id,channel,status,source_url,confidence,checked_at,details,source_provider,evidence,error_code,check_method) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(organization_id,company_id,channel) DO UPDATE SET status=excluded.status,source_url=excluded.source_url,confidence=excluded.confidence,checked_at=excluded.checked_at,source_provider=excluded.source_provider,evidence=excluded.evidence,error_code=excluded.error_code,check_method=excluded.check_method",(check_id,org,company,channel,status,url,confidence,now(),json.dumps({}),provider,json.dumps(evidence),error,'SEARCH_API_AND_WEBSITE_VERIFICATION'))

class DigitalFootprintEngine:
    CHANNELS=('Website','LinkedIn company','Google Business','Facebook')
    def __init__(self,db_connect):self.db_connect=db_connect;self.web=WebsiteDiscoveryEngine(db_connect)
    def status(self):return {'website_discovery':self.web.status(),'google_places':'READY' if os.getenv('GOOGLE_PLACES_API_KEY') else 'NOT_CONFIGURED','channels':self.CHANNELS}
    def analyze(self,org,company_id):
        website=self.web.discover(org,company_id)
        with self.db_connect() as db:row=db.execute('SELECT * FROM companies WHERE organization_id=? AND id=?',(org,company_id)).fetchone()
        if not row:return {'status':'NOT_FOUND'}
        c=dict(row);provider=search_provider();social={}
        for channel,site,prefix in [('LinkedIn company','linkedin.com/company','https://www.linkedin.com/company/'),('Facebook','facebook.com','https://www.facebook.com/')]:
            if not provider.configured():result={'status':'NOT_CHECKED','confidence':None,'url':None,'error':'SEARCH_PROVIDER_NOT_CONFIGURED'}
            else:
                try:
                    hits=provider.search(f'site:{site} "{c["company_name"]}" Luxembourg',5);tokens=company_tokens(c['company_name']);scored=[]
                    for hit in hits:
                        host=urllib.parse.urlsplit(hit['url']).hostname or '';path=urllib.parse.urlsplit(hit['url']).path;matched=[t for t in tokens if t in norm(hit.get('title','')+' '+hit.get('snippet',''))]
                        conf=round(len(matched)/max(len(tokens),1)*.8+.15,3) if host.endswith(site.split('/')[0]) and (channel!='LinkedIn company' or '/company/' in path) else 0
                        if conf:scored.append((conf,hit))
                    scored.sort(key=lambda x:x[0],reverse=True)
                    if scored and scored[0][0]>=.72:result={'status':'FOUND','confidence':scored[0][0],'url':scored[0][1]['url'],'evidence':{'title':scored[0][1].get('title'),'query_provider':provider.name}}
                    elif scored:result={'status':'UNKNOWN','confidence':scored[0][0],'url':scored[0][1]['url'],'evidence':{'reason':'ambiguous match'}}
                    else:result={'status':'NOT_FOUND','confidence':1.0,'url':None,'evidence':{'results_evaluated':len(hits)}}
                except Exception as exc:result={'status':'UNKNOWN','confidence':None,'url':None,'error':'SEARCH_API_ERROR','evidence':{'message':str(exc)}}
            self.web._check(org,company_id,channel,result['status'],result.get('url'),result.get('confidence'),provider.name,result.get('error'),result.get('evidence',{}));social[channel]=result
        google=self._google_business(org,c);known=[x for x in [website,*social.values(),google] if x.get('status') in ('FOUND','NOT_FOUND')];score=round(100*sum(1 for x in known if x['status']=='FOUND')/len(known)) if known else None
        if score is not None:
            with self.db_connect() as db:db.execute('UPDATE companies SET digital_score=?,updated_at=? WHERE organization_id=? AND id=?',(score,now(),org,company_id))
        return {'status':'SUCCESS','website':website,'linkedin':social['LinkedIn company'],'google_business':google,'facebook':social['Facebook'],'digital_score':score}
    def _google_business(self,org,c):
        key=os.getenv('GOOGLE_PLACES_API_KEY','')
        if not key:
            result={'status':'NOT_CHECKED','confidence':None,'error':'GOOGLE_PLACES_NOT_CONFIGURED'};self.web._check(org,c['id'],'Google Business',result['status'],None,None,'google_places',result['error'],{});return result
        payload=json.dumps({'textQuery':f"{c['company_name']}, {c.get('municipality') or ''}, Luxembourg",'languageCode':'fr','regionCode':'LU','maxResultCount':5}).encode();fields='places.id,places.displayName,places.formattedAddress,places.primaryType,places.websiteUri,places.nationalPhoneNumber,places.rating,places.userRatingCount,places.businessStatus,places.googleMapsUri'
        req=urllib.request.Request('https://places.googleapis.com/v1/places:searchText',data=payload,method='POST',headers={'Content-Type':'application/json','X-Goog-Api-Key':key,'X-Goog-FieldMask':fields})
        try:
            with urllib.request.urlopen(req,timeout=15) as response:data=json.load(response)
            tokens=company_tokens(c['company_name']);matches=[]
            for place in data.get('places',[]):
                name=(place.get('displayName') or {}).get('text','');overlap=len([t for t in tokens if t in norm(name)])/max(len(tokens),1);location=.15 if norm(c.get('municipality')) in norm(place.get('formattedAddress','')) else 0;confidence=round(.8*overlap+location,3);matches.append((confidence,place))
            matches.sort(key=lambda x:x[0],reverse=True)
            if matches and matches[0][0]>=.72:
                confidence,place=matches[0];result={'status':'FOUND','confidence':confidence,'url':place.get('googleMapsUri'),'place':place};profile_id='gb_'+hashlib.sha256((org+'|'+c['id']).encode()).hexdigest()[:24]
                with self.db_connect() as db:db.execute("INSERT INTO google_business_profiles(id,organization_id,company_id,place_id,business_name,formatted_address,primary_type,website_url,phone,rating,review_count,status,source_url,checked_at,raw_data) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(organization_id,company_id) DO UPDATE SET place_id=excluded.place_id,business_name=excluded.business_name,formatted_address=excluded.formatted_address,primary_type=excluded.primary_type,website_url=excluded.website_url,phone=excluded.phone,rating=excluded.rating,review_count=excluded.review_count,status=excluded.status,source_url=excluded.source_url,checked_at=excluded.checked_at,raw_data=excluded.raw_data",(profile_id,org,c['id'],place.get('id'),(place.get('displayName') or {}).get('text'),place.get('formattedAddress'),place.get('primaryType'),place.get('websiteUri'),place.get('nationalPhoneNumber'),place.get('rating'),place.get('userRatingCount'),'FOUND',place.get('googleMapsUri'),now(),json.dumps(place)))
            elif matches:result={'status':'UNKNOWN','confidence':matches[0][0],'url':matches[0][1].get('googleMapsUri'),'evidence':{'reason':'ambiguous place match'}}
            else:result={'status':'NOT_FOUND','confidence':1.0,'url':None,'evidence':{'places_evaluated':0}}
        except Exception as exc:result={'status':'UNKNOWN','confidence':None,'url':None,'error':'GOOGLE_PLACES_ERROR','evidence':{'message':str(exc)}}
        self.web._check(org,c['id'],'Google Business',result['status'],result.get('url'),result.get('confidence'),'google_places',result.get('error'),result.get('evidence',{}));return {k:v for k,v in result.items() if k!='place'}
