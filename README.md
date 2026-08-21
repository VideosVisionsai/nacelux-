# NACELUX Rev. 2.1

Functional MVP foundation for **Luxembourg Business Opportunity Intelligence**.

## What is implemented

- Responsive B2B SaaS dashboard and navigation
- Functional REST API (Python standard library)
- Persistent SQLite development database; PostgreSQL production schema included
- Supabase Auth gateway: signup, login, email recovery, password update and logout
- Automatic first-login organization creation with OWNER role
- Organization-scoped data access and OWNER / ADMIN / MEMBER memberships
- Company search and compound filters (location, NACE, niche, website, score)
- Versioned, evidence-backed Business Signal Engine with activation/deactivation history
- Explainable opportunity scoring and recommended actions
- Company detail view with provenance, signals, digital footprint and score breakdown
- Opportunities pipeline and prospect creation
- Functional People, Digital Footprint, SEO, NACE, Categories, Niches, RESA, Reports and Settings views
- Compliant People Engine: official RESA roles, evidence lineage, high-confidence public professional matching, retention and GDPR request workflow
- Explainable website discovery with confidence, documented search-provider adapters, SSRF protection and candidate lineage
- LinkedIn company, Google Business and Facebook public-footprint checks with strict FOUND / NOT_FOUND / UNKNOWN / NOT_CHECKED semantics
- Official Eurostat NACE Rev. 2.1 RDF import: 22 sections, 87 divisions, 287 groups, 651 classes, FR/DE/EN labels, explanatory notes and Rev. 2 → Rev. 2.1 mappings
- Admin-editable scoring weights with validation and automatic recalculation
- Data-source health, auditable jobs and explicit connector states
- Controlled LBR/RESA public-page connector with robots checks, HTTP-first parsing, Playwright fallback, captcha blocking and idempotent metadata
- RESA → validated PDF → SHA-256 deduplication → local or private Supabase object storage
- Stored PDF → native page text → quality checks → selective FR/DE/EN Tesseract OCR fallback
- Import validation/deduplication preview API
- Report history and CSV export using the current filters
- Development fixtures are isolated from production; production fails closed if PostgreSQL or Supabase Auth is unavailable

## Run

```bash
cd nacelux
python3 backend/app.py
```

Open `http://localhost:8000`. In Arena the server binds to `0.0.0.0` for Live Preview.

## Architecture

```text
frontend (HTML/CSS/JS SPA)
       ↓ /api/v1
HTTP API + tenant guard
       ↓
services (scoring, provenance, exports)
       ↓
Explicit SQLite development adapter / PostgreSQL production runtime with TLS
       ↓
connectors (LBR/RESA, Eurostat — disabled until configured and verified)
```

Development can run with the standard-library SQLite adapter; the production image installs psycopg, PDF/OCR dependencies and requires PostgreSQL over TLS. `database/postgresql_schema.sql` documents the relational design, while additive deployment migrations install the active production schema and RLS policies.

## External integrations

- **LBR/RESA:** no undocumented API is assumed. Connector is `NOT_CONNECTED`; implementation requires a terms/robots review and controlled Playwright browser adapter.
- **Eurostat/NACE:** official catalogue base URLs are configuration only. No endpoint is fabricated. Import remains disabled until a precise official dataset/export endpoint is selected and integration-tested.
- **SEO / website checks:** local analyzer interface is prepared; no external service or result is simulated.

## Security notes

Development may use seeded fixtures, but production requires Supabase Auth, HttpOnly/Secure/SameSite cookies, CSRF protection, PostgreSQL TLS and RLS tenant context. Production startup fails closed and never creates a development workspace. Secrets belong server-side only.

## Key directories

- `backend/app.py` — API/router and static server
- `backend/database.py` — schema, seed and tenant-scoped queries
- `backend/scoring.py` — deterministic, explainable opportunity engine
- `frontend/` — responsive SPA
- `database/postgresql_schema.sql` — SaaS-ready production schema
- `docs/ARCHITECTURE.md` — decisions, dependencies, roadmap and integration boundaries
