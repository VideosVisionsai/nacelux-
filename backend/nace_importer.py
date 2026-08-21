"""Official NACE Rev. 2.1 importer from Eurostat ShowVoc RDF distribution.
No classification rows or notes are hand-authored by NACELUX.
"""
from __future__ import annotations
import hashlib, html, io, json, os, re, urllib.parse, urllib.request, uuid, zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import config

DEFAULT_SOURCE='https://showvoc.op.europa.eu/semanticturkey/downloads/ESTAT_Statistical_Classification_of_Economic_Activities_in_the_European_Community_Rev._2.1._%28NACE_2.1%29/distributions/NACE_Rev_2.1.zip'
BASE='http://data.europa.eu/ux2/nace2.1/'
RDF='{http://www.w3.org/1999/02/22-rdf-syntax-ns#}'
XML_LANG='{http://www.w3.org/XML/1998/namespace}lang'
EXPECTED={'SECTION':22,'DIVISION':87,'GROUP':287,'CLASS':651}

def now():return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def digest(value):return hashlib.sha256(value.encode()).hexdigest()
def local(tag):return tag.split('}')[-1]
def clean_html(value):return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',value or ''))).strip()
def code_level(code):
    if re.fullmatch(r'[A-Z]',code):return 'SECTION'
    if re.fullmatch(r'\d{2}',code):return 'DIVISION'
    if re.fullmatch(r'\d{2}\.\d',code):return 'GROUP'
    if re.fullmatch(r'\d{2}\.\d{2}',code):return 'CLASS'
    return None
def format_raw_code(raw):
    raw=urllib.parse.unquote(raw).strip('/')
    if re.fullmatch(r'[A-Z]',raw):return raw
    if re.fullmatch(r'\d{2}',raw):return raw
    if re.fullmatch(r'\d{3}',raw):return raw[:2]+'.'+raw[2:]
    if re.fullmatch(r'\d{4}',raw):return raw[:2]+'.'+raw[2:]
    return raw

def validate_source(url):
    p=urllib.parse.urlsplit(url)
    if p.scheme!='https' or p.hostname!='showvoc.op.europa.eu' or not p.path.startswith('/semanticturkey/downloads/') or not p.path.endswith('/NACE_Rev_2.1.zip'):raise ValueError('Only the official Eurostat ShowVoc NACE Rev. 2.1 distribution URL is accepted')

def parse_rdf(rdf_file,languages=('fr','de','en')):
    entities=defaultdict(lambda:defaultdict(list))
    for _,element in ET.iterparse(rdf_file,events=('end',)):
        if local(element.tag)=='Description':
            about=element.attrib.get(RDF+'about')
            if about:
                for child in element:
                    entities[about][local(child.tag)].append({'text':(child.text or '').strip(),'lang':child.attrib.get(XML_LANG),'resource':child.attrib.get(RDF+'resource')})
            element.clear()
    concepts={};uri_to_code={}
    for uri,props in entities.items():
        notations=[x['text'] for x in props.get('notation',[]) if x['text']]
        if not notations:continue
        code=notations[0];level=code_level(code)
        if level and uri.startswith(BASE):concepts[uri]={'uri':uri,'code':code,'level':level,'props':props};uri_to_code[uri]=code
    items=[];labels=[];notes=[]
    note_refs={'coreContentNote':'INCLUDES','additionalContentNote':'INCLUDES_ALSO','exclusionNote':'EXCLUDES'}
    for uri,concept in concepts.items():
        props=concept['props'];parent_uri=next((x['resource'] for x in props.get('broader',[]) if x['resource']),None);order=next((x['text'] for x in props.get('order',[]) if x['text']),None)
        items.append({'uri':uri,'code':concept['code'],'level':concept['level'],'parent_code':uri_to_code.get(parent_uri),'sort_order':int(order) if order and order.isdigit() else None})
        for lang in languages:
            candidates=[x['text'] for x in props.get('prefLabel',[]) if x['lang']==lang and x['text']]
            if not candidates:candidates=[x['text'] for x in props.get('altLabel',[]) if x['lang']==lang and x['text']]
            if candidates:labels.append({'code':concept['code'],'language':lang,'label_type':'PREF','label':candidates[0]})
        for value in props.get('scopeNote',[]):
            text=clean_html(value['text']);lang=value['lang'] or 'en'
            if text:notes.append({'code':concept['code'],'type':'SCOPE','language':lang,'text':text,'uri':None})
        for predicate,note_type in note_refs.items():
            for reference in props.get(predicate,[]):
                note_uri=reference['resource'];note_props=entities.get(note_uri,{})
                values=note_props.get('plainText',[]) or note_props.get('value',[])
                for value in values:
                    text=clean_html(value['text']);lang=value['lang'] or 'en'
                    if text:notes.append({'code':concept['code'],'type':note_type,'language':lang,'text':text,'uri':note_uri})
    correspondences=[]
    prefix=BASE+'NACE2.1_NACE2_'
    for uri,props in entities.items():
        if not uri.startswith(prefix) or uri==BASE+'NACE2.1_NACE2':continue
        sources=[x['resource'] for x in props.get('sourceConcept',[]) if x['resource'] and x['resource'].startswith(BASE)]
        targets=[x['resource'] for x in props.get('targetConcept',[]) if x['resource'] and '/nace2/' in x['resource']]
        cardinality=next((x['resource'].rsplit('/',1)[-1] for x in props.get('mapping_cardinality',[]) if x['resource']),None)
        if cardinality and '_' in cardinality:
            a,b=cardinality.split('_',1);cardinality=b+':'+a
        for rev21_uri in sources:
            target_code=uri_to_code.get(rev21_uri) or format_raw_code(rev21_uri.rsplit('/',1)[-1])
            for rev2_uri in targets:
                source_code=format_raw_code(rev2_uri.rsplit('/',1)[-1]);correspondences.append({'source_code':source_code,'target_code':target_code,'relationship':cardinality,'uri':uri})
    return {'items':items,'labels':labels,'notes':notes,'correspondences':correspondences}

