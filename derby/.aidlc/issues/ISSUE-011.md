# ISSUE-011: Monte Carlo simulation engine (`api/sim.py`) — Pick 5 hit rate estimation

**Priority**: medium
**Labels**: simulation, phase-3
**Dependencies**: ISSUE-010, ISSUE-009
**Status**: implemented

## Description

Implement `api/sim.py`. Function `simulate(races: list[Race], tickets: list[Ticket], n_iterations: int = 50000) -> SimulationResult`. For each iteration: iterate over the 5 Pick 5 leg races in sequenceRole order; sample one winner per leg using `random.choices(horses, weights=[h.finalProbability for h in non_scratched_horses])`; combine 5 winners into a Pick 5 combo; evaluate combo against each ticket to determine hit. Output: per-ticket `{ticket_id, cost, estimated_hit_rate_pct, chalkiness_pct, chaos_coverage_pct, separator_coverage_pct}`. Chalkiness: fraction of iterations where all 5 winners had marketProbability > 0.30. Chaos coverage: fraction of iterations where at least one leg was won by a horse tagged 'chaos'. Separator coverage: fraction where at least one likely_separator-flagged horse won. Run 50,000 iterations by default; configurable up to 100,000. Wire into POST /api/simulate/{day} endpoint in ISSUE-009.

## Acceptance Criteria

- [ ] 50,000-iteration simulation completes in under 10 seconds on standard hardware
- [ ] estimated_hit_rate_pct is within 1.5 percentage points of analytical approximation for a sample ticket
- [ ] chalkiness_pct, chaos_coverage_pct, separator_coverage_pct all computed per-ticket
- [ ] Scratched horses excluded from winner sampling
- [ ] SimulationResult includes all metric fields for every input ticket
- [ ] POST /api/simulate/{day} returns simulation results for current day's tagged horses

## Implementation Notes


Attempt 1: Added api/sim.py with Monte Carlo Pick 5 engine: Ticket/SimulationResult Pydantic models, simulate(races, tickets, n_iterations) using bisect-based weighted sampling on cum_weights pre-built per leg, scratched/zero-prob runners excluded, chalkiness/chaos/separator metrics per ticket, n_iterations clamped to [1, 100_000], optional seed for tests. default_tickets_from_tags() builds a ticket from {single,A,B,C,chaos} userTags with favorite fallback. Wired POST /api/simulate/{day} in api/main.py to blend missing finalProbability, build default tickets, run sim, and return result.model_dump.