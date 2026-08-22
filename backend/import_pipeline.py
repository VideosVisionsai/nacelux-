"""NACELUX data-import core (ÉTAPE 3).

A reusable, source-agnostic pipeline:

    SOURCE -> RAW RECORD -> VALIDATION -> NORMALISATION -> DEDUPLICATION
           -> COMPANY -> DATA LINEAGE

Design rules enforced here:
* An unknown value stays unknown. Missing email/phone/website/NACE -> NULL;
  status-like fields stay UNKNOWN / NOT_CHECKED. Nothing is ever fabricated.
* Deduplication is deterministic and official-id-first (RCS, then VAT). Companies
  are NEVER merged on name similarity: an uncertain match is recorded in
  ``dedup_candidates`` (PENDING) for human review, and the new row is still
  created independently.
* SHA-256 checksums track content identity/change; a checksum proves content
  integrity only, never the origin of the data.
* Every persisted company row carries provenance: source_id, source_url,
  retrieved_at, checksum, and a data_lineage row pointing back at the raw record.

The module is storage-agnostic: it operates on a connection handle from
``db_adapter.connect()`` (SQLite `?` placeholders, auto-adapted to `%s` for
PostgreSQL) so the same code runs in dev and production. HTTP routes stay thin.
"""
from __future__ import annotations
import hashlib
import json
import re
import uuid
from typing import Any

import database as data

# Canonical company fields used for content checksumming (identity + payload).
CHECKSUM_FIELDS = (
    "company_name", "legal_form", "rcs_number", "vat_number", "creation_date",
    "status", "primary_nace_code", "category", "niche", "subniche", "website",
    "email", "phone", "country", "canton", "municipality", "locality",
    "postal_code", "street", "street_number",
)
REQUIRED_FIELDS = ("company_name",)


def _now() -> str:
    return data.now()


