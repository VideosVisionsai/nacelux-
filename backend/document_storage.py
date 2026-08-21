"""RESA document download → validated PDF → immutable storage pipeline."""
from __future__ import annotations
import hashlib, json, mimetypes, os, re, shutil, tempfile, urllib.error, urllib.parse, urllib.request, uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import config


def now():return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def safe_name(value):return re.sub(r'[^A-Za-z0-9._-]+','-',value or 'document.pdf').strip('-')[:120] or 'document.pdf'
def allowed_hosts():return {x.strip().lower() for x in os.getenv('LBR_PDF_ALLOWED_HOSTS','www.lbr.lu,lbrcontent.public.lu').split(',') if x.strip()}
def validate_document_url(url):
    p=urllib.parse.urlsplit(url)
    if p.scheme!='https' or p.hostname not in allowed_hosts() or p.username or p.password or p.port not in (None,443):raise ValueError('Document URL is outside the approved HTTPS LBR hosts')
    return url

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        validate_document_url(urllib.parse.urljoin(req.full_url,newurl));return super().redirect_request(req,fp,code,msg,headers,newurl)

@dataclass
class StoredObject:
    provider:str;bucket:str;key:str;local_reference:str|None=None

class LocalStorage:
    provider='local'
    def __init__(self):self.root=Path(os.getenv('LOCAL_DOCUMENT_STORAGE_DIR',config.ROOT/'data'/'document-storage'));self.bucket='local-resa-documents'
    def put(self,source,key,mime_type):
        target=(self.root/key).resolve();root=self.root.resolve()
        if root not in target.parents:raise ValueError('Invalid storage key')
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():
            temp=target.with_suffix(target.suffix+'.part');shutil.copyfile(source,temp);os.replace(temp,target)
        try:reference=str(target.relative_to(config.ROOT))
        except ValueError:reference=str(target)
        return StoredObject(self.provider,self.bucket,key,reference)

class SupabaseStorage:
    provider='supabase'
    def __init__(self):
        self.base=os.getenv('SUPABASE_URL','').rstrip('/');self.key=os.getenv('SUPABASE_SERVICE_ROLE_KEY','');self.bucket=os.getenv('SUPABASE_STORAGE_BUCKET','resa-documents')
        if not self.base or not self.key or 'replace-with' in self.key:raise RuntimeError('Supabase Storage is not configured')
    def put(self,source,key,mime_type):
        path=urllib.parse.quote(key,safe='/');url=f'{self.base}/storage/v1/object/{urllib.parse.quote(self.bucket,safe="")}/{path}'
        body=Path(source).read_bytes();req=urllib.request.Request(url,data=body,method='POST',headers={'Authorization':'Bearer '+self.key,'apikey':self.key,'Content-Type':mime_type,'x-upsert':'false'})
        try:
            with urllib.request.urlopen(req,timeout=30) as response:
                if response.status not in (200,201):raise RuntimeError(f'Supabase Storage returned HTTP {response.status}')
        except urllib.error.HTTPError as exc:
            detail=exc.read(1000).decode('utf-8','replace');raise RuntimeError(f'Supabase Storage upload failed ({exc.code}): {detail}')
        return StoredObject(self.provider,self.bucket,key)

def validate_production_storage_config():
    if os.getenv('NACELUX_ENV','development').lower() not in ('production','prod'):
        return
    provider=os.getenv('DOCUMENT_STORAGE_PROVIDER','').lower()
    if provider!='supabase':
        raise RuntimeError('DOCUMENT_STORAGE_PROVIDER=supabase is required in production')
    required=(os.getenv('SUPABASE_URL',''),os.getenv('SUPABASE_SERVICE_ROLE_KEY',''),os.getenv('SUPABASE_STORAGE_BUCKET',''))
    if any(not value or any(marker in value.lower() for marker in ('replace-with','your_','<key','example')) for value in required):
        raise RuntimeError('Supabase private storage configuration is incomplete in production')

if os.getenv('NACELUX_ENV','development').lower() in ('production','prod'):
    validate_production_storage_config()

def storage_backend():
    provider=os.getenv('DOCUMENT_STORAGE_PROVIDER','supabase' if os.getenv('NACELUX_ENV','development').lower() in ('production','prod') else 'local').lower()
    if os.getenv('NACELUX_ENV','development').lower() in ('production','prod') and provider!='supabase':
        raise RuntimeError('Supabase Storage is required in production; local document storage is forbidden')
    return SupabaseStorage() if provider=='supabase' else LocalStorage()

