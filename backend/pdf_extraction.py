"""Stored PDF → native text → selective OCR fallback with field lineage."""
from __future__ import annotations
import hashlib, os, re, shutil, subprocess, tempfile, urllib.error, urllib.parse, urllib.request, uuid
from datetime import datetime, timezone
from pathlib import Path
import config

ENGINE_VERSION='nacelux-pdf-extractor-2'  # PyMuPDF native + OCRmyPDF fallback
def now():return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def normalize_text(value):return re.sub(r'[ \t]+',' ',re.sub(r'\r\n?', '\n',value or '')).strip()
def text_quality(text,min_chars=80):
    if not text:return 0.0
    printable=sum(1 for c in text if c.isprintable() or c in '\n\t')/len(text);alnum=sum(1 for c in text if c.isalnum())/len(text);volume=min(1,len(text)/max(min_chars,1))
    return round(.5*printable+.3*min(1,alnum/.45)+.2*volume,4)

PDF_MAGIC=b'%PDF-'

def validate_pdf_bytes(data, *, max_bytes=None):
    """Validate a PDF buffer: magic bytes + optional size limit. Raises ValueError
    on anything that is not a PDF or exceeds the limit. Pure function (no I/O)."""
    if not isinstance(data,(bytes,bytearray)):
        raise ValueError('PDF data must be bytes')
    if max_bytes is not None and len(data)>max_bytes:
        raise ValueError(f'PDF exceeds maximum size ({len(data)} > {max_bytes})')
    if len(data)<5 or bytes(data[:5])!=PDF_MAGIC:
        raise ValueError('Not a PDF (missing %PDF- magic bytes)')
    return True

def has_pymupdf():
    try:
        import pymupdf  # noqa: F401
        return True
    except Exception:
        return False

def has_ocrmypdf():
    """OCRmyPDF needs the ocrmypdf binary plus tesseract + ghostscript."""
    return bool(shutil.which('ocrmypdf')) and bool(shutil.which('tesseract')) and bool(shutil.which('gs'))

def native_pages_pymupdf(path, *, max_pages=None):
    """Extract native embedded text per page with PyMuPDF. Raises RuntimeError if
    PyMuPDF is unavailable, the PDF is encrypted, or it exceeds max_pages. Native
    text is NEVER silently replaced -- OCR is a separate, opt-in fallback."""
    import pymupdf
    doc=pymupdf.open(path)
    try:
        if doc.is_encrypted:
            raise RuntimeError('PDF is encrypted')
        if max_pages is not None and doc.page_count>max_pages:
            raise RuntimeError(f'PDF has {doc.page_count} pages; configured maximum is {max_pages}')
        return [{'page_number':i+1,'text':doc[i].get_text('text') or ''} for i in range(doc.page_count)]
    finally:
        doc.close()

def run_ocrmypdf(in_path, out_path, *, languages='fra+deu+eng', timeout=180):
    """Run OCRmyPDF over a whole scanned PDF to add a text layer. 100% open source
    (Tesseract + Ghostscript). Raises RuntimeError if not installed; never simulated."""
    if not has_ocrmypdf():
        raise RuntimeError('OCRmyPDF/Tesseract/Ghostscript not installed (REQUIRES_CONFIGURATION)')
    cmd=['ocrmypdf','-l',languages,'--skip-text','--quiet',in_path,out_path]
    proc=subprocess.run(cmd,capture_output=True,text=True,timeout=timeout)
    if proc.returncode!=0 or not Path(out_path).is_file():
        raise RuntimeError(f'OCRmyPDF failed: {(proc.stderr or "").strip()[:500]}')
    return out_path

def has_poppler():
    """Poppler pdftotext availability (technical fallback when PyMuPDF fails)."""
    return bool(shutil.which('pdftotext'))


def native_pages_pdftotext(path, *, max_pages=None):
    """Fallback: extract text per page using Poppler pdftotext. Raises if absent."""
    if not has_poppler():
        raise RuntimeError('pdftotext (Poppler) not installed (REQUIRES_CONFIGURATION)')
    import subprocess
    proc = subprocess.run(['pdftotext', '-layout', path, '-'], capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f'pdftotext failed: {proc.stderr.strip()[:200]}')
    raw_pages = proc.stdout.split('\f')
    pages = [{'page_number': i + 1, 'text': p.strip()} for i, p in enumerate(raw_pages) if p.strip()]
    if max_pages is not None and len(pages) > max_pages:
        raise RuntimeError(f'PDF has {len(pages)} pages; configured maximum is {max_pages}')
    return pages