def sha256_text(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def company_checksum(record: dict) -> str:
    """Stable SHA-256 over the canonical payload. Proves content integrity only."""
    canonical = {k: _norm(record.get(k)) for k in CHECKSUM_FIELDS}
    return sha256_text(json.dumps(canonical, ensure_ascii=False, sort_keys=True))


def _norm(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _norm_name(value: Any) -> str:
    """Aggressive normalization for candidate detection only (never for merging)."""
    text = (str(value or "")).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def validate_record(record: dict) -> tuple[dict, list[str]]:
    """Return (cleaned_record, errors). Never invents missing data."""
    cleaned: dict = {}
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if not _norm(record.get(field)):
            errors.append(f"Missing {field}")
    # Copy known fields through; empty strings become None (unknown -> NULL).
    passthrough = (
        "company_name", "trade_name", "legal_form", "rcs_number", "vat_number",
        "creation_date", "status", "capital", "business_object", "description",
        "primary_nace_code", "secondary_nace_codes", "category", "niche",
        "subniche", "website", "email", "phone", "country", "canton",
        "municipality", "locality", "postal_code", "street", "street_number",
        "latitude", "longitude", "external_id",
    )
    for field in passthrough:
        if field in record:
            cleaned[field] = _norm(record.get(field))
    # Light format checks: a malformed optional value is sanitized to unknown
    # (NULL), never fabricated and never blocking a valid company row.
    email = cleaned.get("email")
    if email and "@" not in email:
        cleaned["email"] = None
    # Status-like fields: unknown stays unknown, do not fabricate a value.
    cleaned.setdefault("website_status", record.get("website_status") or "NOT_CHECKED")
    cleaned.setdefault("google_status", record.get("google_status") or "NOT_CHECKED")
    cleaned.setdefault("decision_maker_status", record.get("decision_maker_status") or "UNKNOWN")
    return cleaned, errors


def normalize_record(record: dict, source: dict | None = None) -> dict:
    """Apply unknown-stays-unknown semantics and attach provenance fields."""
    rec = dict(record)
    rec["checksum"] = company_checksum(record)
    rec["retrieved_at"] = _now()
    rec["provenance"] = (source or {}).get("provenance") or (source or {}).get("name") or "IMPORT"
    if source:
        rec.setdefault("source_url", source.get("source_url") or source.get("url"))
    # Scores / opportunities are explicitly NOT set here (developed later).
    return rec


def find_existing(db, org_id: str, record: dict) -> dict | None:
    """Deterministic dedup by official id only: RCS, then VAT. Returns the matched
    company row (with checksum) or None. Name similarity is NOT a merge key."""
    rcs = _norm(record.get("rcs_number"))
    vat = _norm(record.get("vat_number"))
    if rcs:
        row = db.execute(
            "SELECT id, checksum FROM companies WHERE organization_id=? AND rcs_number=?",
            (org_id, rcs)).fetchone()
        if row:
            return dict(row)
    if vat:
        row = db.execute(
            "SELECT id, checksum FROM companies WHERE organization_id=? AND vat_number=?",
            (org_id, vat)).fetchone()
        if row:
            return dict(row)
    return None


def find_name_candidates(db, org_id: str, record: dict, exclude_id: str | None = None):
    """Detect possible duplicates by normalized name (same org). These are NEVER
    merged; they are recorded as PENDING candidates for human review."""
    target = _norm_name(record.get("company_name"))
    if not target:
        return []
    rows = db.execute(
        "SELECT id, company_name, municipality FROM companies WHERE organization_id=?",
        (org_id,)).fetchall()
    out = []
    for r in rows:
        if exclude_id and r["id"] == exclude_id:
            continue
        if _norm_name(r["company_name"]) == target:
            same_city = _norm(record.get("municipality")) and _norm(record.get("municipality")) == _norm(r["municipality"])
            out.append({
                "company_id": r["id"],
                "company_name": r["company_name"],
                "confidence": 0.9 if same_city else 0.6,
            })
    return out


_COMPANY_COLS = (
    "id", "organization_id", "company_name", "trade_name", "legal_form",
    "rcs_number", "vat_number", "creation_date", "status", "capital",
    "business_object", "description", "primary_nace_code", "secondary_nace_codes",
    "category", "niche", "subniche", "website", "email", "phone", "country",
    "canton", "municipality", "locality", "postal_code", "street", "street_number",
    "latitude", "longitude", "website_status", "google_status",
    "decision_maker_status", "source_id", "source_url", "retrieved_at",
    "provenance", "checksum", "created_at", "updated_at",
)


def persist_raw_record(db, org_id: str, source: dict | None, record: dict) -> str:
    external_id = _norm(record.get("external_id"))
    content = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
    payload = json.dumps({k: record.get(k) for k in ("external_id", "source_url")}, ensure_ascii=False)
    checksum = sha256_text(content)
    # Idempotent: reuse an existing raw_record for the same (org, source, external_id, checksum).
    if external_id is None:
        existing = db.execute(
            "SELECT id FROM raw_records WHERE organization_id=? AND source_id IS ? "
            "AND external_id IS NULL AND checksum=?", (org_id, (source or {}).get("source_id"), checksum)).fetchone()
    else:
        existing = db.execute(
            "SELECT id FROM raw_records WHERE organization_id=? AND source_id=? "
            "AND external_id=? AND checksum=?", (org_id, (source or {}).get("source_id"), external_id, checksum)).fetchone()
    if existing:
        return existing["id"]
    raw_id = "raw_" + uuid.uuid4().hex[:16]
    db.execute(
        "INSERT INTO raw_records(id, organization_id, source_id, external_id, payload, "
        "checksum, retrieved_at, stage, source_url, raw_content, content_format, status, metadata) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (raw_id, org_id, (source or {}).get("source_id"),
         external_id, payload, checksum, _now(), "RAW",
         (source or {}).get("source_url") or record.get("source_url"),
         content, "json", "INGESTED", "{}"))
    return raw_id


def persist_company(db, org_id: str, record: dict, raw_id: str, source: dict | None) -> tuple[str, str]:
    """Insert or update a company. Returns (company_id, 'CREATED'|'UPDATED'|'UNCHANGED')."""
    existing = find_existing(db, org_id, record)
    checksum = record["checksum"]
    if existing:
        if existing.get("checksum") == checksum:
            return existing["id"], "UNCHANGED"
        cid = existing["id"]
        action = "UPDATED"
    else:
        cid = "comp_" + uuid.uuid4().hex[:14]
        action = "CREATED"
    values = []
    for col in _COMPANY_COLS:
        if col == "id":
            values.append(cid)
        elif col == "organization_id":
            values.append(org_id)
        elif col in ("created_at", "updated_at"):
            values.append(_now())
        elif col == "source_id":
            values.append((source or {}).get("source_id"))
        elif col in ("checksum", "retrieved_at", "provenance", "source_url"):
            values.append(record.get(col))
        elif col == "secondary_nace_codes":
            val = record.get(col)
            values.append(json.dumps(val) if isinstance(val, list) else val)
        elif col == "capital":
            values.append(record.get(col))
        elif col in ("latitude", "longitude"):
            values.append(record.get(col))
        else:
            values.append(record.get(col))
    placeholders = ",".join(["?"] * len(_COMPANY_COLS))
    cols = ",".join(_COMPANY_COLS)
    if existing:
        updates = ",".join(f"{c}=excluded.{c}" for c in _COMPANY_COLS if c not in ("id", "organization_id", "created_at"))
        db.execute(
            f"INSERT INTO companies({cols}) VALUES({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}", values)
    else:
        db.execute(f"INSERT INTO companies({cols}) VALUES({placeholders})", values)
    return cid, action


def write_lineage(db, org_id: str, company_id: str, raw_id: str, source: dict | None, record: dict):
    """Field-level provenance: company field <- raw_record <- source."""
    base = {
        "entity_type": "company", "entity_id": company_id,
        "source_id": (source or {}).get("source_id"),
        "source_url": (source or {}).get("source_url") or record.get("source_url"),
        "retrieved_at": _now(), "method": "IMPORT",
        "raw_record_id": raw_id, "checksum": record.get("checksum"),
        "transformation": "NORMALIZATION",
    }
    for field in CHECKSUM_FIELDS:
        if record.get(field) in (None, ""):
            continue
        db.execute(
            "INSERT INTO data_lineage(id, organization_id, entity_type, entity_id, field_name, "
            "source_id, source_url, document_id, retrieved_at, confidence, method, raw_record_id, "
            "checksum, transformation) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("lin_" + uuid.uuid4().hex[:16], org_id, base["entity_type"], company_id, field,
             base["source_id"], base["source_url"], None, base["retrieved_at"], 1.0,
             base["method"], raw_id, base["checksum"], base["transformation"]))


