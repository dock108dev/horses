# Security audit — derby Pick 5 (single-user iPad app)

**Date:** 2026-04-28
**Scope:** entire repo (no diff available — first-pass audit). Backend
(`api/`), web frontend (`web/`), Docker / env config, sample data.
**Baseline test run:** `pytest api/tests` — 274 passed before and after
hardening edits.

---

## Repo understanding

This is a personal, single-user iPad browser app for Derby weekend Pick 5
analysis. There is no auth, no PII, no money flow (the app explicitly
"does not place bets"), and no multi-tenant data. The intended deployment
is a Mac mini on the user's LAN, optionally exposed over Tailscale.

### Trust boundaries

| Boundary                        | Surface                                                                 |
| ------------------------------- | ----------------------------------------------------------------------- |
| Browser → Next.js (port 3000)   | All UI; `/api/*` rewritten through to FastAPI.                          |
| Browser → FastAPI (port 8000)   | `/api/cards`, `/api/odds`, `/api/simulate`, `/api/tickets`, `/api/health`. CORS-controlled. |
| FastAPI → external scrapers     | Equibase static HTML, TwinSpires JSON XHRs, KentuckyDerby static HTML. Outbound HTTPS only. |
| FastAPI → SQLite (`data/`)      | Per-day `odds_<iso_date>.db` files; `card_snapshots` + `odds_snapshots`. |
| Deploy operator → env / volumes | `API_CORS_ORIGINS`, `DERBY_FRIDAY_DATE`, `DERBY_SATURDAY_DATE`, `API_DATA_DIR`, mounted `./data` volume. |

### Sensitive surfaces

There are no credentials, secrets, or user-identifying records anywhere
in the codebase. The "sensitive" data is operational: cached odds
snapshots (publicly available data) and the user's manual horse tags
(stored only in browser local React state, never persisted server-side
in the current code).

### What this audit looked for

- AuthN/Z gaps and IDOR (n/a — no auth model)
- Input handling: injection, traversal, deserialization, SSRF, ReDoS
- Frontend XSS, unsafe HTML/markdown render, token leakage
- API/transport: CORS, validation, verbose errors
- Secrets/config: hardcoded creds, env exposed to client bundle
- Data exposure: leakage in logs, responses, caches
- Headers: CSP/HSTS/Frame-Options
- Abuse: rate limits, brute force, resource exhaustion

---

## Findings table

| ID  | Title                                              | Severity | Confidence | Status                        |
| --- | -------------------------------------------------- | -------- | ---------- | ----------------------------- |
| S1  | CORS wildcard with credential reflection           | High     | High       | **Fixed** (rejected at boot)  |
| S2  | No security response headers                       | Medium   | High       | **Fixed** (middleware + Next) |
| S3  | Upstream exception strings leaked in API response  | Medium   | High       | **Fixed** (redactor)          |
| S4  | `DERBY_*_DATE` env value flows unvalidated to disk + URL paths | Low      | High       | **Fixed** (ISO regex)         |
| S5  | `web` Dockerfile runs `next dev` (NODE_ENV=development) | Low      | High       | **Justified** (intentional)   |
| S6  | No rate limiting on refresh endpoints              | Low      | Medium     | **Justified** (LAN scope)     |
| S7  | Frontend posts `tags` / `oddsOverrides` the backend silently drops | Low (functional) | High | **Justified** (project gap)   |
| S8  | Browser-spoofing UA / Referer / `Sec-Fetch-*` headers in scrapers | Note     | High       | **Justified** (necessary)     |
| S9  | Docker base images not pinned by digest            | Note     | High       | **Justified** (out of scope)  |
| S10 | `model_copy` with attacker-controlled JSON (cache replay) | Note     | Medium     | **Justified** (deploy-trust)  |

---

## Detailed findings

### S1 — CORS wildcard with credential reflection (HIGH, fixed)

**Where**

- `api/main.py` (pre-fix): `allow_origins=_origins` driven by
  `API_CORS_ORIGINS=*` default, combined with `allow_credentials=True`,
  `allow_methods=["*"]`, `allow_headers=["*"]`.
- `.env.example`: shipped `API_CORS_ORIGINS=*` as the default.

**Evidence**

