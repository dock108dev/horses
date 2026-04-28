# ISSUE-012: Ticket builder (`api/tickets.py`) — A/B/chaos tickets, budget variants

**Priority**: medium
**Labels**: tickets, phase-4
**Dependencies**: ISSUE-010, ISSUE-009
**Status**: implemented

## Description

Implement `api/tickets.py`. Function `build_tickets(races: list[Race], budget_dollars: float, base_unit: float = 0.50) -> list[Ticket]`. Ticket construction per BRAINDUMP: (1) Main: one A-tagged horse per leg (A/A/A/A/A); if multiple A horses per leg, include all. (2) Backup tickets ×5: replace one leg with all B-tagged horses, one leg at a time, keeping others as A horses. (3) Chaos ticket: replace high-chaos-flag legs with chaos/value-tagged horses. Ticket cost = product(selections_per_leg) × base_unit. Budget enforcement: if cost > budget, reduce legs with most selections first (remove lowest-finalProbability selections until under budget). Generate tickets for all four standard budgets ($48, $96, $144, $192) plus any custom budget from request body. Return tickets ranked by estimated_hit_rate from simulation (if available) or by cost. Wire into POST /api/tickets/{day}/build.

## Acceptance Criteria

- [ ] Main ticket with one A horse per leg costs exactly base_unit × 1 = $0.50
- [ ] Main ticket with two A horses on one leg and one on others costs $0.50 × 2 = $1.00
- [ ] Backup ticket set contains exactly 5 tickets, each with exactly one leg using B horses
- [ ] Cost formula: product(len(selections) per leg) × base_unit is computed correctly
- [ ] Budget enforcement reduces ticket cost to at or below requested budget
- [ ] All four standard budget variants ($48/$96/$144/$192) returned in response
- [ ] POST /api/tickets/{day}/build returns structured Ticket list with cost per ticket

## Implementation Notes


Attempt 1: Added api/tickets.py with build_tickets (main + 5 B-swap backups + chaos ticket, product-cost formula, budget enforcement that drops lowest-finalProbability from the longest leg) and build_tickets_for_budgets (4 standard + custom). Wired POST /api/tickets/{day}/build to return {variants:[{budget_dollars,tickets}]} for $48/$96/$144/$192 plus optional custom; blends finalProbability if missing. Tickets ranked by Monte-Carlo hit rate, falling back to cost. 24 new tests; 274 total passing.