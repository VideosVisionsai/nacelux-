# NACELUX — Rapport : RESA PDF + OCR + AI/LLM + Human Validation

Date : 2026-08-22 · Branche : `arena/01a0270b-nacelux` · Commit : `875e222`

**Réutilisation totale** des composants existants (Étapes 1–6 + RESA pipeline + PDF reinforcement). **Aucune donnée PDF/personne/rôle/URL/preuve/LLM inventée.**

## Outils réellement installés
| Outil | Version | Statut |
|---|---|---|
| PyMuPDF | 1.28.2 | **VERIFIED** (native + blocks) |
| reportlab | (test PDF generation) | **VERIFIED** |
| OCRmyPDF | — | **NOT INSTALLED** (REQUIRES_CONFIGURATION) |
| Tesseract | — | **NOT INSTALLED** (REQUIRES_CONFIGURATION) |
| Ghostscript | — | **NOT INSTALLED** (REQUIRES_CONFIGURATION) |
| Poppler/pdftotext | — | **NOT INSTALLED** (REQUIRES_CONFIGURATION) |
| LLM (OpenAI/Anthropic/Local) | — | **AI_NOT_CONFIGURED** (no keys; never simulated) |
| RESA (www.lbr.lu) | — | **REQUIRES_CONFIGURATION** (unreachable) |

## Pipeline PDF
`RESA → PDF → validation (magic/size/pages) → SHA-256 → PyMuPDF natif (prioritaire) → si insuffisant : OCRmyPDF + Tesseract → fallback Poppler → extraction par page + blocs/coordonnées → règles déterministes → AI/LLM structuration → validation hallucination → evidence originale → validation humaine → company matching → people evidence → website → digital → SEO → NACE → signals → prospect`

## Extraction par page + blocs/coordonnées — **VERIFIED**
PyMuPDF `get_text('blocks')` → par page : `{page_number, blocks: [{x0, y0, x1, y1, text, block_no}]}`. Coordonnées vérifiées sur un PDF réel reportlab (chaque bloc a x0/y0/x1/y1 de type float). Le texte natif n'est **jamais** remplacé silencieusement par OCR.

## OCR — **REQUIRES_CONFIGURATION**
OCRmyPDF + Tesseract + Ghostscript non installables ici (apt bloqué). Dockerfile porte déjà Tesseract fra/deu/eng + ghostscript + qpdf. **Pas de luxembourgeois** (aucune donnée Tesseract `ltz` installée ; non prétendu). `has_ocrmypdf()→False` ; `run_ocrmypdf` lève REQUIRES_CONFIGURATION.

## Fallback Poppler — **REQUIRES_CONFIGURATION**
`has_poppler()→False` (pdftotext absent). Code présent (`native_pages_pdftotext`), exécute pdftotext si installé, sinon REQUIRES_CONFIGURATION. **Non utilisé par défaut** ; réservé au cas où PyMuPDF échoue.

## LLM Provider — **VERIFIED** (logique) · **AI_NOT_CONFIGURED** (pas de clé)
`backend/llm_provider.py` :
- Abstraction `LLMProvider` : `OpenAIProvider`, `AnthropicProvider`, `LocalLLMProvider` (Ollama/OpenAI-compatible). `get_provider()` retourne `None` sans clé → `AI_NOT_CONFIGURED`. Jamais simulé.
- `validate_extraction(output, excerpt)` : rejet d'hallucination (evidence_quote doit être **verbatim** dans l'extrait) ; `role_confirmed` sans evidence → REJECT ; `signataire`/`mandataire` → `role_type=NON_MANAGER` + `needs_human_review=True` (jamais considérés comme gérant) ; champs absents → `None`/`UNKNOWN`.
- `extract_with_llm` produit `input_hash` (SHA-256 de l'extrait) + `output_hash` (SHA-256 de la sortie validée) + `prompt_version` + provider/model/model_version.
- Schéma strict : `{person_name, role, role_confirmed, evidence_quote, confidence, needs_human_review}`.
- **Le LLM n'est jamais la source de vérité** : la source reste PDF + page + texte original + coordonnées + SHA-256.

## AI Audit — **VERIFIED**
Table `ai_extractions` (migration 0020) : provider, model, model_version, prompt_version, input_hash, output_hash, raw_output (jsonb), normalized (jsonb), evidence_quote, confidence, needs_human_review, status (PENDING/APPLIED/REJECTED), rejection_reason. RLS tenant-scoped. **L'output IA n'est jamais une evidence.**

## Personnes / rôles — **VERIFIED**
Rôles explicitement étiquetés uniquement (gérant/gérante, administrateur/administratrice, associé/associée, mandataire, représentant, signataire…). **signataire ≠ gérant** (testé). Chaque personne : person_name, role, role_type (MANAGER/NON_MANAGER/UNKNOWN), role_confirmed, needs_human_review, confidence, page, evidence_excerpt, coordonnées (x0/y0/x1/y1), block_text, extraction_method.

## Validation humaine — **VERIFIED**
`PENDING_REVIEW / APPROVED / REJECTED`. POST review enregistre reviewer (session), reviewed_at, décision, previous_value (audit), commentaire. Preuve originale (people_evidence + ai_extractions raw_output) jamais supprimée. Une information ambiguë ne devient jamais VERIFIED parce qu'un LLM l'a proposée.

## Tests — **207 passed, 0 failed, 21 skipped**
LLM suite (17) : schema valide, hallucination rejetée, role_confirmed sans evidence rejeté, signataire≠gérant (NON_MANAGER + human review), missing→NULL, JSON parsing (code fences), input/output hash déterministes, AI_NOT_CONFIGURED, coordonnées de blocs, Poppler REQUIRES_CONFIGURATION, pas de secrets.

## Statuts
| Élément | Statut |
|---|---|
| PyMuPDF natif + blocs/coordonnées | **VERIFIED** |
| LLM abstraction + validation + hallucination rejection | **VERIFIED** |
| AI audit (input_hash/output_hash/prompt_version) | **VERIFIED** |
| Person/role extraction + signataire≠gérant | **VERIFIED** |
| Validation humaine (PENDING/APPROVED/REJECTED) | **VERIFIED** |
| OCR (OCRmyPDF + Tesseract) | **REQUIRES_CONFIGURATION** |
| Poppler/pdftotext fallback | **REQUIRES_CONFIGURATION** |
| LLM réel (call API) | **AI_NOT_CONFIGURED** (no keys; never simulated) |
| RESA réel | **REQUIRES_CONFIGURATION** (injoignable) |
| End-to-end RESA réel → prospect | **NOT VERIFIED** |

## Données
**AUCUNE DONNÉE PDF/PERSONNE/RÔLE/PREUVE/LLM INVENTÉE.** OCR non simulé. LLM non simulé. RESA non simulé. Fixtures test-only.

## Limitations
- **REQUIRES_CONFIGURATION** : OCR (binaires absents), Poppler (absent), RESA réel (injoignable).
- **AI_NOT_CONFIGURED** : LLM (aucune clé API dans l'environnement). Le code provider est prêt (OpenAI/Anthropic/Local) ; dès qu'une clé est configurée via le secret manager, `get_provider()` l'utilise.
- **NOT VERIFIED** : extraction end-to-end sur un vrai PDF RESA + LLM réel (source RESA injoignable).
- Scoring commercial : non développé (Étape 7, pas commencé).

---

ARRÊT ici : pas de scoring, pas de Google Business, pas d'emails, pas de CRM avancé. J'attends la validation.