def native_blocks_pymupdf(path, *, max_pages=None):
    """Extract text blocks with bounding-box coordinates per page using PyMuPDF.
    Returns [{page_number, blocks: [{x0, y0, x1, y1, text, block_no}]}]."""
    import pymupdf
    doc = pymupdf.open(path)
    try:
        if doc.is_encrypted:
            raise RuntimeError('PDF is encrypted')
        if max_pages is not None and doc.page_count > max_pages:
            raise RuntimeError(f'PDF has {doc.page_count} pages; configured maximum is {max_pages}')
        result = []
        for i in range(doc.page_count):
            page = doc[i]
            raw_blocks = page.get_text('blocks')
            blocks = []
            for b in raw_blocks:
                if len(b) >= 5 and (b[4] or '').strip():
                    blocks.append({'block_no': len(blocks), 'x0': round(float(b[0]), 2), 'y0': round(float(b[1]), 2),
                                   'x1': round(float(b[2]), 2), 'y1': round(float(b[3]), 2), 'text': b[4].strip()})
            result.append({'page_number': i + 1, 'blocks': blocks})
        return result
    finally:
        doc.close()


def extract_people_from_pages(pages):
    """Extract ONLY explicitly labelled directors/roles from extracted page text.
    Returns [{display_name, official_role, page, excerpt}]. Reuses the RESA pipeline
    explicit-label extractor (never deduces a role). [] when none are labelled."""
    import resa_pipeline as _rp
    out=[]
    for page in pages or []:
        for p in _rp.extract_people_facts(page.get('text') or ''):
            out.append({**p,'page':page.get('page_number')})
    return out

