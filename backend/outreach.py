"""Commercial outreach preparation layer (Étape 9).

Builds a personalized commercial opportunity WITHOUT automatically contacting
anyone. Uses only verified facts from Steps 1-8. No invented data.

Flow: Opportunity → verified facts → commercial reasoning → message draft (LLM
or deterministic fallback) → human review → READY_TO_SEND.
"""
from __future__ import annotations
import hashlib, json, uuid
from datetime import datetime, timezone

import database as data

OUTREACH_PROMPT_VERSION = "outreach-v1"

# Contact-safety: only these role types qualify as a confirmed decision maker.
VERIFIED_DECISION_ROLES = {"MANAGER", "DIRECTOR", "PARTNER"}
# These are NOT decision makers — must not be presented as such.
NON_DECISION_ROLES = {"NON_MANAGER", "SIGNATORY_ONLY", "PERSON_MENTIONED", "UNKNOWN"}


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_verified_contact(org_id: str, company_id: str) -> dict | None:
    """Return a verified decision-maker contact for a company, or None.
    Only MANAGER/DIRECTOR/PARTNER role types with APPROVED review (or OFFICIAL
    source_type) qualify. SIGNATORY_ONLY / PERSON_MENTIONED / UNKNOWN never qualify."""
    with data.connect() as db:
        people = [dict(r) for r in db.execute(
            "SELECT id, display_name, job_title, official_role, role_type, source_type, "
            "review_status, confidence, profile_url, evidence_excerpt, source_page "
            "FROM people WHERE organization_id=? AND company_id=? AND privacy_status='ACTIVE'",
            (org_id, company_id)).fetchall()]
    for p in people:
        role_type = p.get("role_type") or ""
        # Must be a verified decision role
        if role_type not in VERIFIED_DECISION_ROLES:
            continue
        # Must be OFFICIAL or APPROVED review
        if p.get("source_type") == "OFFICIAL" or p.get("review_status") == "APPROVED":
            return {
                "person_id": p["id"], "name": p["display_name"],
                "role": p.get("official_role") or p.get("job_title"),
                "role_type": role_type,
                "verification": "VERIFIED",
                "confidence": p.get("confidence"),
                "evidence_excerpt": p.get("evidence_excerpt"),
                "source_page": p.get("source_page"),
                "email": None,  # only if stored/verified; never invented
                "phone": None,
                "profile_url": p.get("profile_url"),
            }
    return None


def build_reasoning(opportunity: dict, company: dict, signals: list, contact: dict | None) -> dict:
    """Deterministic, evidence-backed commercial reasoning. NO LLM. NO unsupported claims.
    Answers WHY_THIS_COMPANY based only on existing Step 7 data."""
    reasons = []
    score = opportunity.get("score", 0)
    level = opportunity.get("level", "")
    action = opportunity.get("recommended_action") or opportunity.get("action", "")

    active = {s["signal_type"] for s in signals if s.get("status") == "ACTIVE"}

    if "NO_WEBSITE" in active:
        reasons.append({"factor": "NO_WEBSITE", "claim": "The company has no verified website.",
                        "evidence": "Completed website discovery found no evidence-backed official website."})
    if "WEAK_WEBSITE" in active:
        reasons.append({"factor": "WEAK_WEBSITE", "claim": "The company's website has measurable weaknesses.",
                        "evidence": "Digital footprint check observed technical weaknesses."})
    if "WEAK_SEO" in active:
        reasons.append({"factor": "WEAK_SEO", "claim": "The company's SEO has measurable gaps.",
                        "evidence": "Completed SEO audit identified specific findings."})
    if "NO_GOOGLE_BUSINESS" in active:
        reasons.append({"factor": "NO_GOOGLE_BUSINESS", "claim": "The company lacks a Google Business profile.",
                        "evidence": "Completed Google Places check found no qualified profile."})
    if "DECISION_MAKER_FOUND" in active:
        reasons.append({"factor": "DECISION_MAKER_FOUND", "claim": "A verified decision maker is identified.",
                        "evidence": "Official RESA publication or high-confidence public profile."})
    if "HIGH_VALUE_NICHE" in active:
        reasons.append({"factor": "HIGH_VALUE_NICHE", "claim": "The company operates in a high-value niche.",
                        "evidence": "NACELUX taxonomy or official NACE classification."})
    if "NEW_COMPANY" in active or "RECENT_INCORPORATION" in active:
        reasons.append({"factor": "NEW_COMPANY", "claim": "The company was recently incorporated.",
                        "evidence": "Official creation/incorporation date."})

    if score >= 75:
        reasons.append({"factor": "HIGH_SCORE", "claim": f"The opportunity score is {score}/100 ({level}).",
                        "evidence": "Step 7 deterministic scoring engine."})

    if contact:
        reasons.append({"factor": "CONTACT_AVAILABLE",
                        "claim": f"A verified contact ({contact['name']}, {contact['role']}) is available.",
                        "evidence": f"Role type: {contact['role_type']}, verification: {contact['verification']}."})
    else:
        reasons.append({"factor": "NO_VERIFIED_CONTACT",
                        "claim": "No verified natural-person decision maker is available.",
                        "evidence": "The manager/partner identified may be a legal entity, or no person was found."})

    return {
        "why_this_company": reasons,
        "action": action,
        "score": score,
        "level": level,
        "total_reasons": len(reasons),
    }


