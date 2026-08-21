#!/usr/bin/env python3
"""Manage NACELUX Supabase PostgreSQL without exposing credentials."""
import argparse, json, os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))

def load_dotenv(path):
    if not path.exists(): return
    for raw in path.read_text().splitlines():
        raw=raw.strip()
        if raw and not raw.startswith('#') and '=' in raw:
            key,value=raw.split('=',1);os.environ.setdefault(key.strip(),value.strip().strip('"').strip("'"))

load_dotenv(ROOT/'.env')
from db_adapter import DATABASE_URL

def main():
    p=argparse.ArgumentParser(description='NACELUX Supabase PostgreSQL manager')
    p.add_argument('command',choices=['test','migrate','copy-sqlite','setup'])
    p.add_argument('--source',default=None)
    args=p.parse_args()
    if not DATABASE_URL:
        raise SystemExit('DATABASE_URL is missing. Copy .env.example to .env and add the Supabase PostgreSQL URI.')
    from db_adapter import is_production, validate_production_database_config
    if is_production():
        validate_production_database_config()
        if args.command=='copy-sqlite' or os.getenv('MIGRATE_SQLITE_DATA','false').lower() in ('1','true','yes'):
            raise SystemExit('SQLite data copy is forbidden in NACELUX_ENV=production')
    from migrations import connection_test,run_migrations,migrate_sqlite_data
    if args.command=='test': result=connection_test()
    elif args.command=='migrate': result={'migrations':run_migrations()}
    elif args.command=='copy-sqlite': result=migrate_sqlite_data(args.source)
    else:
        result={'connection':connection_test(),'migrations':run_migrations()}
        if os.getenv('MIGRATE_SQLITE_DATA','true').lower() in ('1','true','yes'):result['data_copy']=migrate_sqlite_data(args.source)
    print(json.dumps(result,indent=2,default=str))

if __name__=='__main__':main()
