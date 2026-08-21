import json, os, sqlite3, uuid
from datetime import datetime, timedelta
from pathlib import Path
import config
from scoring import calculate
from db_adapter import connect, BACKEND, IS_POSTGRES, ROOT

ORG_ID = "org_demo_lux"

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS organizations(id TEXT PRIMARY KEY,name TEXT NOT NULL,slug TEXT UNIQUE,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,display_name TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS organization_members(organization_id TEXT,user_id TEXT,role TEXT CHECK(role IN('OWNER','ADMIN','MEMBER')),PRIMARY KEY(organization_id,user_id));
CREATE TABLE IF NOT EXISTS companies(
 id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,company_name TEXT NOT NULL,trade_name TEXT,legal_form TEXT,rcs_number TEXT,vat_number TEXT,
 creation_date TEXT,status TEXT,capital REAL,business_object TEXT,description TEXT,primary_nace_code TEXT,secondary_nace_codes TEXT,
 category TEXT,niche TEXT,subniche TEXT,website TEXT,email TEXT,phone TEXT,country TEXT DEFAULT 'LU',canton TEXT,municipality TEXT,
 locality TEXT,postal_code TEXT,street TEXT,street_number TEXT,address_complement TEXT,latitude REAL,longitude REAL,
 website_status TEXT DEFAULT 'NOT_CHECKED',digital_score INTEGER,seo_score INTEGER,seo_opportunity INTEGER,google_status TEXT DEFAULT 'NOT_CHECKED',
 decision_maker_status TEXT DEFAULT 'UNKNOWN',niche_attractiveness INTEGER DEFAULT 50,commercial_potential INTEGER DEFAULT 50,
 source_status TEXT DEFAULT 'UNKNOWN',source_name TEXT,source_url TEXT,is_demo INTEGER DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 UNIQUE(organization_id,rcs_number));
CREATE INDEX IF NOT EXISTS idx_company_tenant ON companies(organization_id);
CREATE INDEX IF NOT EXISTS idx_company_geo ON companies(organization_id,municipality,postal_code);
CREATE INDEX IF NOT EXISTS idx_company_nace ON companies(organization_id,primary_nace_code);
CREATE INDEX IF NOT EXISTS idx_company_created ON companies(organization_id,creation_date);
CREATE TABLE IF NOT EXISTS business_signals(id TEXT PRIMARY KEY,organization_id TEXT,company_id TEXT,signal_type TEXT,signal_value TEXT,confidence REAL,source TEXT,detected_at TEXT,status TEXT DEFAULT 'ACTIVE',first_detected_at TEXT,last_seen_at TEXT,evidence TEXT DEFAULT '{}',severity TEXT,rule_version TEXT,explanation TEXT,expires_at TEXT,data_quality TEXT DEFAULT 'UNKNOWN',UNIQUE(organization_id,company_id,signal_type));
CREATE TABLE IF NOT EXISTS business_signal_runs(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,company_id TEXT,status TEXT NOT NULL,rule_version TEXT NOT NULL,started_at TEXT NOT NULL,completed_at TEXT,companies_processed INTEGER DEFAULT 0,active_signals INTEGER DEFAULT 0,activated INTEGER DEFAULT 0,deactivated INTEGER DEFAULT 0,error_code TEXT,error_message TEXT,metadata TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS business_signal_definitions(signal_type TEXT PRIMARY KEY,label TEXT NOT NULL,description TEXT NOT NULL,severity TEXT NOT NULL,required_evidence TEXT NOT NULL,is_active INTEGER DEFAULT 1,rule_version TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS opportunity_scores(id TEXT PRIMARY KEY,organization_id TEXT,company_id TEXT,score INTEGER,level TEXT,breakdown TEXT,recommended_action TEXT,calculated_at TEXT);
CREATE INDEX IF NOT EXISTS idx_opp_score ON opportunity_scores(organization_id,score DESC);
CREATE TABLE IF NOT EXISTS prospects(id TEXT PRIMARY KEY,organization_id TEXT,company_id TEXT,status TEXT,priority TEXT,owner TEXT,assigned_to TEXT,notes TEXT,next_action TEXT,next_action_date TEXT,last_contacted_at TEXT,created_at TEXT,updated_at TEXT,UNIQUE(organization_id,company_id));
CREATE TABLE IF NOT EXISTS data_sources(id TEXT PRIMARY KEY,organization_id TEXT,name TEXT,source_type TEXT,base_url TEXT,status TEXT,last_run_at TEXT,records_count INTEGER DEFAULT 0,note TEXT);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,organization_id TEXT,job_type TEXT,status TEXT,started_at TEXT,finished_at TEXT,records_processed INTEGER DEFAULT 0,error TEXT,payload TEXT DEFAULT '{}',attempt INTEGER DEFAULT 0,schedule TEXT);
CREATE TABLE IF NOT EXISTS data_lineage(id TEXT PRIMARY KEY,organization_id TEXT,entity_type TEXT,entity_id TEXT,field_name TEXT,source_id TEXT,source_url TEXT,document_id TEXT,retrieved_at TEXT,confidence REAL,method TEXT);
CREATE TABLE IF NOT EXISTS audit_logs(id TEXT PRIMARY KEY,organization_id TEXT,user_id TEXT,action TEXT,entity_type TEXT,entity_id TEXT,metadata TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS nace_codes(id TEXT PRIMARY KEY,version TEXT NOT NULL,code TEXT NOT NULL,level TEXT NOT NULL,title_fr TEXT,title_de TEXT,title_en TEXT,parent_code TEXT,includes_text TEXT,excludes_text TEXT,source_status TEXT,source_url TEXT,is_demo INTEGER DEFAULT 1,UNIQUE(version,code));
CREATE TABLE IF NOT EXISTS taxonomy_nodes(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,node_type TEXT NOT NULL,parent_id TEXT,name TEXT NOT NULL,slug TEXT,attractiveness INTEGER DEFAULT 50,is_active INTEGER DEFAULT 1,UNIQUE(organization_id,node_type,slug));
CREATE TABLE IF NOT EXISTS people(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,display_name TEXT NOT NULL,job_title TEXT,company_id TEXT,profile_url TEXT,source_type TEXT,match_status TEXT,confidence REAL,is_demo INTEGER DEFAULT 1,created_at TEXT,name_normalized TEXT,official_role TEXT,source_url TEXT,source_document_id TEXT,source_extraction_id TEXT,checked_at TEXT,privacy_status TEXT DEFAULT 'ACTIVE',retention_until TEXT,UNIQUE(organization_id,company_id,name_normalized));
CREATE TABLE IF NOT EXISTS people_engine_runs(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,company_id TEXT NOT NULL,status TEXT NOT NULL,started_at TEXT NOT NULL,completed_at TEXT,official_people_found INTEGER DEFAULT 0,professional_profiles_found INTEGER DEFAULT 0,provider TEXT,error_code TEXT,error_message TEXT,metadata TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS people_evidence(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,person_id TEXT NOT NULL,evidence_type TEXT NOT NULL,source_url TEXT NOT NULL,source_document_id TEXT,source_extraction_id TEXT,excerpt TEXT,confidence REAL NOT NULL,method TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(person_id,evidence_type,source_url));
CREATE TABLE IF NOT EXISTS professional_profiles_public(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,person_id TEXT NOT NULL,company_id TEXT NOT NULL,platform TEXT NOT NULL,profile_url TEXT NOT NULL,public_title TEXT,match_status TEXT NOT NULL,match_confidence REAL NOT NULL,evidence TEXT DEFAULT '{}',source_provider TEXT NOT NULL,checked_at TEXT NOT NULL,UNIQUE(organization_id,platform,profile_url));
CREATE TABLE IF NOT EXISTS privacy_requests(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,person_id TEXT,request_type TEXT NOT NULL,status TEXT NOT NULL,requester_reference TEXT,notes TEXT,created_at TEXT NOT NULL,resolved_at TEXT);
CREATE TABLE IF NOT EXISTS digital_checks(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,company_id TEXT NOT NULL,channel TEXT,status TEXT,source_url TEXT,confidence REAL,checked_at TEXT,details TEXT,source_provider TEXT,evidence TEXT DEFAULT '{}',error_code TEXT,check_method TEXT,UNIQUE(organization_id,company_id,channel));
CREATE TABLE IF NOT EXISTS website_discovery_runs(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,company_id TEXT NOT NULL,status TEXT NOT NULL,provider TEXT,query_text TEXT,started_at TEXT NOT NULL,completed_at TEXT,candidates_found INTEGER DEFAULT 0,selected_candidate_id TEXT,error_code TEXT,error_message TEXT,metadata TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS website_candidates(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,company_id TEXT NOT NULL,run_id TEXT NOT NULL,url TEXT NOT NULL,canonical_url TEXT NOT NULL,domain TEXT NOT NULL,title TEXT,snippet TEXT,confidence REAL NOT NULL,match_status TEXT NOT NULL,evidence TEXT DEFAULT '{}',discovery_source TEXT NOT NULL,checked_at TEXT NOT NULL,UNIQUE(organization_id,company_id,canonical_url));
CREATE TABLE IF NOT EXISTS google_business_profiles(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,company_id TEXT NOT NULL,place_id TEXT,business_name TEXT,formatted_address TEXT,primary_type TEXT,website_url TEXT,phone TEXT,rating REAL,review_count INTEGER,status TEXT NOT NULL,source_url TEXT,checked_at TEXT NOT NULL,raw_data TEXT DEFAULT '{}',UNIQUE(organization_id,company_id));
CREATE TABLE IF NOT EXISTS seo_audits(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,company_id TEXT NOT NULL,url TEXT,status TEXT,seo_score INTEGER,opportunity_score INTEGER,findings TEXT,checked_at TEXT,final_url TEXT,http_status INTEGER,https_status TEXT,title TEXT,title_length INTEGER,h1_count INTEGER,h1_text TEXT,meta_description TEXT,meta_length INTEGER,mobile_status TEXT,performance_score INTEGER,response_ms INTEGER,page_size_bytes INTEGER,canonical_url TEXT,robots_meta TEXT,audit_method TEXT,error_code TEXT,error_message TEXT,UNIQUE(organization_id,company_id));
CREATE TABLE IF NOT EXISTS resa_publications(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,publication_number TEXT,publication_date TEXT,entry_type TEXT,company_name TEXT,rcs_number TEXT,source_url TEXT,document_url TEXT,download_status TEXT,extraction_status TEXT,change_status TEXT,source_status TEXT,is_demo INTEGER DEFAULT 1,created_at TEXT);
CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,report_type TEXT,title TEXT,status TEXT,format TEXT,entity_id TEXT,created_at TEXT,completed_at TEXT);
CREATE TABLE IF NOT EXISTS territories(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,name TEXT NOT NULL,description TEXT,municipalities TEXT,center_lat REAL,center_lng REAL,radius_km REAL,created_at TEXT);
CREATE TABLE IF NOT EXISTS scoring_weights(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,factor TEXT NOT NULL,weight INTEGER NOT NULL,updated_at TEXT,UNIQUE(organization_id,factor));
CREATE TABLE IF NOT EXISTS resa_journals(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,journal_key TEXT NOT NULL,publication_date TEXT,sequence_number TEXT,source_url TEXT NOT NULL,source_status TEXT DEFAULT 'OFFICIAL',first_seen_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,content_hash TEXT,UNIQUE(organization_id,journal_key));
CREATE TABLE IF NOT EXISTS resa_entries(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,journal_id TEXT NOT NULL,natural_key TEXT NOT NULL,row_index INTEGER NOT NULL,publication_number TEXT,entry_type TEXT,company_name TEXT,rcs_number TEXT,row_text TEXT NOT NULL,source_url TEXT NOT NULL,change_status TEXT DEFAULT 'NEW',content_hash TEXT NOT NULL,first_seen_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,UNIQUE(organization_id,journal_id,natural_key));
CREATE TABLE IF NOT EXISTS resa_documents(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,journal_id TEXT NOT NULL,entry_id TEXT,document_url TEXT NOT NULL,canonical_url TEXT NOT NULL,document_type TEXT DEFAULT 'PDF',link_text TEXT,source_url TEXT NOT NULL,download_status TEXT DEFAULT 'NOT_DOWNLOADED',extraction_status TEXT DEFAULT 'NOT_STARTED',checksum TEXT,first_seen_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,storage_object_id TEXT,storage_provider TEXT,storage_bucket TEXT,storage_key TEXT,mime_type TEXT,size_bytes INTEGER,downloaded_at TEXT,http_status INTEGER,last_error TEXT,UNIQUE(organization_id,canonical_url));
CREATE TABLE IF NOT EXISTS storage_objects(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,provider TEXT NOT NULL,bucket TEXT NOT NULL,object_key TEXT NOT NULL,checksum_sha256 TEXT NOT NULL,size_bytes INTEGER NOT NULL,mime_type TEXT NOT NULL,original_filename TEXT,source_url TEXT,local_reference TEXT,created_at TEXT NOT NULL,verified_at TEXT,UNIQUE(organization_id,checksum_sha256),UNIQUE(provider,bucket,object_key));
CREATE TABLE IF NOT EXISTS document_extractions(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,document_id TEXT NOT NULL,storage_object_id TEXT NOT NULL,source_checksum TEXT NOT NULL,status TEXT NOT NULL,extraction_method TEXT,text_content TEXT,text_hash TEXT,page_count INTEGER,extracted_pages INTEGER DEFAULT 0,ocr_pages INTEGER DEFAULT 0,char_count INTEGER DEFAULT 0,quality_score REAL,ocr_language TEXT,engine_version TEXT NOT NULL,started_at TEXT NOT NULL,completed_at TEXT,error_code TEXT,error_message TEXT,UNIQUE(organization_id,document_id,source_checksum,engine_version));
CREATE TABLE IF NOT EXISTS document_page_extractions(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,extraction_id TEXT NOT NULL,document_id TEXT NOT NULL,page_number INTEGER NOT NULL,extraction_method TEXT NOT NULL,text_content TEXT NOT NULL,char_count INTEGER NOT NULL,confidence REAL,quality_score REAL,created_at TEXT NOT NULL,UNIQUE(extraction_id,page_number));
CREATE TABLE IF NOT EXISTS nace_versions_official(id TEXT PRIMARY KEY,version_code TEXT NOT NULL UNIQUE,title TEXT NOT NULL,status TEXT NOT NULL,valid_from TEXT,source_url TEXT NOT NULL,source_checksum TEXT,source_format TEXT NOT NULL,retrieved_at TEXT,activated_at TEXT,item_count INTEGER DEFAULT 0,metadata TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS nace_items_official(id TEXT PRIMARY KEY,version_id TEXT NOT NULL,code TEXT NOT NULL,level TEXT NOT NULL,parent_code TEXT,concept_uri TEXT NOT NULL,sort_order INTEGER,is_current INTEGER DEFAULT 1,source_url TEXT NOT NULL,retrieved_at TEXT NOT NULL,UNIQUE(version_id,code));
CREATE TABLE IF NOT EXISTS nace_labels_official(id TEXT PRIMARY KEY,item_id TEXT NOT NULL,language TEXT NOT NULL,label_type TEXT NOT NULL,label TEXT NOT NULL,source_url TEXT NOT NULL,retrieved_at TEXT NOT NULL,UNIQUE(item_id,language,label_type));
CREATE TABLE IF NOT EXISTS nace_notes_official(id TEXT PRIMARY KEY,item_id TEXT NOT NULL,note_type TEXT NOT NULL,language TEXT NOT NULL,note_text TEXT NOT NULL,note_uri TEXT,source_url TEXT NOT NULL,retrieved_at TEXT NOT NULL,UNIQUE(item_id,note_type,language,note_text));
CREATE TABLE IF NOT EXISTS nace_correspondences_official(id TEXT PRIMARY KEY,source_version TEXT NOT NULL,target_version TEXT NOT NULL,source_code TEXT NOT NULL,target_code TEXT NOT NULL,relationship TEXT,mapping_uri TEXT NOT NULL,source_url TEXT NOT NULL,retrieved_at TEXT NOT NULL,UNIQUE(source_version,target_version,source_code,target_code,mapping_uri));
CREATE TABLE IF NOT EXISTS nace_import_runs(id TEXT PRIMARY KEY,version_code TEXT NOT NULL,status TEXT NOT NULL,source_url TEXT NOT NULL,source_checksum TEXT,started_at TEXT NOT NULL,completed_at TEXT,sections INTEGER DEFAULT 0,divisions INTEGER DEFAULT 0,groups_count INTEGER DEFAULT 0,classes INTEGER DEFAULT 0,labels INTEGER DEFAULT 0,notes INTEGER DEFAULT 0,correspondences INTEGER DEFAULT 0,error_code TEXT,error_message TEXT,metadata TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS resa_sync_runs(id TEXT PRIMARY KEY,organization_id TEXT NOT NULL,journal_id TEXT,source_url TEXT NOT NULL,status TEXT NOT NULL,fetch_method TEXT,started_at TEXT NOT NULL,finished_at TEXT,rows_detected INTEGER DEFAULT 0,documents_detected INTEGER DEFAULT 0,new_entries INTEGER DEFAULT 0,updated_entries INTEGER DEFAULT 0,unchanged_entries INTEGER DEFAULT 0,duplicate_entries INTEGER DEFAULT 0,robots_status TEXT,captcha_status TEXT,error_code TEXT,error_message TEXT,snapshot_hash TEXT,metadata TEXT DEFAULT '{}');
"""

DEMO_COMPANIES = [
 ("demo_01","Aster Digital Sàrl","B299001","Sàrl",12,"Luxembourg","Esch-sur-Alzette","Esch-sur-Alzette","L-4010","62.10","Technology","Software Development","B2B SaaS",None,"NOT_FOUND",12,None,88,"NOT_FOUND","FOUND",95,90),
 ("demo_02","Nordlicht Conseil Sàrl-S","B299002","Sàrl-S",24,"Luxembourg","Luxembourg","Luxembourg","L-1611","70.20","Professional Services","Business Consulting","Strategy","https://example.invalid","FOUND",51,42,79,"FOUND","FOUND",76,72),
 ("demo_03","Minett Atelier Sàrl","B299003","Sàrl",41,"Esch-sur-Alzette","Differdange","Differdange","L-4501","74.12","Creative","Graphic Design","Brand Identity",None,"NOT_FOUND",18,None,70,"NOT_FOUND","UNKNOWN",82,74),
 ("demo_04","Moselle Habitat S.A.","B299004","S.A.",78,"Remich","Remich","Remich","L-5550","68.31","Real Estate","Real Estate Agency","Residential","https://example.invalid","FOUND",63,56,62,"FOUND","FOUND",70,85),
 ("demo_05","Éislek Green Services Sàrl","B299005","Sàrl",130,"Diekirch","Clervaux","Clervaux","L-9701","81.30","Home & Local Services","Landscape Services","Sustainable Landscaping",None,"NOT_FOUND",10,None,55,"NOT_FOUND","POSSIBLE",71,65),
 ("demo_06","Alzette Finance Partners Sàrl","B299006","Sàrl",220,"Luxembourg","Strassen","Strassen","L-8009","66.19","Financial Services","Financial Consulting","Corporate Finance","https://example.invalid","FOUND",82,78,31,"FOUND","FOUND",88,92),
]

def now(): return datetime.utcnow().replace(microsecond=0).isoformat()+"Z"

def init_db():
    if IS_POSTGRES:
        from migrations import run_migrations, migrate_sqlite_data, connection_test
        # Production startup never mutates the schema unless explicitly enabled.
        if os.getenv('AUTO_MIGRATE','false').lower() in ('1','true','yes'):
            run_migrations()
            if os.getenv('MIGRATE_SQLITE_DATA','false').lower() in ('1','true','yes'):
                migrate_sqlite_data()
        else:
            connection_test()
        return
    with connect() as db:
        db.executescript(SCHEMA)
        # Additive local-development migration mirroring PostgreSQL 0004.
        existing={r['name'] for r in db.execute("PRAGMA table_info(resa_documents)")}
        for name,kind in {'storage_object_id':'TEXT','storage_provider':'TEXT','storage_bucket':'TEXT','storage_key':'TEXT','mime_type':'TEXT','size_bytes':'INTEGER','downloaded_at':'TEXT','http_status':'INTEGER','last_error':'TEXT'}.items():
            if name not in existing:db.execute(f'ALTER TABLE resa_documents ADD COLUMN {name} {kind}')
        digital_existing={r['name'] for r in db.execute("PRAGMA table_info(digital_checks)")}
        for name,kind in {'source_provider':'TEXT','evidence':"TEXT DEFAULT '{}'",'error_code':'TEXT','check_method':'TEXT'}.items():
            if name not in digital_existing:db.execute(f'ALTER TABLE digital_checks ADD COLUMN {name} {kind}')
        seo_existing={r['name'] for r in db.execute("PRAGMA table_info(seo_audits)")}
        for name,kind in {'final_url':'TEXT','http_status':'INTEGER','https_status':'TEXT','title':'TEXT','title_length':'INTEGER','h1_count':'INTEGER','h1_text':'TEXT','meta_description':'TEXT','meta_length':'INTEGER','mobile_status':'TEXT','performance_score':'INTEGER','response_ms':'INTEGER','page_size_bytes':'INTEGER','canonical_url':'TEXT','robots_meta':'TEXT','audit_method':'TEXT','error_code':'TEXT','error_message':'TEXT'}.items():
            if name not in seo_existing:db.execute(f'ALTER TABLE seo_audits ADD COLUMN {name} {kind}')
        signal_existing={r['name'] for r in db.execute("PRAGMA table_info(business_signals)")}
        for name,kind in {'status':"TEXT DEFAULT 'ACTIVE'",'first_detected_at':'TEXT','last_seen_at':'TEXT','evidence':"TEXT DEFAULT '{}'",'severity':'TEXT','rule_version':'TEXT','explanation':'TEXT','expires_at':'TEXT','data_quality':"TEXT DEFAULT 'UNKNOWN'"}.items():
            if name not in signal_existing:db.execute(f'ALTER TABLE business_signals ADD COLUMN {name} {kind}')
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_business_signal_unique ON business_signals(organization_id,company_id,signal_type)")
        jobs_existing={r['name'] for r in db.execute("PRAGMA table_info(jobs)")}
        for name,kind in {'payload':"TEXT DEFAULT '{}'",'attempt':'INTEGER DEFAULT 0','schedule':'TEXT'}.items():
            if name not in jobs_existing:db.execute(f'ALTER TABLE jobs ADD COLUMN {name} {kind}')
        people_existing={r['name'] for r in db.execute("PRAGMA table_info(people)")}
        for name,kind in {'name_normalized':'TEXT','official_role':'TEXT','source_url':'TEXT','source_document_id':'TEXT','source_extraction_id':'TEXT','checked_at':'TEXT','privacy_status':"TEXT DEFAULT 'ACTIVE'",'retention_until':'TEXT'}.items():
            if name not in people_existing:db.execute(f'ALTER TABLE people ADD COLUMN {name} {kind}')
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_people_company_name ON people(organization_id,company_id,name_normalized) WHERE name_normalized IS NOT NULL")
        ts=now(); db.execute("INSERT OR IGNORE INTO organizations VALUES(?,?,?,?)",(ORG_ID,"NACELUX Demo Workspace","nacelux-demo",ts))
        db.execute("INSERT OR IGNORE INTO users VALUES(?,?,?,?)",("user_demo_owner","demo@nacelux.local","Demo Owner",ts))
        db.execute("INSERT OR IGNORE INTO organization_members VALUES(?,?,?)",(ORG_ID,"user_demo_owner","OWNER"))
        if db.execute("SELECT count(*) FROM companies WHERE organization_id=?",(ORG_ID,)).fetchone()[0]==0:
            for r in DEMO_COMPANIES:
                cid,name,rcs,form,days,canton,muni,locality,postal,nace,cat,niche,sub,web,ws,ds,seo,seoop,google,dm,attr,potential=r
                created=(datetime.utcnow()-timedelta(days=days)).date().isoformat()
                db.execute("""INSERT INTO companies(id,organization_id,company_name,legal_form,rcs_number,creation_date,status,business_object,primary_nace_code,category,niche,subniche,website,canton,municipality,locality,postal_code,website_status,digital_score,seo_score,seo_opportunity,google_status,decision_maker_status,niche_attractiveness,commercial_potential,source_status,source_name,is_demo,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cid,ORG_ID,name,form,rcs,created,"ACTIVE","Demonstration record — not sourced from a registry.",nace,cat,niche,sub,web,canton,muni,locality,postal,ws,ds,seo,seoop,google,dm,attr,potential,"DEMO","NACELUX demo seed",1,ts,ts))
        sources=[("src_lbr","LBR / RESA","OFFICIAL","https://www.lbr.lu/","NOT_CONNECTED","No undocumented API assumed. Compliance review required."),("src_nace","Eurostat NACE Rev. 2.1","OFFICIAL","https://ec.europa.eu/eurostat/web/nace","NOT_CONNECTED","Official source identified; import endpoint not configured."),("src_web","Website analysis","PUBLIC_WEB",None,"READY","On-demand analyzer boundary; no checks run on demo data.")]
        for s in sources: db.execute("INSERT OR IGNORE INTO data_sources(id,organization_id,name,source_type,base_url,status,note) VALUES(?,?,?,?,?,?,?)",(s[0],ORG_ID,*s[1:]))
        # Demonstration taxonomy: explicitly non-official until a verified Eurostat import runs.
        nace=[('62.10','CLASS','Programmation informatique','Programmierungstätigkeiten','Computer programming activities','62'),('70.20','CLASS','Conseil pour les affaires','Unternehmensberatung','Business and management consultancy','70'),('74.12','CLASS','Activités de design graphique','Grafikdesign','Graphic design activities','74'),('68.31','CLASS','Activités des agences immobilières','Immobilienvermittlung','Real estate agency activities','68'),('81.30','CLASS','Services d’aménagement paysager','Garten- und Landschaftsbau','Landscape service activities','81'),('66.19','CLASS','Activités auxiliaires des services financiers','Sonstige Finanzdienstleistungen','Other financial service support activities','66')]
        for code,level,fr,de,en,parent in nace: db.execute("INSERT OR IGNORE INTO nace_codes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",('nace_'+code.replace('.','_'),'2.1',code,level,fr,de,en,parent,'Demonstration label only',None,'DEMO','https://ec.europa.eu/eurostat/web/nace',1))
        taxonomy=[('cat_tech','CATEGORY',None,'Technology','technology',90),('cat_prof','CATEGORY',None,'Professional Services','professional-services',76),('cat_creative','CATEGORY',None,'Creative','creative',82),('cat_real','CATEGORY',None,'Real Estate','real-estate',84),('cat_local','CATEGORY',None,'Home & Local Services','local-services',70),('cat_fin','CATEGORY',None,'Financial Services','financial-services',88),('niche_software','NICHE','cat_tech','Software Development','software-development',95),('niche_consult','NICHE','cat_prof','Business Consulting','business-consulting',76),('niche_design','NICHE','cat_creative','Graphic Design','graphic-design',82),('niche_agency','NICHE','cat_real','Real Estate Agency','real-estate-agency',84),('niche_land','NICHE','cat_local','Landscape Services','landscape-services',71),('niche_fin','NICHE','cat_fin','Financial Consulting','financial-consulting',88)]
        for r in taxonomy: db.execute("INSERT OR IGNORE INTO taxonomy_nodes(id,organization_id,node_type,parent_id,name,slug,attractiveness) VALUES(?,?,?,?,?,?,?)",(r[0],ORG_ID,*r[1:]))
        demo_people=[('person_1','Sophie Weber','Managing Director','demo_01','CONFIRMED',.92),('person_2','Marc Hoffmann','Founder','demo_02','PROBABLE',.78),('person_3','Anne Muller','Director','demo_04','CONFIRMED',.94),('person_4','Tom Schmit','Partner','demo_06','PROBABLE',.81)]
        for pid,name,title,cid,status,conf in demo_people: db.execute("INSERT OR IGNORE INTO people(id,organization_id,display_name,job_title,company_id,profile_url,source_type,match_status,confidence,is_demo,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(pid,ORG_ID,name,title,cid,None,'DEMO',status,conf,1,ts))
        for c in db.execute("SELECT * FROM companies WHERE organization_id=?",(ORG_ID,)).fetchall():
            for channel,status,url,conf in [('Website',c['website_status'],c['website'],.9),('Google Business',c['google_status'],None,.7),('LinkedIn','NOT_CHECKED',None,None)]:
                db.execute("INSERT OR IGNORE INTO digital_checks(id,organization_id,company_id,channel,status,source_url,confidence,checked_at,details) VALUES(?,?,?,?,?,?,?,?,?)",('dig_'+c['id']+'_'+channel.lower().replace(' ',''),ORG_ID,c['id'],channel,status,url,conf,ts,json.dumps({'demo':True})))
            db.execute("INSERT OR IGNORE INTO seo_audits(id,organization_id,company_id,url,status,seo_score,opportunity_score,findings,checked_at) VALUES(?,?,?,?,?,?,?,?,?)",('seo_'+c['id'],ORG_ID,c['id'],c['website'],'NOT_CHECKED' if c['seo_score'] is None else 'DEMO',c['seo_score'],c['seo_opportunity'],json.dumps([{'severity':'INFO','message':'Demonstration finding; no live crawl performed'}]) if c['seo_score'] is not None else '[]',ts))
        weights={'freshness':20,'niche':20,'digital_gap':20,'seo_opportunity':15,'local_presence':10,'decision_maker':5,'commercial_potential':10}
        for factor,weight in weights.items(): db.execute("INSERT OR IGNORE INTO scoring_weights VALUES(?,?,?,?,?)",('weight_'+factor,ORG_ID,factor,weight,ts))
        recalculate_all(db, ORG_ID)

def rows(sql, params=()):
    with connect() as db: return [dict(x) for x in db.execute(sql,params).fetchall()]
def one(sql, params=()):
    with connect() as db:
        x=db.execute(sql,params).fetchone(); return dict(x) if x else None

def recalculate_all(db, org_id):
    companies=[dict(r) for r in db.execute("SELECT * FROM companies WHERE organization_id=?",(org_id,))]
    try: weights={r['factor']:r['weight'] for r in db.execute("SELECT factor,weight FROM scoring_weights WHERE organization_id=?",(org_id,))}
    except sqlite3.OperationalError: weights={}
    for c in companies:
        result=calculate(c,weights); oid="opp_"+c["id"]
        db.execute("""INSERT INTO opportunity_scores(id,organization_id,company_id,score,level,breakdown,recommended_action,calculated_at)
        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET score=excluded.score,level=excluded.level,breakdown=excluded.breakdown,recommended_action=excluded.recommended_action,calculated_at=excluded.calculated_at""",(oid,org_id,c["id"],result["score"],result["level"],json.dumps(result["factors"]),result["action"],now()))

def list_companies(org_id, q):
    where=["c.organization_id=?"]; params=[org_id]
    mapping={"municipality":"c.municipality","canton":"c.canton","nace":"c.primary_nace_code","category":"c.category","niche":"c.niche","website":"c.website_status","level":"o.level"}
    if q.get("search"):
        where.append("(c.company_name LIKE ? OR c.rcs_number LIKE ? OR c.primary_nace_code LIKE ? OR c.niche LIKE ? OR c.municipality LIKE ?)"); term=f"%{q['search']}%"; params += [term]*5
    for key,col in mapping.items():
        if q.get(key): where.append(f"{col}=?"); params.append(q[key])
    if q.get("min_score"):
        where.append("o.score>=?"); params.append(int(q["min_score"]))
    if q.get("days"):
        if BACKEND=='postgresql':
            where.append("c.creation_date >= CURRENT_DATE - (? * INTERVAL '1 day')"); params.append(int(q["days"]))
        else:
            where.append("date(c.creation_date)>=date('now', ?)"); params.append(f"-{int(q['days'])} days")
    sql=f"""SELECT c.*,o.score AS opportunity_score,o.level AS opportunity_level,o.recommended_action
    FROM companies c JOIN opportunity_scores o ON o.company_id=c.id AND o.organization_id=c.organization_id
    WHERE {' AND '.join(where)} ORDER BY o.score DESC,c.company_name LIMIT 500"""
    return rows(sql,params)

def company_detail(org_id,cid):
    c=one("""SELECT c.*,o.score opportunity_score,o.level opportunity_level,o.breakdown,o.recommended_action,o.calculated_at FROM companies c JOIN opportunity_scores o ON o.company_id=c.id AND o.organization_id=c.organization_id WHERE c.organization_id=? AND c.id=?""",(org_id,cid))
    if c:
        raw_breakdown=c.get("breakdown") or []
        c["breakdown"]=json.loads(raw_breakdown) if isinstance(raw_breakdown,str) else raw_breakdown
        c["signals"]=rows("SELECT * FROM business_signals WHERE organization_id=? AND company_id=?",(org_id,cid))
        c["lineage"]=rows("SELECT * FROM data_lineage WHERE organization_id=? AND entity_id=?",(org_id,cid))
        c["prospect"]=one("SELECT * FROM prospects WHERE organization_id=? AND company_id=?",(org_id,cid))
    return c

def audit(org_id,action,etype,eid,metadata=None):
    with connect() as db: db.execute("INSERT INTO audit_logs VALUES(?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),org_id,"user_demo_owner",action,etype,eid,json.dumps(metadata or {}),now()))