def draft_message_deterministic(reasoning: dict, company: dict, contact: dict | None) -> dict:
    """Deterministic message draft (no LLM). Uses only verified facts.
    Every claim references evidence."""
    name = company.get("company_name", "your company")
    contact_name = contact["name"] if contact else None
    action = reasoning.get("action", "MONITOR")

    greeting = f"Dear {contact_name}," if contact_name else "Dear Sir/Madam,"
    subject_parts = []
    body_parts = []

    for r in reasoning.get("why_this_company", []):
        if r["factor"] == "NO_WEBSITE":
            subject_parts.append("Website opportunity")
            body_parts.append(f"Our analysis indicates that {name} currently does not have a verified website.")
        elif r["factor"] == "WEAK_SEO":
            body_parts.append(f"We identified specific SEO improvement opportunities for {name}.")
        elif r["factor"] == "HIGH_VALUE_NICHE":
            body_parts.append(f"{name} operates in a sector we classify as high-value.")

    if not subject_parts:
        subject_parts.append(f"Introduction — {name}")

    subject = " — ".join(subject_parts[:2])
    body = f"{greeting}\n\n" + "\n".join(body_parts) + "\n\nWe would welcome the opportunity to discuss this with you.\n\nBest regards"

    input_hash = hashlib.sha256(json.dumps(reasoning, sort_keys=True, default=str).encode()).hexdigest()
    output_hash = hashlib.sha256((subject + body).encode()).hexdigest()

    return {
        "subject": subject,
        "greeting": greeting,
        "body": body,
        "claims": [{"claim": r["claim"], "evidence_ref": r["evidence"]} for r in reasoning.get("why_this_company", [])],
        "evidence_references": [r["factor"] for r in reasoning.get("why_this_company", [])],
        "confidence": 1.0,  # deterministic = fully grounded
        "needs_human_review": True,  # ALWAYS requires human review
        "provider": "deterministic",
        "model": "nacelux-deterministic-outreach",
        "prompt_version": OUTREACH_PROMPT_VERSION,
        "input_hash": input_hash,
        "output_hash": output_hash,
    }


