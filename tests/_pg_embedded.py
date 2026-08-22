"""DEV/TEST-ONLY helper: boot a REAL embedded PostgreSQL server (via the
``pgserver`` wheel, which bundles the actual PostgreSQL server binary) for
genuine local verification of migrations, RLS, roles and the job queue.

This is NOT production infrastructure and is never imported by the application.
It is used only by the Step 2 verification suite and ``tests/run_step2_embedded.py``.

Notes
-----
* The bundled PostgreSQL build has no OpenSSL (``--without-openssl``), so the
  server runs WITHOUT SSL over the loopback. RLS / tenant isolation / migrations
  are independent of transport encryption and are therefore verified for real
  here. The SSL *handshake* itself is verified separately against an SSL-capable
  PostgreSQL/Supabase (see scripts/verify_rls.sh and docs/STEP1_REPORT.md).
* No mock database and no fabricated data: every object is created by the real
  PostgreSQL engine and the real migration files.
"""
from __future__ import annotations
import atexit
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_BIN = None


def _bin_path() -> Path:
    global _BIN
    if _BIN is None:
        from pgserver._commands import POSTGRES_BIN_PATH  # type: ignore
        _BIN = Path(POSTGRES_BIN_PATH)
    return _BIN


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _run(cmd, **kw):
    try:
        return subprocess.run(cmd, check=True, text=True, capture_output=True, **kw)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"command failed ({exc.returncode}): {' '.join(cmd)}\nSTDOUT:\n{exc.stdout}\nSTDERR:\n{exc.stderr}"
        ) from exc


def bootstrap(*, pgdata: Path | str | None = None, dbname: str = "nacelux_test", set_app_database_url: bool = False):
    """Start an embedded PostgreSQL, create the non-owner roles + database, and
    apply every migration as the migration (superuser) role.

    Returns a dict with the connection URIs (superuser + non-owner runtime and
    worker roles) and a ``stop`` callable.
    """
    pgdata = Path(pgdata or tempfile.mkdtemp(prefix="nacelux_pg_"))
    pgdata.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    b = _bin_path()

    # 1. initdb (trust auth on loopback; we are a non-root user). pgdata MUST be
    #    empty for initdb, so the socket dir is created afterwards.
    if not (pgdata / "PG_VERSION").exists():
        _run([str(b / "initdb"), "-D", str(pgdata), "--auth=trust",
              "--auth-local=trust", "--encoding=utf8", "-U", "postgres"])

    socket_dir = pgdata / "sock"
    socket_dir.mkdir(exist_ok=True)

    # 2. Configure: TCP loopback, fixed port, unix socket, verbose-enough logs.
    conf = pgdata / "postgresql.conf"
    with conf.open("a") as fh:
        fh.write("\n# --- nacelux embedded test config ---\n")
        fh.write("listen_addresses = '127.0.0.1'\n")
        fh.write(f"port = {port}\n")
        fh.write(f"unix_socket_directories = '{socket_dir}'\n")
        fh.write("logging_collector = off\n")
        fh.write("log_min_messages = warning\n")

    # 3. Start the server.
    log = pgdata / "server.log"
    _run([str(b / "pg_ctl"), "-D", str(pgdata), "-l", str(log),
          "-w", "-o", "-i", "start"])

    super_uri = f"postgresql://postgres@127.0.0.1:{port}/{dbname}"
    pg_uri = f"postgresql://postgres@127.0.0.1:{port}/postgres"
    runtime_uri = f"postgresql://nacelux_runtime@127.0.0.1:{port}/{dbname}"
    worker_uri = f"postgresql://nacelux_worker@127.0.0.1:{port}/{dbname}"
    if set_app_database_url:
        # Must be set BEFORE db_adapter is first imported (during migrations
        # import below) so IS_POSTGRES resolves to True for the app adapter.
        os.environ["DATABASE_URL"] = runtime_uri
        os.environ["DB_PROVIDER"] = "postgresql"

    # Wait until reachable.
    import psycopg  # noqa: WPS433 (lazy import; only needed when bootstrapping)
    deadline = time.time() + 15
    while True:
        try:
            with psycopg.connect(pg_uri):
                break
        except Exception:
            if time.time() > deadline:
                raise RuntimeError(f"embedded PostgreSQL did not become reachable; log:\n{log.read_text(errors='ignore')}")
            time.sleep(0.2)

    # 4. Create the database + the two non-owner application roles BEFORE
    #    migrations (migrations 0013/0014 raise if these roles are absent).
    with psycopg.connect(pg_uri, autocommit=True) as conn:
        conn.execute("CREATE DATABASE %s" % dbname) if not _db_exists(conn, dbname) else None
    with psycopg.connect(super_uri, autocommit=True) as conn:
        for role in ("nacelux_runtime", "nacelux_worker"):
            conn.execute("DROP ROLE IF EXISTS %s" % role)
            conn.execute("CREATE ROLE %s LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION" % role)
        # Grant the roles on the database so they can connect.
        conn.execute("GRANT CONNECT ON DATABASE %s TO nacelux_runtime, nacelux_worker" % dbname)

    # 5. The bundled PostgreSQL ships no pgcrypto (real Supabase always has it),
    #    but no migration actually *uses* a pgcrypto function — it is only declared
    #    in 0001. Register a no-op stub so CREATE EXTENSION succeeds without
    #    altering any migration file or checksum.
    _ensure_pgcrypto_stub()

    # 6. Apply migrations as the migration (superuser) role.
    sys.path.insert(0, str(ROOT / "backend"))
    os.environ["MIGRATION_DATABASE_URL"] = super_uri
    os.environ.pop("NACELUX_ENV", None)  # dev mode: migrations do not hard-require SSL on the URL
    from migrations import run_migrations  # type: ignore
    applied = run_migrations()

    def stop():
        try:
            _run([str(b / "pg_ctl"), "-D", str(pgdata), "-m", "fast", "stop"])
        except Exception:
            pass

    return {
        "pgdata": str(pgdata),
        "port": port,
        "superuser_uri": super_uri,
        "runtime_uri": runtime_uri,
        "worker_uri": worker_uri,
        "applied_migrations": applied,
        "stop": stop,
    }


def _db_exists(conn, dbname: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone())


def _ensure_pgcrypto_stub():
    """Register a no-op pgcrypto extension in the bundled PostgreSQL share dir.

    The pgserver bundle (PG 16.2) ships plpgsql + vector but not pgcrypto.
    Migrations declare ``CREATE EXTENSION IF NOT EXISTS pgcrypto`` yet never call
    any pgcrypto function, so an empty extension script lets the real migrations
    apply unchanged. Real Supabase/PostgreSQL always provides pgcrypto natively.
    """
    ext_dir = _bin_path().parent / "share" / "postgresql" / "extension"
    control = ext_dir / "pgcrypto.control"
    script = ext_dir / "pgcrypto--1.3.sql"
    if control.exists():
        return
    ext_dir.mkdir(parents=True, exist_ok=True)
    control.write_text(
        "# pgcrypto stub (embedded test verification only)\n"
        "comment = 'pgcrypto stub; no functions used by NACELUX migrations'\n"
        "default_version = '1.3'\n"
        "relocatable = true\n"
    )
    script.write_text(
        "/* pgcrypto stub: NACELUX migrations declare but never invoke pgcrypto. */\n"
    )
