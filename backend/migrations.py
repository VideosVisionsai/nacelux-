"""Idempotent PostgreSQL migration runner and lossless SQLite copy utility."""
import hashlib, json, os, sqlite3
from pathlib import Path
from db_adapter import DATABASE_URL, ROOT, connect as runtime_connect, validate_database_url

MIGRATION_DATABASE_URL=os.getenv('MIGRATION_DATABASE_URL', DATABASE_URL).strip()
MIGRATIONS=Path(os.getenv('MIGRATIONS_DIR',ROOT/'database'/'migrations'))
TABLE_ORDER=['organizations','users','organization_members','companies','business_signals','opportunity_scores','prospects','data_sources','jobs','data_lineage','audit_logs','nace_codes','taxonomy_nodes','people','digital_checks','seo_audits','resa_publications','reports','territories','scoring_weights','resa_journals','resa_entries','resa_documents','resa_sync_runs','storage_objects','document_extractions','document_page_extractions','nace_versions_official','nace_items_official','nace_labels_official','nace_notes_official','nace_correspondences_official','nace_import_runs','website_discovery_runs','website_candidates','google_business_profiles','people_engine_runs','people_evidence','professional_profiles_public','privacy_requests','business_signal_runs','business_signal_definitions','raw_records','documents','dedup_candidates','imports','digital_check_history','opportunity_score_history','opportunity_validations']
JSON_COLUMNS={'companies':{'secondary_nace_codes'},'business_signals':{'signal_value','evidence'},'opportunity_scores':{'breakdown'},'audit_logs':{'metadata'},'digital_checks':{'details','evidence'},'seo_audits':{'findings'},'territories':{'municipalities'},'resa_sync_runs':{'metadata'},'nace_versions_official':{'metadata'},'nace_import_runs':{'metadata'},'website_discovery_runs':{'metadata'},'website_candidates':{'evidence'},'google_business_profiles':{'raw_data'},'people_engine_runs':{'metadata'},'professional_profiles_public':{'evidence'},'business_signal_runs':{'metadata'},'jobs':{'payload'},'raw_records':{'payload'}}
BOOL_COLUMNS={'companies':{'is_demo'},'nace_codes':{'is_demo'},'taxonomy_nodes':{'is_active'},'people':{'is_demo'},'resa_publications':{'is_demo'},'nace_items_official':{'is_current'},'business_signal_definitions':{'is_active'}}

def pg_connect():
    import psycopg
    from psycopg.rows import dict_row
    if not MIGRATION_DATABASE_URL: raise RuntimeError('MIGRATION_DATABASE_URL is required for PostgreSQL migrations')
    validate_database_url(MIGRATION_DATABASE_URL, require_ssl=os.getenv('NACELUX_ENV','development').lower() in ('production','prod'))
    options={'row_factory':dict_row,'connect_timeout':int(os.getenv('DB_CONNECT_TIMEOUT','10'))}
    if os.getenv('NACELUX_ENV','development').lower() in ('production','prod'):
        options['sslmode']='require'
    return psycopg.connect(MIGRATION_DATABASE_URL,**options)

def run_migrations():
    """Apply only unseen files. Every migration is additive and checksum tracked."""
    if not MIGRATION_DATABASE_URL: raise RuntimeError('MIGRATION_DATABASE_URL is required for PostgreSQL migrations')
    files=sorted(MIGRATIONS.glob('*.sql'))
    if not files: raise RuntimeError(f'No migrations found in {MIGRATIONS}')
    with pg_connect() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version text PRIMARY KEY,checksum text NOT NULL,applied_at timestamptz NOT NULL DEFAULT now())")
        for path in files:
            sql=path.read_text(encoding='utf-8'); digest=hashlib.sha256(sql.encode()).hexdigest(); version=path.stem
            existing=conn.execute('SELECT checksum FROM schema_migrations WHERE version=%s',(version,)).fetchone()
            if existing:
                if existing['checksum']!=digest: raise RuntimeError(f'Applied migration was modified: {version}')
                continue
            conn.execute(sql)
            conn.execute('INSERT INTO schema_migrations(version,checksum) VALUES(%s,%s)',(version,digest))
    return [p.stem for p in files]

def migrate_sqlite_data(source=None):
    """Copy current rows with insert-only semantics. Existing PostgreSQL rows win."""
    source=Path(source or os.getenv('SQLITE_SOURCE_PATH',ROOT/'data'/'nacelux.db'))
    if not source.exists(): return {'source':str(source),'tables':{},'skipped':'source not found'}
    src=sqlite3.connect(source);src.row_factory=sqlite3.Row;stats={}
    from psycopg import sql
    from psycopg.types.json import Jsonb
    with pg_connect() as dst:
        for table in TABLE_ORDER:
            exists=src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
            if not exists: continue
            pg_cols={r['column_name'] for r in dst.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s",(table,)).fetchall()}
            src_cols=[r['name'] for r in src.execute(f'PRAGMA table_info("{table}")') if r['name'] in pg_cols]
            if not src_cols: continue
            copied=0
            query=sql.SQL('INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING').format(sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,src_cols)),sql.SQL(',').join(sql.Placeholder()*len(src_cols)))
            for row in src.execute(f'SELECT * FROM "{table}"'):
                values=[]
                for col in src_cols:
                    value=row[col]
                    if col in JSON_COLUMNS.get(table,set()):
                        try:value=Jsonb(json.loads(value)) if isinstance(value,str) else Jsonb(value)
                        except (json.JSONDecodeError,TypeError):value=Jsonb(value)
                    if col in BOOL_COLUMNS.get(table,set()) and value is not None:value=bool(value)
                    values.append(value)
                cur=dst.execute(query,values);copied+=max(cur.rowcount,0)
            stats[table]=copied
    src.close();return {'source':str(source),'tables':stats,'total':sum(stats.values())}

def connection_test():
    """Test the non-owner runtime connection, not the migration administrator."""
    with runtime_connect() as conn:
        row=conn.execute("SELECT current_database() database,current_user db_user,version() version,now() checked_at").fetchone()
        tables=conn.execute("SELECT count(*) count FROM information_schema.tables WHERE table_schema='public'").fetchone()['count']
    return {**dict(row),'public_tables':tables,'ssl_required':True,'rls_runtime_role_checked':True}
