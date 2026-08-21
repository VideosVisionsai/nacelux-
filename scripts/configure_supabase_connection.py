#!/usr/bin/env python3
"""Configure and test Supabase PostgreSQL without printing the password.
This command never applies migrations or copies data.
"""
from getpass import getpass
from pathlib import Path
from urllib.parse import quote
import os, subprocess, sys

ROOT=Path(__file__).resolve().parents[1]
ENV_FILE=ROOT/'.env'

def read_env():
    values={}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
            if line and not line.lstrip().startswith('#') and '=' in line:
                k,v=line.split('=',1);values[k]=v
    return values

def main():
    print('NACELUX — Supabase Session Pooler configuration')
    project=input('Project ref [eiyrneemqhqqgvssjtql]: ').strip() or 'eiyrneemqhqqgvssjtql'
    region=input('AWS region [eu-west-2]: ').strip() or 'eu-west-2'
    password=getpass('New Supabase database password: ')
    if not password:raise SystemExit('Password is required.')
    confirm=getpass('Confirm password: ')
    if password!=confirm:raise SystemExit('Passwords do not match.')
    user=f'postgres.{project}';host=f'aws-0-{region}.pooler.supabase.com'
    url=f'postgresql://{user}:{quote(password,safe="")}@{host}:5432/postgres?sslmode=require'
    values=read_env();values.update({'DATABASE_URL':url,'DB_PROVIDER':'postgresql','DB_SSLMODE':'require','DB_CONNECT_TIMEOUT':'10','AUTO_MIGRATE':'true','MIGRATE_SQLITE_DATA':'false','SQLITE_SOURCE_PATH':'data/nacelux.db'})
    ENV_FILE.write_text('\n'.join(f'{k}={v}' for k,v in values.items())+'\n',encoding='utf-8');os.chmod(ENV_FILE,0o600)
    print(f'Configuration written to {ENV_FILE} with permissions 0600.')
    print('Testing connection only — no migrations...')
    result=subprocess.run([sys.executable,str(ROOT/'scripts'/'supabase_db.py'),'test'],cwd=ROOT)
    if result.returncode:raise SystemExit('Connection test failed. Verify the rotated password and Session Pooler region.')
    print('Connection successful. AUTO_MIGRATE=true and MIGRATE_SQLITE_DATA=false remain configured.')

if __name__=='__main__':main()
