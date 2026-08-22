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
MODEL_VERSION = "nacelux-scoring-7.0"
LEVELS = {"LOW": (0, 50), "MEDIUM": (50, 75), "HIGH": (75, 90), "VERY_HIGH": (90, 101)}


def _age_days(value):
    try:
        return (date.today() - datetime.strptime(value, "%Y-%m-%d").date()).days
    except (TypeError, ValueError):
        return 9999


def _level_for(score):
    for name, (lo, hi) in LEVELS.items():
        if lo <= score < hi:
            return name.replace("_", " ")
    return "LOW"


def calculate(company, weights=None, signals=None):
    """Deterministic, evidence-backed score. Unknown data earns 0 points.
    When business signals are available (Step 6), they take priority over raw
    company fields because they are evidence-backed.
    Includes full input snapshot + SHA-256 fingerprint for exact reproducibility."""
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    sig = set(signals or [])
    factors = []

    # --- Freshness (20) ---
    age = _age_days(company.get("creation_date"))
    if "NEW_COMPANY" in sig or "RECENT_INCORPORATION" in sig:
        fr_ratio, fr_label = 1.0, "New company (signal-backed)"
    elif age <= 30: fr_ratio, fr_label = 1.0, "Very recent"
    elif age <= 90: fr_ratio, fr_label = .65, "Recent"
    elif age <= 365: fr_ratio, fr_label = .3, "Within first year"
    else: fr_ratio, fr_label = 0, "Established"
    factors.append({"key":"freshness","label":fr_label,"ratio":fr_ratio,"points":round(w["freshness"]*fr_ratio),"max":w["freshness"]})

    # --- Niche attractiveness (20) ---
    if "HIGH_VALUE_NICHE" in sig: n_ratio, n_label = 1.0, "High-value niche (signal-backed)"
    else:
        n_ratio = float(company.get("niche_attractiveness") or 0) / 100; n_label = "Niche attractiveness"
    factors.append({"key":"niche","label":n_label,"ratio":n_ratio,"points":round(w["niche"]*n_ratio),"max":w["niche"]})

    # --- Digital gap (20) ---
    if "NO_WEBSITE" in sig: d_ratio, d_label = 1.0, "No website (signal-backed)"
    elif "WEAK_WEBSITE" in sig: d_ratio, d_label = .65, "Weak website (signal-backed)"
    else:
        ws = company.get("website_status"); ds = company.get("digital_score")
        if ws == "NOT_FOUND": d_ratio, d_label = 1.0, "No website"
        elif ds is not None and ds < 40: d_ratio, d_label = .65, "Low digital score"
        elif ds is not None and ds < 70: d_ratio, d_label = .2, "Moderate digital"
        else: d_ratio, d_label = 0, "Digital presence"
    factors.append({"key":"digital_gap","label":d_label,"ratio":d_ratio,"points":round(w["digital_gap"]*d_ratio),"max":w["digital_gap"]})

    # --- SEO opportunity (15) ---
    if "WEAK_SEO" in sig:
        s_val = company.get("seo_opportunity"); s_ratio = float(s_val)/100 if isinstance(s_val,(int,float)) else .6; s_label = "Weak SEO (signal-backed)"
    else:
        s_val = company.get("seo_opportunity"); s_ratio = float(s_val or 0)/100 if s_val is not None else 0; s_label = "SEO opportunity"
    factors.append({"key":"seo_opportunity","label":s_label,"ratio":s_ratio,"points":round(w["seo_opportunity"]*s_ratio),"max":w["seo_opportunity"]})

    # --- Local presence (10) ---
    l_ratio = 1.0 if ("NO_GOOGLE_BUSINESS" in sig or company.get("google_status")=="NOT_FOUND") else 0
    factors.append({"key":"local_presence","label":"No Google Business" if l_ratio else "Local presence","ratio":l_ratio,"points":round(w["local_presence"]*l_ratio),"max":w["local_presence"]})

    # --- Decision maker (5) ---
    p_ratio = 1.0 if ("DECISION_MAKER_FOUND" in sig or company.get("decision_maker_status")=="FOUND") else 0
    factors.append({"key":"decision_maker","label":"Decision maker found" if p_ratio else "No confirmed decision maker","ratio":p_ratio,"points":round(w["decision_maker"]*p_ratio),"max":w["decision_maker"]})

    # --- Commercial potential (10) ---
    pot_ratio = float(company.get("commercial_potential") or 0)/100
    factors.append({"key":"commercial_potential","label":"Commercial potential","ratio":pot_ratio,"points":round(w["commercial_potential"]*pot_ratio),"max":w["commercial_potential"]})

    score = min(100, sum(f["points"] for f in factors))
    level = _level_for(score)

    # --- Recommended actions (deterministic, signal-driven) ---
    actions = []
    if "NO_WEBSITE" in sig or company.get("website_status")=="NOT_FOUND": actions.append("CREATE_WEBSITE")
    if "WEAK_WEBSITE" in sig: actions.append("WEBSITE_REDESIGN")
    if "WEAK_SEO" in sig: actions.append("SEO_SERVICE")
    if "NO_GOOGLE_BUSINESS" in sig: actions.append("LOCAL_SEO")
    if not actions and score < 50: actions.append("LOW_PRIORITY")
    if not actions: actions.append("MONITOR")
    action = " + ".join(actions)

    input_snapshot = {"creation_date":company.get("creation_date"),"website_status":company.get("website_status"),
        "digital_score":company.get("digital_score"),"seo_opportunity":company.get("seo_opportunity"),
        "google_status":company.get("google_status"),"decision_maker_status":company.get("decision_maker_status"),
        "niche_attractiveness":company.get("niche_attractiveness"),"commercial_potential":company.get("commercial_potential"),
        "signals":sorted(sig),"weights":w,"model_version":MODEL_VERSION}
    fingerprint = hashlib.sha256(json.dumps(input_snapshot, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    return {"score":score,"level":level,"action":action,"model_version":MODEL_VERSION,
            "provenance_fingerprint":fingerprint,"input_snapshot":input_snapshot,"factors":factors}
