# ISSUE-013: Next.js frontend — iPad-optimized day pages, race card UI, horse tagging, manual overrides

**Priority**: medium
**Labels**: frontend, phase-2
**Dependencies**: ISSUE-001, ISSUE-009
**Status**: implemented

## Description

Implement Next.js 14 App Router frontend at `web/`. `web/app/page.tsx`: landing page with Friday and Saturday navigation cards. `web/app/sequence/[day]/page.tsx`: day view with header row (Refresh Card, Refresh Odds, Run Sim, Build Tickets buttons; Last card refresh / Last odds refresh timestamps; Source attribution; Budget input defaulting $96; Base unit input defaulting $0.50). Shows stale data banner 'Showing cached odds from {time} — Refresh failed at {time}' when API returns stale=true. Renders the 5 Pick 5 race cards in sequence. `web/components/RaceCard.tsx`: section header with race number, leg label (Leg 1–5), race name if available, surface/distance, post time. `web/components/HorseRow.tsx`: columns Post | Horse | ML Odds | Current Odds | Drift | Market% | Final% | Tag | Flags. Tap horse row to open tag picker (single/A/B/C/toss/chaos/boost/fade). Tap odds cell for manual override input. `web/components/OddsBadge.tsx`: shows ML + current side by side; green background when odds shortening (taking money), grey when lengthening. All touch targets minimum 44px. `viewport-fit=cover` meta tag. API calls proxied via `next.config.ts` rewrites from `/api/*` to `http://api:8000/api/*` inside Docker.

## Acceptance Criteria

- [ ] App opens at http://mac-mini.local:3000 on iPad without horizontal scroll
- [ ] Refresh Card button triggers POST /api/cards/{day}/refresh and reloads race display
- [ ] Refresh Odds button triggers POST /api/odds/{day}/refresh and updates odds in-place
- [ ] All 5 Pick 5 legs visible with correct leg labels, race info, and horse rows
- [ ] ML odds and current odds shown per horse; drift column shows movement direction
- [ ] Stale banner appears when API response has stale=true
- [ ] Tapping a horse row opens tag picker; selecting tag persists in UI state and is included in simulate/build-tickets requests
- [ ] Manual odds override accepted via tap on odds cell; override value sent to backend
- [ ] All interactive elements have minimum 44px touch target

## Implementation Notes


Attempt 1: Built Next.js 14 frontend at web/. Added /api/* proxy rewrites in next.config.mjs (env-driven, defaults to http://api:8000), viewport-fit=cover, and globals.css base. Implemented landing page with Friday/Saturday cards, sequence/[day] client page with header (Refresh Card/Odds, Run Sim, Build Tickets, timestamps, source, $96 budget, $0.50 base unit), stale banner, RaceCard with leg label/race info, HorseRow with Post|Horse|ML→Current|Drift|Market%|Final%|Tag|Flags, OddsBadge with green/grey drift coloring, TagPicker (single/A/B/C/toss/chaos/boost/fade) and OddsOverride modals. All taps ≥44px. Tags + overrides held in UI state and sent in simulate/build-tickets request bodies. lib/api.ts client and lib/odds.ts helpers added.