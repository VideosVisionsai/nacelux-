"""RESA -> Commercial intelligence integration (orchestration layer).

This does NOT re-implement the RESA connector, PDF storage, extraction, people
engine, website/digital/SEO or signals. It REUSES them and adds the bridge that
turns a RESA publication (already fetched + extracted) into the NACELUX
commercial pipeline:

    RESA publication -> raw_record -> document -> extraction -> evidence
        -> company matching -> people/roles -> data_lineage
        -> (website / digital / SEO / NACE / signals run by the existing engines)

Rules:
* No fictive data. Company facts and people/roles are EXTRACTED from the real
  document text only (explicit labels); anything absent stays UNKNOWN/NULL.
* RESA itself is only consumed when the connector is enabled and the source is
  reachable. Until then the registered source stays REQUIRES_CONFIRMATION and
  nothing is fabricated.
* Reuses import_pipeline (Étape 3) for deterministic dedup/matching and lineage.
"""
from __future__ import annotations
import json
import re
import uuid
from typing import Any

import database as data
import import_pipeline as pipeline

SOURCE_ID = "lbr_resa"
SOURCE_NAME = "LBR / RESA (Luxembourg Business Registers)"
SOURCE_URL = "https://www.lbr.lu/"


def _sid(org_id: str) -> str:
    """data_sources.id is a global primary key and data_sources is tenant-scoped,
    so the RESA source id is org-scoped (one row per organization)."""
    return f"{SOURCE_ID}_{org_id}"

# Explicit-label extractors. A value is captured ONLY when the official label is
# present in the text; nothing is guessed or generated.
_RCS_RE = re.compile(r"(?<![A-Z0-9])([A-Z])\s*([0-9]{4,8})(?![0-9])")
_NAME_RE = re.compile(r"(?:d[ée]nomination|denomination|firmenname|company name)\s*[:\-]\s*(.{2,120}?)"
                      r"(?=\s+(?:RCS|B\s+\d|code\s*nace|nace|activit|capital|forme\s*legal|si[èe]ge|g[ée]rant|administrateur|directeur|associ[ée]|commissaire|repr[ée]sent)|$)", re.I)
_NACE_RE = re.compile(r"(?:code\s*nace|nace|activit[ée] principale)\s*[:\-]\s*([0-9]{2}(?:\.[0-9]{1,2})?)", re.I)
_ROLE_KW = r"g[ée]rant|administrateur|directeur|pr[ée]sident|associ[ée]e?|manager|commissaire"
_NAME_WORD = r"[A-ZÉÀ-Ý][a-zà-ÿ]+(?:-[A-ZÉÀ-Ý][a-zà-ÿ]+)?"
_ROLE_RE = re.compile("(" + _ROLE_KW + r")\s*:?\s+(" + _NAME_WORD + r"(?:\s+(?!(" + _ROLE_KW + r")\b)" + _NAME_WORD + r"){0,3})", re.I)

# Legal-entity indicators that disqualify a candidate from being a natural person.
# If any of these appear in the excerpt near a candidate name, it is a legal entity.
_LEGAL_ENTITY_RE = re.compile(
    r"(?:RCS\s*B\s*\d|B\s*\d{5,}|société|S\.?\s*à\s*r\.?|SARL|Sàrl|SCSP|SCA|GmbH|"
    r"société en commandite|ayant son siège|société à responsabilité limitée|"
    r"société anonyme|holding|capital\s+variable|SE\s*S\.?C\.?A\.?)", re.I)

# French legal phrases that look like names but are NOT persons.
_LEGAL_PHRASES = {"solidairement responsable", "indéfiniment responsable",
                  "responsable indéfiniment", "non associé", "non partenaire",
                  "responsable solidairement"}


def _is_natural_person(name: str, excerpt: str) -> bool:
    """Return True ONLY if the candidate is plausibly a natural person (not a
    legal entity or legal phrase). Never infers a person — only rejects obvious
    non-persons. A legal-entity manager (e.g. a Sàrl named as 'gérant') must NOT
    be treated as a natural-person decision maker."""
    if not name or len(name) < 3:
        return False
    # Legal phrase check (e.g. "solidairement responsable")
    if name.lower().strip() in _LEGAL_PHRASES:
        return False
    # Name must start with uppercase (re.I in the regex allows lowercase; enforce here)
    if not name[0].isupper():
        return False
    # Legal-entity indicators in the surrounding excerpt (RCS number, legal form, etc.)
    if _LEGAL_ENTITY_RE.search(excerpt):
        return False
    return True


