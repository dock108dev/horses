# ISSUE-004: TwinSpires + KentuckyDerby source adapters — live odds, program data, scratch detection

**Priority**: high
**Labels**: data-source, phase-1
**Dependencies**: ISSUE-002
**Status**: implemented

## Description

Implement `api/sources/twinspires.py` and `api/sources/kentuckyderby.py`. Per twinspires-scraper-feasibility.md: TwinSpires is a React SPA — raw HTML returns no data. Target internal XHR endpoints: `GET /ts-res/api/racing/program?track=CD&date={YYYYMMDD}&race={N}` for entries/program; `GET /ts-res/api/racing/odds?track=CD&date={YYYYMMDD}&race={N}` for live odds. Always seed session cookies via homepage GET before API calls. Primary HTTP client: `curl_cffi` with `impersonate='chrome124'` for Cloudflare bypass; fallback to plain `httpx` if curl_cffi unavailable. Full browser headers required (User-Agent, Referer, Origin, Accept, Sec-Fetch-*). Respect 30s polling interval for odds — matching the ~60s tote cadence per live-odds-timing-and-frequency.md. Scratch detection: diff `runners[]` array by programNumber between successive polls; flag when `scratched` transitions false→true. KentuckyDerby adapter: attempt `__NEXT_DATA__` JSON extraction from page HTML (regex `<script id="__NEXT_DATA__"...>`); fall back to JSON-LD `competitor` array for horse name list. Per scratch-detection-source.md, TwinSpires has privileged low-latency CDI data. Endpoint URLs should be verified via DevTools 48h before race day.

## Acceptance Criteria

- [ ] TwinSpires adapter fetches live odds JSON for a given CD race, returning winOdds per horse as fractional strings
- [ ] Session cookie seeding (homepage GET) runs before any API call in a session
- [ ] curl_cffi impersonation used automatically when plain httpx returns 403
- [ ] Scratch detection: calling poll twice on a race where a horse scratched between polls returns Scratch event with horse name and reason
- [ ] Polls respect 30s minimum interval between odds calls per race
- [ ] KentuckyDerby adapter extracts entries list from __NEXT_DATA__ when present; returns empty list gracefully when absent

## Implementation Notes


Attempt 1: Added api/sources/twinspires.py: TwinSpiresAdapter that seeds session via homepage GET, sends full browser headers, parses /ts-res/api/racing/{program,odds} JSON, returns winOdds as fractional strings, enforces 30s per-race odds floor, auto-fallbacks to curl_cffi on httpx 403, and emits ScratchEvent on programNumber scratched=false→true diff. Added api/sources/kentuckyderby.py: KentuckyDerbyAdapter that extracts __NEXT_DATA__ JSON via regex, falls back to JSON-LD competitor[] names, returns [] gracefully when neither present. 35 new tests cover every acceptance criterion.