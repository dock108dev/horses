"""Monte Carlo Pick 5 simulation engine.

For each iteration the engine walks the five Pick 5 legs in
``sequenceRole`` order, samples one winner per leg using
``random.choices(horses, weights=[h.finalProbability for h in non_scratched])``,
and combines the five winners into a Pick 5 combo. Each input ticket is
evaluated against the combo to track its hit rate. Three iteration-level
metrics are also accumulated and reported on every ticket:

- ``chalkiness_pct``: fraction of iterations where every winner had
  ``marketProbability > 0.30`` (an all-favorite combo).
- ``chaos_coverage_pct``: fraction where at least one winner carries the
  ``"chaos"`` user tag.
- ``separator_coverage_pct``: fraction where at least one winner carries
  the ``"likely_separator"`` flag.

In addition to the iteration-driven metrics, each
:class:`TicketSimulationResult` also reports two per-ticket pre-sim
scalars derived from the ticket's leg selections and the race state:

- ``payout_score``: ``(1 - raw_chalkiness) ** PAYOUT_SCORE_EXPONENT``
  where ``raw_chalkiness`` is the mean of ``max(marketProbability)``
  across the five legs. Higher = less chalky = higher expected payout.
- ``confidence``: mean of ``confidence_score`` across every selected
  horse. Higher = more confident the legs will hold.

The simulator pre-builds cumulative weights and per-horse flag arrays
once per call so the inner loop is just one ``bisect_left`` per leg.
That keeps a 50,000-iteration run well under the 10-second budget on
ordinary hardware.
"""

from __future__ import annotations

import random
from bisect import bisect_left

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from api.model import (
    FLAG_LIKELY_SEPARATOR,
    PICK5_LEG_COUNT,
    Horse,
    Race,
    select_pick5_legs,
)

TicketLabel = Literal["Balanced", "Safer", "Upside"]

DEFAULT_ITERATIONS = 50_000
MAX_ITERATIONS = 100_000

CHALKINESS_PROB_THRESHOLD = 0.30
CHAOS_USER_TAG = "chaos"

DEFAULT_BASE_UNIT = 0.50
TAGS_FOR_DEFAULT_TICKET: frozenset[str] = frozenset(
    {"single", "A", "B", "C", "chaos"}
)