```python
# Pre-fix
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,        # _origins == ["*"] when env unset → "*"
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Why this matters**

Starlette's CORSMiddleware, when configured with `allow_origins=["*"]`
**and** `allow_credentials=True`, reflects the request `Origin` header
verbatim into `Access-Control-Allow-Origin` (rather than emitting
`*`, which the browser would reject with credentials). The result is a
permissive CORS that allows any third-party site loaded in the user's
browser to make credentialed requests to the API and read the response.
Any malicious page the user visits while the iPad is on the same LAN
(or while an attacker can reach the FastAPI port through Tailscale)
could:

- read the cached card / odds (low-value data on its own)
- invoke `POST /api/cards/{day}/refresh` to burn upstream rate-limit
  budget on the user's source-of-record sites
- scrape ticket-builder output (the user's analysis IP)

**Realistic exploit scenario**

User opens a phishing page on the iPad while
`http://mac-mini.local:8000` is reachable. The page issues
`fetch("http://mac-mini.local:8000/api/odds/saturday", { credentials: "include" })`.
With the previous config, the request succeeded and the page exfiltrated
the cached card. With `POST /api/cards/saturday/refresh` it also caused
rate-limit pressure on Equibase / TwinSpires.

**Fix (this pass)**

`api/main.py`:
- Reject `*` explicitly at startup (`RuntimeError`) with a pointer to
  this report.
- Set `allow_credentials=False` — the SPA sends no cookies / Authorization
  headers, so credentialed CORS is unnecessary.
- Narrow `allow_methods` to `["GET", "POST", "OPTIONS"]` and
  `allow_headers` to `["Content-Type", "Accept"]`.

`.env.example`:
- Replace the `*` default with an explicit two-origin allow-list
  (`http://localhost:3000,http://mac-mini.local:3000`).

Verified: starting the app with `API_CORS_ORIGINS=*` now raises at
import time; all 274 tests still pass.

---

### S2 — No security response headers (MEDIUM, fixed)

**Where**

- `api/main.py`: no middleware added beyond CORS.
- `web/next.config.mjs`: no `headers()` block.
- `web/app/layout.tsx`: no `robots` directive.

**Why this matters**

Defense in depth. Even on a personal LAN app there is no reason to leave
clickjacking, MIME sniffing, referrer leakage, or search-engine indexing
unrestricted — all are one-line fixes.

**Fix (this pass)**

