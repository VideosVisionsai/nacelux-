"""Database adapter for local SQLite development and production PostgreSQL.

Production is deliberately fail-closed: PostgreSQL, an explicit provider and
TLS are mandatory.  SQLite is available only outside production.
"""
from contextvars import ContextVar
import os
import re
import sqlite3
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
PROVIDER = os.getenv("DB_PROVIDER", "auto").lower().strip()
_PRODUCTION = os.getenv("NACELUX_ENV", "development").lower() in ("production", "prod")
_EXPLICIT_PG = PROVIDER in ("postgresql", "postgres", "supabase")

_tenant_organization: ContextVar[str | None] = ContextVar("nacelux_tenant_organization", default=None)
_tenant_user: ContextVar[str | None] = ContextVar("nacelux_tenant_user", default=None)


class ProductionConfigurationError(RuntimeError):
    """Raised when a production process would not be safe to start."""


def is_production() -> bool:
    return _PRODUCTION


def validate_database_url(url: str, *, require_ssl: bool = False) -> None:
    """Validate connection properties without ever including the URL in errors."""
    if not url:
        raise ProductionConfigurationError("DATABASE_URL is required for PostgreSQL production runtime")
    try:
        parsed = urlsplit(url)
        query = {key.lower(): value.lower() for key, value in parse_qsl(parsed.query, keep_blank_values=True)}
    except Exception as exc:
        raise ProductionConfigurationError("DATABASE_URL is malformed") from exc
    if parsed.scheme not in ("postgresql", "postgres") or not parsed.hostname:
        raise ProductionConfigurationError("DATABASE_URL must be a PostgreSQL URL")
    if require_ssl and query.get("sslmode") != "require":
        raise ProductionConfigurationError("DATABASE_URL must explicitly require PostgreSQL SSL with sslmode=require")


def validate_production_database_config() -> None:
    if not _PRODUCTION:
        return
    if PROVIDER != "postgresql":
        raise ProductionConfigurationError("DB_PROVIDER=postgresql is required in NACELUX_ENV=production")
    validate_database_url(DATABASE_URL, require_ssl=True)
    if os.getenv('DB_SSLMODE','') != 'require':
        raise ProductionConfigurationError('DB_SSLMODE=require is required in NACELUX_ENV=production')


# Import-time validation prevents app.py, worker.py or scripts from silently
# selecting SQLite after a production configuration error.
validate_production_database_config()
IS_POSTGRES = True if _PRODUCTION or _EXPLICIT_PG else bool(DATABASE_URL) and PROVIDER in ("auto", "postgresql", "postgres", "supabase")
BACKEND = "postgresql" if IS_POSTGRES else "sqlite"


def set_tenant_context(organization_id: str | None, user_id: str | None = None) -> None:
    """Set the trusted request/job context used when opening PostgreSQL sessions."""
    _tenant_organization.set(str(organization_id) if organization_id else None)
    _tenant_user.set(str(user_id) if user_id else None)


def clear_tenant_context() -> None:
    _tenant_organization.set(None)
    _tenant_user.set(None)


def tenant_context() -> tuple[str | None, str | None]:
    return _tenant_organization.get(), _tenant_user.get()


class SqliteConnection:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, typ, value, tb):
        if typ is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        self._conn.close()

    def execute(self, sql, params=()):
        return self._conn.execute(sql, params)

    def executescript(self, sql):
        return self._conn.executescript(sql)


class PgConnection:
    def __init__(self, conn):
        self._conn = conn
        organization_id, user_id = tenant_context()
        # set_config(..., false) applies to this transaction/session and is
        # parameterized. It is never built from a client-provided SQL string.
        if organization_id:
            self._conn.execute("SELECT set_config('app.organization_id', %s, false)", (organization_id,))
        if user_id:
            self._conn.execute("SELECT set_config('app.user_id', %s, false)", (user_id,))

    def __enter__(self):
        return self

    def __exit__(self, typ, value, tb):
        if typ is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        self._conn.close()

    def execute(self, sql, params=()):
        return self._conn.execute(adapt_sql(sql), params)

    def executescript(self, sql):
        for statement in sql.split(";"):
            if statement.strip():
                self._conn.execute(statement)


def adapt_sql(sql):
    """Adapt the small SQLite query subset used by the repository."""
    sql = sql.replace(
        "date(c.creation_date)>=date('now', ?)",
        "c.creation_date >= CURRENT_DATE - (%s || ' days')::interval",
    )
    return sql.replace("?", "%s")


def connect():
    if IS_POSTGRES:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL selected but psycopg is not installed. Run: pip install -r requirements.txt"
            ) from exc
        timeout = int(os.getenv("DB_CONNECT_TIMEOUT", "10"))
        options={'row_factory':dict_row,'connect_timeout':timeout}
        if _PRODUCTION:
            options['sslmode']='require'
        connection=PgConnection(psycopg.connect(DATABASE_URL,**options))
        if _PRODUCTION:
            role=connection.execute("SELECT rolname,rolbypassrls,rolsuper FROM pg_roles WHERE rolname=current_user").fetchone()
            if not role or role['rolbypassrls'] or role['rolsuper']:
                connection._conn.rollback()
                connection._conn.close()
                raise ProductionConfigurationError('Runtime PostgreSQL role must not bypass RLS or be superuser')
        return connection
    if _PRODUCTION:
        # Defensive belt-and-suspenders guard: this branch must be unreachable.
        raise ProductionConfigurationError("SQLite is forbidden in NACELUX_ENV=production")
    path = Path(os.getenv("NACELUX_DB", ROOT / "data" / "nacelux.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return SqliteConnection(conn)


def redact_error(value: object) -> str:
    """Return a safe diagnostic string without passwords, tokens or URLs."""
    text = str(value)
    text = re.sub(r"(?i)(postgres(?:ql)?://[^:]+:)[^@\s]+@", r"\1<redacted>@", text)
    text = re.sub(r"(?i)((?:password|secret|token|key|authorization)[\s:=]+)[^\s,;]+", r"\1<redacted>", text)
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", '<jwt-redacted>', text)
    text = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~-]+", 'Bearer <redacted>', text)
    return text[:500]
