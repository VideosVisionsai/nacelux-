"""LLM provider abstraction for RESA PDF structuring.

The LLM is NEVER the source of truth. The source of truth is the original PDF
page text + coordinates + SHA-256. The LLM only structures information that
deterministic rules have already identified as a candidate passage. If the LLM
invents information not present in the excerpt, the output is REJECTED.

Providers: OpenAI, Anthropic, local (Ollama/OpenAI-compatible). Configured via
backend env only — no keys in frontend, Git, or API responses.

If no provider is configured: AI_NOT_CONFIGURED. The pipeline never simulates a
response.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import urllib.error
import urllib.request

PROMPT_VERSION = "resa-person-extract-1"

SCHEMA_KEYS = ("person_name", "role", "role_confirmed", "evidence_quote", "confidence", "needs_human_review")

# Roles that are definitively a management/decision role.
MANAGER_ROLES = {"gérant", "gérante", "administrateur", "administratrice", "directeur", "directrice", "président", "présidente", "manager"}
# "signataire" / "mandataire" are NOT management roles — they need human review.
NON_MANAGER_ROLES = {"signataire", "mandataire", "représentant", "représentante", "représentant légal", "associé", "associée"}

SYSTEM_PROMPT = (
    "You extract person and role information from RESA (Luxembourg Business Registers) "
    "publication excerpts. Rules:\n"
    "1. Extract ONLY information explicitly present in the excerpt.\n"
    "2. If the person name or role is NOT present, return null for that field.\n"
    "3. 'evidence_quote' MUST be a verbatim substring of the excerpt.\n"
    "4. 'role_confirmed' is true ONLY if the excerpt explicitly states the role "
    "(e.g. 'est nommé gérant'). A person merely mentioned is NOT confirmed.\n"
    "5. 'signataire' or 'mandataire' is NOT a management role.\n"
    "6. 'needs_human_review' is true if the role is ambiguous or uncertain.\n"
    "7. 'confidence' is a number 0.0–1.0.\n"
    "8. Never invent, deduce, or complete information. Return JSON only."
)


class LLMError(Exception):
    pass


class LLMProvider:
    name = "base"

    def __init__(self):
        self.model = ""
        self.model_version = ""

    def configured(self) -> bool:
        return False

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError


def _looks_configured(value: str) -> bool:
    return bool(value) and not any(m in value.lower() for m in ("replace-with", "your_", "sk-", "placeholder"))


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.model_version = self.model

    def configured(self) -> bool:
        return _looks_configured(self.api_key)

    def complete(self, system_prompt, user_prompt):
        body = json.dumps({"model": self.model, "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], "temperature": 0, "max_tokens": 500}).encode()
        req = urllib.request.Request(f"{self.base}/chat/completions", data=body, method="POST",
                                     headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
        except (urllib.error.HTTPError, urllib.error.URLError, KeyError) as exc:
            raise LLMError(f"OpenAI request failed: {exc}") from exc


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.base = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
        self.model_version = self.model

    def configured(self) -> bool:
        return _looks_configured(self.api_key)

    def complete(self, system_prompt, user_prompt):
        body = json.dumps({"model": self.model, "max_tokens": 500, "system": system_prompt,
                           "messages": [{"role": "user", "content": user_prompt}]}).encode()
        req = urllib.request.Request(f"{self.base}/v1/messages", data=body, method="POST",
                                     headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                                               "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            return data["content"][0]["text"]
        except (urllib.error.HTTPError, urllib.error.URLError, KeyError, IndexError) as exc:
            raise LLMError(f"Anthropic request failed: {exc}") from exc


class LocalLLMProvider(LLMProvider):
    name = "local"

    def __init__(self):
        self.base = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/")
        self.api_key = os.getenv("LLM_API_KEY", "")
        self.model = os.getenv("LLM_MODEL", "llama3")
        self.model_version = self.model

    def configured(self) -> bool:
        return bool(self.base)

    def complete(self, system_prompt, user_prompt):
        body = json.dumps({"model": self.model, "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], "temperature": 0, "max_tokens": 500}).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(f"{self.base}/chat/completions", data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
        except (urllib.error.HTTPError, urllib.error.URLError, KeyError) as exc:
            raise LLMError(f"Local LLM request failed: {exc}") from exc


def get_provider():
    """Return the configured provider, or None (AI_NOT_CONFIGURED)."""
    name = os.getenv("LLM_PROVIDER", "").lower()
    providers = {"openai": OpenAIProvider, "anthropic": AnthropicProvider,
                 "local": LocalLLMProvider, "ollama": LocalLLMProvider, "openai_compatible": LocalLLMProvider}
    cls = providers.get(name)
    if not cls:
        return None
    p = cls()
    return p if p.configured() else None


def is_configured() -> bool:
    return get_provider() is not None


def status() -> dict:
    p = get_provider()
    if p:
        return {"status": "READY", "provider": p.name, "model": p.model, "prompt_version": PROMPT_VERSION}
    return {"status": "AI_NOT_CONFIGURED", "provider": os.getenv("LLM_PROVIDER", "none"),
            "prompt_version": PROMPT_VERSION}


def build_prompt(excerpt: str) -> tuple[str, str]:
    return SYSTEM_PROMPT, f"Excerpt:\n---\n{excerpt}\n---\nReturn ONLY JSON with keys: {', '.join(SCHEMA_KEYS)}"


def _extract_json(raw: str) -> dict:
    """Extract a JSON object from a raw LLM string (tolerates code fences)."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if brace:
            text = brace.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"LLM output is not valid JSON: {exc}") from exc


