# NACELUX internal API v1

All business endpoints are scoped by the authenticated organization. The Arena MVP accepts `X-Organization-ID` only for the seeded demo tenant; production replaces this with a server-derived session context.

## Read endpoints

- `GET /api/v1/session`
- `GET /api/v1/dashboard`
- `GET /api/v1/companies` — search, canton, municipality, NACE, category, niche, website, level, minimum score and recency filters
- `GET /api/v1/companies/{id}`
- `GET /api/v1/opportunities`
- `GET /api/v1/prospects`
- `GET /api/v1/people`
- `GET /api/v1/digital`
- `GET /api/v1/seo`
- `GET /api/v1/nace`
- `GET /api/v1/taxonomy`
- `GET /api/v1/resa`
- `GET /api/v1/sources`
- `GET /api/v1/reports`
- `GET /api/v1/logs`
- `GET /api/v1/settings`
- `GET /api/v1/export/companies.csv`

## Commands

- `POST /api/v1/prospects`
- `POST /api/v1/jobs`
- `POST /api/v1/reports`
- `POST /api/v1/settings/scoring`
- `POST /api/v1/import/preview`

## Status semantics

`NOT_CHECKED` means no check ran. `NOT_FOUND` means a completed check found no result. `UNKNOWN` means evidence is inconclusive. `NOT_CONNECTED` means an integration is unavailable. These values must never be conflated.
