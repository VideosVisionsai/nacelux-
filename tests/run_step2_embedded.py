#!/usr/bin/env python3
"""DEV/TEST runner: boot a REAL embedded PostgreSQL and execute the Step 2
verification suite (real migrations, real RLS, real tenant isolation, real
atomic job claim).

Usage:
    python3 tests/run_step2_embedded.py

This uses the real PostgreSQL server binary bundled in the ``pgserver`` wheel.
It is NOT used in production and does not use SQLite or any mock.
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from _pg_embedded import bootstrap  # noqa: E402


def main():
    print("=== Booting REAL embedded PostgreSQL (pgserver) ===")
    server = bootstrap()
    print(f"  pgdata : {server['pgdata']}")
    print(f"  port   : {server['port']}")
    print(f"  applied: {len(server['applied_migrations'])} migrations -> {server['applied_migrations']}")

    os.environ["NACELUX_TEST_DATABASE_URL"] = server["runtime_uri"]
    os.environ["NACELUX_WORKER_TEST_DATABASE_URL"] = server["worker_uri"]
    os.environ["DB_SSLMODE"] = "require"  # informs adapter-level checks; server itself is loopback/no-SSL

    try:
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromName("tests.test_step2_rls_isolation")
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        return 0 if result.wasSuccessful() else 1
    finally:
        server["stop"]()


if __name__ == "__main__":
    sys.exit(main())