def classify_role_type(role: str | None) -> str:
    """Classify a role into MANAGER / NON_MANAGER / UNKNOWN."""
    if not role:
        return "UNKNOWN"
    r = role.strip().lower()
    if r in MANAGER_ROLES:
        return "MANAGER"
    if r in NON_MANAGER_ROLES or "signataire" in r or "mandataire" in r:
        return "NON_MANAGER"
    return "UNKNOWN"


def validate_extraction(output: dict, excerpt: str) -> dict:
    """Validate an LLM extraction output against the excerpt. REJECT hallucinations.

    Rules:
    - evidence_quote MUST be a verbatim substring of the excerpt (if present).
    - If role_confirmed is true but evidence_quote is absent or not found -> REJECT.
    - 'signataire'/'mandataire' -> role_type NON_MANAGER, never MANAGER.
    - Missing fields -> None / UNKNOWN, never invented.
    """
    if not isinstance(output, dict):
        raise LLMError("LLM output is not a dict")
    result = {k: output.get(k) for k in SCHEMA_KEYS}
    # Normalize types
    result["person_name"] = str(result["person_name"]).strip() if result["person_name"] else None
    result["role"] = str(result["role"]).strip().lower() if result["role"] else None
    result["evidence_quote"] = str(result["evidence_quote"]).strip() if result["evidence_quote"] else None
    result["role_confirmed"] = bool(result["role_confirmed"])
    result["needs_human_review"] = bool(result["needs_human_review"])
    try:
        result["confidence"] = round(float(result["confidence"]), 3) if result["confidence"] is not None else 0.0
    except (TypeError, ValueError):
        result["confidence"] = 0.0
    # Hallucination check: evidence_quote must be in excerpt
    if result["evidence_quote"] and excerpt:
        if result["evidence_quote"] not in excerpt:
            raise LLMError("HALLUCINATION: evidence_quote not found in excerpt")
    if result["role_confirmed"] and not result["evidence_quote"]:
        raise LLMError("REJECT: role_confirmed without evidence_quote")
    # signataire/mandataire are NOT management roles
    result["role_type"] = classify_role_type(result["role"])
    if result["role_type"] == "NON_MANAGER":
        result["needs_human_review"] = True
    return result


def extract_with_llm(provider, excerpt: str) -> dict:
    """Run the LLM on an excerpt, validate, and return (result + audit metadata).

    Never call this without checking is_configured() first.
    """
    system, user = build_prompt(excerpt)
    raw = provider.complete(system, user)
    raw_output = _extract_json(raw)
    validated = validate_extraction(raw_output, excerpt)
    input_hash = hashlib.sha256(excerpt.encode()).hexdigest()
    output_hash = hashlib.sha256(json.dumps(validated, sort_keys=True, default=str).encode()).hexdigest()
    return {
        "result": validated,
        "audit": {
            "provider": provider.name, "model": provider.model, "model_version": provider.model_version,
            "prompt_version": PROMPT_VERSION, "input_hash": input_hash, "output_hash": output_hash,
            "raw_output": raw_output, "confidence": validated.get("confidence", 0.0),
            "needs_human_review": validated.get("needs_human_review", False),
        },
    }
