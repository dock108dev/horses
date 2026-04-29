# Derby Pick 5

Personal iPad browser app for analyzing the Friday (Oaks) and Saturday (Derby)
Pick 5 sequences at Churchill Downs. Pulls race cards, morning-line, and live
odds from public sources, runs Monte Carlo simulations, and builds budget-bound
A/B/chaos tickets. The app does not place bets. See `BRAINDUMP.md` for the
product brief.

The codebase is two services wired together by Docker Compose:

- `api/` — FastAPI backend. Source adapters (Equibase, TwinSpires, plus a
  fixture mode for offline workflow testing), per-day SQLite cache for
  stale-fallback, post-refresh validation, blend/flag probability layer,
  Monte Carlo sim, ticket builder.
- `web/` — Next.js (App Router) frontend. iPad-targeted UI for refreshing
  the card, tagging horses, running simulations, and viewing tickets. Calls
  the backend through a `/api/:path*` rewrite.

## Run locally

```sh
cp .env.example .env
docker compose up
```

Open `http://localhost:3000` (or `http://mac-mini.local:3000` from the iPad
on the same LAN). The backend is reachable directly at port 8000; the SPA
proxies `/api/*` through Next.js.

`pytest api/tests` runs the backend test suite. `npx tsc --noEmit` from
`web/` typechecks the frontend.

### Required configuration

`.env.example` covers the defaults the operator needs day-to-day; a
couple of optional overrides are read directly by the API and aren't in
the example file. The full set:

- `API_CORS_ORIGINS` (in `.env.example`) — explicit comma-separated
  origin allow-list. `*` is rejected at startup; the rationale is
  documented inline at `api/main.py` where the wildcard guard is
  enforced.
- `PICK5_DATA_MODE=fixture` (in `.env.example`, commented) — serve
  `POST /api/cards/{day}/refresh` and `POST /api/odds/{day}/refresh`
  from `fixtures/pick5/*.json` instead of hitting Equibase / TwinSpires.
  Per-request override: `?source=fixture`.
- `API_BASE_URL` (in `.env.example`) — used by the Next.js server-side
  fetches inside the docker network (default `http://api:8000`).
  Browser requests hit the same-origin `/api` proxy, so no public base
  URL is needed.
- `DERBY_FRIDAY_DATE` / `DERBY_SATURDAY_DATE` (read by `api/main.py`,
  not in `.env.example`) — override the defaults (`2026-05-01` /
  `2026-05-02`) when targeting a different year. Must match
  `YYYY-MM-DD`; an anchored regex check rejects anything else at
  request time.

## Deploy

The intended deployment is a Mac mini on the user's LAN, optionally exposed
over Tailscale. Both Docker images run with `restart: unless-stopped` and a
mounted `./data` volume that persists per-day SQLite snapshots.

The `web` Dockerfile runs `next dev` for the operator's HMR ergonomics; the
`api` Dockerfile runs `uvicorn` against `api.main:app`. There is no auth, no
PII, no money flow — the trust boundary is the LAN/Tailscale perimeter.
Exposing the app beyond the LAN is out of scope; if it ever comes up, add
auth and re-evaluate the CORS/headers posture in `api/main.py` first.

## Documentation

- `BRAINDUMP.md` — product brief, customer voice. Authoritative source
  for what the app must do.
- `docs/audits/` — code-quality (`cleanup-report.md`), error-handling
  (`error-handling-report.md`), security (`security-report.md`), and
  SSOT (`ssot-report.md`) audit reports. Each one is cited by inline
  comments at the code sites they justify; treat them as the rationale
  archive for non-obvious decisions in the codebase.
- `docs/audits/docs-consolidation.md` — log of the latest docs
  reconciliation pass (what was rewritten, deleted, or escalated).
