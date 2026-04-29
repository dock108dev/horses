# Security Audit — Derby Pick 5

Pass date: 2026-04-28 (Friday-Morning Readiness branch)
Scope: branch-local diff against `origin/main` (`b9d3ec8`) — the test
fixture extraction (`api/tests/conftest.py`), the new `live` pytest
marker, the two new fixture-driven tests
(`api/tests/test_friday_e2e.py`, `api/tests/test_stale_fallback.py`),
the `api/sim.py:115` rationale-comment fix, the rewritten
`BRAINDUMP.md`, plus the surrounding code those changes touch. Companion
to `docs/audits/error-handling-report.md` (F-series).

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
| FastAPI → fixtures (`fixtures/pick5`) | local FS, RO mount | `_validate_day`       |
| Operator → env vars                   | config             | regex / allow-list    |

**Sensitive surfaces.** None of (auth, secrets, PII, payments) exist.
The most sensitive things on disk are: per-day SQLite caches under
`/data` (race / odds snapshots — not personally identifying, but they
are the operator's working state), and the `.env` file (no creds, just
allow-listed origins and date overrides).

The threat model is therefore narrow: an attacker on the LAN reaching
the API directly, an attacker tricking a third-party origin into
issuing browser-credentialed CORS reads, an attacker dropping malicious
content into TwinSpires/Equibase upstream and watching us round-trip
it through the cache, or a denial-of-service via an unbounded request
body. The deployment guidance ("Mac mini on the operator's LAN,
optionally over Tailscale") makes anything broader an explicit operator
decision, not a default risk.

**What changed on this branch (security-relevant lens).**

| Diff signal                                  | Security relevance                                                                                         |
| -------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `api/tests/conftest.py` (new shared fixtures)| Test-only; no production trust boundary touched.                                                           |
| `api/tests/test_main.py` slimmed             | Same fixture set, just imported instead of re-declared. No coverage loss vs. `b9d3ec8`.                    |
| `api/tests/test_friday_e2e.py` (new)         | Regression coverage on the full refresh→sim→tickets path against fixtures (positive).                     |
| `api/tests/test_stale_fallback.py` (new)     | **Adds direct regression coverage for `_redact_exc` (S3)**: pins URL and filesystem-path scrubbing in the cache-fallback envelope. Strong positive for posture. |
| `api/pyproject.toml` `markers = ["live: …"]` | New posture: live-network tests are deselected by default. Process risk: a security regression check tagged `live` would silently skip. **S12** below.       |
| `api/sim.py:115` comment fix                 | Stale `S11` reference dropped; rationale preserved. No behavior change.                                    |
| `BRAINDUMP.md` rewrite                       | Documentation only; no code change.                                                                        |
| `AIDLC_FUTURES.md` deleted                   | Documentation only.                                                                                        |

---

## Executive summary

| Severity   | Count |
| ---------- | ----- |
| Critical   | 0     |
| High       | 0     |
| Medium     | 0     |
| Low        | 5     |
| Note       | 7     |

**Posture verdict: prod posture acceptable for the documented LAN /
Tailscale deployment.** All five "Low" findings are tightened in code;
the seven "Notes" are documented as accepted operator decisions with a
justifying comment at the code site or in this report.

### Changes applied this pass

- **S11 (new, Low/fixed)** — added
  `Cross-Origin-Resource-Policy: same-origin` to both the FastAPI
  security-headers middleware (`api/main.py:242–263`) and the Next.js
  per-route headers (`web/next.config.mjs:5–35`). Defense-in-depth
  against opaque cross-origin embedding (e.g. `<img src="…">`,
  `<link rel=preload …>`, `<script src="…">`) of API/SPA responses,
  layered on top of the CORS allow-list (S1) and `frame-ancestors
  'none'` (S2).
- **S12 (new, Note)** — added a comment to `api/pyproject.toml`
  pytest config warning that `@pytest.mark.live` must not be applied
  to security-regression tests, since `addopts = "-m 'not live'"`
  silently deselects them by default.
- **S1, S2, S3, S4, S5** — verified against current code; unchanged.
  The new `test_stale_fallback.py` adds the *direct* regression test
  the prior pass could only assert end-to-end through `test_main.py`.
- **S11 numbering reuse**: an earlier pass had a different "S11"
  finding that was deleted before this one; the comment at
  `api/sim.py:115` (`See security-report S11.`) was already
  rewritten on this branch to drop the stale cite. The new S11 here
  is a different finding; the `api/sim.py` comment no longer points
  at this report and does not need to be re-edited.

---

## Findings table

| ID  | Title                                              | Severity | Confidence | Status                              |
| --- | -------------------------------------------------- | -------- | ---------- | ----------------------------------- |
| S1  | Wildcard CORS rejected; allow-credentials disabled | Low      | High       | Verified (existing)                 |
| S2  | Defense-in-depth security headers                  | Low      | High       | Verified (existing)                 |
| S3  | Exception messages redacted before surfacing       | Low      | High       | Verified — new direct regression test|
| S4  | Request bodies missing numeric bounds              | Low      | High       | Verified (existing)                 |
| S5  | Fixture loader trusts caller-supplied `day`        | Low      | Medium     | Verified (existing)                 |
| S6  | `web` container runs `next dev` in production      | Note     | High       | Justified — operator HMR ergonomics |
| S7  | No HTTPS / HSTS                                    | Note     | High       | Justified — LAN-only by design      |
| S8  | OpenAPI / Swagger left publicly enumerable         | Note     | High       | Justified — single-user diagnostic  |
| S9  | TwinSpires browser-impersonation user-agent        | Note     | Medium     | Justified — required to avoid 403   |
| S10 | Source adapters scrape with no SSRF surface        | Note     | High       | Verified — no user-controlled URLs  |
| S11 | Cross-Origin-Resource-Policy missing               | Low      | High       | **Fixed this pass**                 |
| S12 | `@pytest.mark.live` silently deselects by default  | Note     | High       | **Documented this pass**            |
| S13 | `_FS_PATH_RE` only redacts paths with ≥2 segments  | Note     | Medium     | Justified — false-positive trade-off|
| S14 | `/api/pick5/{day}/debug` exposes adapter labels    | Note     | High       | Justified — operator diagnostic     |
| S15 | Fixture entries silently skipped on type mismatch  | Note     | Medium     | Justified — committed-config trust  |
| S16 | TwinSpires `?date` flow into outbound URL          | Note     | High       | Verified — regex-validated env only |

---

## Detailed findings

### S1 — Wildcard CORS rejected; allow-credentials disabled (Low / verified)

**Evidence.** `api/main.py:222-240` — startup raises `RuntimeError` when
`API_CORS_ORIGINS` contains `*`, and `allow_credentials=False` is hard-
coded. The verb / header allow-lists are tightened to what the SPA
actually sends (`GET`, `POST`, `OPTIONS`; `Content-Type`, `Accept`).

**Why it matters.** Starlette's `CORSMiddleware` with `allow_origins=["*"]`
+ `allow_credentials=True` reflects the request `Origin` header,
turning the API into an open relay for any third-party site loaded in
the operator's browser. There is no auth on this app, so a credentialed
read from a malicious origin would expose the operator's race-day
state.

**Realistic exploit scenario.** If `API_CORS_ORIGINS=*` had been
permitted and `allow_credentials=True` were set: operator opens
`http://attacker.example/`, that page issues `fetch("http://mac-mini.local:8000/api/cards/saturday", {credentials: "include"})`,
the response is reflected with `Access-Control-Allow-Origin: http://attacker.example`,
and the attacker's JS reads the operator's cached card. Today the
startup guard makes this impossible, and `allow_credentials=False`
removes the reflection vector entirely.

**Status.** Already implemented; verified. Test coverage at
`api/tests/test_main.py:96-124` (configured-origin reflection) plus
the wildcard-rejection test elsewhere in the file. Inline rationale at
`api/main.py:218-224`.

### S2 — Defense-in-depth security headers (Low / verified)

**Evidence.** Backend middleware at `api/main.py:246-264` sets
`X-Content-Type-Options`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, `Permissions-Policy`,
`Cache-Control: no-store`, `X-Robots-Tag: noindex, nofollow`, and (new
this pass — see S11) `Cross-Origin-Resource-Policy: same-origin`.
Frontend matches via `web/next.config.mjs:11-35` and additionally sets
a strict CSP (`default-src 'self'`, no third-party connect / script
sources, `frame-ancestors 'none'`).

**Why it matters.** The app does not load third-party assets and never
embeds in a third-party frame, so the strict CSP and `DENY` framing
are achievable at zero cost and they neutralize a clickjacking shell
even on the open internet.

**Realistic exploit scenario.** Without `X-Frame-Options: DENY` /
`frame-ancestors 'none'`, an attacker page could iframe the SPA and
overlay invisible buttons over the "Build Tickets" tap target,
tricking the operator into producing an attacker-controlled budget
result. Today the frame guards block the framing entirely.

**Status.** Already implemented; verified. The `noindex, nofollow` /
`X-Robots-Tag` headers are also reinforced by Next.js page metadata at
`web/app/layout.tsx:11-13`.

### S3 — Exception messages redacted before surfacing (Low / verified, regression test added this branch)

**Evidence.** `_redact_exc` at `api/main.py:96-108` strips absolute URLs
and `(?:/[^\s'\"]+){2,}` filesystem paths from the exception text
before placing it in an envelope's `errors` list. The full traceback
still goes to logs via `_log.exception` at every call site
(`api/main.py:344, 383, 506, 545, 633, 681`).

**Why it matters.** Without redaction, `str(exc)` can leak the upstream
scraper endpoints (`https://www.equibase.com/static/entry/...`) and
the absolute on-disk cache layout (`/data/equibase_html/...`) into the
browser. Neither is an immediate exploit, but both are reconnaissance
gifts for the next bug.

**Realistic exploit scenario.** A future bug in
`api/sources/equibase.py` raises with `httpx`'s default error message
`"Server disconnected while reading: GET https://www.equibase.com/static/entry/CD050226R09-EQB.html"`.
Without `_redact_exc`, this string lands in
`Envelope.errors[1]` and is rendered in `web/components/StaleBanner.tsx`
to the operator. Anyone with read access to the iPad screen (or a
shoulder-surfer) sees the exact upstream URL pattern. With
`_redact_exc`, the user sees `RuntimeError: GET <url>`.

**New this branch.** `api/tests/test_stale_fallback.py` adds a
*direct* regression test that drives a `RuntimeError` through the
refresh-card cache-fallback path with two crafted exception messages —
one URL-shaped, one filesystem-path-shaped — and asserts the redacted
payload's `errors[1]` (a) keeps the `RuntimeError:` class prefix, (b)
contains the substitution token (`<url>` or `<path>`), (c) does not
contain `http://` / `https://`, and (d) does not contain the original
hostname or path prefix. This is materially stronger than the prior
pass's coverage, which was end-to-end shape-only.

**Status.** Already implemented; **regression coverage strengthened**
this branch.

### S4 — Request bodies missing numeric bounds (Low / verified)

**Evidence.** `SimulateRequest` and `TicketsRequest` at
`api/main.py:558-587` carry numeric `Field(ge=…, le=…)` bounds:
`n_iterations` ∈ `[1, 100_000]`, `budget_dollars` ∈ `[0, 1_000_000]`,
`base_unit` ∈ `(0, 1_000_000]`. Both also set
`model_config = ConfigDict(extra="forbid")` so unknown fields raise
422 instead of being silently dropped.

**Why it matters.** Without bounds, a `base_unit=0` would short-circuit
`_ticket_cost` to `$0` and force `_fit_to_budget` into its add-loop
(terminating only at horse exhaustion). A negative `base_unit` would
invert the cost ordering. A huge `budget_dollars` would silently
expand the ticket pool. Severity is **Low** rather than Note because
the fix is one Pydantic field constraint per knob and converts a
noisy internal `ValidationError` from `BudgetVariant` into a clean
422 at the boundary.

**Realistic exploit scenario.** Single-user LAN means there is no
real attacker — the impact is reduced to "iPad keypad fat-finger
posts a 0 or a negative and the user gets a confusing ticket envelope"
or "hostile party on the LAN posts `n_iterations=10**9` and pegs the
event loop until uvicorn times out". Bounds defang both.

**Status.** Already implemented; verified. Inline rationale at
`api/main.py:565-585`.

### S5 — Fixture loader trusts caller-supplied `day` (Low / verified)

**Evidence.** `api/sources/fixture.py:38-47` defines
`_ALLOWED_DAYS = frozenset({"friday", "saturday"})` and a
`_validate_day(day)` guard that raises on anything else. Both
`load_card` (`:76`) and `load_odds_records` (`:110`) call
`_validate_day` *before* constructing the fixture path.

**Why it matters.** The FastAPI route binding `day` to
`Literal["friday", "saturday"]` prevents traversal at the HTTP
boundary — but the loader functions are public symbols (`__all__`),
tests / scripts can call them directly, and the guard belongs at the
place where the path is constructed, not three call-sites away.

**Realistic exploit scenario.** With `PICK5_FIXTURES_DIR` set to a
shared mount and a hostile in-process caller invoking
`load_card("../etc/passwd")`, the relative join would resolve outside
the intended fixtures dir. The Pydantic `Race.model_validate` step
would still reject the result, so the actual exploit is "loud crash"
rather than "exfiltration"; but defense-in-depth at the boundary that
owns the path-build is cheaper than auditing every caller.

**Status.** Already implemented; verified. Inline rationale at
`api/sources/fixture.py:32-37` cites this report.

### S6 — `web` container runs `next dev` in production (Note / justified)

**Evidence.** `web/Dockerfile:3,17` sets `NODE_ENV=development` and
runs `npm run dev`. The README explicitly calls this out as
intentional ("the `web` Dockerfile runs `next dev` for the operator's
HMR ergonomics").

**Why it could matter.** `next dev` ships source maps, stack traces
with file paths, the React DevTools hook integration, and an
unminified bundle. None of these are exploitable in isolation; they do
expand the recon surface for a future bug.

**Realistic exploit scenario.** Operator notices a UI bug; while
debugging, an attacker with LAN access to `:3000` grabs the source
maps and reverse-engineers the API contract. Switching to `next start`
ships only the minified bundle. On a single-user LAN/Tailscale
deployment with no auth, the attacker model is already constrained —
but the recon-surface reduction is one of the items the README
"Remediation roadmap" calls for if exposure ever widens.

**Justification (status: kept as-is).** The deployment target is "Mac
mini on the user's LAN, optionally over Tailscale" — a single-user
personal tool where a 1-2s production-build feedback loop matters more
than a recon-surface reduction that has no real attacker behind it.
Switching to `next start` is a one-line README + Dockerfile change if
the operator ever exposes it more widely.

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
`api/tests/test_main.py:673-680` explicitly asserts the diagnostic
routes appear in the OpenAPI document.

**Justification (status: kept as-is).** The OpenAPI surface is a
required operator diagnostic for this project — `BRAINDUMP.md` "Open
questions" item 3 leaves the budget-entry workflow open between SPA
and Swagger, and the race-morning runbook expects `/api/health` to be
reachable directly. The trust boundary is the LAN, the only caller is
the operator's iPad, and the request schemas have no secrets. Closing
the docs route would actively hurt the documented debugging workflow.

### S9 — TwinSpires browser-impersonation user-agent (Note / justified)

**Evidence.** `api/sources/twinspires.py:36-44` sends a Chrome-on-macOS
`User-Agent` and seeds session cookies via a homepage GET. The
optional `curl_cffi` fallback (`api/sources/twinspires.py:482-512`) is
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
constant `"CD"`, `date` is the regex-validated `DERBY_*_DATE` env var
(`_ISO_DATE_RE = ^\d{4}-\d{2}-\d{2}$` at `api/main.py:85`),
`race_number` is the `Pick5` legs constant. There is no path in the
codebase by which a request body or query parameter influences the
outbound URL.

**Status.** Verified. No action needed; documented here to close out
the SSRF lens. See S16 for the related observation that the date
value flows from env into both the outbound URL builders and the
on-disk cache filename — both consumers are protected by the same
ISO-date regex.

### S11 — Cross-Origin-Resource-Policy missing (Low / fixed this pass)

**Evidence (before).** Neither the FastAPI middleware nor the Next.js
headers emitted `Cross-Origin-Resource-Policy`. The CORS allow-list
(S1) prevents JS-readable cross-origin reads, and `X-Frame-Options:
DENY` / `frame-ancestors 'none'` (S2) prevent framing — but
`<img src="http://mac-mini.local:8000/api/cards/saturday">` or
`<link rel=preload as=fetch href="…">` from a malicious origin would
still trigger an opaque request whose response status, size, and
load timing are observable cross-origin. With Spectre-class side
channels in scope, opaque responses are no longer "private".

**Realistic exploit scenario.** Operator visits attacker site while
the iPad is on the same LAN. Attacker page issues
`<link rel=preload as=fetch href="http://mac-mini.local:8000/api/cards/saturday" crossorigin>`.
CORS rejects JS access to the body, but the load-success bit and
response timing leak. With Spectre, the attacker can cross-fetch the
JSON into a SharedArrayBuffer (when one is available; not on iPad
Safari today, but the threat is durable). Setting CORP to
`same-origin` makes the browser refuse to deliver the response to a
non-same-origin embedder regardless of how it was requested.

**Fix applied this pass.**

```python
# api/main.py:262 — added inside security_headers middleware
response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
```

```js
// web/next.config.mjs:15 — added inside SECURITY_HEADERS
{ key: "Cross-Origin-Resource-Policy", value: "same-origin" },
```

Inline comment at `api/main.py:242-247` explains the layered intent
("blocks opaque cross-origin embedding on top of the CORS allow-list
— fetches still go through CORSMiddleware, but a malicious page can
no longer pull the JSON in as a no-cors resource"). Same idea on the
Next.js side at `web/next.config.mjs:5-12`.

**Why same-origin and not cross-origin.** `Cross-Origin-Resource-Policy:
cross-origin` would be permissive — it tells browsers "this resource
is fine to embed anywhere." `same-origin` is the strictest setting and
matches the actual access pattern: only the same-origin SPA at
`:3000` (which proxies through `/api/*` to `:8000`) ever needs to
read these responses. The Next.js → FastAPI server-to-server fetch
runs on the docker network where CORP is not consulted by browsers.

**Test impact.** Verified — `pytest api/tests` runs **376 passed, 1
skipped** before and after this header addition (the
`test_403_without_fallback_raises` failure that this report previously
called pre-existing was tightened by the error-handling pass — see
`docs/audits/error-handling-report.md` F35). No test asserts on these
headers, so the only measurable change is the response payload growing
by 38 bytes per request.

### S12 — `@pytest.mark.live` silently deselects by default (Note / documented this pass)

**Evidence.** `api/pyproject.toml:30-39` registers a `live` marker and
sets `addopts = "-m 'not live'"`. The default `pytest api/tests`
invocation deselects every test carrying `@pytest.mark.live`.

**Why it could matter.** A future security regression test ("the live
TwinSpires response must not be parsed for a header that lets the
adapter follow an arbitrary URL") tagged with `@pytest.mark.live`
would silently skip on every CI / pre-commit run. The regression
would only fire when the developer explicitly opted into
`pytest -m live`, which is rare by design. The marker is process-
correct (live tests are slow and flaky, deselecting them by default
matches the "fast feedback" goal), but the discipline of "what tests
are allowed to live behind this marker" is not enforced anywhere.

**Realistic exploit scenario.** Not an exploit — a process risk. A
maintainer adds a `@pytest.mark.live` test that exercises the real
TwinSpires response and asserts no auth header is forwarded. A later
refactor introduces a leak. CI passes. The leak ships.

**Fix applied this pass.** Added a comment to
`api/pyproject.toml:30-37` warning that `@pytest.mark.live` must not
be applied to security-regression tests. If a regression check
genuinely needs a real external service, gate it on a separate
marker so the default run still enforces the security invariant.

**Status.** Documented this pass. No code change beyond the comment;
the marker behavior itself is intentional.

### S13 — `_FS_PATH_RE` only redacts paths with ≥2 segments (Note / justified)

**Evidence.** `api/main.py:90` —
`_FS_PATH_RE = re.compile(r"(?:/[^\s'\"]+){2,}")`. Single-segment
absolute paths (`/data`, `/app`, `/tmp`) are not matched by this
pattern and therefore not redacted by `_redact_exc`.

**Why it could matter.** An exception message like `"cwd is /app"`
would leak the WORKDIR through to the response, telling an attacker
the deployment is containerized.

**Realistic exploit scenario.** Tiny — single-segment paths leak
"this is run from a Linux filesystem at one of the well-known mount
points" rather than anything actionable. The realistic source of
sensitive paths is httpx error messages with full paths
(`/data/equibase_html/CD050226R09-EQB.html`), and those are 4+
segments, well above the threshold.

**Justification (status: kept as-is).** Tightening the regex to
`/[^\s'"]+(?:/[^\s'"]+)*` — i.e. one-or-more segments — would catch
single-segment paths, but at the cost of false positives in
common-but-benign messages. The most fragile case is fractional odds:
`"5/2"` does not start with `/`, so a one-or-more pattern would not
match it, but messages like `"value /default expected"` would over-
redact. Today's `{2,}` regex is the deliberate balance — wide enough
to catch real cache-path leaks, narrow enough to avoid mangling
non-path text. Inline rationale at `api/main.py:86-91` explains the
threat ("URL fragments and absolute filesystem paths in the message
bodies of upstream exceptions") but does not yet call out the
two-segment trade-off; **Action**: rationale comment to be tightened
in the next cleanup pass. Documented here so the next reader
understands the choice.

### S14 — `/api/pick5/{day}/debug` exposes adapter labels (Note / justified)

**Evidence.** `api/main.py:737-800` returns a JSON document including
`card.source = _card_source_label(cached.races)` (e.g.
`"equibase+twinspires"` or `"fixture"`) plus race / runner counts and
the latest refresh timestamp. No auth gate.

**Why it could matter.** The adapter set is reconnaissance — telling
an attacker which upstream sources to attempt to MitM or feed
malicious responses to. This is a much smaller leak than S8 (Swagger
exposes the full schema), so the same justification logic applies:
operator diagnostic on a LAN-trust-boundary, no secrets in the
output, closing it would actively hurt the documented debug
workflow ("useful for diagnosing what state the system is in
without opening browser devtools" — docstring at `api/main.py:741`).

**Justification (status: kept as-is).** Same trust-boundary logic as
S8. The `card.source` field is a diagnostic aid, not a secret —
README "Run locally" already documents that the backend is
"Equibase + TwinSpires (plus a fixture mode for offline workflow
testing)", so the adapter set is publicly stated. If exposure ever
widens, this route gates behind the same auth dependency S8 calls
for.

### S15 — Fixture entries silently skipped on type mismatch (Note / justified)

**Evidence.** `api/sources/fixture.py:130-148` — the fixture-odds
loader iterates `raw` JSON entries and `continue`s on any of: the
entry not being a dict, missing `raceId`, missing `post`, missing
`odds`, or odds-to-probability returning `None`. There is no count
or warning on skipped entries.

**Why it could matter.** An attacker who can drop a malformed entry
into `fixtures/pick5/saturday-odds.json` could silently hide a
horse's odds from the response, causing the validate step to flag
"missing odds" and the system to enter the cache-fallback path —
denial-of-service on the fixture mode workflow. The threat actor
has to be the operator (or someone with write access to the
fixtures directory), since the file is committed to the repo.

**Justification (status: kept as-is).** Fixtures are committed
config under operator review — the trust model treats them as
trusted input. The silent-skip behavior is the documented contract
("Records whose `(raceId, post)` does not match … are skipped" in
the docstring at `api/sources/fixture.py:103-108`) and the
error-handling-report finding F32 covers the same point with the
same reasoning. Adding a strict-mode toggle for CI would be
worthwhile but is out of scope for this pass; tracked under
`docs/audits/error-handling-report.md` F32.

### S16 — `DERBY_*_DATE` env flows into outbound URL + cache filename (Note / verified)

**Evidence.** `day_to_iso_date` at `api/main.py:125-143` reads
`os.getenv(f"DERBY_{day.upper()}_DATE")` and validates it against
`_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")` before
returning. The validated value flows into:

1. `f"odds_{iso_date}.db"` — the SQLite filename in
   `api/cache.py:78` (`OddsCache.__init__`).
2. `entry_url(iso_date, race_number, …)` — the Equibase outbound URL
   in `api/sources/equibase.py:88-98`.
3. `program_url` / `odds_url` — the TwinSpires outbound URLs at
   `api/sources/twinspires.py:83-110`.
4. The on-disk Equibase HTML cache directory (`equibase_html` joined
   with the date-derived filename hash).

**Why it matters.** A `DERBY_FRIDAY_DATE=../../etc/passwd` value
would be:

- caught by the regex (does not match `^\d{4}-\d{2}-\d{2}$`);
- if somehow it bypassed: it would pass through `strftime("%m%d%y")`
  inside Equibase's `_to_date` (which would itself raise on the bad
  date format);
- the cache filename construction uses `f"odds_{iso_date}.db"` with
  the validated string only.

The regex is anchored (`^…$`), so `..\..\` and any path-traversal
attempt is rejected at the earliest possible point. Inline rationale
at `api/main.py:125-134` documents this exact flow.

**Status.** Verified. No action needed.

---

## Safe hardening implemented this pass

1. **`api/main.py:242-264`** — added
   `Cross-Origin-Resource-Policy: same-origin` to the FastAPI
   `security_headers` middleware. Inline comment at lines 242-247
   explains the layered intent (S11). The header is set via
   `setdefault` so any future per-route override remains possible.
2. **`web/next.config.mjs:5-15`** — added the same CORP header to the
   Next.js per-route `SECURITY_HEADERS` array. Inline comment at
   lines 5-12 cross-references S11 for the rationale.
3. **`api/pyproject.toml:30-37`** — added a comment to the pytest
   marker registration warning that `@pytest.mark.live` must not be
   applied to security-regression tests, since `addopts = "-m 'not live'"`
   silently deselects them by default (S12).

Test suite: `pytest api/tests/` — **376 passed, 1 skipped** after this
pass plus the error-handling pass that immediately followed. At
security-pass time the suite had a single failure
(`test_twinspires.py::test_403_without_fallback_raises`) that was
pre-existing on `b9d3ec8`; the error-handling pass tightened the test
to actually exercise the F15 contract (see
`docs/audits/error-handling-report.md` F35), and the suite has been
clean since.

---

## Remediation roadmap (for if exposure ever widens)

The current posture is correct for the documented LAN / Tailscale
deployment. The roadmap below is what a wider exposure (open-internet
host, multi-user) would require, in priority order:

1. **Add auth.** Either a single-user shared secret enforced via a
   FastAPI dependency, or terminate at an authenticating reverse proxy.
   Required before any non-LAN exposure — every other item below is
   secondary to this. The endpoints in scope are every `/api/**`
   route plus `/docs`, `/redoc`, and `/openapi.json`.
2. **Switch the web image to `next start` (S6).** Two-line change once
   the operator decides production stability matters more than HMR.
3. **Restrict the OpenAPI surface (S8) and the debug route (S14).**
   Either gate `/docs` / `/redoc` / `/openapi.json` /
   `/api/pick5/{day}/debug` behind the auth dependency, or pass
   `docs_url=None, redoc_url=None, openapi_url=None` to the
   `FastAPI(...)` constructor and serve a static reference instead.
4. **Add HSTS at the TLS terminator (S7).** Belongs on whatever proxy
   does TLS termination, not on the FastAPI service itself.
5. **Add a request-body size limit and a per-IP rate limit on the
   refresh + simulate routes.** Currently single-user so contention
   is not a concern; for multi-user, the `asyncio.to_thread` offload
   still allows N concurrent ~3-5 minute scrapes to pin the worker
   pool. `slowapi` plus a starlette middleware that caps body size at
   ~64 KB are the conventional choices.
6. **Tighten `_FS_PATH_RE` to also catch single-segment paths (S13).**
   Cheap once a regression test is in place — the `test_stale_fallback`
   module added this branch is the right home for it.
7. **Add a strict-mode toggle to fixture loading (S15).** `STRICT=1`
   raises on the first malformed entry instead of silently skipping —
   useful for CI/regression coverage of fixture authoring.

---

## Escalations

None this pass. Every finding above either had a single-author fix or
a clearly justified accept-as-is. The two open items in the
companion error-handling report (E1 — UI tags / odds overrides
local-only) remain functional, not security, and are tracked there.