def record_dedup_candidate(db, org_id: str, company_a: str, company_b: str, confidence: float, meta: dict):
    db.execute(
        "INSERT INTO dedup_candidates(id, organization_id, company_a_id, company_b_id, "
        "match_basis, confidence, status, metadata, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        ("ded_" + uuid.uuid4().hex[:16], org_id, company_a, company_b, "NAME_SIMILARITY",
         confidence, "PENDING", json.dumps(meta), _now()))


def ensure_source(db, org_id: str, source: dict | None):
    """Register the source row if it does not exist yet, so raw_records.source_id
    satisfies its foreign key. The status comes from the importer (default ACTIVE,
    never 'VERIFIED' -- a source is only VERIFIED after explicit out-of-band proof)."""
    sid = (source or {}).get("source_id")
    if not sid:
        return
    if db.execute("SELECT 1 FROM data_sources WHERE organization_id=? AND id=?", (org_id, sid)).fetchone():
        return
    status = (source or {}).get("status") or "ACTIVE"
    if str(status).upper() == "VERIFIED":
        status = "REQUIRES_CONFIRMATION"  # never auto-mark a source as verified
    db.execute(
        "INSERT INTO data_sources(id, organization_id, name, source_type, status, provider, "
        "base_url, note, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (sid, org_id, (source or {}).get("name") or sid, (source or {}).get("source_type") or "IMPORT",
         status, (source or {}).get("provider"), (source or {}).get("source_url") or (source or {}).get("url"),
         (source or {}).get("description"), _now(), _now()))