def draft_message_llm(provider, reasoning: dict, company: dict, contact: dict | None) -> dict:
    """LLM-backed message draft. Only relevant evidence excerpts are sent (never
    the full PDF). If the provider is not configured, raises AI_NOT_CONFIGURED."""
    import llm_provider as lp
    system = (
        "You draft a concise, professional commercial outreach message for a Luxembourg "
        "business opportunity. Rules:\n"
        "1. Use ONLY the facts provided below. Do not invent any information.\n"
        "2. Do not invent email addresses, phone numbers, or website URLs.\n"
        "3. Do not make claims not supported by the provided evidence.\n"
        "4. Do not invent person details. Use the provided contact name or 'Sir/Madam'.\n"
        "5. Return ONLY JSON with keys: subject, greeting, body, claims (list of {claim, evidence_ref}), "
        "evidence_references (list), confidence (0-1), needs_human_review (always true)."
    )
    context = json.dumps({
        "company_name": company.get("company_name"),
        "action": reasoning.get("action"),
        "reasons": reasoning.get("why_this_company"),
        "contact_name": contact["name"] if contact else None,
        "contact_role": contact["role"] if contact else None,
    }, ensure_ascii=False, default=str)
    raw = provider.complete(system, f"Evidence context:\n{context}\n\nReturn JSON.")
    parsed = lp._extract_json(raw)
    # Validate: every claim must reference a provided evidence factor
    provided_factors = {r["factor"] for r in reasoning.get("why_this_company", [])}
    for claim in parsed.get("claims", []):
        ref = claim.get("evidence_ref", "")
        if ref and ref not in provided_factors:
            raise lp.LLMError(f"REJECT: LLM claim references unsupported evidence: {ref}")
    input_hash = hashlib.sha256(json.dumps(reasoning, sort_keys=True, default=str).encode()).hexdigest()
    output_hash = hashlib.sha256(json.dumps(parsed, sort_keys=True, default=str).encode()).hexdigest()
    parsed.update({
        "provider": provider.name, "model": provider.model, "prompt_version": OUTREACH_PROMPT_VERSION,
        "input_hash": input_hash, "output_hash": output_hash, "needs_human_review": True,
    })
    return parsed


def prepare_outreach(org_id: str, company_id: str) -> dict:
    """Full outreach preparation for one opportunity. Does NOT send anything.
    Returns reasoning + draft (deterministic or LLM) + contact + review status."""
    company = data.company_detail(org_id, company_id)
    if not company:
        return {"status": "NOT_FOUND", "error_code": "COMPANY_NOT_FOUND"}

    score_data = data.one(
        "SELECT score, level, recommended_action, model_version, fingerprint, calculated_at "
        "FROM opportunity_scores WHERE organization_id=? AND company_id=?",
        (org_id, company_id))
    if not score_data:
        return {"status": "NO_SCORE", "error_code": "OPPORTUNITY_NOT_SCORED",
                "message": "Run scoring before preparing outreach."}

    signals = data.rows(
        "SELECT signal_type, status, severity, confidence, explanation, data_quality "
        "FROM business_signals WHERE organization_id=? AND company_id=?",
        (org_id, company_id))

    contact = get_verified_contact(org_id, company_id)
    reasoning = build_reasoning(dict(score_data), company, signals, contact)

    # Draft: LLM if configured, deterministic otherwise (never simulated)
    import llm_provider as lp
    provider = lp.get_provider()
    if provider:
        try:
            draft = draft_message_llm(provider, reasoning, company, contact)
        except lp.LLMError as exc:
            draft = draft_message_deterministic(reasoning, company, contact)
            draft["llm_error"] = str(exc)
    else:
        draft = draft_message_deterministic(reasoning, company, contact)

    return {
        "status": "SUCCESS",
        "company": {
            "id": company["id"], "name": company.get("company_name"),
            "legal_form": company.get("legal_form"), "rcs_number": company.get("rcs_number"),
            "website_status": company.get("website_status"),
        },
        "score": dict(score_data),
        "contact": contact,
        "reasoning": reasoning,
        "draft": draft,
        "ai_status": "AI_GENERATED" if draft.get("provider") not in ("deterministic",) else "DETERMINISTIC",
        "review_status": "DRAFT",
        "ready_to_send": False,  # NEVER automatically ready
    }
