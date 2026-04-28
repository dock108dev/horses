# Security Audit — Derby Pick 5

Pass date: 2026-04-28
Scope: branch-local changes (the in-progress refactor of `api/`,
`web/`, `docker-compose.yml`, `fixtures/pick5/`, and the new `Spinner`
component) plus the surrounding code those changes touch. Companion to
`docs/audits/error-handling-report.md` (F-series) and the deleted legacy
security report referenced by inline `S{n}` comments.

The actionability contract: every finding here is either fixed in the
code (action recorded inline) or justified in this report **and** at the
code site. There are no bare TODOs.

---

## Repo understanding

**What this app is.** A single-user iPad browser tool for analyzing the
Friday-Oaks / Saturday-Derby Pick 5 sequence at Churchill Downs. Two
services in one Docker compose: a FastAPI backend (`api/`) that scrapes
Equibase + TwinSpires, persists snapshots to per-day SQLite under
`/data`, and serves a JSON-envelope API; a Next.js SPA (`web/`) that
calls the backend through a same-origin `/api/*` rewrite. There is no
auth, no PII, no money flow, no third-party assets.

**Trust boundaries actually touched on this branch:**

| Boundary                              | Direction          | Validation            |
| ------------------------------------- | ------------------ | --------------------- |
| iPad browser → Next.js (`:3000`)      | inbound            | LAN/Tailscale only    |
| Next.js → FastAPI (`:8000`, docker)   | server-to-server   | docker network ACL    |
| Browser → FastAPI (CORS, `:8000`)     | inbound            | explicit allow-list   |
| FastAPI → Equibase / TwinSpires       | outbound HTTP      | hardcoded base URLs   |
| FastAPI → SQLite cache (`/data`)      | local FS           | per-day filename only |
| FastAPI → fixtures (`fixtures/pick5`) | local FS, RO mount | new this branch (S5)  |
| Operator → env vars                   | config             | regex / allow-list    |

**Sensitive surfaces.** None of (auth, secrets, PII, payments) exist.
The most sensitive things on disk are: per-day SQLite caches under
`/data` (race / odds snapshots — not personally identifying, but they
are the operator's working state), and the `.env` file (no creds, just
allow-listed origins and date overrides).

