"""GDPR-conscious People Engine for official directors and high-confidence public profiles."""
from __future__ import annotations
import hashlib,json,os,re,unicodedata,urllib.parse,uuid
from datetime import date,datetime,timedelta,timezone
from website_intelligence import search_provider,company_tokens,norm

ROLE_WORDS=r"gérant|gérante|administrateur|administratrice|directeur|directrice|managing director|manager|director|geschäftsführer|geschäftsführerin|vorstand|président|présidente"
NAME_WORD=r"[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+"
FORWARD=re.compile(rf"\b(?P<role>{ROLE_WORDS})\b\s*[:\-–]\s*(?P<name>(?:{NAME_WORD}\s+){{1,4}}{NAME_WORD})",re.I)
REVERSE=re.compile(rf"\b(?P<name>(?:{NAME_WORD}\s+){{1,4}}{NAME_WORD})\s*[,;\-–]\s*(?P<role>{ROLE_WORDS})\b",re.I)
BLOCKED_NAME_WORDS={'sarl','société','societe','anonyme','company','luxembourg','registered','siège','siege','capital','publication'}

def now():return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def normalized_name(value):return re.sub(r'[^a-z ]','',unicodedata.normalize('NFKD',value).encode('ascii','ignore').decode().lower()).strip()
def clean_name(value):return re.sub(r'\s+',' ',re.sub(r'^(monsieur|madame|m\.|mme\.)\s+','',value.strip(),flags=re.I)).strip(' ,;:-')
def extract_official_people(text):
    found=[];seen=set()
    for pattern in (FORWARD,REVERSE):
        for match in pattern.finditer(text or ''):
            name=clean_name(match.group('name'));role=match.group('role').strip();key=normalized_name(name)
            words=set(key.split());name_parts=[x for x in re.split(r'\s+',name) if x]
            if len(words)<2 or len(name)>120 or words & BLOCKED_NAME_WORDS or key in seen or not all(x[0].isupper() for x in name_parts):continue
            seen.add(key);start=max(0,match.start()-100);end=min(len(text),match.end()+100);found.append({'name':name,'name_normalized':key,'role':role,'confidence':.95,'excerpt':re.sub(r'\s+',' ',text[start:end]).strip()})
    return found