class ResaPdfStoragePipeline:
    def __init__(self,db_connect):
        self.db_connect=db_connect;self.max_bytes=int(os.getenv('LBR_PDF_MAX_BYTES','52428800'));self.user_agent=os.getenv('LBR_USER_AGENT','NACELUX/1.0 (controlled RESA reader)')
    def status(self):
        provider=os.getenv('DOCUMENT_STORAGE_PROVIDER','local').lower()
        try:store=storage_backend();return {'status':'READY','provider':store.provider,'bucket':store.bucket,'max_bytes':self.max_bytes}
        except Exception:
            return {'status':'NOT_CONFIGURED','provider':provider,'error_code':'STORAGE_NOT_CONFIGURED','max_bytes':self.max_bytes}
    def store_document(self,organization_id,document_id):
        with self.db_connect() as db:
            doc=db.execute('SELECT * FROM resa_documents WHERE organization_id=? AND id=?',(organization_id,document_id)).fetchone()
            if not doc:return {'status':'NOT_FOUND','error_code':'DOCUMENT_NOT_FOUND'}
            doc=dict(doc)
            if doc.get('storage_object_id'):
                return {'status':'ALREADY_STORED','document_id':document_id,'storage_object_id':doc['storage_object_id'],'checksum':doc.get('checksum')}
            db.execute("UPDATE resa_documents SET download_status='DOWNLOADING',last_error=NULL WHERE id=?",(document_id,))
        temp=None
        try:
            url=validate_document_url(doc['document_url']);temp,meta=self._download(url)
            existing=self._existing(organization_id,meta['checksum'])
            if existing:
                self._link(document_id,existing,meta,'DUPLICATE');return {'status':'DUPLICATE','document_id':document_id,'storage_object_id':existing['id'],'checksum':meta['checksum'],'size_bytes':meta['size_bytes']}
            store=storage_backend();year=datetime.now(timezone.utc).strftime('%Y');filename=safe_name(urllib.parse.unquote(Path(urllib.parse.urlsplit(url).path).name))
            if not filename.lower().endswith('.pdf'):filename+='.pdf'
            object_key=f'{organization_id}/{year}/{meta["checksum"][:2]}/{meta["checksum"]}-{filename}'
            stored=store.put(temp,object_key,'application/pdf');object_id='storage_'+hashlib.sha256((organization_id+'|'+meta['checksum']).encode()).hexdigest()[:24];ts=now()
            with self.db_connect() as db:
                db.execute("INSERT INTO storage_objects(id,organization_id,provider,bucket,object_key,checksum_sha256,size_bytes,mime_type,original_filename,source_url,local_reference,created_at,verified_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(organization_id,checksum_sha256) DO NOTHING",(object_id,organization_id,stored.provider,stored.bucket,stored.key,meta['checksum'],meta['size_bytes'],'application/pdf',filename,url,stored.local_reference,ts,ts))
                obj=db.execute('SELECT * FROM storage_objects WHERE organization_id=? AND checksum_sha256=?',(organization_id,meta['checksum'])).fetchone();self._link_in_db(db,document_id,dict(obj),meta,'STORED')
            return {'status':'STORED','document_id':document_id,'storage_object_id':object_id,'provider':stored.provider,'bucket':stored.bucket,'storage_key':stored.key,'checksum':meta['checksum'],'size_bytes':meta['size_bytes']}
        except Exception as exc:
            with self.db_connect() as db:db.execute("UPDATE resa_documents SET download_status='FAILED',last_error=? WHERE id=?",(str(exc)[:1000],document_id))
            return {'status':'FAILED','document_id':document_id,'error_code':'PDF_STORAGE_FAILED','message':str(exc)}
        finally:
            if temp:Path(temp).unlink(missing_ok=True)
    def _download(self,url):
        opener=urllib.request.build_opener(SafeRedirect());req=urllib.request.Request(url,headers={'User-Agent':self.user_agent,'Accept':'application/pdf'})
        fd,path=tempfile.mkstemp(prefix='resa-pdf-',suffix='.part',dir=config.ROOT/'data');os.close(fd);digest=hashlib.sha256();size=0;first=b''
        try:
            with opener.open(req,timeout=30) as response,open(path,'wb') as out:
                status=getattr(response,'status',200)
                if status!=200:raise RuntimeError(f'Document download returned HTTP {status}')
                while True:
                    chunk=response.read(65536)
                    if not chunk:break
                    size+=len(chunk)
                    if size>self.max_bytes:raise RuntimeError('PDF exceeds configured maximum size')
                    if len(first)<1024:first=(first+chunk)[:1024]
                    digest.update(chunk);out.write(chunk)
            if b'%PDF-' not in first:raise RuntimeError('Downloaded content is not a validated PDF')
            if size<8:raise RuntimeError('Downloaded PDF is empty or truncated')
            return path,{'checksum':digest.hexdigest(),'size_bytes':size,'http_status':200,'mime_type':'application/pdf'}
        except Exception:
            Path(path).unlink(missing_ok=True);raise
    def _existing(self,org,checksum):
        with self.db_connect() as db:
            row=db.execute('SELECT * FROM storage_objects WHERE organization_id=? AND checksum_sha256=?',(org,checksum)).fetchone();return dict(row) if row else None
    def _link(self,document_id,obj,meta,status):
        with self.db_connect() as db:self._link_in_db(db,document_id,obj,meta,status)
    def _link_in_db(self,db,document_id,obj,meta,status):
        db.execute("UPDATE resa_documents SET storage_object_id=?,storage_provider=?,storage_bucket=?,storage_key=?,checksum=?,mime_type='application/pdf',size_bytes=?,downloaded_at=?,http_status=?,download_status=?,last_error=NULL WHERE id=?",(obj['id'],obj['provider'],obj['bucket'],obj['object_key'],meta['checksum'],meta['size_bytes'],now(),meta.get('http_status',200),status,document_id))