The threat model is therefore narrow: an attacker on the LAN reaching
the API directly, an attacker tricking a third-party origin into
issuing browser-credentialed CORS reads, or a denial-of-service via an
unbounded request body. The deployment guidance ("Mac mini on the
operator's LAN, optionally over Tailscale") makes anything broader an
explicit operator decision, not a default risk.

---

## Executive summary

| Severity   | Count |
| ---------- | ----- |
| Critical   | 0     |
| High       | 0     |
| Medium     | 0     |
| Low        | 4     |
| Note       | 5     |

**Posture verdict: prod posture acceptable for the documented LAN /
Tailscale deployment.** All four "Low" findings were tightened in this
pass; the five "Notes" are documented as accepted operator decisions
with a justifying comment at the code site or in the README.

### Changes applied this pass

- **S4** — `SimulateRequest.n_iterations` and `TicketsRequest.{budget_dollars,base_unit}`
  now carry numeric bounds (`Field(ge=…, le=…)` / `gt=0` for
  `base_unit`). Fixed at `api/main.py:559-588`.
- **S5** — `api.sources.fixture.load_card` and `load_odds_records` now
  validate `day` against an explicit allow-list before interpolating it
  into the fixture file path. Fixed at `api/sources/fixture.py:33-49`.
- **S1, S2, S3** were already in place from the prior pass; verified
  against the current code — they remain correct and unmodified.

---

## Findings table

| ID  | Title                                              | Severity | Confidence | Status                              |
| --- | -------------------------------------------------- | -------- | ---------- | ----------------------------------- |
| S1  | Wildcard CORS rejected; allow-credentials disabled | Low      | High       | Verified (existing)                 |
| S2  | Defense-in-depth security headers                  | Low      | High       | Verified (existing)                 |
| S3  | Exception messages redacted before surfacing       | Low      | High       | Verified (existing)                 |
| S4  | Request bodies missing numeric bounds              | Low      | High       | **Fixed this pass**                 |
| S5  | Fixture loader trusts caller-supplied `day`        | Low      | Medium     | **Fixed this pass**                 |
| S6  | `web` container runs `next dev` in production      | Note     | High       | Justified — operator HMR ergonomics |
| S7  | No HTTPS / HSTS                                    | Note     | High       | Justified — LAN-only by design      |
| S8  | OpenAPI / Swagger left publicly enumerable         | Note     | High       | Justified — single-user diagnostic  |
| S9  | TwinSpires browser-impersonation user-agent        | Note     | Medium     | Justified — required to avoid 403   |
| S10 | Source adapters scrape with no SSRF surface        | Note     | High       | Verified — no user-controlled URLs  |

---

## Detailed findings

### S1 — Wildcard CORS rejected; allow-credentials disabled (Low / verified)

**Evidence.** `api/main.py:222-240` — startup raises `RuntimeError` when
`API_CORS_ORIGINS` contains `*`, and `allow_credentials=False` is hard-
coded. The verb / header allow-lists are also tightened to what the
SPA actually sends.

**Why it matters.** Starlette's `CORSMiddleware` with `allow_origins=["*"]`
+ `allow_credentials=True` reflects the request `Origin` header,
turning the API into an open relay for any third-party site loaded in
the operator's browser. There is no auth on this app, so a credentialed
read from a malicious origin would expose the operator's race-day
state.

**Status.** Already implemented by the prior pass; verified still
correct. Test coverage at `api/tests/test_main.py:227-256`.

### S2 — Defense-in-depth security headers (Low / verified)

**Evidence.** Backend middleware at `api/main.py:246-257` sets
`X-Content-Type-Options`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, `Permissions-Policy`,
`Cache-Control: no-store`, and `X-Robots-Tag: noindex, nofollow`.
Frontend matches via `web/next.config.mjs:10-33` and additionally sets
a strict CSP (`default-src 'self'`, no third-party connect / script
sources, `frame-ancestors 'none'`).

**Why it matters.** The app does not load third-party assets and never
embeds in a third-party frame, so the strict CSP and `DENY` framing
are achievable at zero cost and they neutralize a clickjacking shell
even on the open internet.

**Status.** Already implemented; verified.

### S3 — Exception messages redacted before surfacing (Low / verified)

**Evidence.** `_redact_exc` at `api/main.py:96-108` strips absolute URLs
and `(?:/[^\s'\"]+){2,}` filesystem paths from the exception text
before placing it in an envelope's `errors` list. The full traceback
still goes to logs via `_log.exception`.

**Why it matters.** Without redaction, `str(exc)` can leak the upstream
scraper endpoints (`https://www.equibase.com/static/entry/...`) and
the absolute on-disk cache layout (`/data/equibase_html/...`) into the
browser. Neither is an immediate exploit, but both are reconnaissance
gifts for someone trying to find the next bug.

**Status.** Already implemented; verified.

### S4 — Request bodies missing numeric bounds (Low / fixed this pass)

**Evidence (before).** `SimulateRequest.n_iterations` and
`TicketsRequest.{budget_dollars,base_unit}` were typed as
`int | None` / `float | None` with no range constraint. `n_iterations`
was internally clamped by `api.sim._clamp_iterations` (good), but
`budget_dollars` and `base_unit` flowed into `build_tickets_for_budgets`
unchecked. A `base_unit=0` would short-circuit `_ticket_cost` to `$0`
and force `_fit_to_budget` into its add-loop (terminating at horse
exhaustion, but still wasted work and a confusing zero-cost ticket
output). A negative `base_unit` would invert the cost ordering. A
huge `budget_dollars` would just silently expand the ticket pool.

**Realistic exploit scenario.** Single-user LAN means there is no
real attacker here — the impact is reduced to "iPad keypad fat-finger
posts a 0 or a negative and the user gets a confusing ticket envelope".
Severity is **Low** rather than Note because the fix is one Pydantic
field constraint per knob and converts a noisy internal
`ValidationError` from `BudgetVariant` into a clean 422 at the
boundary.

**Fix applied.**

```python
# api/main.py:559-588
class SimulateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n_iterations: int | None = Field(default=None, ge=1, le=100_000)

class TicketsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    budget_dollars: float | None = Field(default=None, ge=0.0, le=1_000_000.0)
    base_unit: float | None = Field(default=None, gt=0.0, le=1_000_000.0)
```

`le=1_000_000.0` is a "never legitimate" upper bound — keeps a hostile
or fat-fingered payload from ever materializing as a string-encoded
huge float in a downstream JSON response.

### S5 — Fixture loader trusts caller-supplied `day` (Low / fixed this pass)

**Evidence (before).** `api/sources/fixture.py:load_card(day)` and
`load_odds_records(day, …)` interpolated `day` directly into the
fixture path:

```python
path = fixtures_dir() / f"{day}-card.json"
```

The FastAPI route binding `day` to `Literal["friday", "saturday"]`
prevents traversal at the HTTP boundary — but the loader functions are
public symbols (`__all__`), tests / scripts can call them directly,
and the `_validate_day` guard belongs in the place where the path is
constructed, not three call-sites away.

**Realistic exploit scenario.** With `PICK5_FIXTURES_DIR` set to a
shared mount and a hostile caller invoking `load_card("../etc/passwd")`,
the relative join would resolve outside the intended fixtures dir and
either succeed (if the named file ended in `-card.json`) or fail
loudly. No real exploit on this branch — but defense-in-depth at the
boundary that owns the path-build is cheaper than auditing every
caller.

**Fix applied.**

```python
# api/sources/fixture.py:33-49
_ALLOWED_DAYS: frozenset[str] = frozenset({"friday", "saturday"})

def _validate_day(day: str) -> str:
    if day not in _ALLOWED_DAYS:
        raise ValueError(...)
    return day
```

Both `load_card` and `load_odds_records` now call `_validate_day(day)`
before constructing the fixture path. The route-level
`Literal["friday", "saturday"]` guard remains as the first line of
defense.

### S6 — `web` container runs `next dev` in production (Note / justified)

**Evidence.** `web/Dockerfile:3,17` sets `NODE_ENV=development` and
runs `npm run dev`. The README explicitly calls this out as
intentional ("the `web` Dockerfile runs `next dev` for the operator's
HMR ergonomics").

**Why it could matter.** `next dev` ships source maps, stack traces
with file paths, the React DevTools hook integration, and an
unminified bundle. None of these are exploitable in isolation; they do
expand the recon surface for a future bug.

**Justification (status: kept as-is).** The deployment target is "Mac
mini on the user's LAN, optionally over Tailscale" — a single-user
personal tool where a 1-2s production-build feedback loop matters more
than a recon-surface reduction that has no real attacker behind it.
Switching to `next start` is a one-line README + Dockerfile change if
the operator ever exposes it more widely; documented under "Wider
exposure requires the steps in `docs/audits/security-report.md`
'Remediation roadmap'" in the project README.

### S7 — No HTTPS / HSTS (Note / justified)

**Evidence.** Both services bind plain HTTP. The middleware does not
emit `Strict-Transport-Security`, and there is no TLS termination in
the compose file.

**Justification (status: kept as-is).** The deployment plan is HTTP on
the LAN with optional Tailscale. Tailscale already provides TLS-grade
encryption end-to-end on the WireGuard tunnel; emitting HSTS for an
HTTP origin would be incoherent (HSTS without TLS is a self-denial-of-
service). If the operator later puts a TLS-terminating proxy in front,
HSTS belongs there, not here.

### S8 — OpenAPI / Swagger left publicly enumerable (Note / justified)

**Evidence.** FastAPI's `/docs`, `/redoc`, and `/openapi.json` are
left on the default — anyone reaching the API can enumerate every
route plus the request schema. The test at
`api/tests/test_main.py:805-810` explicitly asserts the diagnostic
routes appear in the OpenAPI document.

**Justification (status: kept as-is).** Per BRAINDUMP "Phase 10 —
Swagger/API cleanup", the OpenAPI surface is a *required* operator
diagnostic for this project. The trust boundary is the LAN, the only
caller is the operator's iPad, and the request schemas have no
secrets. Closing the docs route would actively hurt the documented
debugging workflow.

### S9 — TwinSpires browser-impersonation user-agent (Note / justified)

**Evidence.** `api/sources/twinspires.py:36-44` sends a Chrome-on-macOS
`User-Agent` and seeds session cookies via a homepage GET. The
optional `curl_cffi` fallback (`api/sources/twinspires.py:481-510`) is
configured to impersonate Chrome 124 (TLS fingerprint level).

**Justification (status: kept as-is).** Without the impersonation
profile TwinSpires returns 403 for every XHR; the fallback is the only
documented way to keep the live odds path working. This is a polite
scrape of public information, not a credential theft surface — there
is no auth being faked, only a TLS / UA fingerprint. Documented in the
adapter's module docstring and at the `_build_curl_cffi_client` call
site.

### S10 — Source adapters scrape with no SSRF surface (Note / verified)

**Evidence.** Every outbound URL is built from hardcoded base URLs
(`https://www.equibase.com`, `https://www.twinspires.com/ts-res/api/...`)
and the `(track_code, date, race_number)` triple — `track_code` is the
constant `"CD"`, `date` is the regex-validated `DERBY_*_DATE` env var,
`race_number` is the `Pick5` legs constant. There is no path in the
codebase by which a request body or query parameter influences the
outbound URL.

**Status.** Verified. No action needed; documented here to close out
the SSRF lens.

---

## Safe hardening implemented this pass

1. `api/main.py` — added `pydantic.Field(...)` numeric bounds to
   `SimulateRequest.n_iterations` (range `[1, 100_000]` mirroring
   `api.sim.MAX_ITERATIONS`), `TicketsRequest.budget_dollars`
   (`[0, 1_000_000]`), and `TicketsRequest.base_unit`
   (`(0, 1_000_000]`). Imports `Field` alongside the existing
   `BaseModel` / `ConfigDict`. Citations point at this report's S4.
2. `api/sources/fixture.py` — added `_ALLOWED_DAYS` allow-list and
   `_validate_day` guard, called from `load_card` and
   `load_odds_records` before any fixture path is constructed.
   Citations point at this report's S5.

Test suite: `pytest api/tests/` — **373 passed** before and after the
changes (no regressions).

---

## Remediation roadmap (for if exposure ever widens)

The current posture is correct for the documented LAN / Tailscale
deployment. The roadmap below is what a wider exposure (open-internet
host, multi-user) would require, in priority order:

1. **Add auth.** Either a single-user shared secret enforced via a
   FastAPI dependency, or terminate at an authenticating reverse proxy.
   Required before any non-LAN exposure — every other item below is
   secondary to this.
2. **Switch the web image to `next start` (S6).** Two-line change once
   the operator decides production stability matters more than HMR.
3. **Restrict the OpenAPI surface (S8).** Either gate `/docs` /
   `/redoc` / `/openapi.json` behind the auth dependency or pass
   `docs_url=None, redoc_url=None, openapi_url=None` to the
   `FastAPI(...)` constructor and serve a static reference instead.
4. **Add HSTS at the TLS terminator (S7).** Belongs on whatever proxy
   does TLS termination, not on the FastAPI service itself.
5. **Rate-limit the refresh + simulate routes.** Currently single-user
   so contention is not a concern; for multi-user, the `asyncio.to_thread`
   offload still allows N concurrent ~3-5 minute scrapes to pin the
   worker pool.

---

## Escalations

None this pass. Every finding above either had a single-author fix or
a clearly justified accept-as-is. The two open items in the
companion error-handling report (E1 — UI tags / odds overrides
local-only) are functional, not security, and remain tracked there.
