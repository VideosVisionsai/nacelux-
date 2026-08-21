#!/usr/bin/env python3
"""Manual controlled RESA journal analysis command."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
import config,database
from resa_connector import LBRResaConnector

def main():
    p=argparse.ArgumentParser(description='Analyze one canonical public LBR/RESA journal URL')
    p.add_argument('url');p.add_argument('--organization',default=database.ORG_ID);p.add_argument('--no-browser',action='store_true');p.add_argument('--headed',action='store_true',help='Visible browser for operator-supervised captcha; no automated bypass')
    args=p.parse_args();database.init_db();result=LBRResaConnector(database.connect).analyze(args.organization,args.url,allow_browser=not args.no_browser,headless=not args.headed);print(json.dumps(result,indent=2,default=str));return 0 if result.get('status')=='SUCCESS' else 2
if __name__=='__main__':raise SystemExit(main())
