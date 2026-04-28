# ISSUE-003: Equibase source adapter — race cards, entries, morning line odds, scratches

**Priority**: high
**Labels**: data-source, phase-1
**Dependencies**: ISSUE-002
**Status**: implemented

## Description

Implement `api/sources/equibase.py` to fetch Churchill Downs race cards from Equibase static HTML. Per equibase-data-access.md: URL pattern `/static/entry/CD{MMDDYY}R{NN}-EQB.html` (2-digit year, race zero-padded to 2 digits). Full card discovery via `/static/card/CD{MMDDYY}-EQB.html`. Parse with BeautifulSoup: race header (number, distance, surface, purse, post time in Eastern), entries table (post position, horse name with country suffix stripped, jockey, trainer, ML odds as fractional string, medication flags, scratched detection via 'SCR' cell or strikethrough markup). Browser-like User-Agent + Referer headers required. 3-second minimum between requests. Soft-404 detection: check response text for 'No data found' or empty table body before treating as valid. Race discovery: probe race numbers sequentially, stop at first miss. Cache fetched HTML locally to avoid re-fetching stable entry pages. Per findings.md, this is the primary source for entries and morning line — no live odds available here.

## Acceptance Criteria

- [ ] Given a Churchill Downs date and race number, returns list of horses with post, name, jockey, trainer, ML odds
- [ ] Soft-404 handled: 'No data found' response returns None, not raises
- [ ] Scratched horses flagged via HTML markup detection
- [ ] Rate limiting enforced: minimum 3s between HTTP requests
- [ ] Country-of-origin suffix stripped from horse names (e.g. '(IRE)' removed)
- [ ] Race discovery scans up to 15 races and stops at first 404/soft-404

## Implementation Notes


Attempt 1: Added api/sources/equibase.py — Equibase static-HTML adapter with URL builders for entry/card pages (CD{MMDDYY}R{NN}-EQB.html), browser-like UA+Referer headers, 3s rate-limit floor, on-disk HTML cache, soft-404 detection ('No data found'), country-suffix stripping, BeautifulSoup parsing of race header (distance/surface/post-time) and entries table (post, name, jockey, trainer, ML odds, medication flags), scratched detection via SCR text + strikethrough + scratch class + line-through style, and discover_races() that probes 1..15 and stops at first miss. Created api/sources/__init__.py and 19 tests in tests/test_equibase.py covering URL formats, parsing, soft-404, scratch markers, cache reuse, rate limiting, and discovery cap.