def ensure_source(db, org_id: str) -> None:
    """Register RESA as a data_source. Status is REQUIRES_CONFIRMATION until a
    real, compliant access has been confirmed out-of-band (never VERIFIED here)."""
    ts = data.now()
    db.execute(
        "INSERT INTO data_sources(id, organization_id, name, source_type, base_url, status, provider, note, "
        "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
        "name=excluded.name, provider=excluded.provider, updated_at=excluded.updated_at",
        (_sid(org_id), org_id, SOURCE_NAME, "OFFICIAL_PUBLIC_REGISTER", SOURCE_URL,
         "REQUIRES_CONFIRMATION", "LBR", "Controlled public RESA reader; enabled only after compliance approval.", ts, ts))


def extract_company_facts(text: str) -> dict:
    """Extract ONLY explicitly labelled company facts from document text."""
    text = text or ""
    facts: dict[str, Any] = {}
    m = _NAME_RE.search(text)
    if m:
        facts["company_name"] = re.sub(r"\s+", " ", m.group(1)).strip()
    rcs = _RCS_RE.search(text)
    if rcs:
        facts["rcs_number"] = (rcs.group(1) + rcs.group(2)).upper()
    nace = _NACE_RE.search(text)
    if nace:
        facts["primary_nace_code"] = nace.group(1)
    return facts


def extract_people_facts(text: str) -> list[dict]:
    """Extract ONLY explicitly labelled directors/roles who are NATURAL PERSONS.
    Legal entities (companies named as gérant, legal phrases) are rejected.
    Returns [] when none are labelled -- never invents a person or role."""
    text = text or ""
    out: list[dict] = []
    for match in _ROLE_RE.finditer(text):
        role = re.sub(r"\s+", " ", match.group(1)).strip().lower()
        name = re.sub(r"\s+", " ", match.group(2)).strip()
        excerpt = match.group(0).strip()
        ctx_start = max(0, match.start() - 30)
        ctx_end = min(len(text), match.end() + 200)
        context = text[ctx_start:ctx_end]
        if name and len(name) >= 3 and _is_natural_person(name, context):
            out.append({"display_name": name, "official_role": role, "excerpt": excerpt})
    seen = set(); unique = []
    for p in out:
        key = (p["display_name"], p["official_role"])
        if key not in seen:
            seen.add(key); unique.append(p)
    return unique


def ingest(org_id: str, *, source_url: str, document_text: str,
           storage_object_id: str | None = None, extraction_id: str | None = None,
           resa_entry_id: str | None = None) -> dict:
    """Transactional RESA -> commercial integration for one publication's text.

    1. register source; 2. raw_record (provenance); 3. extract explicit company
    facts; 4. deterministic match/create company (RCS then VAT); 5. data_lineage;
    6. explicit people/roles -> people + people_evidence (OFFICIAL).
    Returns a summary. No website/digital/SEO/signals here -- those run via the
    existing engines/jobs (the company is now 'ready for scoring')."""
    source = {"source_id": _sid(org_id), "name": SOURCE_NAME, "source_url": source_url,
              "import_type": "RESA", "provenance": "RESA"}
    facts = extract_company_facts(document_text)
    people = extract_people_facts(document_text)
    if not facts.get("company_name"):
        return {"status": "NO_COMPANY", "company_name": None, "people_found": len(people),
                "message": "No explicit company name found in the document; nothing invented."}
    with data.connect() as db:
        ensure_source(db, org_id)
        # raw record preserving the official text exactly.
        raw_id = pipeline.persist_raw_record(db, org_id, source,
                                              {**facts, "external_id": resa_entry_id, "source_url": source_url,
                                               "people": [p["display_name"] for p in people]})
        cleaned, _ = pipeline.validate_record(facts)
        record = pipeline.normalize_record(cleaned, source)
        company_id, action = pipeline.persist_company(db, org_id, record, raw_id, source)
        pipeline.write_lineage(db, org_id, company_id, raw_id, source, record)
        # explicit people/roles -> official people evidence
        created_people = []
        for p in people:
            norm = re.sub(r"\s+", " ", p["display_name"]).strip().lower()
            pid = "person_resa_" + pipeline.sha256_text(org_id + "|" + company_id + "|" + norm)[:22]
            db.execute(
                "INSERT INTO people(id, organization_id, display_name, job_title, company_id, source_type, "
                "match_status, confidence, is_demo, created_at, name_normalized, official_role, source_url, "
                "source_document_id, source_extraction_id, checked_at, privacy_status) "
                "VALUES(?,?,?,?,?, 'OFFICIAL', 'CONFIRMED', 1.0, 0, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE') "
                "ON CONFLICT(organization_id, company_id, name_normalized) DO UPDATE SET "
                "official_role=excluded.official_role, source_type='OFFICIAL', match_status='CONFIRMED', "
                "confidence=1.0, source_document_id=COALESCE(excluded.source_document_id, people.source_document_id), "
                "source_extraction_id=COALESCE(excluded.source_extraction_id, people.source_extraction_id), "
                "checked_at=excluded.checked_at",
                (pid, org_id, p["display_name"], p["official_role"], company_id, data.now(), norm,
                 p["official_role"], source_url, None, extraction_id, data.now()))
            eid = "pev_" + pipeline.sha256_text(pid + "|OFFICIAL_ROLE|" + source_url)[:22]
            db.execute(
                "INSERT INTO people_evidence(id, organization_id, person_id, evidence_type, source_url, "
                "source_document_id, source_extraction_id, excerpt, confidence, method, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(person_id, evidence_type, source_url) DO UPDATE SET "
                "excerpt=excluded.excerpt, confidence=1.0, method=excluded.method",
                (eid, org_id, pid, "OFFICIAL_ROLE", source_url, None, extraction_id, p["excerpt"], 1.0,
                 "RESA_EXTRACTION", data.now()))
            created_people.append({"person_id": pid, "display_name": p["display_name"], "official_role": p["official_role"]})
        audit_meta = {"source": SOURCE_ID, "source_url": source_url, "company_id": company_id,
                      "action": action, "people": len(created_people)}
    data.audit(org_id, "RESA_INGEST", "company", company_id, audit_meta)
    return {"status": "SUCCESS", "company_id": company_id, "company_name": facts.get("company_name"),
            "rcs_number": facts.get("rcs_number"), "nace": facts.get("primary_nace_code"),
            "action": action, "people_found": len(created_people), "people": created_people,
            "raw_record_id": raw_id, "signals_ready": True}