class PeopleEngine:
    def __init__(self,db_connect):self.db_connect=db_connect;self.threshold=float(os.getenv('PEOPLE_PROFILE_MIN_CONFIDENCE','.82'));self.retention=int(os.getenv('PEOPLE_RETENTION_DAYS','365'));self.max_searches=int(os.getenv('PEOPLE_MAX_SEARCHES_PER_RUN','10'))
    def status(self):
        provider=search_provider();return {'status':'READY','official_source':'RESA_EXTRACTED_DOCUMENTS','professional_search':'READY' if provider.configured() else 'NOT_CONFIGURED','provider':provider.name,'minimum_profile_confidence':self.threshold,'privacy':'Public professional data only; no private contact or protected profile scraping.'}
    def analyze(self,org,company_id):
        with self.db_connect() as db:company=db.execute('SELECT * FROM companies WHERE organization_id=? AND id=?',(org,company_id)).fetchone()
        if not company:return {'status':'NOT_FOUND','error_code':'COMPANY_NOT_FOUND'}
        c=dict(company);provider=search_provider();run='people_run_'+uuid.uuid4().hex;started=now()
        with self.db_connect() as db:db.execute("INSERT INTO people_engine_runs(id,organization_id,company_id,status,started_at,provider,metadata) VALUES(?,?,?,'RUNNING',?,?,?)",(run,org,company_id,started,provider.name,json.dumps({'policy':'public_professional_only'})))
        try:
            official=self._official_people(org,c);profiles=self._professional_profiles(org,c,provider,official);completed=now()
            with self.db_connect() as db:
                db.execute("UPDATE people_engine_runs SET status='SUCCESS',completed_at=?,official_people_found=?,professional_profiles_found=? WHERE id=?",(completed,len(official),len(profiles),run))
                if official:db.execute("UPDATE companies SET decision_maker_status='FOUND',updated_at=? WHERE organization_id=? AND id=?",(completed,org,company_id))
            return {'status':'SUCCESS','run_id':run,'official_people_found':len(official),'professional_profiles_found':len(profiles),'official_people':official,'professional_profiles':profiles,'profile_search_status':'COMPLETED' if provider.configured() else 'NOT_CONFIGURED'}
        except Exception as exc:
            with self.db_connect() as db:db.execute("UPDATE people_engine_runs SET status='FAILED',completed_at=?,error_code='PEOPLE_ENGINE_FAILED',error_message=? WHERE id=?",(now(),str(exc)[:2000],run))
            return {'status':'FAILED','run_id':run,'error_code':'PEOPLE_ENGINE_FAILED','message':str(exc)}
    def _official_people(self,org,c):
        if not c.get('rcs_number'):return []
        with self.db_connect() as db:
            extracts=db.execute("""SELECT x.id extraction_id,x.text_content,d.id document_id,d.source_url
            FROM document_extractions x JOIN resa_documents d ON d.id=x.document_id AND d.organization_id=x.organization_id
            JOIN resa_entries e ON e.id=d.entry_id AND e.organization_id=d.organization_id
            WHERE x.organization_id=? AND e.rcs_number=? AND x.status IN ('SUCCESS','PARTIAL')""",(org,c['rcs_number'])).fetchall()
        output=[]
        for row in extracts:
            row=dict(row)
            for person in extract_official_people(row['text_content']):
                pid='person_'+hashlib.sha256((org+'|'+c['id']+'|'+person['name_normalized']).encode()).hexdigest()[:24];checked=now();retention=(date.today()+timedelta(days=self.retention)).isoformat()
                with self.db_connect() as db:
                    db.execute("""INSERT INTO people(id,organization_id,display_name,job_title,company_id,source_type,match_status,confidence,is_demo,created_at,name_normalized,official_role,source_url,source_document_id,source_extraction_id,checked_at,privacy_status,retention_until)
                    VALUES(?,?,?,?,?,'OFFICIAL','CONFIRMED',?,FALSE,?,?,?,?,?,?,?,'ACTIVE',?) ON CONFLICT(organization_id,company_id,name_normalized) DO UPDATE SET display_name=excluded.display_name,job_title=excluded.job_title,source_type='OFFICIAL',match_status='CONFIRMED',confidence=excluded.confidence,official_role=excluded.official_role,source_url=excluded.source_url,source_document_id=excluded.source_document_id,source_extraction_id=excluded.source_extraction_id,checked_at=excluded.checked_at,privacy_status='ACTIVE',retention_until=excluded.retention_until""",
                    (pid,org,person['name'],person['role'],c['id'],person['confidence'],checked,person['name_normalized'],person['role'],row['source_url'],row['document_id'],row['extraction_id'],checked,retention))
                    evidence_id='evidence_'+hashlib.sha256((pid+'|'+row['source_url']).encode()).hexdigest()[:24]
                    db.execute("INSERT INTO people_evidence(id,organization_id,person_id,evidence_type,source_url,source_document_id,source_extraction_id,excerpt,confidence,method,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(person_id,evidence_type,source_url) DO UPDATE SET excerpt=excluded.excerpt,confidence=excluded.confidence,created_at=excluded.created_at",(evidence_id,org,pid,'OFFICIAL_ROLE',row['source_url'],row['document_id'],row['extraction_id'],person['excerpt'],person['confidence'],'REGEX_EXPLICIT_ROLE_LABEL',checked))
                output.append({'id':pid,'name':person['name'],'role':person['role'],'confidence':person['confidence'],'source_type':'OFFICIAL','source_url':row['source_url'],'document_id':row['document_id']})
        unique={x['id']:x for x in output};return list(unique.values())
    def _professional_profiles(self,org,c,provider,official):
        if not provider.configured():return []
        people=list(official)
        if not people:
            with self.db_connect() as db:people=[dict(x) for x in db.execute("SELECT id,display_name name,official_role role FROM people WHERE organization_id=? AND company_id=? AND source_type='OFFICIAL' AND privacy_status='ACTIVE' ORDER BY confidence DESC LIMIT ?",(org,c['id'],self.max_searches)).fetchall()]
        profiles=[]
        for person in people[:self.max_searches]:
            hits=provider.search(f'"{person["name"]}" "{c["company_name"]}" site:linkedin.com/in',5);best=None
            for hit in hits:
                parsed=urllib.parse.urlsplit(hit['url']);combined=norm(hit.get('title','')+' '+hit.get('snippet',''));name_match=normalized_name(person['name']) in combined;tokens=company_tokens(c['company_name']);company_overlap=len([t for t in tokens if t in combined])/max(len(tokens),1);role_tokens=set(norm(person.get('role','')).split());role_overlap=len([t for t in role_tokens if t in combined])/max(len(role_tokens),1) if role_tokens else 0;location=.05 if norm(c.get('municipality')) in combined or 'luxembourg' in combined else 0;confidence=round((.55 if name_match else 0)+.3*company_overlap+.1*role_overlap+location,3)
                if parsed.hostname and parsed.hostname.endswith('linkedin.com') and '/in/' in parsed.path and (best is None or confidence>best[0]):best=(confidence,hit,{'name_match':name_match,'company_overlap':company_overlap,'role_overlap':role_overlap,'location_signal':bool(location)})
            if not best or best[0]<self.threshold:continue
            confidence,hit,evidence=best;status='CONFIRMED' if confidence>=.92 else 'PROBABLE';profile_id='profile_'+hashlib.sha256((org+'|'+hit['url']).encode()).hexdigest()[:24];checked=now()
            with self.db_connect() as db:db.execute("INSERT INTO professional_profiles_public(id,organization_id,person_id,company_id,platform,profile_url,public_title,match_status,match_confidence,evidence,source_provider,checked_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(organization_id,platform,profile_url) DO UPDATE SET person_id=excluded.person_id,company_id=excluded.company_id,public_title=excluded.public_title,match_status=excluded.match_status,match_confidence=excluded.match_confidence,evidence=excluded.evidence,checked_at=excluded.checked_at",(profile_id,org,person['id'],c['id'],'LINKEDIN',hit['url'],hit.get('title'),status,confidence,json.dumps(evidence),provider.name,checked));db.execute("UPDATE people SET profile_url=?,match_status=?,confidence=?,checked_at=? WHERE id=? AND organization_id=?",(hit['url'],status,confidence,checked,person['id'],org))
            profiles.append({'id':profile_id,'person_id':person['id'],'platform':'LINKEDIN','profile_url':hit['url'],'public_title':hit.get('title'),'match_status':status,'confidence':confidence,'evidence':evidence,'source_provider':provider.name})
        return profiles
    def create_privacy_request(self,org,person_id,request_type,reference=None,notes=None):
        if request_type not in ('ACCESS','CORRECTION','SUPPRESSION','OBJECTION'):raise ValueError('Unsupported privacy request type')
        with self.db_connect() as db:
            person=db.execute('SELECT id FROM people WHERE organization_id=? AND id=?',(org,person_id)).fetchone()
            if not person:raise ValueError('Person not found')
            rid='privacy_'+uuid.uuid4().hex;db.execute("INSERT INTO privacy_requests(id,organization_id,person_id,request_type,status,requester_reference,notes,created_at) VALUES(?,?,?,?,?,?,?,?)",(rid,org,person_id,request_type,'OPEN',reference,notes,now()))
            if request_type in ('SUPPRESSION','OBJECTION'):db.execute("UPDATE people SET privacy_status='REVIEW_REQUIRED' WHERE organization_id=? AND id=?",(org,person_id))
        return {'id':rid,'status':'OPEN','request_type':request_type}