# Exponent applied to ``(1 - raw_chalkiness)`` when computing
# ``payout_score``. Values > 1 amplify the penalty for chalk-heavy
# selections; 1.5 is the chosen calibration point.
PAYOUT_SCORE_EXPONENT = 1.5


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class Ticket(BaseModel):
    """A Pick 5 ticket — one set of horse-id selections per leg.

    ``selections`` is exactly five entries (one per leg) in
    :data:`PICK5_LEG_ROLES` order. Each entry is the list of horse ids
    selected for that leg; the ticket "hits" an iteration when, for every
    leg, the sampled winner's id is in that leg's selection list.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    cost: float = Field(ge=0.0)
    selections: list[list[str]] = Field(
        min_length=PICK5_LEG_COUNT, max_length=PICK5_LEG_COUNT
    )
    # Pass 2 ticket-quality outputs — defaulted so existing builds remain
    # valid before the edge model populates them. Bounds match the
    # producer ranges (``compute_payout_score``, ``compute_ticket_confidence``,
    # ``compute_chalk_exposure``); ``edge_score`` is intentionally
    # unconstrained because per-horse ``edge_score`` can be negative.
    edge_score: float | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    payout_score: float | None = Field(default=None, ge=0.0, le=1.0)
    chalk_exposure: float | None = Field(default=None, ge=0.0, le=1.0)
    notes: str | None = None
    label: TicketLabel | None = None
    hit_rate_pct: float | None = Field(default=None, ge=0.0, le=100.0)


class TicketSimulationResult(BaseModel):
    """Per-ticket simulation output."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: str
    cost: float
    estimated_hit_rate_pct: float
    chalkiness_pct: float
    chaos_coverage_pct: float
    separator_coverage_pct: float
    # Bounds match the producer ranges in ``api.tickets``.
    payout_score: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class SimulationResult(BaseModel):
    """Aggregated simulation output across every input ticket."""

    model_config = ConfigDict(extra="forbid")

    n_iterations: int
    tickets: list[TicketSimulationResult] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def simulate(
    races: list[Race],
    tickets: list[Ticket],
    n_iterations: int = DEFAULT_ITERATIONS,
    *,
    seed: int | None = None,
) -> SimulationResult:
    """Run a Monte Carlo Pick 5 simulation.

    ``races`` must contain all five Pick 5 legs (by ``sequenceRole``).
    Scratched horses and horses with a missing or zero
    ``finalProbability`` are excluded from sampling. ``n_iterations`` is
    clamped to ``[1, MAX_ITERATIONS]``. Pass ``seed`` for reproducibility
    in tests; the default uses the module-level ``random`` source.
    """
    n = _clamp_iterations(n_iterations)
    legs = select_pick5_legs(races)
    if len(legs) != PICK5_LEG_COUNT:
        raise ValueError(
            f"Pick 5 card must have {PICK5_LEG_COUNT} legs, got {len(legs)}"
        )

    leg_data = [_prepare_leg(race) for race in legs]
    ticket_sets = _prepare_ticket_sets(tickets)

    if not tickets:
        return SimulationResult(n_iterations=n, tickets=[])

    rng = random.Random(seed) if seed is not None else random
    chalk_count = 0
    chaos_count = 0
    sep_count = 0
    hit_counts = [0] * len(tickets)
    winners: list[str] = [""] * PICK5_LEG_COUNT

    for _ in range(n):
        chalk_all = True
        chaos_any = False
        sep_any = False
        for leg_idx, (ids, cum_weights, is_chalk, is_chaos, is_sep) in enumerate(
            leg_data
        ):
            r = rng.random() * cum_weights[-1]
            idx = bisect_left(cum_weights, r)
            if idx >= len(ids):
                idx = len(ids) - 1
            winners[leg_idx] = ids[idx]
            if not is_chalk[idx]:
                chalk_all = False
            if is_chaos[idx]:
                chaos_any = True
            if is_sep[idx]:
                sep_any = True

        if chalk_all:
            chalk_count += 1
        if chaos_any:
            chaos_count += 1
        if sep_any:
            sep_count += 1
        for t_idx, sels in enumerate(ticket_sets):
            if all(winners[leg] in sels[leg] for leg in range(PICK5_LEG_COUNT)):
                hit_counts[t_idx] += 1

    chalk_pct = 100.0 * chalk_count / n
    chaos_pct = 100.0 * chaos_count / n
    sep_pct = 100.0 * sep_count / n

    horse_index = _horse_index(legs)
    return SimulationResult(
        n_iterations=n,
        tickets=[
            TicketSimulationResult(
                ticket_id=t.id,
                cost=t.cost,
                estimated_hit_rate_pct=100.0 * hit_counts[i] / n,
                chalkiness_pct=chalk_pct,
                chaos_coverage_pct=chaos_pct,
                separator_coverage_pct=sep_pct,
                payout_score=compute_payout_score(t.selections, horse_index),
                confidence=compute_ticket_confidence(t.selections, horse_index),
            )
            for i, t in enumerate(tickets)
        ],
    )


def default_tickets_from_tags(
    races: list[Race], *, base_unit: float = DEFAULT_BASE_UNIT
) -> list[Ticket]:
    """Build a single 'default' ticket from the card's tagged horses.

    Per leg, selects every non-scratched horse whose ``userTag`` is in
    :data:`TAGS_FOR_DEFAULT_TICKET`. If a leg has no tagged horses, falls
    back to the lone favorite (highest ``finalProbability``, then
    ``marketProbability``). Returns an empty list when the card is
    missing any Pick 5 leg or any leg has no eligible runners.

    Cost = ``product(len(selections)) * base_unit``.
    """
    legs = select_pick5_legs(races)
    if len(legs) != PICK5_LEG_COUNT:
        return []

    selections: list[list[str]] = []
    for race in legs:
        non_scratched = [h for h in race.horses if not h.scratched]
        if not non_scratched:
            return []
        tagged = [h.id for h in non_scratched if h.userTag in TAGS_FOR_DEFAULT_TICKET]
        if tagged:
            selections.append(tagged)
            continue
        favorite = max(
            non_scratched,
            key=lambda h: (
                h.finalProbability if h.finalProbability is not None
                else h.marketProbability if h.marketProbability is not None
                else 0.0
            ),
        )
        selections.append([favorite.id])

    n_combos = 1
    for s in selections:
        n_combos *= len(s)
    cost = float(n_combos) * float(base_unit)
    return [Ticket(id="default", cost=cost, selections=selections)]


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _clamp_iterations(n: int) -> int:
    if n < 1:
        return 1
    if n > MAX_ITERATIONS:
        return MAX_ITERATIONS
    return n


