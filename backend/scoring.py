import hashlib, json
from datetime import date, datetime

DEFAULT_WEIGHTS = {
    "freshness": 20,
    "niche": 20,
    "digital_gap": 20,
    "seo_opportunity": 15,
    "local_presence": 10,
    "decision_maker": 5,
    "commercial_potential": 10,
}
MODEL_VERSION = "nacelux-scoring-2.1"


def _age_days(value):
    try:
        return (date.today() - datetime.strptime(value, "%Y-%m-%d").date()).days
    except (TypeError, ValueError):
        return 9999


def calculate(company, weights=None):
    """Deterministic score. Unknown data earns no points; it is never guessed.
    Includes full input snapshot and cryptographic provenance fingerprint for exact reproducibility.
    """
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    factors = []

    age = _age_days(company.get("creation_date"))
    freshness_ratio = 1 if age <= 30 else .65 if age <= 90 else .3 if age <= 365 else 0
    factors.append(("freshness", "Recent company" if age <= 90 else "Company freshness", round(w["freshness"] * freshness_ratio)))

    niche_ratio = float(company.get("niche_attractiveness") or 0) / 100
    factors.append(("niche", "Niche attractiveness", round(w["niche"] * niche_ratio)))

    website_status = company.get("website_status")
    digital_score = company.get("digital_score")
    # Missing measurement is unknown, not automatically a digital gap.
    digital_ratio = 1 if website_status == "NOT_FOUND" else .65 if digital_score is not None and digital_score < 40 else .2 if digital_score is not None and digital_score < 70 else 0
    factors.append(("digital_gap", "No website" if website_status == "NOT_FOUND" else "Digital gap", round(w["digital_gap"] * digital_ratio)))

    seo = company.get("seo_opportunity")
    seo_ratio = float(seo or 0) / 100
    factors.append(("seo_opportunity", "SEO opportunity" if seo is not None else "SEO not assessed", round(w["seo_opportunity"] * seo_ratio)))

    gb = company.get("google_status")
    local_ratio = 1 if gb == "NOT_FOUND" else 0
    factors.append(("local_presence", "No Google Business profile" if gb == "NOT_FOUND" else "Local presence", round(w["local_presence"] * local_ratio)))

    people = company.get("decision_maker_status")
    people_ratio = 1 if people == "FOUND" else 0
    factors.append(("decision_maker", "Decision maker found" if people == "FOUND" else "Decision maker not confirmed", round(w["decision_maker"] * people_ratio)))

    potential_ratio = float(company.get("commercial_potential") or 0) / 100
    factors.append(("commercial_potential", "Commercial potential", round(w["commercial_potential"] * potential_ratio)))

    score = min(100, sum(points for _, _, points in factors))
    level = "VERY HIGH" if score >= 90 else "HIGH" if score >= 75 else "MEDIUM" if score >= 50 else "LOW"

    if website_status == "NOT_FOUND":
        action = "CREATE WEBSITE"
        if seo_ratio >= .6: action += " + SEO"
    elif gb == "NOT_FOUND" and seo_ratio >= .55:
        action = "LOCAL SEO"
    elif seo_ratio >= .65:
        action = "SEO SERVICE"
    elif digital_score is not None and digital_score < 45:
        action = "WEBSITE REDESIGN"
    elif score < 50:
        action = "LOW PRIORITY"
    else:
        action = "MONITOR"

    # Input snapshot and cryptographic fingerprint for reproducibility
    input_snapshot = {
        "creation_date": company.get("creation_date"),
        "website_status": company.get("website_status"),
        "digital_score": company.get("digital_score"),
        "seo_opportunity": company.get("seo_opportunity"),
        "google_status": company.get("google_status"),
        "decision_maker_status": company.get("decision_maker_status"),
        "niche_attractiveness": company.get("niche_attractiveness"),
        "commercial_potential": company.get("commercial_potential"),
        "weights": w,
        "model_version": MODEL_VERSION
    }
    fingerprint = hashlib.sha256(json.dumps(input_snapshot, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    return {
        "score": score,
        "level": level,
        "action": action,
        "model_version": MODEL_VERSION,
        "provenance_fingerprint": fingerprint,
        "input_snapshot": input_snapshot,
        "factors": [{"key": key, "label": label, "points": points, "max": w[key]} for key, label, points in factors]
    }
