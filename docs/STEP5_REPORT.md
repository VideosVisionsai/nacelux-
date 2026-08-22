# NACELUX — Rapport Étape 5 (Website Discovery + Digital Footprint)

Date : 2026-08-22 · Branche : `arena/01a0270b-nacelux` · Commit : `fe1579c`

**Aucune donnée fictive. Aucune URL inventée depuis le nom.** Une URL n'est une preuve qu'après vérification réelle. Une absence de vérification n'est **jamais** convertie en NO_WEBSITE.

## Website Discovery — pipeline **VERIFIED** · discovery (search) **REQUIRES CONFIGURATION**
- `verify_website` (vérification evidence-backed d'une URL connue/fournie) : **VERIFIED** en réel (github.com → CONNECTED).
- `discover` (découverte via API de recherche Brave/Google) : code présent, **REQUIRES CONFIGURATION** (aucune clé API de recherche ; jamais de candidat inventé depuis le nom). Statut AMBIGUOUS conservé si preuve insuffisante.

## Digital Footprint — **VERIFIED**
Analyse technique réelle : title, H1 (+count), meta description, viewport mobile, canonical, robots meta, statut/URL finale HTTPS (handshake validé), charset, page bytes, response time. Enregistré dans `digital_checks` (upsert dernière) + `digital_check_history` (append-only, jamais remplacé silencieusement).

## SSRF — **VERIFIED** (tests exécutés)
`validate_public_url` : http/https uniquement, ports 80/443, pas d'identifiants, hôtes metadata bloqués, DNS résolu et **chaque IP** doit être globalement routable (`is_global` → privé/loopback/link-local/reserved/multicast/unspecified exclus), pré-contrôle IP littérales + localhost, **redirections revalidées** (`SafeWebsiteRedirect`).
Tests bloquant réellement : 127.0.0.1, ::1, localhost, 10.x, 172.16.x, 192.168.x, 169.254.x, 0.0.0.0, IPv6 privé (fc00::), IPv6 link-local (fe80::), metadata endpoints, **DNS rebinding** (getaddrinfo monkeypatché → privé), **redirect vers privé/localhost/metadata**, file://, ftp://, javascript:, data:, port arbitraire, URL invalide.

## HTTPS — **VERIFIED**
`https_status=VALID` provient du **handshake TLS réel** (urllib avec contexte SSL par défaut qui valide le certificat), pas du simple schéma. Vérifié en réel (github.com/pypi.org → VALID).

## HTML — **VERIFIED**
title, H1, H1 count, meta description, viewport, canonical, robots, page bytes, response time, charset — extraits par parsing passif (aucun script exécuté). Tests fixtures + réel.

## Jobs — **VERIFIED**
`WEBSITE_DISCOVERY` et `DIGITAL_FOOTPRINT_CHECK` traités par le worker via la file atomique PostgreSQL (`app_claim_jobs`, `FOR UPDATE SKIP LOCKED`), retry/backoff/max-attempts/orphan-recovery déjà vérifiés (étape 2). Deux workers ne traitent pas deux fois le même job.

## API
- `POST /api/v1/digital/check` (company_id + URL optionnelle non fiable → SSRF complet) — **VERIFIED**
- `POST /api/v1/websites/discover` (company_id) — **VERIFIED** (route ; discovery search = REQUIRES CONFIGURATION)
- `GET /api/v1/digital` (existant), `GET /api/v1/companies/:id` (retourne désormais `digital`).
Toutes les routes : auth + membership, organisation depuis la session, jamais `organization_id` du client.

## Frontend — **VERIFIED**
Drawer entreprise : section « Website technical analysis » (Website status, HTTPS, Title, H1, Meta description, Mobile viewport, Canonical, Robots, Response time, Page size, HTTP status, Last checked, Explanation). États UNKNOWN/NOT_CHECKED/BLOCKED/ERROR affichés explicitement (jamais « No website » sur un inconnu).

## Tests — **145 passed, 0 failed, 21 skipped**
Step 5 : 17 OK (SSRF, HTML, statuts, verify_website flow, historique, tenant isolation, **réseau réel** contre github.com/pypi.org). Skipped = suites PostgreSQL conditionnelles + gated real download NACE.

## PostgreSQL — **VERIFIED**
Migration 0018 appliquée (18 migrations) ; `digital_check_history` RLS ENABLE+FORCE vérifiés sur vrai PostgreSQL embarqué. digital_checks étendu (http_status, response_ms, page_bytes, https_status, final_url, value, explanation, rule_version).

## RLS — **VERIFIED**
`digital_checks` et `digital_check_history` tenant-scoped (ENABLE+FORCE, `app_user_has_org_access`). Tenant isolation vérifiée (les checks d'un tenant ne fuient pas vers l'autre). Rôles non-owner/non-BYPASSRLS.

## Données
**AUCUNE DONNÉE FICTIVE EN PRODUCTION.** Aucune entreprise factice, aucune URL inventée, aucune métrique fabriquée. États vide/explicites affichés quand rien n'est vérifié.

## Internet
- **VERIFIED** : HTTPS/HTML/connectivity/status/size/timing réels contre `github.com` et `pypi.org` (hôtes publiquement joignables depuis le sandbox).
- **REQUIRES CONFIGURATION** : discovery via API de recherche (Brave/Google Programmable Search — clé requise) et vérification de sites arbitraires non joignables depuis le sandbox (seuls pypi.org/github.com sont joignables).

## Fichiers modifiés
- `backend/website_intelligence.py` (SSRF durci, `WebsiteHTMLAnalyzer`/`parse_html`, `analyze_website`, `verify_website`, `_record_check`, statuts)
- `backend/database.py` (colonnes digital_checks SCHEMA, `digital_check_history` SCHEMA, `company_detail.digital`)
- `backend/migrations.py` (TABLE_ORDER)
- `backend/app.py` (`POST /api/v1/digital/check`, `POST /api/v1/websites/discover`)
- `frontend/app.js` (section « Website technical analysis » dans le drawer)
- `database/migrations/0018_digital_footprint_metrics.sql`
- `tests/test_step5_website.py`

## Problèmes restants
- **Search-provider discovery** (Brave/Google) : REQUIRES CONFIGURATION (clé API). Sans clé, `discover` retourne NOT_CONFIGURED et ne marque jamais NOT_FOUND.
- **Sites arbitraires non joignables** depuis ce sandbox : toute vérification autre que pypi.org/github.com est REQUIRES CONFIGURATION (egress limité).
- **DNS rebinding au moment du fetch** : la validation résout et bloque les IPs privées, et les redirections sont revalidées ; le pinning IP strict (anti-rebinding TOCTOU au fetch) n'est pas implémenté (résiduel documenté).

---

VERIFIED = code exécuté + test réel + résultat observé. Aucune donnée inconnue inventée. Je m'arrête à la fin de l'Étape 5 (pas d'Étape 6 automatique).
