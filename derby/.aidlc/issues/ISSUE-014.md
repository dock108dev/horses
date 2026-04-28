# ISSUE-014: Simulation + ticket UI components — SimulationSummary and TicketBuilder

**Priority**: medium
**Labels**: frontend, phase-2, phase-4
**Dependencies**: ISSUE-013, ISSUE-011, ISSUE-012
**Status**: implemented

## Description

Implement `web/components/SimulationSummary.tsx` and `web/components/TicketBuilder.tsx`. SimulationSummary: after Run Sim completes, show per-ticket summary card: estimated hit rate %, cost, chalkiness %, chaos coverage %, separator coverage %. One card per ticket (main, 5 backups, chaos). TicketBuilder: after Build Tickets completes, show all budget variants ($48/$96/$144/$192) as tabs or accordion sections. Per ticket: leg-by-leg breakdown showing which horses are included (post number + name), total cost, estimated hit rate if sim has run. Allow user to mark tickets as 'keep' or 'drop'. Wire Run Sim button (in ISSUE-013 day page) to POST /api/simulate/{day}, populate SimulationSummary. Wire Build Tickets button to POST /api/tickets/{day}/build with current tags, budget, and base unit, populate TicketBuilder. Both components handle loading state and error state (display 'Simulation failed' with error message on API error).

## Acceptance Criteria

- [ ] SimulationSummary renders after Run Sim with hit rate %, chalkiness %, chaos coverage % per ticket
- [ ] TicketBuilder renders all 4 standard budget variants with tab or accordion navigation
- [ ] Each ticket shows leg breakdown: per-leg horse selections with post number and name
- [ ] Cost displayed per ticket matches backend cost field
- [ ] Estimated hit rate shown per ticket when simulation results available
- [ ] Loading spinner shown while POST requests are in-flight
- [ ] Error state shown with message when POST returns non-200

## Implementation Notes


Attempt 1: Added web/components/SimulationSummary.tsx and web/components/TicketBuilder.tsx; extended web/lib/types.ts and web/lib/api.ts with typed sim/build payloads; wired Run Sim and Build Tickets results into web/app/sequence/[day]/page.tsx with per-action loading + error state. Each ticket shows cost, leg-by-leg post+name breakdown, sim hit rate, and a keep/drop toggle; budgets render as tabs.