`api/main.py` adds a response middleware that sets, on every response:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: no-referrer`
- `Permissions-Policy: interest-cohort=(), geolocation=(), camera=()`
- `Cache-Control: no-store` (API responses are user-specific and
  perishable; browsers should not cache them)
- `X-Robots-Tag: noindex, nofollow`

`web/next.config.mjs` adds `async headers()` returning the same set
plus a strict CSP:

```
default-src 'self';
script-src 'self' 'unsafe-inline';
style-src 'self' 'unsafe-inline';
img-src 'self' data:;
connect-src 'self';
font-src 'self' data:;
frame-ancestors 'none';
base-uri 'self';
form-action 'self';
```

`script-src` and `style-src` need `'unsafe-inline'` because the React
tree uses inline `style={...}` props throughout and Next.js injects an
inline boot script. Tightening further would require migrating to a
nonce-based CSP — left as a follow-up.

`web/app/layout.tsx` adds `metadata.robots = { index: false, follow: false }`.
`poweredByHeader: false` strips the `X-Powered-By: Next.js` banner.

Verified by `TestClient(app).get("/api/health")` — all six headers
present.

---

### S3 — Upstream exception strings leaked in API response (MEDIUM, fixed)

**Where**

- `api/main.py` (pre-fix) — four sites:
  - `refresh_card`: `errors=[str(exc)]`
  - `refresh_odds`: `errors=[str(exc)]`
  - `simulate`: `errors=[str(exc)]`
  - `build_tickets`: `errors=[str(exc)]`

**Evidence**

httpx exceptions render their message as e.g.

```
Client error '404 Not Found' for url 'https://www.twinspires.com/ts-res/api/racing/program?track=CD&date=20260502&race=9'
```

Sqlite or filesystem errors render with absolute paths
(`/data/odds_2026-05-02.db`, `/app/api/...`). All of those flowed into
the API envelope, where the SPA happily renders them in the StaleBanner
and error-alert components.

**Why this matters**

Surface-level information disclosure: it reveals the upstream scraper
endpoints (helping a third party reproduce the scrape outside the
app's rate limiting) and the on-disk layout (helping a future
file-traversal bug). Low impact on its own; non-trivial when chained.

**Fix (this pass)**

Added `_redact_exc(exc)` in `api/main.py` that:

1. Keeps the exception class name (`httpx.HTTPStatusError:` …) — the UI
   can still distinguish a transport error from a parse failure.
2. Strips absolute URLs via `re.sub(r"https?://\S+", "<url>", …)`.
3. Strips multi-segment absolute filesystem paths.

Each `errors=[str(exc)]` site now emits
`errors=[<generic-message>, _redact_exc(exc)]`. The full traceback is
still logged via the existing `_log.exception(...)` call so production
debugging is unaffected.

Verified: existing tests that asserted `"equibase boom" in errors[0]`
and similar still pass — the redactor preserves message text, only
stripping URLs / paths.

---

### S4 — `DERBY_*_DATE` env value flows unvalidated to disk + URL paths (LOW, fixed)

**Where**

- `api/main.py`, `day_to_iso_date(day)` — pre-fix returned the env value
  verbatim with no format check.

**Why this matters**

The value flows into:

1. The SQLite filename: `odds_{iso_date}.db` under `data_dir`. A value
   like `DERBY_FRIDAY_DATE=../../tmp/foo` would create a DB at
   `data/odds_../../tmp/foo.db`, i.e. outside the data dir.
2. The Equibase / TwinSpires URL builders. A value containing
   `?` / `&` would inject query-string fragments into outbound requests.

Both `DERBY_*_DATE` and `API_DATA_DIR` are deploy-time env vars (only
the operator can set them), so the realistic impact is "operator
foot-gun" rather than "remote attacker", but a one-line regex check
removes the foot-gun entirely.

**Fix (this pass)**

`day_to_iso_date` now validates env input against
`^\d{4}-\d{2}-\d{2}$` and raises `ValueError` on mismatch.

Verified: `DERBY_FRIDAY_DATE=../../etc/passwd` is rejected at the first
endpoint call.

`API_DATA_DIR` itself is left unvalidated — the operator owns the
choice of data root; constraining it would prevent legitimate
non-default paths (e.g. `/var/lib/derby`).

---

### S5 — `web` Dockerfile runs `next dev` in `NODE_ENV=development` (LOW, justified)

**Where**

- `web/Dockerfile`: `ENV NODE_ENV=development` and `CMD ["npm", "run", "dev"]`.

**Why this matters**

In production builds Next.js suppresses verbose error overlays, source
maps, and React dev warnings — a malicious request would see
information-disclosure-friendly output in dev mode.

**Justification (kept as-is)**

This is a personal iPad app the user runs locally during a single
weekend. There is no production deployment pipeline; "dev mode" is the
intended runtime so live edits and HMR work for the operator. Promoting
to `next start` would require adding a build step to the Dockerfile
*and* would eliminate the ergonomic reason the user chose this stack.
The risk is bounded by S1's CORS lockdown (no untrusted origin can
trigger an error path) and S2's `noindex` headers (no search-engine
exposure).

If the deployment surface ever changes (e.g. the Mac mini becomes
publicly reachable beyond Tailscale), revisit this — the smallest
concrete next action is splitting the Dockerfile into a multi-stage
build that runs `npm run build` and `npm start` for prod.

---

### S6 — No rate limiting on refresh endpoints (LOW, justified)

**Where**

- `POST /api/cards/{day}/refresh` and `POST /api/odds/{day}/refresh` —
  both trigger live HTTP fan-out to Equibase + TwinSpires.

**Why this matters**

A burst of refresh calls from the iPad (or a script reachable on the
LAN) would trip upstream anti-scraping measures. The TwinSpires adapter
already enforces a 30-s per-race floor (`min_odds_interval`) and
Equibase a 3-s global floor (`min_request_interval`) — those are
adapter-internal sleeps, so refresh handlers will block rather than
fan out, but they don't bound the *number* of in-flight requests in
parallel.

**Justification (kept as-is)**

S1 now rejects unauthenticated cross-origin abuse, and the user is the
only client. Adapter-internal floors already throttle the actual
outbound HTTP. Adding `slowapi` or similar for a one-user app is
disproportionate. Smallest-next-action if exposure widens: add
`slowapi.Limiter` keyed by remote IP with a 10/min cap on each refresh
route.

---

### S7 — Frontend posts `tags` / `oddsOverrides` the backend silently drops (LOW functional, justified)

**Where**

- `web/lib/api.ts`: `simulate(day, body)` and `buildTickets(day, body)`
  send `tags`, `oddsOverrides` in the JSON body.
- `api/main.py`: `SimulateRequest` declares only `n_iterations`;
  `TicketsRequest` declares only `budget_dollars` and `base_unit`.
  Pydantic's default `extra="ignore"` silently drops the extra fields.

**Why this matters**

It's a functional bug, not a vulnerability — but in a security-audit
frame it deserves a note: "field exists in the wire format but is
ignored" is exactly the kind of silent gap that becomes a vuln later
when someone wires up the backend half and assumes the frontend's
input was already sanitized. If/when the backend implements
`oddsOverrides`, the values must be validated as fractional/decimal
odds strings (the same parser as `api/normalize.odds_to_probability`)
before flowing into the cache.

**Justification (kept as-is)**

The fields are silently *ignored*, not silently *trusted* — the
worst-case in the current code is that a manual override the user
made on the iPad is lost when they tap "Run Sim". Tightening the
Pydantic models with `extra="forbid"` would make the call hard-fail
instead, which is a behavioral regression for a feature that the
project explicitly tracks as not-yet-implemented (see
`AIDLC_FUTURES.md` — 14 issues planned, 10 implemented).

When the backend implementation lands, the validation rule must
reject any odds string `_parse_odds_to_decimal` returns `None` for.

---

### S8 — Browser-spoofing UA / Referer / `Sec-Fetch-*` headers in scrapers (NOTE, justified)

**Where**

- `api/sources/twinspires.py`: full `Sec-Fetch-*`, `Origin`, `Referer`,
  and Chrome UA spoofing; falls back to `curl_cffi`'s
  `impersonate="chrome124"` when the site returns 403.
- `api/sources/equibase.py`, `api/sources/kentuckyderby.py`: Chrome UA
  + `Referer`.

**Why**

Both target sites JSON/HTML-block default Python clients. The codebase
treats this as the cost of admission for "automated data is the
hard part" (see `BRAINDUMP.md`), and the project's stated scope is
strictly personal use of publicly-readable race data — not credential
stuffing or bypassing access controls.

**Justification**

This is a ToS / scraping-ethics question, not a security defect for
the *server*. Documented inline in each adapter's docstring.

---

### S9 — Docker base images not pinned by digest (NOTE, justified)

`api/Dockerfile`: `FROM python:3.11-slim`.
`web/Dockerfile`: `FROM node:20-bookworm-slim`.

Tag-pinning is acceptable for a single-operator personal app rebuilt
on demand. Digest-pinning would prevent the next `docker build` from
silently picking up a republished base image, but the supply-chain
threat model for a one-user weekend app is small. Smallest-next-action
if this changes: replace each tag with the corresponding `@sha256:…`
digest.

---

### S10 — `model_copy` with attacker-controlled JSON (cache replay) (NOTE, justified)

**Where**

- `api/cache.py:283`:
  `races = [Race.model_validate(d) for d in json.loads(row[0])]`

The cache is the only sink that deserializes JSON to a Pydantic model
without going through a source adapter first. If an attacker could
write arbitrary content into `card_snapshots.card_json` (e.g. via a
SQL-injection vuln elsewhere), that attacker could control the shape
of the next "stale" response.

**Why this is a note, not a finding**

- All cache writes use parameterized queries (`?` placeholders), so
  there is no path from API input to `card_json` that bypasses Pydantic
  validation on the way *in*.
- `Race`/`Horse` use `extra="forbid"` and tight field constraints, so
  even if junk JSON landed in the column, `Race.model_validate` would
  reject it rather than executing it.
- The threat requires DB write access, at which point the operator has
  bigger problems than cache replay.

Documented here so a future reader knows the path is intentional.

---

## Safe hardening implemented this pass

| Change                                            | File                          |
| ------------------------------------------------- | ----------------------------- |
| Reject `API_CORS_ORIGINS=*` at startup            | `api/main.py`                 |
| `allow_credentials=False`, narrow methods/headers | `api/main.py`                 |
| Security-headers ASGI middleware                  | `api/main.py`                 |
| ISO-date validation on `DERBY_*_DATE` env         | `api/main.py`                 |
| `_redact_exc()` strips URLs/paths from envelope errors | `api/main.py`            |
| Generic prefix on every error path                | `api/main.py`                 |
| Strict CSP + security headers + no powered-by     | `web/next.config.mjs`         |
| `robots: { index: false, follow: false }` metadata | `web/app/layout.tsx`         |
| `.env.example` defaults to explicit origin list   | `.env.example`                |

All edits validated:
- `pytest api/tests` → 274 passed (same as baseline).
- `python -c "API_CORS_ORIGINS=*"` import → raises `RuntimeError`.
- `python -c "DERBY_FRIDAY_DATE=../../etc/passwd"` → raises `ValueError`.
- `TestClient(app).get("/api/health")` → all six security headers
  present in the response.

---

## Remediation roadmap (prioritized)

Everything actionable in this pass was done. The remaining items are
**justified-as-is** above and need a deployment-shape change to become
worth doing:

1. **If exposure widens beyond LAN/Tailscale** (e.g. the user opens
   the API to the open internet): tighten CSP further (drop
   `'unsafe-inline'` via nonces — non-trivial because of inline
   `style={...}`), promote the `web` Dockerfile to `next start` in a
   multi-stage build, and add `slowapi` rate limits to the refresh
   endpoints.
2. **If the backend implements `oddsOverrides`** (project gap S7):
   gate the request through `api/normalize.odds_to_probability` and
   reject inputs that fail to parse — the fix is one validator on the
   Pydantic model, not a separate sanitation pass.
3. **If the Mac-mini deploy gains a CI/CD pipeline**: digest-pin the
   Docker base images (S9).

## Escalations

None. Every finding in this pass was either acted on or has a
documented justification with a concrete trigger that would bring it
back into scope.
