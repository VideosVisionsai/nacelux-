#!/usr/bin/env python3
import csv, io, json, mimetypes, os, sys, uuid
from datetime import date, datetime
from decimal import Decimal
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).parent))
import database as data
import auth
from resa_connector import LBRResaConnector
from document_storage import ResaPdfStoragePipeline
from pdf_extraction import PdfTextExtractionEngine
from nace_importer import OfficialNaceImporter
from website_intelligence import WebsiteDiscoveryEngine, DigitalFootprintEngine
from seo_engine import SEOAuditEngine, BusinessSignalEngine
from people_engine import PeopleEngine

PEOPLE_ENGINE=PeopleEngine(data.connect)
SEO_AUDIT=SEOAuditEngine(data.connect)
BUSINESS_SIGNALS=BusinessSignalEngine(data.connect)
WEBSITE_DISCOVERY=WebsiteDiscoveryEngine(data.connect)
DIGITAL_FOOTPRINT=DigitalFootprintEngine(data.connect)
NACE_IMPORTER=OfficialNaceImporter(data.connect)
RESA_CONNECTOR=LBRResaConnector(data.connect)
PDF_STORAGE=ResaPdfStoragePipeline(data.connect)
PDF_EXTRACTION=PdfTextExtractionEngine(data.connect)
ROOT=Path(__file__).resolve().parents[1]
FRONTEND=ROOT/"frontend"
PORT=int(os.environ.get("PORT","8000"))
_PRODUCTION=os.environ.get('NACELUX_ENV','development').lower() in ('production','prod')
AUTH_ACTIVE=auth.AUTH_ENABLED and data.IS_POSTGRES

if _PRODUCTION and not AUTH_ACTIVE:
    raise RuntimeError('Production authentication and PostgreSQL are mandatory; refusing Demo/SQLite runtime')

def flatten(qs): return {k:v[-1] for k,v in parse_qs(qs).items() if v}