class PdfTextExtractionEngine:
    def __init__(self,db_connect):
        self.db_connect=db_connect;self.max_pages=int(os.getenv('PDF_EXTRACTION_MAX_PAGES','100'));self.min_chars=int(os.getenv('PDF_TEXT_MIN_CHARS_PER_PAGE','80'));self.min_quality=float(os.getenv('PDF_TEXT_MIN_QUALITY','.55'));self.ocr_enabled=os.getenv('PDF_OCR_ENABLED','true').lower() in ('1','true','yes');self.languages=os.getenv('PDF_OCR_LANGUAGES','fra+deu+eng');self.dpi=int(os.getenv('PDF_OCR_DPI','300'));self.ocr_timeout=int(os.getenv('PDF_OCR_TIMEOUT_SECONDS','90'))
    def status(self):
        pymupdf='AVAILABLE' if has_pymupdf() else 'NOT_INSTALLED'
        try:
            import pypdf  # noqa: F401
            pypdf='AVAILABLE'
        except Exception:
            pypdf='NOT_INSTALLED'
        ocrmypdf='AVAILABLE' if has_ocrmypdf() else 'NOT_INSTALLED'
        tesseract='AVAILABLE' if shutil.which('tesseract') else 'NOT_INSTALLED'
        ready = pymupdf=='AVAILABLE' or pypdf=='AVAILABLE'
        return {'status':'READY' if ready else 'NOT_CONFIGURED','native_text':pymupdf,'pypdf':pypdf,'ocrmypdf':ocrmypdf,'tesseract':tesseract,'ocr_enabled':self.ocr_enabled,
                'ocr_status':'REQUIRES_CONFIGURATION' if ocrmypdf!='AVAILABLE' else 'READY','languages':self.languages,'max_pages':self.max_pages,'engine_version':ENGINE_VERSION}
    def extract_document(self,organization_id,document_id,force_ocr=False):
        with self.db_connect() as db:
            row=db.execute("SELECT d.*,s.provider,s.bucket,s.object_key,s.local_reference,s.checksum_sha256 FROM resa_documents d LEFT JOIN storage_objects s ON s.id=d.storage_object_id AND s.organization_id=d.organization_id WHERE d.organization_id=? AND d.id=?",(organization_id,document_id)).fetchone()
            if not row:return {'status':'NOT_FOUND','error_code':'DOCUMENT_NOT_FOUND'}
            doc=dict(row)
            if not doc.get('storage_object_id'):return {'status':'NOT_STORED','error_code':'PDF_NOT_STORED','message':'Store and validate the PDF before text extraction.'}
            engine=ENGINE_VERSION+('-force-ocr' if force_ocr else '')
            existing=db.execute("SELECT * FROM document_extractions WHERE organization_id=? AND document_id=? AND source_checksum=? AND engine_version=?",(organization_id,document_id,doc['checksum_sha256'],engine)).fetchone()
            if existing and existing['status'] in ('SUCCESS','PARTIAL'):
                return {'status':'ALREADY_EXTRACTED','extraction_id':existing['id'],'method':existing['extraction_method'],'char_count':existing['char_count'],'ocr_pages':existing['ocr_pages']}
            extraction_id=existing['id'] if existing else 'extract_'+uuid.uuid4().hex;ts=now()
            if existing:db.execute("UPDATE document_extractions SET status='RUNNING',started_at=?,error_code=NULL,error_message=NULL WHERE id=?",(ts,extraction_id))
            else:db.execute("INSERT INTO document_extractions(id,organization_id,document_id,storage_object_id,source_checksum,status,engine_version,started_at) VALUES(?,?,?,?,?,'RUNNING',?,?)",(extraction_id,organization_id,document_id,doc['storage_object_id'],doc['checksum_sha256'],engine,ts))
            db.execute("UPDATE resa_documents SET extraction_status='RUNNING',last_error=NULL WHERE id=?",(document_id,))
        path=None
        try:
            path=self._materialize(doc);pages=self._native_pages(path)
            if len(pages)>self.max_pages:raise RuntimeError(f'PDF has {len(pages)} pages; configured maximum is {self.max_pages}')
            final=[];ocr_count=0;ocr_failures=[]
            for item in pages:
                native=normalize_text(item['text']);quality=text_quality(native,self.min_chars);needs_ocr=force_ocr or len(native)<self.min_chars or quality<self.min_quality
                chosen={'page_number':item['page_number'],'text':native,'method':'TEXT','confidence':None,'quality':quality}
                if needs_ocr and self.ocr_enabled:
                    try:
                        ocr=self._ocr_page(path,item['page_number']);ocr_text=normalize_text(ocr['text']);ocr_quality=text_quality(ocr_text,self.min_chars)
                        if force_ocr or len(ocr_text)>len(native) or ocr_quality>quality:
                            chosen={'page_number':item['page_number'],'text':ocr_text,'method':'OCR','confidence':ocr['confidence'],'quality':ocr_quality};ocr_count+=1
                    except Exception as exc:ocr_failures.append(f"page {item['page_number']}: {exc}")
                final.append(chosen)
            text='\n\n'.join(f"--- PAGE {p['page_number']} ---\n{p['text']}" for p in final if p['text']);char_count=sum(len(p['text']) for p in final);quality=round(sum(p['quality'] for p in final)/len(final),4) if final else 0
            if not text:raise RuntimeError('No text could be extracted from the PDF, including OCR fallback')
            method='MIXED' if ocr_count and ocr_count<len(final) else 'OCR' if ocr_count==len(final) else 'TEXT';status='PARTIAL' if ocr_failures else 'SUCCESS';completed=now();text_hash=hashlib.sha256(text.encode('utf-8')).hexdigest()
            with self.db_connect() as db:
                for p in final:
                    pid='page_'+hashlib.sha256(f'{extraction_id}|{p["page_number"]}'.encode()).hexdigest()[:24]
                    db.execute("INSERT INTO document_page_extractions(id,organization_id,extraction_id,document_id,page_number,extraction_method,text_content,char_count,confidence,quality_score,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(extraction_id,page_number) DO UPDATE SET extraction_method=excluded.extraction_method,text_content=excluded.text_content,char_count=excluded.char_count,confidence=excluded.confidence,quality_score=excluded.quality_score",(pid,organization_id,extraction_id,document_id,p['page_number'],p['method'],p['text'],len(p['text']),p['confidence'],p['quality'],completed))
                db.execute("UPDATE document_extractions SET status=?,extraction_method=?,text_content=?,text_hash=?,page_count=?,extracted_pages=?,ocr_pages=?,char_count=?,quality_score=?,ocr_language=?,completed_at=?,error_code=?,error_message=? WHERE id=?",(status,method,text,text_hash,len(final),sum(1 for p in final if p['text']),ocr_count,char_count,quality,self.languages if ocr_count else None,completed,'OCR_PAGE_FAILURE' if ocr_failures else None,'; '.join(ocr_failures)[:2000] if ocr_failures else None,extraction_id))
                db.execute("UPDATE resa_documents SET extraction_status=?,last_error=? WHERE id=?",(status,'; '.join(ocr_failures)[:1000] if ocr_failures else None,document_id))
            return {'status':status,'extraction_id':extraction_id,'method':method,'page_count':len(final),'extracted_pages':sum(1 for p in final if p['text']),'ocr_pages':ocr_count,'char_count':char_count,'quality_score':quality,'text_hash':text_hash,'ocr_failures':ocr_failures}
        except Exception as exc:
            with self.db_connect() as db:
                db.execute("UPDATE document_extractions SET status='FAILED',completed_at=?,error_code='EXTRACTION_FAILED',error_message=? WHERE id=?",(now(),str(exc)[:2000],extraction_id));db.execute("UPDATE resa_documents SET extraction_status='FAILED',last_error=? WHERE id=?",(str(exc)[:1000],document_id))
            return {'status':'FAILED','extraction_id':extraction_id,'error_code':'EXTRACTION_FAILED','message':str(exc)}
        finally:
            if path and getattr(self,'_temporary',False):Path(path).unlink(missing_ok=True)
    def extract_people(self, organization_id, extraction_id):
        """Extract ONLY explicitly labelled people/roles from an extraction's page
        text and persist them as PENDING_REVIEW observations (source_type
        PDF_EXTRACTION). They are never presented as verified deciders before a
        human review. Idempotent (deterministic person id per extraction+name)."""
        with self.db_connect() as db:
            ext = db.execute("SELECT document_id FROM document_extractions WHERE organization_id=? AND id=?", (organization_id, extraction_id)).fetchone()
            if not ext:
                return {'status': 'NOT_FOUND', 'error_code': 'EXTRACTION_NOT_FOUND'}
            rows = db.execute("SELECT page_number, text_content FROM document_page_extractions WHERE organization_id=? AND extraction_id=? ORDER BY page_number", (organization_id, extraction_id)).fetchall()
            source_url = db.execute("SELECT source_url FROM resa_documents WHERE organization_id=? AND id=?", (organization_id, ext['document_id'])).fetchone()
        source_url = source_url['source_url'] if source_url else None
        people = extract_people_from_pages([{'page_number': r['page_number'], 'text': r['text_content'] or ''} for r in rows])
        created = []
        with self.db_connect() as db:
            for p in people:
                norm = normalize_text(p['display_name']).lower()
                pid = 'person_pdf_' + hashlib.sha256((organization_id + '|' + extraction_id + '|' + norm).encode()).hexdigest()[:22]
                db.execute(
                    "INSERT INTO people(id, organization_id, display_name, job_title, source_type, match_status, confidence, "
                    "is_demo, created_at, name_normalized, official_role, source_url, source_extraction_id, checked_at, "
                    "privacy_status, review_status, source_page, evidence_excerpt) "
                    "VALUES(?,?,?,?, 'PDF_EXTRACTION', 'PENDING', 1.0, 0, ?, ?, ?, ?, ?, ?, 'ACTIVE', 'PENDING_REVIEW', ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET official_role=excluded.official_role, job_title=excluded.job_title, "
                    "source_extraction_id=excluded.source_extraction_id, source_page=excluded.source_page, "
                    "evidence_excerpt=excluded.evidence_excerpt",
                    (pid, organization_id, p['display_name'], p['official_role'], now(), norm, p['official_role'],
                     source_url, extraction_id, now(), p.get('page'), p.get('excerpt')))
                eid = 'pev_pdf_' + hashlib.sha256((pid + '|PDF_ROLE|' + (source_url or extraction_id)).encode()).hexdigest()[:22]
                db.execute(
                    "INSERT INTO people_evidence(id, organization_id, person_id, evidence_type, source_url, source_extraction_id, "
                    "excerpt, confidence, method, created_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(person_id, evidence_type, source_url) "
                    "DO UPDATE SET excerpt=excluded.excerpt, confidence=1.0, method='PDF_EXTRACTION'",
                    (eid, organization_id, pid, 'PDF_ROLE', source_url, extraction_id, p.get('excerpt'), 1.0, 'PDF_EXTRACTION', now()))
                created.append({'person_id': pid, 'display_name': p['display_name'], 'official_role': p['official_role'], 'page': p.get('page')})
        return {'status': 'SUCCESS', 'extraction_id': extraction_id, 'people_found': len(created), 'people': created}

    def _materialize(self,doc):
        self._temporary=False
        if doc['provider']=='local':
            reference=Path(doc['local_reference']);path=reference if reference.is_absolute() else config.ROOT/reference
            path=path.resolve();root=Path(os.getenv('LOCAL_DOCUMENT_STORAGE_DIR',config.ROOT/'data'/'document-storage')).resolve()
            if root not in path.parents or not path.is_file():raise RuntimeError('Stored local PDF reference is invalid')
        elif doc['provider']=='supabase':
            base=os.getenv('SUPABASE_URL','').rstrip('/');key=os.getenv('SUPABASE_SERVICE_ROLE_KEY','')
            if not base or not key:raise RuntimeError('Supabase Storage credentials are unavailable')
            url=f"{base}/storage/v1/object/{urllib.parse.quote(doc['bucket'],safe='')}/{urllib.parse.quote(doc['object_key'],safe='/')}";req=urllib.request.Request(url,headers={'Authorization':'Bearer '+key,'apikey':key})
            fd,tempfile_path=tempfile.mkstemp(prefix='pdf-extract-',suffix='.pdf',dir=config.ROOT/'data');os.close(fd)
            with urllib.request.urlopen(req,timeout=30) as response,open(tempfile_path,'wb') as out:shutil.copyfileobj(response,out)
            path=Path(tempfile_path);self._temporary=True
        else:raise RuntimeError(f"Unsupported storage provider: {doc['provider']}")
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest!=doc['checksum_sha256']:raise RuntimeError('Stored PDF checksum does not match database metadata')
        validate_pdf_bytes(path.read_bytes(), max_bytes=int(os.getenv('LBR_PDF_MAX_BYTES','52428800')))
        return str(path)
    def _native_pages(self,path):
        if has_pymupdf():
            return native_pages_pymupdf(path, max_pages=self.max_pages)
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError('No native PDF text backend (install pymupdf or pypdf)') from exc
        reader=PdfReader(path,strict=False)
        pages=[{'page_number':i+1,'text':page.extract_text() or ''} for i,page in enumerate(reader.pages)]
        if len(pages)>self.max_pages:raise RuntimeError(f'PDF has {len(pages)} pages; configured maximum is {self.max_pages}')
        return pages
    def _ocr_page(self,path,page_number):
        if not shutil.which('tesseract'):raise RuntimeError('Tesseract OCR is not installed')
        try:import pypdfium2 as pdfium
        except ImportError as exc:raise RuntimeError('pypdfium2 is not installed') from exc
        pdf=pdfium.PdfDocument(path);page=pdf[page_number-1];bitmap=page.render(scale=self.dpi/72);image=bitmap.to_pil()
        with tempfile.NamedTemporaryFile(suffix='.png',delete=False,dir=config.ROOT/'data') as tmp:image.save(tmp.name,'PNG');image_path=tmp.name
        try:
            cmd=['tesseract',image_path,'stdout','-l',self.languages,'--psm','6','tsv'];proc=subprocess.run(cmd,capture_output=True,text=True,timeout=self.ocr_timeout)
            if proc.returncode!=0:raise RuntimeError(proc.stderr.strip() or 'Tesseract failed')
            words=[];conf=[]
            for line in proc.stdout.splitlines()[1:]:
                cols=line.split('\t')
                if len(cols)>=12 and cols[11].strip():
                    words.append(cols[11].strip())
                    try:
                        value=float(cols[10]);
                        if value>=0:conf.append(value/100)
                    except ValueError:pass
            return {'text':' '.join(words),'confidence':round(sum(conf)/len(conf),4) if conf else None}
        finally:Path(image_path).unlink(missing_ok=True);page.close();pdf.close()