class OfficialNaceImporter:
    def __init__(self,db_connect):
        self.db_connect=db_connect;self.source=os.getenv('NACE21_SOURCE_URL',DEFAULT_SOURCE);self.languages=tuple(x.strip().lower() for x in os.getenv('NACE21_LANGUAGES','fr,de,en').split(',') if x.strip());self.artifacts=Path(os.getenv('NACE21_ARTIFACT_DIR',config.ROOT/'data'/'nace-imports'))
    def status(self):
        with self.db_connect() as db:
            version=db.execute("SELECT * FROM nace_versions_official WHERE version_code='2.1'").fetchone();run=db.execute("SELECT * FROM nace_import_runs WHERE version_code='2.1' ORDER BY started_at DESC LIMIT 1").fetchone()
        return {'status':'ACTIVE' if version and version['status']=='ACTIVE' else 'NOT_IMPORTED','version':dict(version) if version else None,'last_run':dict(run) if run else None,'source_url':self.source,'languages':self.languages}
    def import_official(self):
        validate_source(self.source);run_id='nace_run_'+uuid.uuid4().hex;started=now()
        with self.db_connect() as db:db.execute("INSERT INTO nace_import_runs(id,version_code,status,source_url,started_at,metadata) VALUES(?,'2.1','RUNNING',?,?,?)",(run_id,self.source,started,json.dumps({'languages':self.languages})))
        try:
            req=urllib.request.Request(self.source,headers={'User-Agent':'NACELUX/1.0 official-Eurostat-import','Accept':'application/zip,application/octet-stream'})
            with urllib.request.urlopen(req,timeout=60) as response:data=response.read(25_000_001)
            if len(data)>25_000_000:raise RuntimeError('Official distribution exceeds safety limit')
            if not data.startswith(b'PK\x03\x04'):raise RuntimeError('Official distribution is not a ZIP archive')
            checksum=hashlib.sha256(data).hexdigest();self.artifacts.mkdir(parents=True,exist_ok=True);artifact=self.artifacts/f'NACE_Rev_2.1_{checksum}.zip'
            if not artifact.exists():artifact.write_bytes(data)
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names=[n for n in archive.namelist() if n.lower().endswith('.rdf')]
                if names!=['NACE_Rev_2.1.rdf']:raise RuntimeError(f'Unexpected official archive contents: {names}')
                parsed=parse_rdf(archive.open(names[0]),self.languages)
            counts=defaultdict(int)
            for item in parsed['items']:counts[item['level']]+=1
            for level,expected in EXPECTED.items():
                if counts[level]!=expected:raise RuntimeError(f'Validation failed for {level}: expected {expected}, received {counts[level]}')
            for lang in self.languages:
                available={x['code'] for x in parsed['labels'] if x['language']==lang}
                if len(available)!=sum(EXPECTED.values()):raise RuntimeError(f'Incomplete {lang} labels: {len(available)} of {sum(EXPECTED.values())}')
            if not parsed['notes']:raise RuntimeError('No explanatory notes found in official RDF')
            if len(parsed['correspondences'])<1000:raise RuntimeError(f'Incomplete correspondence table: {len(parsed["correspondences"])} mappings')
            retrieved=now();version_id='nace_version_2_1';source=self.source
            with self.db_connect() as db:
                db.execute("INSERT INTO nace_versions_official(id,version_code,title,status,valid_from,source_url,source_checksum,source_format,retrieved_at,item_count,metadata) VALUES(?,'2.1','NACE Rev. 2.1','IMPORTING','2025-01-01',?,?,?, ?,?,?) ON CONFLICT(version_code) DO UPDATE SET status='IMPORTING',source_url=excluded.source_url,source_checksum=excluded.source_checksum,retrieved_at=excluded.retrieved_at,metadata=excluded.metadata",(version_id,source,checksum,'RDF/XML ZIP',retrieved,len(parsed['items']),json.dumps({'publisher':'Eurostat','distribution':'ShowVoc','artifact':str(artifact.relative_to(config.ROOT))})))
                db.execute("UPDATE nace_items_official SET is_current=FALSE WHERE version_id=?",(version_id,))
                item_ids={}
                for item in parsed['items']:
                    iid='nace21_'+item['code'].replace('.','_');item_ids[item['code']]=iid
                    db.execute("INSERT INTO nace_items_official(id,version_id,code,level,parent_code,concept_uri,sort_order,is_current,source_url,retrieved_at) VALUES(?,?,?,?,?,?,?,TRUE,?,?) ON CONFLICT(version_id,code) DO UPDATE SET level=excluded.level,parent_code=excluded.parent_code,concept_uri=excluded.concept_uri,sort_order=excluded.sort_order,is_current=TRUE,source_url=excluded.source_url,retrieved_at=excluded.retrieved_at",(iid,version_id,item['code'],item['level'],item['parent_code'],item['uri'],item['sort_order'],source,retrieved))
                for label in parsed['labels']:
                    lid='nace_label_'+digest(item_ids[label['code']]+'|'+label['language']+'|'+label['label_type'])[:24]
                    db.execute("INSERT INTO nace_labels_official(id,item_id,language,label_type,label,source_url,retrieved_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(item_id,language,label_type) DO UPDATE SET label=excluded.label,source_url=excluded.source_url,retrieved_at=excluded.retrieved_at",(lid,item_ids[label['code']],label['language'],label['label_type'],label['label'],source,retrieved))
                for note in parsed['notes']:
                    nid='nace_note_'+digest(item_ids[note['code']]+'|'+note['type']+'|'+note['language']+'|'+note['text'])[:24]
                    db.execute("INSERT INTO nace_notes_official(id,item_id,note_type,language,note_text,note_uri,source_url,retrieved_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(item_id,note_type,language,note_text) DO UPDATE SET note_uri=excluded.note_uri,source_url=excluded.source_url,retrieved_at=excluded.retrieved_at",(nid,item_ids[note['code']],note['type'],note['language'],note['text'],note['uri'],source,retrieved))
                for corr in parsed['correspondences']:
                    cid='nace_corr_'+digest(corr['source_code']+'|'+corr['target_code']+'|'+corr['uri'])[:24]
                    db.execute("INSERT INTO nace_correspondences_official(id,source_version,target_version,source_code,target_code,relationship,mapping_uri,source_url,retrieved_at) VALUES(?,'2','2.1',?,?,?,?,?,?) ON CONFLICT(source_version,target_version,source_code,target_code,mapping_uri) DO UPDATE SET relationship=excluded.relationship,source_url=excluded.source_url,retrieved_at=excluded.retrieved_at",(cid,corr['source_code'],corr['target_code'],corr['relationship'],corr['uri'],source,retrieved))
                db.execute("UPDATE nace_versions_official SET status='ACTIVE',activated_at=?,item_count=? WHERE id=?",(retrieved,len(parsed['items']),version_id))
                db.execute("UPDATE nace_import_runs SET status='SUCCESS',source_checksum=?,completed_at=?,sections=?,divisions=?,groups_count=?,classes=?,labels=?,notes=?,correspondences=?,metadata=? WHERE id=?",(checksum,retrieved,counts['SECTION'],counts['DIVISION'],counts['GROUP'],counts['CLASS'],len(parsed['labels']),len(parsed['notes']),len(parsed['correspondences']),json.dumps({'artifact':str(artifact.relative_to(config.ROOT)),'rdf_file':'NACE_Rev_2.1.rdf'}),run_id))
            return {'status':'SUCCESS','run_id':run_id,'source_checksum':checksum,'sections':counts['SECTION'],'divisions':counts['DIVISION'],'groups':counts['GROUP'],'classes':counts['CLASS'],'labels':len(parsed['labels']),'notes':len(parsed['notes']),'correspondences':len(parsed['correspondences']),'artifact':str(artifact.relative_to(config.ROOT))}
        except Exception as exc:
            with self.db_connect() as db:db.execute("UPDATE nace_import_runs SET status='FAILED',completed_at=?,error_code='NACE_IMPORT_FAILED',error_message=? WHERE id=?",(now(),str(exc)[:2000],run_id))
            return {'status':'FAILED','run_id':run_id,'error_code':'NACE_IMPORT_FAILED','message':str(exc)}