class API(BaseHTTPRequestHandler):
    server_version="NACELUX/0.1"
    def log_message(self, fmt, *args): print("[http]",fmt%args)
    @property
    def auth_context(self):
        if hasattr(self,'_auth_context'): return self._auth_context
        if not AUTH_ACTIVE:
            if _PRODUCTION:
                raise auth.AuthError('Production authentication is not configured',503,'AUTH_NOT_CONFIGURED')
            self._auth_context={'user_id':'user_demo_owner','display_name':'Development User','organization_id':data.ORG_ID,'organization_name':'Development Workspace','role':'OWNER','demo':True}
            return self._auth_context
        session=auth.get_session(self.headers.get('Cookie'))
        if not session: raise auth.AuthError('Authentication required',401,'AUTH_REQUIRED')
        # Seed only the authenticated identity while provisioning/looking up the
        # workspace; the organization context is set only from that membership.
        data.set_tenant_context(None,session['auth_user'].get('id'))
        self._auth_context=auth.ensure_workspace(session['auth_user'],data.connect)
        data.set_tenant_context(self._auth_context['organization_id'],self._auth_context['user_id'])
        self._auth_context['csrf']=session.get('csrf')
        self._refreshed_session=session.get('refreshed')
        return self._auth_context

    def finish(self):
        try:
            super().finish()
        finally:
            data.clear_tenant_context()
    @property
    def org(self): return self.auth_context['organization_id']
    def json(self,payload,status=200,headers=None):
        def encode(value):
            if isinstance(value,(date,datetime)): return value.isoformat()
            if isinstance(value,Decimal): return float(value)
            if isinstance(value,uuid.UUID): return str(value)
            raise TypeError(f'Unsupported JSON value: {type(value).__name__}')
        raw=json.dumps(payload,ensure_ascii=False,default=encode).encode(); self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(raw))); self.send_header("Cache-Control","no-store")
        outgoing=list(headers or [])
        if getattr(self,'_refreshed_session',None): outgoing += [('Set-Cookie',v) for v in auth.cookie_headers(self._refreshed_session)]
        for key,value in outgoing:self.send_header(key,value)
        self.end_headers(); self.wfile.write(raw)
    def body(self):
        try: return json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))) or b"{}")
        except Exception: return {}
    def do_GET(self):
        p=urlparse(self.path); path=p.path; q=flatten(p.query)
        try:
            if path in ("/health", "/health/liveness"):
                return self.json({"status": "ALIVE", "version": "2.1", "timestamp": data.now()})
            if path in ("/api/v1/health", "/health/readiness"):
                # Active database connectivity check
                db_healthy = True
                db_err = None
                try:
                    with data.connect() as db:
                        db.execute("SELECT 1").fetchone()
                except Exception as exc:
                    db_healthy = False
                    db_err = exc
                    print(f"[health] code=DATABASE_UNAVAILABLE detail={data.redact_error(exc)}", file=sys.stderr)

                db_status = {"status": "CONNECTED", "provider": "supabase-postgresql"} if data.IS_POSTGRES else {"status": "LOCAL_FALLBACK", "provider": "sqlite"}
                if not db_healthy:
                    db_status["status"] = "UNAVAILABLE"
                    db_status["code"] = "DATABASE_UNAVAILABLE"

                overall_status = "HEALTHY" if db_healthy else "UNHEALTHY"
                http_code = 200 if db_healthy else 503
                return self.json({
                    "status": overall_status,
                    "version": "2.1",
                    "database": db_status,
                    "storage": PDF_STORAGE.status(),
                    "ocr": PDF_EXTRACTION.status(),
                    "resa_connector": RESA_CONNECTOR.status(),
                    "auth_enabled": AUTH_ACTIVE,
                    "timestamp": data.now()
                }, status=http_code)
            if path=="/api/v1/auth/config": return self.json({"enabled":AUTH_ACTIVE,"provider":"supabase","password_reset":True})
            if path=="/api/v1/session":
                ctx=self.auth_context
                return self.json({"authenticated":True,"user":{"id":ctx['user_id'],"name":ctx['display_name'],"email":ctx.get('email'),"role":ctx['role']},"organization":{"id":ctx['organization_id'],"name":ctx['organization_name']},"mode":"DEMO" if ctx.get('demo') else "AUTHENTICATED","database":data.BACKEND,"csrf":ctx.get('csrf')})
            if path=="/api/v1/health/database":
                if data.IS_POSTGRES:
                    from migrations import connection_test
                    return self.json({"status":"CONNECTED","provider":"supabase-postgresql",**connection_test()})
                return self.json({"status":"LOCAL_FALLBACK","provider":"sqlite","message":"Set DATABASE_URL and DB_PROVIDER=postgresql to activate Supabase."})
            if path=="/api/v1/dashboard": return self.dashboard()
            if path=="/api/v1/companies": return self.json({"items":data.list_companies(self.org,q)})
            if path.startswith("/api/v1/companies/"): 
                item=data.company_detail(self.org,path.rsplit("/",1)[-1]); return self.json(item if item else {"error":"Not found"},200 if item else 404)
            if path=="/api/v1/opportunities": return self.json({"items":data.list_companies(self.org,q)})
            if path=="/api/v1/prospects": return self.json({"items":data.rows("""SELECT p.*,c.company_name,c.municipality,o.score FROM prospects p JOIN companies c ON c.id=p.company_id AND c.organization_id=p.organization_id JOIN opportunity_scores o ON o.company_id=c.id AND o.organization_id=c.organization_id WHERE p.organization_id=? ORDER BY p.updated_at DESC""",(self.org,))})
            if path=="/api/v1/sources": return self.json({"items":data.rows("SELECT * FROM data_sources WHERE organization_id=? ORDER BY name",(self.org,)),"jobs":data.rows("SELECT * FROM jobs WHERE organization_id=? ORDER BY started_at DESC LIMIT 20",(self.org,))})
            if path=="/api/v1/filters": return self.filters()
            if path=="/api/v1/export/companies.csv": return self.export_csv(q)
            if path.startswith('/api/v1/nace/') and path!='/api/v1/nace/import':
                code=path.rsplit('/',1)[-1];item=data.one("SELECT i.*,v.status version_status,v.source_checksum,v.retrieved_at,l.label FROM nace_items_official i JOIN nace_versions_official v ON v.id=i.version_id LEFT JOIN nace_labels_official l ON l.item_id=i.id AND l.language=? AND l.label_type='PREF' WHERE v.version_code='2.1' AND i.code=? AND i.is_current=1",(q.get('lang','fr').lower(),code))
                if not item:return self.json({'error':'NACE code not found'},404)
                item['labels']=data.rows("SELECT language,label_type,label FROM nace_labels_official WHERE item_id=? ORDER BY language",(item['id'],));item['notes']=data.rows("SELECT note_type,language,note_text,note_uri,source_url FROM nace_notes_official WHERE item_id=? ORDER BY note_type",(item['id'],));item['children']=data.rows("SELECT i.code,i.level,l.label FROM nace_items_official i LEFT JOIN nace_labels_official l ON l.item_id=i.id AND l.language=? AND l.label_type='PREF' WHERE i.version_id=? AND i.parent_code=? AND i.is_current=1 ORDER BY i.sort_order,i.code",(q.get('lang','fr').lower(),item['version_id'],code));item['from_rev2']=data.rows("SELECT source_code,target_code,relationship,mapping_uri,source_url FROM nace_correspondences_official WHERE source_version='2' AND target_version='2.1' AND target_code=? ORDER BY source_code",(code,));return self.json(item)
            if path=="/api/v1/nace":
                lang=q.get('lang','fr').lower();level=q.get('level');params=[lang];where="WHERE v.version_code='2.1' AND i.is_current=1"
                if level:where+=' AND i.level=?';params.append(level.upper())
                items=data.rows(f"SELECT i.code,i.level,i.parent_code,i.sort_order,i.concept_uri,l.label,v.status source_status,v.source_url,v.retrieved_at FROM nace_items_official i JOIN nace_versions_official v ON v.id=i.version_id LEFT JOIN nace_labels_official l ON l.item_id=i.id AND l.language=? AND l.label_type='PREF' {where} ORDER BY i.sort_order,i.code",params)
                return self.json({"version":"2.1","languages":["FR","DE","EN"],"status":NACE_IMPORTER.status(),"counts":{r['level']:r['count'] for r in data.rows("SELECT level,count(*) count FROM nace_items_official i JOIN nace_versions_official v ON v.id=i.version_id WHERE v.version_code='2.1' AND i.is_current=1 GROUP BY level")},"items":items})
            if path=="/api/v1/taxonomy": return self.json({"items":data.rows("SELECT n.*,p.name parent_name FROM taxonomy_nodes n LEFT JOIN taxonomy_nodes p ON p.id=n.parent_id WHERE n.organization_id=? ORDER BY n.node_type,n.name",(self.org,))})
            if path=="/api/v1/people": return self.json({"engine":PEOPLE_ENGINE.status(),"items":data.rows("SELECT p.*,c.company_name,c.municipality,(SELECT count(*) FROM people_evidence e WHERE e.person_id=p.id AND e.organization_id=p.organization_id) evidence_count FROM people p LEFT JOIN companies c ON c.id=p.company_id AND c.organization_id=p.organization_id WHERE p.organization_id=? AND COALESCE(p.privacy_status,'ACTIVE')!='SUPPRESSED' ORDER BY p.confidence DESC",(self.org,)),"profiles":data.rows("SELECT pr.*,p.display_name,c.company_name FROM professional_profiles_public pr JOIN people p ON p.id=pr.person_id AND p.organization_id=pr.organization_id JOIN companies c ON c.id=pr.company_id AND c.organization_id=pr.organization_id WHERE pr.organization_id=? AND pr.match_confidence>=? ORDER BY pr.match_confidence DESC",(self.org,PEOPLE_ENGINE.threshold)),"runs":data.rows("SELECT r.*,c.company_name FROM people_engine_runs r JOIN companies c ON c.id=r.company_id AND c.organization_id=r.organization_id WHERE r.organization_id=? ORDER BY r.started_at DESC LIMIT 100",(self.org,))})
            if path=="/api/v1/digital": return self.json({"engine":DIGITAL_FOOTPRINT.status(),"items":data.rows("SELECT d.*,c.company_name,c.municipality FROM digital_checks d JOIN companies c ON c.id=d.company_id AND c.organization_id=d.organization_id WHERE d.organization_id=? ORDER BY c.company_name,d.channel",(self.org,)),"discoveries":data.rows("SELECT r.*,c.company_name FROM website_discovery_runs r JOIN companies c ON c.id=r.company_id AND c.organization_id=r.organization_id WHERE r.organization_id=? ORDER BY r.started_at DESC LIMIT 100",(self.org,)),"candidates":data.rows("SELECT * FROM website_candidates WHERE organization_id=? ORDER BY checked_at DESC,confidence DESC LIMIT 200",(self.org,))})
            if path=="/api/v1/signals": return self.json({"engine":BUSINESS_SIGNALS.status(),"definitions":data.rows("SELECT * FROM business_signal_definitions WHERE is_active=TRUE ORDER BY signal_type"),"items":data.rows("SELECT b.*,c.company_name,c.municipality,c.niche FROM business_signals b JOIN companies c ON c.id=b.company_id AND c.organization_id=b.organization_id WHERE b.organization_id=? AND b.status='ACTIVE' ORDER BY b.last_seen_at DESC,b.signal_type",(self.org,)),"runs":data.rows("SELECT * FROM business_signal_runs WHERE organization_id=? ORDER BY started_at DESC LIMIT 50",(self.org,)),"counts":{r['signal_type']:r['count'] for r in data.rows("SELECT signal_type,count(*) count FROM business_signals WHERE organization_id=? AND status='ACTIVE' GROUP BY signal_type",(self.org,))}})
            if path=="/api/v1/seo": return self.json({"engine":SEO_AUDIT.status(),"items":data.rows("SELECT s.*,c.company_name,c.municipality,c.website_status FROM seo_audits s JOIN companies c ON c.id=s.company_id AND c.organization_id=s.organization_id WHERE s.organization_id=? ORDER BY COALESCE(s.opportunity_score,-1) DESC",(self.org,)),"signals":data.rows("SELECT b.*,c.company_name FROM business_signals b JOIN companies c ON c.id=b.company_id AND c.organization_id=b.organization_id WHERE b.organization_id=? AND b.status='ACTIVE' ORDER BY b.last_seen_at DESC",(self.org,))})
            if path.startswith('/api/v1/resa/extractions/'):
                extraction_id=path.rsplit('/',1)[-1];item=data.one("SELECT * FROM document_extractions WHERE organization_id=? AND id=?",(self.org,extraction_id))
                if not item:return self.json({'error':'Extraction not found'},404)
                item['pages']=data.rows("SELECT * FROM document_page_extractions WHERE organization_id=? AND extraction_id=? ORDER BY page_number",(self.org,extraction_id));return self.json(item)
            if path=="/api/v1/resa": return self.json({"connector":RESA_CONNECTOR.status(),"storage":PDF_STORAGE.status(),"extraction_engine":PDF_EXTRACTION.status(),"extractions":data.rows("SELECT id,document_id,status,extraction_method,page_count,ocr_pages,char_count,quality_score,completed_at,error_code,error_message FROM document_extractions WHERE organization_id=? ORDER BY started_at DESC LIMIT 100",(self.org,)),"journals":data.rows("SELECT * FROM resa_journals WHERE organization_id=? ORDER BY last_seen_at DESC",(self.org,)),"items":data.rows("SELECT e.*,j.journal_key,(SELECT count(*) FROM resa_documents d WHERE d.entry_id=e.id AND d.organization_id=e.organization_id) document_count FROM resa_entries e JOIN resa_journals j ON j.id=e.journal_id WHERE e.organization_id=? ORDER BY j.last_seen_at DESC,e.row_index",(self.org,)),"documents":data.rows("SELECT * FROM resa_documents WHERE organization_id=? ORDER BY last_seen_at DESC LIMIT 500",(self.org,)),"runs":data.rows("SELECT * FROM resa_sync_runs WHERE organization_id=? ORDER BY started_at DESC LIMIT 50",(self.org,))})
            if path=="/api/v1/reports": return self.json({"items":data.rows("SELECT * FROM reports WHERE organization_id=? ORDER BY created_at DESC",(self.org,))})
            if path=="/api/v1/logs": return self.json({"items":data.rows("SELECT * FROM audit_logs WHERE organization_id=? ORDER BY created_at DESC LIMIT 100",(self.org,))})
            if path=="/api/v1/organization/members": return self.json({"items":data.rows("SELECT u.id,u.email,u.display_name,m.role FROM organization_members m JOIN users u ON u.id=m.user_id WHERE m.organization_id=? ORDER BY CASE m.role WHEN 'OWNER' THEN 1 WHEN 'ADMIN' THEN 2 ELSE 3 END,u.display_name",(self.org,))})
            if path=="/api/v1/settings": return self.json({"weights":{r['factor']:r['weight'] for r in data.rows("SELECT factor,weight FROM scoring_weights WHERE organization_id=?",(self.org,))},"plans":["Free","Starter","Pro","Agency","Enterprise"],"billing":"NOT_CONNECTED","role":"OWNER","tenant_isolation":"ACTIVE"})
            return self.static(path)
        except auth.AuthError as e: return self.json({"error":str(e),"code":e.code},e.status)
        except Exception as e:
            print(f"[http] ERROR detail={data.redact_error(e)}", file=sys.stderr); return self.json({"error":"Internal error","status":"ERROR"},500)
    def do_POST(self):
        path=urlparse(self.path).path; body=self.body()
        if path.startswith('/api/v1/auth/'):
            return self.auth_post(path,body)
        if AUTH_ACTIVE:
            try: ctx=self.auth_context
            except auth.AuthError as e:return self.json({'error':str(e),'code':e.code},e.status)
            cookies=auth.parse_cookies(self.headers.get('Cookie'))
            if not cookies.get(auth.CSRF_COOKIE) or self.headers.get('X-CSRF-Token')!=cookies.get(auth.CSRF_COOKIE): return self.json({'error':'Invalid CSRF token','code':'CSRF_FAILED'},403)
        if path=="/api/v1/prospects":
            cid=body.get("company_id"); company=data.one("SELECT id FROM companies WHERE organization_id=? AND id=?",(self.org,cid))
            if not company:return self.json({"error":"Company not found"},404)
            ts=data.now(); pid="prospect_"+str(uuid.uuid4())[:8]
            try:
                with data.connect() as db: db.execute("INSERT INTO prospects(id,organization_id,company_id,status,priority,notes,next_action,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(pid,self.org,cid,"NEW",body.get("priority","HIGH"),body.get("notes"),body.get("next_action"),ts,ts))
            except Exception: return self.json({"error":"Prospect already exists"},409)
            data.audit(self.org,"CREATE_PROSPECT","company",cid,{"prospect_id":pid}); return self.json({"id":pid,"status":"NEW"},201)
        if path=='/api/v1/signals/refresh':
            result=BUSINESS_SIGNALS.refresh(self.org,body.get('company_id'))
            with data.connect() as db:data.recalculate_all(db,self.org)
            data.audit(self.org,'REFRESH_BUSINESS_SIGNALS','organization',self.org,{'run_id':result.get('run_id'),'active_signals':result.get('active_signals')});return self.json(result,200 if result.get('status')=='SUCCESS' else 422)
        if path.startswith('/api/v1/companies/') and path.endswith('/people-intelligence'):
            company_id=path.split('/')[-2];result=PEOPLE_ENGINE.analyze(self.org,company_id);BUSINESS_SIGNALS.detect(self.org,company_id)
            with data.connect() as db:data.recalculate_all(db,self.org)
            data.audit(self.org,'PEOPLE_INTELLIGENCE','company',company_id,{'status':result.get('status'),'official_people':result.get('official_people_found'),'profiles':result.get('professional_profiles_found')});return self.json(result,200 if result.get('status')=='SUCCESS' else 422)
        if path.startswith('/api/v1/people/') and path.endswith('/privacy-request'):
            person_id=path.split('/')[-2]
            try:result=PEOPLE_ENGINE.create_privacy_request(self.org,person_id,str(body.get('request_type','')).upper(),body.get('requester_reference'),body.get('notes'))
            except ValueError as exc:return self.json({'error':str(exc)},400)
            data.audit(self.org,'CREATE_PRIVACY_REQUEST','person',person_id,result);return self.json(result,201)
        if path.startswith('/api/v1/companies/') and path.endswith('/seo-audit'):
            company_id=path.split('/')[-2];result=SEO_AUDIT.audit(self.org,company_id)
            with data.connect() as db:data.recalculate_all(db,self.org)
            data.audit(self.org,'SEO_AUDIT','company',company_id,{'status':result.get('status'),'seo_score':result.get('seo_score'),'seo_opportunity':result.get('seo_opportunity')});return self.json(result,200 if result.get('status') in ('SUCCESS','NOT_APPLICABLE') else 422)
        if path.startswith('/api/v1/companies/') and path.endswith('/discover-website'):
            company_id=path.split('/')[-2];result=WEBSITE_DISCOVERY.discover(self.org,company_id)
            if result.get('status')=='FOUND':
                with data.connect() as db:data.recalculate_all(db,self.org)
            data.audit(self.org,'WEBSITE_DISCOVERY','company',company_id,result);return self.json(result,200 if result.get('status') in ('FOUND','NOT_FOUND','NOT_CONFIGURED') else 422)
        if path.startswith('/api/v1/companies/') and path.endswith('/digital-footprint'):
            company_id=path.split('/')[-2];result=DIGITAL_FOOTPRINT.analyze(self.org,company_id)
            with data.connect() as db:data.recalculate_all(db,self.org)
            data.audit(self.org,'DIGITAL_FOOTPRINT_CHECK','company',company_id,{'status':result.get('status'),'digital_score':result.get('digital_score')});return self.json(result,200 if result.get('status')=='SUCCESS' else 422)
        if path=="/api/v1/nace/import":
            result=NACE_IMPORTER.import_official();data.audit(self.org,'IMPORT_OFFICIAL_NACE','nace_version','2.1',result)
            return self.json(result,200 if result.get('status')=='SUCCESS' else 422)
        if path.startswith('/api/v1/resa/documents/') and path.endswith('/store'):
            document_id=path.split('/')[-2];result=PDF_STORAGE.store_document(self.org,document_id)
            data.audit(self.org,'STORE_RESA_PDF','resa_document',document_id,{'status':result.get('status'),'storage_object_id':result.get('storage_object_id')})
            return self.json(result,200 if result.get('status') in ('STORED','DUPLICATE','ALREADY_STORED') else 422)
        if path.startswith('/api/v1/resa/documents/') and path.endswith('/extract'):
            document_id=path.split('/')[-2];result=PDF_EXTRACTION.extract_document(self.org,document_id,bool(body.get('force_ocr',False)))
            data.audit(self.org,'EXTRACT_RESA_PDF','resa_document',document_id,{'status':result.get('status'),'method':result.get('method'),'extraction_id':result.get('extraction_id')})
            return self.json(result,200 if result.get('status') in ('SUCCESS','PARTIAL','ALREADY_EXTRACTED') else 422)
        if path=="/api/v1/resa/analyze":
            source_url=str(body.get('source_url','')).strip()
            try:result=RESA_CONNECTOR.analyze(self.org,source_url,allow_browser=body.get('allow_browser',True))
            except ValueError as exc:return self.json({'error':str(exc),'code':'INVALID_RESA_URL'},400)
            data.audit(self.org,'ANALYZE_RESA','resa_journal',result.get('journal_id'),{'source_url':source_url,'status':result.get('status'),'run_id':result.get('run_id')})
            return self.json(result,200 if result.get('status')=='SUCCESS' else 409)
        if path=="/api/v1/jobs":
            allowed={"RESA_SYNC","NACE_SYNC","DOCUMENT_DOWNLOAD","PDF_EXTRACTION","OCR_PROCESSING","WEBSITE_DISCOVERY","DIGITAL_FOOTPRINT_CHECK","PEOPLE_INTELLIGENCE","SEO_AUDIT","BUSINESS_SIGNAL_REFRESH","OPPORTUNITY_RECALCULATION"}; typ=body.get("job_type")
            if typ not in allowed:return self.json({"error":"Unsupported job type"},400)
            if typ=='BUSINESS_SIGNAL_REFRESH':
                signal_result=BUSINESS_SIGNALS.refresh(self.org,body.get('company_id'));jid="job_"+str(uuid.uuid4())[:8];ok=signal_result.get('status')=='SUCCESS';status='SUCCESS' if ok else 'FAILED';err=signal_result.get('message')
                with data.connect() as db:data.recalculate_all(db,self.org);data.insert_job(db,jid,self.org,typ,status,data.now(),data.now(),signal_result.get('companies_processed',0),err)
                data.audit(self.org,'RUN_JOB','job',jid,{'type':typ,'signal_run_id':signal_result.get('run_id')});return self.json({'id':jid,'status':status,'result':signal_result},201)
            if typ=='PEOPLE_INTELLIGENCE':
                company_id=str(body.get('company_id','')).strip()
                if not company_id:return self.json({'error':'company_id is required'},400)
                people_result=PEOPLE_ENGINE.analyze(self.org,company_id);BUSINESS_SIGNALS.detect(self.org,company_id);jid="job_"+str(uuid.uuid4())[:8];ok=people_result.get('status')=='SUCCESS';status='SUCCESS' if ok else 'FAILED';err=people_result.get('message')
                with data.connect() as db:data.recalculate_all(db,self.org);data.insert_job(db,jid,self.org,typ,status,data.now(),data.now(),people_result.get('official_people_found',0),err)
                data.audit(self.org,'RUN_JOB','job',jid,{'type':typ,'company_id':company_id});return self.json({'id':jid,'status':status,'result':people_result},201)
            if typ=='SEO_AUDIT':
                company_id=str(body.get('company_id','')).strip()
                if not company_id:return self.json({'error':'company_id is required'},400)
                seo_result=SEO_AUDIT.audit(self.org,company_id);jid="job_"+str(uuid.uuid4())[:8];ok=seo_result.get('status') in ('SUCCESS','NOT_APPLICABLE');status='SUCCESS' if ok else 'FAILED';err=seo_result.get('message')
                with data.connect() as db:data.recalculate_all(db,self.org);data.insert_job(db,jid,self.org,typ,status,data.now(),data.now(),1 if ok else 0,err)
                data.audit(self.org,'RUN_JOB','job',jid,{'type':typ,'company_id':company_id});return self.json({'id':jid,'status':status,'result':seo_result},201)
            if typ in ('WEBSITE_DISCOVERY','DIGITAL_FOOTPRINT_CHECK'):
                company_id=str(body.get('company_id','')).strip()
                if not company_id:return self.json({'error':'company_id is required'},400)
                intelligence=WEBSITE_DISCOVERY.discover(self.org,company_id) if typ=='WEBSITE_DISCOVERY' else DIGITAL_FOOTPRINT.analyze(self.org,company_id);jid="job_"+str(uuid.uuid4())[:8];ok=intelligence.get('status') in ('FOUND','NOT_FOUND','NOT_CONFIGURED','SUCCESS');status='SUCCESS' if ok else 'FAILED';err=intelligence.get('message')
                with data.connect() as db:data.recalculate_all(db,self.org);data.insert_job(db,jid,self.org,typ,status,data.now(),data.now(),1 if ok else 0,err)
                data.audit(self.org,'RUN_JOB','job',jid,{'type':typ,'company_id':company_id});return self.json({'id':jid,'status':status,'result':intelligence},201)
            if typ=='NACE_SYNC':
                nace_result=NACE_IMPORTER.import_official();jid="job_"+str(uuid.uuid4())[:8];status='SUCCESS' if nace_result.get('status')=='SUCCESS' else 'FAILED';err=nace_result.get('message')
                with data.connect() as db:data.insert_job(db,jid,self.org,typ,status,data.now(),data.now(),nace_result.get('classes',0),err)
                data.audit(self.org,'RUN_JOB','job',jid,{'type':typ,'nace_run_id':nace_result.get('run_id')});return self.json({'id':jid,'status':status,'result':nace_result},201)
            if typ in ('PDF_EXTRACTION','OCR_PROCESSING'):
                document_id=str(body.get('document_id','')).strip()
                if not document_id:return self.json({'error':'document_id is required'},400)
                extract_result=PDF_EXTRACTION.extract_document(self.org,document_id,force_ocr=(typ=='OCR_PROCESSING'));jid="job_"+str(uuid.uuid4())[:8];status='SUCCESS' if extract_result.get('status') in ('SUCCESS','PARTIAL','ALREADY_EXTRACTED') else 'FAILED';err=extract_result.get('message')
                with data.connect() as db:data.insert_job(db,jid,self.org,typ,status,data.now(),data.now(),extract_result.get('extracted_pages',0),err)
                data.audit(self.org,'RUN_JOB','job',jid,{'type':typ,'document_id':document_id,'extraction_id':extract_result.get('extraction_id')});return self.json({'id':jid,'status':status,'result':extract_result},201)
            if typ=='DOCUMENT_DOWNLOAD':
                document_id=str(body.get('document_id','')).strip()
                if not document_id:return self.json({'error':'document_id is required for DOCUMENT_DOWNLOAD'},400)
                storage_result=PDF_STORAGE.store_document(self.org,document_id);jid="job_"+str(uuid.uuid4())[:8];status='SUCCESS' if storage_result.get('status') in ('STORED','DUPLICATE','ALREADY_STORED') else 'FAILED';err=storage_result.get('message')
                with data.connect() as db:data.insert_job(db,jid,self.org,typ,status,data.now(),data.now(),1 if status=='SUCCESS' else 0,err)
                data.audit(self.org,'RUN_JOB','job',jid,{'type':typ,'document_id':document_id});return self.json({'id':jid,'status':status,'result':storage_result},201)
            if typ=='RESA_SYNC':
                source_url=str(body.get('source_url','')).strip()
                if not source_url:return self.json({'error':'source_url is required for RESA_SYNC'},400)
                try:sync_result=RESA_CONNECTOR.analyze(self.org,source_url,allow_browser=body.get('allow_browser',True))
                except ValueError as exc:return self.json({'error':str(exc)},400)
                jid="job_"+str(uuid.uuid4())[:8];status='SUCCESS' if sync_result.get('status')=='SUCCESS' else 'FAILED';err=sync_result.get('message')
                with data.connect() as db:data.insert_job(db,jid,self.org,typ,status,data.now(),data.now(),sync_result.get('rows_detected',0),err)
                data.audit(self.org,'RUN_JOB','job',jid,{'type':typ,'resa_run_id':sync_result.get('run_id')});return self.json({'id':jid,'status':status,'result':sync_result},201)
            jid="job_"+str(uuid.uuid4())[:8]; status="SUCCESS" if typ=="OPPORTUNITY_RECALCULATION" else "FAILED"; err=None if status=="SUCCESS" else "Connector NOT_CONNECTED — no data was fabricated"
            with data.connect() as db:
                if typ=="OPPORTUNITY_RECALCULATION": data.recalculate_all(db,self.org)
                data.insert_job(db,jid,self.org,typ,status,data.now(),data.now(),0,err)
            data.audit(self.org,"RUN_JOB","job",jid,{"type":typ,"status":status}); return self.json({"id":jid,"status":status,"error":err},201)
        if path=="/api/v1/organization/members/role":
            ctx=self.auth_context
            if ctx['role'] not in ('OWNER','ADMIN'):return self.json({'error':'Insufficient permission'},403)
            target=str(body.get('user_id',''));role=str(body.get('role','')).upper()
            if role not in ('OWNER','ADMIN','MEMBER'):return self.json({'error':'Invalid role'},400)
            current=data.one("SELECT role FROM organization_members WHERE organization_id=? AND user_id=?",(self.org,target))
            if not current:return self.json({'error':'Member not found'},404)
            if ctx['role']=='ADMIN' and (current['role']=='OWNER' or role=='OWNER'):return self.json({'error':'Only an owner can manage owner roles'},403)
            if current['role']=='OWNER' and role!='OWNER':
                owners=data.one("SELECT count(*) count FROM organization_members WHERE organization_id=? AND role='OWNER'",(self.org,))['count']
                if owners<=1:return self.json({'error':'The organization must keep at least one owner'},409)
            with data.connect() as db:db.execute("UPDATE organization_members SET role=? WHERE organization_id=? AND user_id=?",(role,self.org,target))
            data.audit(self.org,'UPDATE_MEMBER_ROLE','user',target,{'role':role});return self.json({'status':'SUCCESS','role':role})
        if path=="/api/v1/reports":
            typ=body.get('report_type','OPPORTUNITY'); fmt=body.get('format','CSV'); rid='report_'+str(uuid.uuid4())[:8]; ts=data.now()
            with data.connect() as db: db.execute("INSERT INTO reports VALUES(?,?,?,?,?,?,?,?,?)",(rid,self.org,typ,f"{typ.title()} intelligence report","SUCCESS",fmt,body.get('entity_id'),ts,ts))
            data.audit(self.org,"GENERATE_REPORT","report",rid,{"format":fmt}); return self.json({"id":rid,"status":"SUCCESS"},201)
        if path=="/api/v1/settings/scoring":
            weights=body.get('weights',{}); allowed={'freshness','niche','digital_gap','seo_opportunity','local_presence','decision_maker','commercial_potential'}
            if set(weights)-allowed or any(not isinstance(v,int) or v<0 or v>100 for v in weights.values()) or sum(weights.values())!=100: return self.json({"error":"Weights must be integers from 0 to 100 and total 100"},400)
            with data.connect() as db:
                for f,w in weights.items(): db.execute("UPDATE scoring_weights SET weight=?,updated_at=? WHERE organization_id=? AND factor=?",(w,data.now(),self.org,f))
                data.recalculate_all(db,self.org)
            data.audit(self.org,"UPDATE_SCORING","organization",self.org,weights); return self.json({"status":"SUCCESS","weights":weights})
        if path=="/api/v1/import/preview":
            rows=body.get('rows',[])
            if not isinstance(rows,list) or len(rows)>1000:return self.json({"error":"Invalid import or preview limit exceeded"},400)
            required=['company_name']; preview=[]
            for i,r in enumerate(rows):
                errors=[f"Missing {k}" for k in required if not str(r.get(k,'')).strip()]
                duplicate=bool(r.get('rcs_number') and data.one("SELECT id FROM companies WHERE organization_id=? AND rcs_number=?",(self.org,r.get('rcs_number'))))
                preview.append({'row':i+1,'valid':not errors and not duplicate,'duplicate':duplicate,'errors':errors,'data':r})
            return self.json({'total':len(rows),'valid':sum(1 for x in preview if x['valid']),'items':preview})
        return self.json({"error":"Not found"},404)
    def auth_post(self,path,body):
        if not AUTH_ACTIVE:return self.json({'error':'Supabase Auth requires both Supabase credentials and PostgreSQL','code':'AUTH_NOT_CONFIGURED'},503)
        try:
            if path.endswith('/signup'):
                email=str(body.get('email','')).strip().lower();password=str(body.get('password',''));name=str(body.get('display_name','')).strip()
                if '@' not in email or len(password)<8:return self.json({'error':'Valid email and password of at least 8 characters required'},400)
                result=auth.signup(email,password,name)
                session=result.get('session') or (result if result.get('access_token') else None)
                headers=[('Set-Cookie',v) for v in auth.cookie_headers(session)] if session else []
                if session:
                    auth_user=result.get('user') or auth.user(session['access_token'])
                    data.set_tenant_context(None,auth_user.get('id'))
                    workspace=auth.ensure_workspace(auth_user,data.connect)
                    data.set_tenant_context(workspace['organization_id'],workspace['user_id'])
                return self.json({'status':'SIGNED_UP','confirmation_required':not bool(session),'message':'Check your email to confirm your account.' if not session else 'Account created.'},201,headers)
            if path.endswith('/login'):
                session=auth.login(str(body.get('email','')).strip().lower(),str(body.get('password','')))
                auth_user=session.get('user') or auth.user(session['access_token'])
                data.set_tenant_context(None,auth_user.get('id'))
                ctx=auth.ensure_workspace(auth_user,data.connect)
                data.set_tenant_context(ctx['organization_id'],ctx['user_id'])
                headers=[('Set-Cookie',v) for v in auth.cookie_headers(session)]
                return self.json({'status':'AUTHENTICATED','user':{'name':ctx['display_name'],'role':ctx['role']},'organization':{'id':ctx['organization_id'],'name':ctx['organization_name']}},200,headers)
            if path.endswith('/recover'):
                email=str(body.get('email','')).strip().lower()
                if '@' not in email:return self.json({'error':'Valid email required'},400)
                auth.recover(email);return self.json({'status':'EMAIL_SENT','message':'If this account exists, a reset email has been sent.'})
            if path.endswith('/adopt-session'):
                access=str(body.get('access_token',''));refresh_token=str(body.get('refresh_token',''))
                verified=auth.user(access)
                data.set_tenant_context(None,verified.get('id'))
                ctx=auth.ensure_workspace(verified,data.connect)
                data.set_tenant_context(ctx['organization_id'],ctx['user_id'])
                session={'access_token':access,'refresh_token':refresh_token,'expires_in':int(body.get('expires_in',3600))}
                return self.json({'status':'AUTHENTICATED'},200,[('Set-Cookie',v) for v in auth.cookie_headers(session)])
            if path.endswith('/update-password'):
                cookies=auth.parse_cookies(self.headers.get('Cookie'))
                if not cookies.get(auth.CSRF_COOKIE) or self.headers.get('X-CSRF-Token')!=cookies.get(auth.CSRF_COOKIE):return self.json({'error':'Invalid CSRF token','code':'CSRF_FAILED'},403)
                session=auth.get_session(self.headers.get('Cookie'))
                if not session:raise auth.AuthError('Authentication required',401,'AUTH_REQUIRED')
                password=str(body.get('password',''))
                if len(password)<8:return self.json({'error':'Password must contain at least 8 characters'},400)
                auth.update_password(session['access_token'],password);return self.json({'status':'PASSWORD_UPDATED'})
            if path.endswith('/logout'):
                session=auth.get_session(self.headers.get('Cookie'))
                if session:
                    try:auth.logout(session['access_token'])
                    except auth.AuthError:pass
                return self.json({'status':'SIGNED_OUT'},200,[('Set-Cookie',v) for v in auth.cookie_headers(clear=True)])
            return self.json({'error':'Not found'},404)
        except auth.AuthError as e:return self.json({'error':str(e),'code':e.code},e.status)
    def dashboard(self):
        items=data.list_companies(self.org,{})
        def n(pred): return sum(1 for x in items if pred(x))
        today={"new_companies":n(lambda x:(x.get("creation_date") or "") >= __import__('datetime').date.today().isoformat()),"new_opportunities":n(lambda x:x["opportunity_score"]>=75),"high_priority":n(lambda x:x["opportunity_score"]>=90),"without_website":n(lambda x:x["website_status"]=="NOT_FOUND"),"weak_seo":n(lambda x:x.get("seo_score") is not None and x["seo_score"]<50),"without_google":n(lambda x:x["google_status"]=="NOT_FOUND"),"decision_makers":n(lambda x:x["decision_maker_status"]=="FOUND")}
        def group(field):
            out={}
            for x in items: out[x.get(field) or "Unknown"]=out.get(x.get(field) or "Unknown",0)+1
            return [{"label":k,"value":v} for k,v in sorted(out.items(),key=lambda z:-z[1])]
        return self.json({"today":today,"top":items[:10],"analytics":{"category":group("category"),"municipality":group("municipality"),"level":group("opportunity_level"),"nace":group("primary_nace_code")},"demo":bool(self.auth_context.get('demo'))})
    def filters(self):
        fields=["canton","municipality","primary_nace_code","category","niche","website_status"]
        result={}
        for f in fields: result[f]=[r["value"] for r in data.rows(f"SELECT DISTINCT {f} value FROM companies WHERE organization_id=? AND {f} IS NOT NULL ORDER BY {f}",(self.org,))]
        return self.json(result)
    def export_csv(self,q):
        items=data.list_companies(self.org,q); buf=io.StringIO(); cols=["company_name","rcs_number","creation_date","primary_nace_code","category","niche","municipality","website_status","digital_score","seo_score","opportunity_score","recommended_action","source_status"]
        w=csv.DictWriter(buf,fieldnames=cols,extrasaction="ignore"); w.writeheader(); w.writerows(items); raw=buf.getvalue().encode("utf-8-sig")
        self.send_response(200);self.send_header("Content-Type","text/csv; charset=utf-8");self.send_header("Content-Disposition","attachment; filename=nacelux-companies.csv");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
    def static(self,path):
        rel="index.html" if path in ("/","") else path.lstrip("/"); file=(FRONTEND/rel).resolve()
        if FRONTEND.resolve() not in file.parents or not file.is_file(): file=FRONTEND/"index.html"
        raw=file.read_bytes(); self.send_response(200); self.send_header("Content-Type",mimetypes.guess_type(str(file))[0] or "application/octet-stream");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)

if __name__=="__main__":
    defer_db_init=os.environ.get('NACELUX_SKIP_DB_INIT','false').lower() in ('1','true','yes')
    if defer_db_init:
        print('[db] Initialization deferred to startup supervisor; liveness is available.')
    else:
        data.init_db()
    print(f"NACELUX running on http://0.0.0.0:{PORT}")
    ThreadingHTTPServer(("0.0.0.0",PORT),API).serve_forever()