def provenance(org_id: str, company_id: str) -> dict | None:
    """Return the full RESA -> commercial provenance chain for a company."""
    company = data.company_detail(org_id, company_id)
    if not company:
        return None
    lineage = data.rows(
        "SELECT field_name, source_id, source_url, retrieved_at, method, raw_record_id, checksum, transformation "
        "FROM data_lineage WHERE organization_id=? AND entity_id=? AND source_id=? ORDER BY retrieved_at",
        (org_id, company_id, _sid(org_id)))
    raw_ids = sorted({l["raw_record_id"] for l in lineage if l.get("raw_record_id")})
    raw_records = []
    if raw_ids:
        placeholders = ",".join(["?"] * len(raw_ids))
        raw_records = data.rows(
            "SELECT id, external_id, checksum, retrieved_at, source_url, content_format, status "
            "FROM raw_records WHERE organization_id=? AND id IN (" + placeholders + ")",
            [org_id, *raw_ids])
    people = data.rows(
        "SELECT p.id, p.display_name, p.official_role, p.source_type, p.confidence, p.source_url, "
        "p.source_extraction_id, (SELECT count(*) FROM people_evidence e WHERE e.person_id=p.id) AS evidence_count "
        "FROM people p WHERE p.organization_id=? AND p.company_id=?", (org_id, company_id))
    website = data.one("SELECT status, final_url, https_status, checked_at, response_ms, page_bytes FROM digital_checks WHERE organization_id=? AND company_id=? AND channel='Website'", (org_id, company_id))
    seo = data.one("SELECT status, seo_score, checked_at FROM seo_audits WHERE organization_id=? AND company_id=?", (org_id, company_id))
    signals = data.rows("SELECT signal_type, status, severity, confidence, explanation, data_quality, last_seen_at FROM business_signals WHERE organization_id=? AND company_id=? AND status='ACTIVE'", (org_id, company_id))
    nace = None
    if company.get("primary_nace_code"):
        nace = data.one("SELECT i.code, l.label, v.status FROM nace_items_official i JOIN nace_versions_official v ON v.id=i.version_id LEFT JOIN nace_labels_official l ON l.item_id=i.id AND l.language='fr' AND l.label_type='PREF' WHERE v.version_code='2.1' AND i.is_current AND i.code=?", (company["primary_nace_code"],))
    return {
        "company": {"id": company["id"], "name": company["company_name"], "rcs_number": company.get("rcs_number"),
                    "primary_nace_code": company.get("primary_nace_code"), "website_status": company.get("website_status")},
        "source": {"id": SOURCE_ID, "name": SOURCE_NAME, "status": "REQUIRES_CONFIRMATION"},
        "lineage": lineage, "raw_records": raw_records, "people": people,
        "website": dict(website) if website else None,
        "seo": dict(seo) if seo else None,
        "nace": dict(nace) if nace else None,
        "signals": signals,
    }
