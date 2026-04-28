"""Ticket builder for the Pick 5 — A/B/chaos tickets, budget variants.

The builder returns three families of :class:`api.sim.Ticket` per budget:

1. **main** — one A-tagged horse per leg (A/A/A/A/A); if a leg has multiple
   A horses, all of them ride. If a leg has no A horse, it falls back to
   the leg favorite (highest ``finalProbability``).
2. **backup-{n}** — five tickets, one per leg, where leg ``n`` swaps in
   every B-tagged horse on that leg while the others keep their A
   selections. Skipped for legs with no B horses (those would duplicate
   the main ticket).
3. **chaos** — replace every leg flagged ``chaos_race`` with that leg's
   chaos-tagged + ``useful_value``-flagged horses. Built only when at
   least one chaos leg has a chaos/value horse.

Each ticket is then trimmed to fit ``budget_dollars`` by removing the
lowest-``finalProbability`` selection from the leg with the most
selections, repeating until ``cost <= budget`` or every leg is down to
one horse.

Tickets are ranked by Monte-Carlo estimated hit rate when the card is
fully blended; otherwise by ascending cost.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from api.model import (
    FLAG_CHAOS_RACE,
    FLAG_USEFUL_VALUE,
    PICK5_LEG_COUNT,
    Horse,
    Race,
    select_pick5_legs,
)
from api.sim import DEFAULT_BASE_UNIT, Ticket

STANDARD_BUDGETS: tuple[float, ...] = (48.0, 96.0, 144.0, 192.0)

A_TAG = "A"
B_TAG = "B"
CHAOS_TAG = "chaos"

_DEFAULT_RANKING_ITERATIONS = 2_000
_DEFAULT_RANKING_SEED = 0

_log = logging.getLogger(__name__)


class BudgetVariant(BaseModel):
    """Tickets generated for a single budget."""

    model_config = ConfigDict(extra="forbid")

    budget_dollars: float = Field(ge=0.0)
    tickets: list[Ticket] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_tickets(
    races: list[Race],
    budget_dollars: float,
    base_unit: float = DEFAULT_BASE_UNIT,
) -> list[Ticket]:
    """Build A/B/chaos tickets within ``budget_dollars``.

    Returns an empty list when the card is missing any Pick 5 leg or
    when the main ticket cannot be built (e.g. a leg with no eligible
    runners). See module docstring for the ticket-family construction
    rules and ranking behavior.
    """
    legs = select_pick5_legs(races)
    if len(legs) != PICK5_LEG_COUNT:
        return []

    main_sel = _build_main_selections(legs)
    if main_sel is None:
        return []

    tickets: list[Ticket] = []

    main_after_budget = _enforce_budget(main_sel, legs, budget_dollars, base_unit)
    tickets.append(
        Ticket(
            id="main",
            cost=_ticket_cost(main_after_budget, base_unit),
            selections=main_after_budget,
        )
    )

    for i in range(PICK5_LEG_COUNT):
        bsel = _build_backup_selections(legs, main_sel, i)
        if bsel is None:
            continue
        bsel = _enforce_budget(bsel, legs, budget_dollars, base_unit)
        tickets.append(
            Ticket(
                id=f"backup-{i + 1}",
                cost=_ticket_cost(bsel, base_unit),
                selections=bsel,
            )
        )

    csel = _build_chaos_selections(legs, main_sel)
    if csel is not None:
        csel = _enforce_budget(csel, legs, budget_dollars, base_unit)
        tickets.append(
            Ticket(
                id="chaos",
                cost=_ticket_cost(csel, base_unit),
                selections=csel,
            )
        )

    return _rank_tickets(races, tickets)


def build_tickets_for_budgets(
    races: list[Race],
    budgets: Iterable[float] = STANDARD_BUDGETS,
    base_unit: float = DEFAULT_BASE_UNIT,
) -> list[BudgetVariant]:
    """Run :func:`build_tickets` once per unique budget, preserving order.

    Duplicate budgets (e.g. a custom ``96.0`` alongside the standard
    ``96.0``) collapse to a single variant.
    """
    out: list[BudgetVariant] = []
    seen: set[float] = set()
    for raw in budgets:
        b = float(raw)
        if b in seen:
            continue
        seen.add(b)
        out.append(
            BudgetVariant(
                budget_dollars=b,
                tickets=build_tickets(races, b, base_unit),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Selection construction
# ---------------------------------------------------------------------------


def _eligible(horse: Horse) -> bool:
    return not horse.scratched


def _horses_with_tag(race: Race, tag: str) -> list[Horse]:
    return [h for h in race.horses if _eligible(h) and h.userTag == tag]


def _favorite(race: Race) -> Horse | None:
    """Highest finalProbability — falls back to marketProbability, then 0."""
    candidates = [h for h in race.horses if _eligible(h)]
    if not candidates:
        return None
    return max(candidates, key=_horse_probability_key)


def _horse_probability_key(horse: Horse) -> float:
    if horse.finalProbability is not None:
        return horse.finalProbability
    if horse.marketProbability is not None:
        return horse.marketProbability
    return 0.0


def _build_main_selections(legs: list[Race]) -> list[list[str]] | None:
    """One selection per leg — every A horse, or the favorite if no A tag."""
    selections: list[list[str]] = []
    for race in legs:
        a_horses = _horses_with_tag(race, A_TAG)
        if a_horses:
            selections.append([h.id for h in a_horses])
            continue
        fav = _favorite(race)
        if fav is None:
            return None
        selections.append([fav.id])
    return selections


def _build_backup_selections(
    legs: list[Race],
    main_selections: list[list[str]],
    swap_leg_idx: int,
) -> list[list[str]] | None:
    """Replace one leg's selections with that leg's B horses; ``None`` if no B."""
    race = legs[swap_leg_idx]
    b_horses = _horses_with_tag(race, B_TAG)
    if not b_horses:
        return None
    selections = [list(s) for s in main_selections]
    selections[swap_leg_idx] = [h.id for h in b_horses]
    return selections


def _build_chaos_selections(
    legs: list[Race],
    main_selections: list[list[str]],
) -> list[list[str]] | None:
    """Swap chaos-flagged legs to chaos / useful_value horses; ``None`` if no swap.

    A leg is "chaos-flagged" when any of its horses carries the
    ``chaos_race`` flag. Chaos/value horses are non-scratched horses
    whose ``userTag == "chaos"`` or whose ``flags`` include
    ``"useful_value"``. If the chaos pool on a flagged leg is empty,
    the leg keeps its main selection.
    """
    selections = [list(s) for s in main_selections]
    changed = False
    for i, race in enumerate(legs):
        if not _race_is_chaos(race):
            continue
        chaos_horses = _chaos_value_horses(race)
        if not chaos_horses:
            continue
        new_ids = [h.id for h in chaos_horses]
        if new_ids != selections[i]:
            selections[i] = new_ids
            changed = True
    if not changed:
        return None
    return selections


def _race_is_chaos(race: Race) -> bool:
    return any(FLAG_CHAOS_RACE in h.flags for h in race.horses)


def _chaos_value_horses(race: Race) -> list[Horse]:
    return [
        h
        for h in race.horses
        if _eligible(h)
        and (h.userTag == CHAOS_TAG or FLAG_USEFUL_VALUE in h.flags)
    ]


# ---------------------------------------------------------------------------
# Cost + budget enforcement
# ---------------------------------------------------------------------------


def _ticket_cost(selections: list[list[str]], base_unit: float) -> float:
    n = 1
    for leg in selections:
        n *= len(leg)
    return float(n) * float(base_unit)


def _enforce_budget(
    selections: list[list[str]],
    legs: list[Race],
    budget: float,
    base_unit: float,
) -> list[list[str]]:
    """Trim selections until cost fits the budget.

    Each iteration: pick the leg with the most selections (ties broken by
    leg order). Drop the horse with the lowest finalProbability (then
    marketProbability, then arbitrary) from that leg. Repeat until
    ``cost <= budget`` or every leg has a single selection.
    """
    sels = [list(leg) for leg in selections]
    horses_by_leg: list[dict[str, Horse]] = [
        {h.id: h for h in race.horses} for race in legs
    ]
    while _ticket_cost(sels, base_unit) > budget:
        reducible = [i for i, s in enumerate(sels) if len(s) > 1]
        if not reducible:
            break
        leg_idx = max(reducible, key=lambda i: len(sels[i]))
        leg_horses = horses_by_leg[leg_idx]
        sorted_ids = sorted(
            sels[leg_idx],
            key=lambda hid: _horse_probability_key(leg_horses[hid])
            if hid in leg_horses
            else 0.0,
        )
        drop_id = sorted_ids[0]
        sels[leg_idx] = [hid for hid in sels[leg_idx] if hid != drop_id]
    return sels


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def _rank_tickets(races: list[Race], tickets: list[Ticket]) -> list[Ticket]:
    """Order tickets by simulated hit rate descending, then cost ascending.

    Falls back to cost-only ordering when the simulator can't run (e.g.
    some leg has no ``finalProbability``). The catch is broad because the
    contract here is "must never break ticket construction" — but the
    fallback is logged at warning so a real sim-engine bug doesn't go
    silent in production. See error-handling-report finding F16.
    """
    if not tickets:
        return tickets
    try:
        from api import sim

        result = sim.simulate(
            races,
            tickets,
            n_iterations=_DEFAULT_RANKING_ITERATIONS,
            seed=_DEFAULT_RANKING_SEED,
        )
        rates = {tr.ticket_id: tr.estimated_hit_rate_pct for tr in result.tickets}
        return sorted(tickets, key=lambda t: (-rates.get(t.id, 0.0), t.cost))
    except Exception as exc:
        _log.warning(
            "Hit-rate ranking failed; falling back to cost order: %s", exc
        )
        return sorted(tickets, key=lambda t: t.cost)


__all__ = [
    "STANDARD_BUDGETS",
    "A_TAG",
    "B_TAG",
    "CHAOS_TAG",
    "BudgetVariant",
    "build_tickets",
    "build_tickets_for_budgets",
]
