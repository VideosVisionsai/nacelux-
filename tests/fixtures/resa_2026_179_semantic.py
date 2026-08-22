"""ATTACHMENT_DERIVED_SEMANTIC_FIXTURE — RESA_2026_179.931.pdf

Fixture metadata:
  fixture_type:             ATTACHMENT_DERIVED_SEMANTIC_FIXTURE
  source_filename:          RESA_2026_179.931.pdf
  original_pdf_processed:   false
  live_resa_data:           false
  arena_filesystem_access:  false
  source_confidence:        MANUALLY_REVIEWED_ATTACHMENT_CONTENT

The original PDF was NOT opened or parsed by any NACELUX tool inside the Arena
sandbox. The file was not available on disk. This fixture captures the
manually-reviewed semantic content of the attachment and is used exclusively to
validate that the parser's legal-entity rejection logic and the scoring engine's
safety rules produce correct results.

This is NOT an actual PDF integration test. It is NOT live RESA data.
No OCR coordinates, file hashes, or extraction methods are fabricated.
"""

FIXTURE_METADATA = {
    "fixture_type": "ATTACHMENT_DERIVED_SEMANTIC_FIXTURE",
    "source_filename": "RESA_2026_179.931.pdf",
    "original_pdf_processed": False,
    "live_resa_data": False,
    "arena_filesystem_access": False,
    "source_confidence": "MANUALLY_REVIEWED_ATTACHMENT_CONTENT",
}

# ── Company facts (manually reviewed from the attachment) ─────────────────────

COMPANY = {
    "legal_name": "ROUNDTABLE LUX SCSP NEWCO 86 USD",
    "legal_form": "SCSP",
    "formation_date": "2026-08-18",
    "registered_address": "7, rue Robert Stümper, L-2557 Luxembourg",
}

# ── Related legal entities (NOT natural persons) ─────────────────────────────

RELATED_ENTITIES = [
    {
        "legal_name": "Roundtable Lux GP",
        "rcs_number": "B266208",
        "role": "GENERAL_PARTNER",
        "french_role": "associé solidairement responsable",
        "entity_type": "LEGAL_ENTITY",
        "natural_person": False,
    },
    {
        "legal_name": "Roundtable Lux Ops",
        "rcs_number": "B266215",
        "role": "MANAGER",
        "french_role": "gérant",
        "entity_type": "LEGAL_ENTITY",
        "is_partner": False,
        "natural_person": False,
    },
]

# ── Natural persons extracted from the publication ───────────────────────────
# EMPTY — no verified natural persons are present in this publication.

NATURAL_PERSONS: list = []

# ── Expected signals ─────────────────────────────────────────────────────────

EXPECTED_SIGNALS = {
    "DECISION_MAKER_FOUND": {"status": "UNKNOWN", "points": 0,
                             "reason": "No verified natural person is available."},
    "HIGH_VALUE_NICHE": {"status": "UNKNOWN", "points": 0,
                         "reason": "No verified NACELUX/NACE classification is available."},
    "NO_WEBSITE": {"status": "NOT_CHECKED", "points": 0},
    "WEAK_SEO": {"status": "NOT_CHECKED", "points": 0},
    "NO_GOOGLE_BUSINESS": {"status": "NOT_CHECKED", "points": 0},
}