def preview(org_id: str, source: dict | None, rows: list[dict]) -> dict:
    """Dry run: analyse rows against the current data WITHOUT writing anything."""
    items: list[dict] = []
    valid = invalid = duplicates = new = changes = 0
    with data.connect() as db:
        for i, raw in enumerate(rows):
            cleaned, errors = validate_record(raw)
            if errors:
                invalid += 1
                items.append({"row": i + 1, "valid": False, "errors": errors})
                continue
            valid += 1
            record = normalize_record(cleaned, source)
            existing = find_existing(db, org_id, record)
            if existing:
                duplicates += 1
                changed = existing.get("checksum") != record["checksum"]
                if changed:
                    changes += 1
                items.append({"row": i + 1, "valid": True, "duplicate": True,
                              "match": "OFFICIAL_ID", "changed": changed,
                              "company_name": record.get("company_name")})
            else:
                new += 1
                cands = find_name_candidates(db, org_id, record)
                items.append({"row": i + 1, "valid": True, "duplicate": False,
                              "new": True, "name_candidates": len(cands),
                              "company_name": record.get("company_name")})
    return {
        "records_received": len(rows), "records_valid": valid, "records_invalid": invalid,
        "duplicates": duplicates, "new": new, "changes_detected": changes,
        "errors_count": invalid, "items": items,
    }


def run(org_id: str, source: dict | None, rows: list[dict], *, import_id: str) -> dict:
    """Transactional import. The caller wraps this in a single transaction so a
    failure rolls back every partial write. Returns per-row counters."""
    stats = {"received": len(rows), "valid": 0, "invalid": 0, "created": 0,
             "updated": 0, "skipped": 0, "failed": 0, "candidates": 0}
    error_summary: list[str] = []
    with data.connect() as db:
        ensure_source(db, org_id, source)
        for raw in rows:
            cleaned, errors = validate_record(raw)
            if errors:
                stats["invalid"] += 1
                stats["failed"] += 1
                error_summary.append(f"row invalid: {errors}")
                continue
            stats["valid"] += 1
            record = normalize_record(cleaned, source)
            raw_id = persist_raw_record(db, org_id, source, record)
            cid, action = persist_company(db, org_id, record, raw_id, source)
            write_lineage(db, org_id, cid, raw_id, source, record)
            if action == "CREATED":
                stats["created"] += 1
                for cand in find_name_candidates(db, org_id, record, exclude_id=cid):
                    record_dedup_candidate(db, org_id, cid, cand["company_id"],
                                           cand["confidence"], {"name": record.get("company_name")})
                    stats["candidates"] += 1
            elif action == "UPDATED":
                stats["updated"] += 1
            else:
                stats["skipped"] += 1
        db.execute(
            "INSERT INTO imports(id, organization_id, source_id, import_type, status, "
            "records_received, records_valid, records_created, records_updated, records_skipped, "
            "records_failed, error_summary, metadata, started_at, finished_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (import_id, org_id, (source or {}).get("source_id"),
             (source or {}).get("import_type") or "COMPANIES",
             "PARTIAL" if stats["failed"] else "SUCCESS",
             stats["received"], stats["valid"], stats["created"], stats["updated"],
             stats["skipped"], stats["failed"],
             ("; ".join(error_summary[:10]) or None) if error_summary else None,
             json.dumps({"source": (source or {}).get("name")}), _now(), _now()))
    return stats
