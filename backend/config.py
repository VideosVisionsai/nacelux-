import os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def load_env(path=None):
    path=Path(path or ROOT/'.env')
    if not path.exists():return
    for raw in path.read_text(encoding='utf-8').splitlines():
        raw=raw.strip()
        if raw and not raw.startswith('#') and '=' in raw:
            key,value=raw.split('=',1)
            os.environ.setdefault(key.strip(),value.strip().strip('"').strip("'"))

load_env()
