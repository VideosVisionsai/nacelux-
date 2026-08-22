#!/usr/bin/env python3
"""DEV/TEST runner: boot a REAL embedded PostgreSQL and execute the Step 4 NACE
reference-data RLS suite against it (real engine, not a mock).

Usage:
    python3 tests/run_step4_embedded.py
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
    print(f"  applied: {len(server['applied_migrations'])} migrations")
    os.environ["NACELUX_TEST_DATABASE_URL"] = server["runtime_uri"]
    try:
        suite = unittest.TestLoader().loadTestsFromName("tests.test_step4_nace.NaceReferenceRLSTests")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    finally:
        server["stop"]()


if __name__ == "__main__":
    sys.exit(main())
