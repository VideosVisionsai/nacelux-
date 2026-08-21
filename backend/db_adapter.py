"""Database adapter selecting Supabase PostgreSQL when DATABASE_URL is set.
SQLite remains available only as an explicit local-development fallback.
"""
import os, re, sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATABASE_URL=os.getenv('DATABASE_URL','').strip()
PROVIDER=os.getenv('DB_PROVIDER','auto').lower()
IS_POSTGRES=bool(DATABASE_URL) and PROVIDER in ('auto','postgresql','postgres','supabase')
BACKEND='postgresql' if IS_POSTGRES else 'sqlite'

class SqliteConnection:
    def __init__(self,conn):self._conn=conn
    def __enter__(self):return self
    def __exit__(self,typ,value,tb):
        if typ is None:self._conn.commit()
        else:self._conn.rollback()
        self._conn.close()
    def execute(self,sql,params=()):return self._conn.execute(sql,params)
    def executescript(self,sql):return self._conn.executescript(sql)

class PgConnection:
    def __init__(self,conn): self._conn=conn
    def __enter__(self): return self
    def __exit__(self,typ,value,tb):
        if typ is None:self._conn.commit()
        else:self._conn.rollback()
        self._conn.close()
    def execute(self,sql,params=()):
        sql=adapt_sql(sql)
        return self._conn.execute(sql,params)
    def executescript(self,sql):
        for statement in sql.split(';'):
            if statement.strip(): self._conn.execute(statement)


def adapt_sql(sql):
    """Adapt the small SQLite query subset used by the current repository."""
    sql=sql.replace('date(c.creation_date)>=date(\'now\', ?)',"c.creation_date >= CURRENT_DATE - (%s || ' days')::interval")
    # All remaining positional placeholders are DB-API placeholders.
    sql=sql.replace('?','%s')
    return sql


def connect():
    if IS_POSTGRES:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError('PostgreSQL selected but psycopg is not installed. Run: pip install -r requirements.txt') from exc
        timeout=int(os.getenv('DB_CONNECT_TIMEOUT','10'))
        return PgConnection(psycopg.connect(DATABASE_URL,row_factory=dict_row,connect_timeout=timeout))
    path=Path(os.getenv('NACELUX_DB',ROOT/'data'/'nacelux.db'))
    path.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(path);conn.row_factory=sqlite3.Row;conn.execute('PRAGMA foreign_keys=ON')
    return SqliteConnection(conn)
