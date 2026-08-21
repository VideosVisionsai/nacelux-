#!/usr/bin/env python3
"""Download, validate and import the official Eurostat NACE Rev. 2.1 RDF."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
import config,database
from nace_importer import OfficialNaceImporter

def main():
    database.init_db();result=OfficialNaceImporter(database.connect).import_official();print(json.dumps(result,indent=2,default=str));return 0 if result.get('status')=='SUCCESS' else 2
if __name__=='__main__':raise SystemExit(main())