def _prepare_leg(
    race: Race,
) -> tuple[list[str], list[float], list[bool], list[bool], list[bool]]:
    """Pre-build the per-leg sampling tables.

    Returns ``(ids, cum_weights, is_chalk, is_chaos, is_separator)`` —
    parallel arrays indexed by sampled position. Filters out scratched
    horses and horses with a missing or non-positive ``finalProbability``.
    Raises if no eligible runners remain (the leg cannot be sampled).
    """
    ids: list[str] = []
    weights: list[float] = []
    is_chalk: list[bool] = []
    is_chaos: list[bool] = []
    is_sep: list[bool] = []
    for h in race.horses:
        if h.scratched:
            continue
        prob = h.finalProbability
        if prob is None or prob <= 0:
            continue
        ids.append(h.id)
        weights.append(float(prob))
        is_chalk.append(
            h.marketProbability is not None
            and h.marketProbability > CHALKINESS_PROB_THRESHOLD
        )
        is_chaos.append(h.userTag == CHAOS_USER_TAG)
        is_sep.append(FLAG_LIKELY_SEPARATOR in h.flags)
    if not ids:
        raise ValueError(
            f"Race {race.raceNumber}: no horses eligible for sampling "
            "(need non-scratched runners with finalProbability > 0)"
        )
    cum_weights: list[float] = []
    running = 0.0
    for w in weights:
        running += w
        cum_weights.append(running)
    return ids, cum_weights, is_chalk, is_chaos, is_sep


def _horse_index(legs: list[Race]) -> list[dict[str, Horse]]:
    """Return one ``{horse.id: horse}`` map per leg in leg order."""
    return [{h.id: h for h in race.horses} for race in legs]


def compute_payout_score(
    selections: list[list[str]],
    horse_index: list[dict[str, Horse]],
    *,
    exponent: float = PAYOUT_SCORE_EXPONENT,
) -> float | None:
    """Return ``(1 - raw_chalkiness) ** exponent`` for ``selections``.

    ``raw_chalkiness`` is the mean over legs of the maximum
    ``marketProbability`` among each leg's non-scratched selections.
    Returns ``None`` when ``selections`` does not match the leg count;
    otherwise always returns a value in ``[0, 1]``.
    """
    if len(selections) != len(horse_index):
        return None
    chalk = compute_chalk_exposure(selections, horse_index)
    if chalk is None:
        return None
    base = max(0.0, 1.0 - chalk)
    return base ** exponent


def compute_chalk_exposure(
    selections: list[list[str]], horse_index: list[dict[str, Horse]]
) -> float | None:
    """Mean of ``max(marketProbability)`` per leg across ``selections``."""
    if len(selections) != len(horse_index):
        return None
    per_leg: list[float] = []
    for leg_sel, by_id in zip(selections, horse_index):
        leg_max = 0.0
        for hid in leg_sel:
            h = by_id.get(hid)
            if h is None or h.scratched:
                continue
            prob = h.marketProbability
            if prob is None:
                prob = h.finalProbability
            if prob is None:
                continue
            if prob > leg_max:
                leg_max = prob
        per_leg.append(leg_max)
    if not per_leg:
        return None
    return sum(per_leg) / len(per_leg)


def compute_ticket_confidence(
    selections: list[list[str]], horse_index: list[dict[str, Horse]]
) -> float | None:
    """Mean ``confidence_score`` across every selected non-scratched horse.

    Returns ``None`` when no selected horse exposes a confidence score —
    typically because the edge model has not been applied to the card.
    """
    if len(selections) != len(horse_index):
        return None
    values: list[float] = []
    for leg_sel, by_id in zip(selections, horse_index):
        for hid in leg_sel:
            h = by_id.get(hid)
            if h is None or h.scratched:
                continue
            if h.confidence_score is not None:
                values.append(h.confidence_score)
    if not values:
        return None
    return sum(values) / len(values)


def _prepare_ticket_sets(tickets: list[Ticket]) -> list[list[set[str]]]:
    """Convert each ticket's selections into per-leg ``set[str]`` for O(1) lookup."""
    out: list[list[set[str]]] = []
    for t in tickets:
        if len(t.selections) != PICK5_LEG_COUNT:
            raise ValueError(
                f"Ticket {t.id} has {len(t.selections)} legs, "
                f"expected {PICK5_LEG_COUNT}"
            )
        out.append([set(leg) for leg in t.selections])
    return out


__all__ = [
    "DEFAULT_ITERATIONS",
    "MAX_ITERATIONS",
    "CHALKINESS_PROB_THRESHOLD",
    "CHAOS_USER_TAG",
    "DEFAULT_BASE_UNIT",
    "TAGS_FOR_DEFAULT_TICKET",
    "PAYOUT_SCORE_EXPONENT",
    "TicketLabel",
    "Ticket",
    "TicketSimulationResult",
    "SimulationResult",
    "simulate",
    "default_tickets_from_tags",
    "compute_payout_score",
    "compute_chalk_exposure",
    "compute_ticket_confidence",
]
