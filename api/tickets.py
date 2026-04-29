"""Ticket builder for the Pick 5 — Balanced / Safer / Upside families.

Internally the builder constructs the same A/B/chaos candidate pool as
before:

1. **classification main** — initial leg sizes are driven by race
   classification when every leg has one (KEY → 1, TIGHT → 2, MID → 3,
   CHAOS → 5–7 by entropy ratio). Each leg picks the top-N non-scratched,
   non-DEAD horses by ``finalProbability``. Falls back to A-tag-driven
   selection (one A horse per leg, or the leg favorite when no A horse
   is tagged) when any leg has no classification.
2. **backup-{n} swaps** — five candidates, one per leg, where leg ``n``
   swaps in every B-tagged horse while the others keep their main
   selections. Skipped for legs with no B horses.
3. **chaos** — replace every leg flagged ``chaos_race`` with that leg's
   chaos-tagged + ``useful_value``-flagged horses. Built only when at
   least one chaos leg has a chaos/value horse.

Each candidate is fitted to ``budget_dollars`` via the spend-efficiency
model: rank candidates by ``efficiency_ratio = finalProbability × n_i /
P_leg_i`` (the ranking-equivalent of ``ΔP_ticket / ΔCost``). When over
budget, the (leg, horse) pair with the lowest efficiency ratio is
removed, and the loop repeats until cost ≤ budget or every leg is at
one selection. Classification-driven main tickets additionally run a
greedy add loop that picks the highest-ratio affordable (leg, horse)
pair until the budget is exhausted; the A-tag fallback path keeps its
tag-only selections (no greedy add).

Candidates are then scored:

- ``win_probability`` = simulated ``estimated_hit_rate_pct / 100``
- ``payout_score`` = ``(1 - raw_chalkiness) ** PAYOUT_SCORE_EXPONENT``
- ``confidence`` = mean of selected horses' ``confidence_score``
- ``score`` = ``win_probability × payout_score × confidence``

The scored pool is collapsed to exactly three labeled output tickets:

- **Balanced** — candidate with the highest ``score``.
- **Safer** — candidate with the highest ``win_probability`` whose
  ``payout_score ≥ SAFER_PAYOUT_FLOOR``; falls back to the highest-score
  candidate when no candidate clears the floor.
- **Upside** — candidate with the highest ``payout_score`` whose
  ``win_probability ≥ UPSIDE_WIN_PROB_FLOOR``; falls back to the
  highest-score candidate when no candidate clears the floor.

When the underlying simulation fails the builder falls back to selecting
all three by ascending cost, but still emits exactly three labeled
tickets so the output contract holds.

LOC note: ~812 LOC, over the 500-line guideline. Candidate-pool
construction, budget fitting, and Balanced/Safer/Upside scoring all
share the same ``Ticket`` / ``Race`` / ``horses_by_id`` plumbing; a
split would force every internal helper to thread the candidate pool
back across module boundaries for no behavioral win. See
``docs/audits/cleanup-report.md`` "Files still >500 LOC".
"""

from __future__ import annotations

import logging
import math
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
from api.sim import (
    DEFAULT_BASE_UNIT,
    Ticket,
    TicketLabel,
    TicketSimulationResult,
    compute_chalk_exposure,
    compute_payout_score,
    compute_ticket_confidence,
)

STANDARD_BUDGETS: tuple[float, ...] = (48.0, 96.0, 144.0, 192.0)

A_TAG = "A"
B_TAG = "B"
CHAOS_TAG = "chaos"

# Output ticket family — three labeled tickets selected from the
# A/B/chaos candidate pool. See the ``Balanced/Safer/Upside`` section
# of the module docstring for the selection rules.
BALANCED_LABEL: TicketLabel = "Balanced"
SAFER_LABEL: TicketLabel = "Safer"
UPSIDE_LABEL: TicketLabel = "Upside"
BALANCED_TICKET_ID = "balanced"
SAFER_TICKET_ID = "safer"
UPSIDE_TICKET_ID = "upside"

# Constraint floors for the Safer / Upside selection rules. A candidate
# must clear the floor to be eligible for the corresponding label; when
# no candidate clears the floor, the slot falls back to the
# highest-``score`` candidate so the output always has three tickets.
SAFER_PAYOUT_FLOOR = 0.30
UPSIDE_WIN_PROB_FLOOR = 0.05

# Threshold for tagging a single-horse leg as a "Strong single" in the
# generated notes — calibrated so that only legs with a high-confidence
# selection trigger the call-out.
STRONG_SINGLE_CONFIDENCE_MIN = 0.50

# Strategy label that triggers a "MAX CHAOS coverage" note for a leg.
MAX_CHAOS_STRATEGY = "MAX CHAOS"

# Classification → initial leg horse count. KEY/TIGHT/MID are constants;
# CHAOS varies in [CHAOS_TARGET_MIN..CHAOS_TARGET_MAX] with the leg's
# entropy ratio (entropy / log2(field_size)).
CLASSIFICATION_TARGET_COUNT: dict[str, int] = {
    "KEY": 1,
    "TIGHT": 2,
    "MID": 3,
}
CHAOS_TARGET_MIN = 5
CHAOS_TARGET_MAX = 7
# Entropy ratio thresholds for the chaos-leg width: ratio < LOW → 5,
# ratio < HIGH → 6, ratio ≥ HIGH → 7.
CHAOS_ENTROPY_RATIO_LOW = 0.70
CHAOS_ENTROPY_RATIO_HIGH = 0.85

DEAD_BUCKET = "DEAD"

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
    """Build the three Balanced / Safer / Upside tickets within ``budget_dollars``.

    Returns an empty list when the card is missing any Pick 5 leg or
    when no main candidate can be built (e.g. a leg with no eligible
    runners). Otherwise always returns exactly three labeled tickets.
    See module docstring for the candidate-pool construction and
    selection rules.
    """
    legs = select_pick5_legs(races)
    if len(legs) != PICK5_LEG_COUNT:
        return []

    candidates = _build_candidate_pool(legs, budget_dollars, base_unit)
    if not candidates:
        return []

    return _score_and_select(legs, candidates)


def _build_candidate_pool(
    legs: list[Race], budget_dollars: float, base_unit: float
) -> list[Ticket]:
    """Build the A/B/chaos candidate pool fitted to ``budget_dollars``."""
    main_sel = _build_main_selections_classified(legs)
    used_classification = main_sel is not None
    if main_sel is None:
        main_sel = _build_main_selections(legs)
    if main_sel is None:
        return []

    candidates: list[Ticket] = []

    main_after_budget = _fit_to_budget(
        main_sel, legs, budget_dollars, base_unit, allow_add=used_classification
    )
    candidates.append(
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
        bsel = _fit_to_budget(bsel, legs, budget_dollars, base_unit, allow_add=False)
        candidates.append(
            Ticket(
                id=f"backup-{i + 1}",
                cost=_ticket_cost(bsel, base_unit),
                selections=bsel,
            )
        )

    csel = _build_chaos_selections(legs, main_sel)
    if csel is not None:
        csel = _fit_to_budget(csel, legs, budget_dollars, base_unit, allow_add=False)
        candidates.append(
            Ticket(
                id="chaos",
                cost=_ticket_cost(csel, base_unit),
                selections=csel,
            )
        )

    return candidates


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


def _eligible_for_classified_pick(horse: Horse) -> bool:
    """Non-scratched and not in the DEAD bucket — eligible for class-driven picks."""
    if horse.scratched:
        return False
    if horse.computedBucket == DEAD_BUCKET:
        return False
    return True


def _horses_with_tag(race: Race, tag: str) -> list[Horse]:
    return [h for h in race.horses if _eligible(h) and h.userTag == tag]


def _favorite(race: Race) -> Horse | None:
    """Highest finalProbability — falls back to marketProbability, then 0."""
    candidates = [h for h in race.horses if _eligible(h)]
    if not candidates:
        return None
    return max(candidates, key=_horse_probability_key)


def _horse_probability_key(horse: Horse | None) -> float:
    if horse is None:
        return 0.0
    if horse.finalProbability is not None:
        return horse.finalProbability
    if horse.marketProbability is not None:
        return horse.marketProbability
    return 0.0


def _classification_target_count(race: Race) -> int | None:
    """Return the initial horse count for a leg from its classification.

    Returns ``None`` when the race has no classification yet — caller
    falls back to the A-tag selection path.
    """
    cls = race.classification
    if cls is None:
        return None
    if cls in CLASSIFICATION_TARGET_COUNT:
        return CLASSIFICATION_TARGET_COUNT[cls]
    if cls == "CHAOS":
        return _chaos_target_count(race)
    return None


def _chaos_target_count(race: Race) -> int:
    """Pick a CHAOS leg width in [5..7] from the race's entropy ratio."""
    entropy = race.entropy
    if entropy is None or entropy <= 0:
        return CHAOS_TARGET_MIN
    field_size = sum(1 for h in race.horses if not h.scratched)
    if field_size <= 1:
        return CHAOS_TARGET_MIN
    max_entropy = math.log2(field_size)
    if max_entropy <= 0:
        return CHAOS_TARGET_MIN
    ratio = entropy / max_entropy
    if ratio >= CHAOS_ENTROPY_RATIO_HIGH:
        return CHAOS_TARGET_MAX
    if ratio >= CHAOS_ENTROPY_RATIO_LOW:
        return CHAOS_TARGET_MIN + 1
    return CHAOS_TARGET_MIN


def _build_main_selections_classified(legs: list[Race]) -> list[list[str]] | None:
    """Initial main selections from race classification, or ``None`` to fall back.

    Returns ``None`` if any leg has no classification or no eligible
    horse (non-scratched, non-DEAD). Otherwise picks the top-N horses
    per leg by ``finalProbability``, where N is :func:`_classification_target_count`.
    """
    selections: list[list[str]] = []
    for race in legs:
        target = _classification_target_count(race)
        if target is None:
            return None
        eligible = [h for h in race.horses if _eligible_for_classified_pick(h)]
        if not eligible:
            return None
        eligible.sort(key=_horse_probability_key, reverse=True)
        chosen = eligible[: max(1, target)]
        selections.append([h.id for h in chosen])
    return selections


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
# Cost + budget enforcement (spend-efficiency model)
# ---------------------------------------------------------------------------


def _ticket_cost(selections: list[list[str]], base_unit: float) -> float:
    n = 1
    for leg in selections:
        n *= len(leg)
    return float(n) * float(base_unit)


def _leg_probability_sum(
    horses_by_id: dict[str, Horse], selection: list[str]
) -> float:
    total = 0.0
    for hid in selection:
        horse = horses_by_id.get(hid)
        if horse is None:
            continue
        total += _horse_probability_key(horse)
    return total


def _efficiency_ratio(fp: float, n_leg: int, p_leg: float) -> float:
    """Ranking-equivalent of ΔP_ticket / ΔCost across legs.

    Within a single leg this is monotone in ``fp``; the ``n_leg / p_leg``
    factor lets the trim/add loops compare candidates across legs of
    different width. Returns ``+inf`` for a positive-probability candidate
    on a zero-coverage leg so it sorts above any normal score (it improves
    a degenerate leg the most). Returns ``0.0`` for a zero-probability
    candidate regardless of leg state.
    """
    if fp <= 0:
        return 0.0
    if p_leg <= 0:
        return float("inf")
    return fp * n_leg / p_leg


def _fit_to_budget(
    selections: list[list[str]],
    legs: list[Race],
    budget: float,
    base_unit: float,
    *,
    allow_add: bool,
) -> list[list[str]]:
    """Trim or grow selections so cost fits ``budget`` using efficiency ratio.

    Trim phase: while ``cost > budget`` and at least one leg has more
    than one selection, drop the (leg, horse) pair with the lowest
    efficiency ratio across all reducible legs. This generalizes the
    prior "widest leg, lowest finalProbability" heuristic — within a
    single leg the efficiency ratio is monotone in ``finalProbability``,
    but across legs the ``n_i / P_leg_i`` factor lets the algorithm
    drop a low-prob horse on a narrow leg before a slightly-lower-prob
    horse on a much wider leg.

    Add phase (only when ``allow_add``): while ``cost + ΔCost <=
    budget`` for some addition, add the highest-efficiency-ratio
    (leg, horse) candidate that is non-scratched, non-DEAD, has
    ``finalProbability > 0``, and is not already in the leg's selection.
    Stops when no affordable addition exists.
    """
    sels = [list(s) for s in selections]
    horses_by_leg: list[dict[str, Horse]] = [
        {h.id: h for h in race.horses} for race in legs
    ]

    while _ticket_cost(sels, base_unit) > budget:
        worst: tuple[float, int, str] | None = None
        for i, sel in enumerate(sels):
            if len(sel) <= 1:
                continue
            n_i = len(sel)
            p_leg = _leg_probability_sum(horses_by_leg[i], sel)
            for hid in sel:
                fp = _horse_probability_key(horses_by_leg[i].get(hid))
                eff = _efficiency_ratio(fp, n_i, p_leg)
                key = (eff, i, hid)
                if worst is None or key < worst:
                    worst = key
        if worst is None:
            break
        _eff, leg_idx, drop_id = worst
        sels[leg_idx] = [hid for hid in sels[leg_idx] if hid != drop_id]

    if not allow_add:
        return sels

    while True:
        current_cost = _ticket_cost(sels, base_unit)
        if current_cost >= budget:
            break
        n_per_leg = [len(s) for s in sels]
        if any(n == 0 for n in n_per_leg):
            break
        n_total = 1
        for n in n_per_leg:
            n_total *= n
        p_legs = [
            _leg_probability_sum(horses_by_leg[i], sels[i]) for i in range(len(sels))
        ]
        best: tuple[float, int, str] | None = None
        for i, race in enumerate(legs):
            n_others = n_total // n_per_leg[i]
            delta_cost = float(n_others) * float(base_unit)
            if current_cost + delta_cost > budget + 1e-9:
                continue
            already = set(sels[i])
            p_leg = p_legs[i]
            n_i = n_per_leg[i]
            for h in race.horses:
                if h.id in already:
                    continue
                if not _eligible_for_classified_pick(h):
                    continue
                fp = h.finalProbability
                if fp is None or fp <= 0:
                    continue
                eff = _efficiency_ratio(fp, n_i, p_leg)
                # Higher eff wins; deterministic tie-break by lowest
                # leg index then lowest horse id.
                if best is None:
                    best = (eff, i, h.id)
                else:
                    if eff > best[0] or (
                        eff == best[0] and (i, h.id) < (best[1], best[2])
                    ):
                        best = (eff, i, h.id)
        if best is None:
            break
        _eff, leg_idx, add_id = best
        sels[leg_idx] = [*sels[leg_idx], add_id]

    return sels


# ---------------------------------------------------------------------------
# Scoring + Balanced/Safer/Upside selection
# ---------------------------------------------------------------------------


class _Scored:
    """Per-candidate scoring snapshot used by the selection step."""

    __slots__ = (
        "candidate",
        "win_probability",
        "hit_rate_pct",
        "payout_score",
        "confidence",
        "edge_score",
        "chalk_exposure",
        "score",
    )

    def __init__(
        self,
        candidate: Ticket,
        win_probability: float,
        hit_rate_pct: float,
        payout_score: float,
        confidence: float,
        edge_score: float,
        chalk_exposure: float,
    ) -> None:
        self.candidate = candidate
        self.win_probability = win_probability
        self.hit_rate_pct = hit_rate_pct
        self.payout_score = payout_score
        self.confidence = confidence
        self.edge_score = edge_score
        self.chalk_exposure = chalk_exposure
        self.score = win_probability * payout_score * confidence


def _score_and_select(legs: list[Race], candidates: list[Ticket]) -> list[Ticket]:
    """Score the candidate pool and return three labeled output tickets.

    Always returns exactly three tickets when ``candidates`` is non-empty:
    Balanced (highest ``score``), Safer (highest ``win_probability`` with
    ``payout_score ≥ SAFER_PAYOUT_FLOOR``, fallback by score), and
    Upside (highest ``payout_score`` with ``win_probability ≥
    UPSIDE_WIN_PROB_FLOOR``, fallback by score). When the simulator
    fails the cheap fallback assigns ``win_probability = 0`` to every
    candidate; the scoring path still runs so payout / chalk / edge
    fields stay populated and the output contract holds.
    """
    if not candidates:
        return []

    horse_index = [{h.id: h for h in race.horses} for race in legs]
    sim_by_id = _simulate_candidates(legs, candidates)

    scored: list[_Scored] = []
    for c in candidates:
        sim_res = sim_by_id.get(c.id)
        hit_rate_pct = sim_res.estimated_hit_rate_pct if sim_res else 0.0
        win_probability = hit_rate_pct / 100.0
        payout = sim_res.payout_score if sim_res and sim_res.payout_score is not None else None
        if payout is None:
            payout = compute_payout_score(c.selections, horse_index) or 0.0
        confidence = (
            sim_res.confidence
            if sim_res and sim_res.confidence is not None
            else None
        )
        if confidence is None:
            confidence = compute_ticket_confidence(c.selections, horse_index)
        # When the edge model has not populated ``confidence_score`` on any
        # selected horse, fall back to a neutral 1.0 so the multiplicative
        # ``score`` does not collapse to zero on every candidate. Collapsing
        # to zero would tie every candidate at score=0 and make Balanced
        # selection arbitrary; the neutral default keeps win_probability ×
        # payout_score as the deciding signal. See
        # docs/audits/error-handling-report.md F24.
        if confidence is None:
            confidence = 1.0
        chalk = compute_chalk_exposure(c.selections, horse_index)
        edge = _compute_ticket_edge(c.selections, horse_index)
        scored.append(
            _Scored(
                candidate=c,
                win_probability=win_probability,
                hit_rate_pct=hit_rate_pct,
                payout_score=payout,
                confidence=confidence,
                edge_score=edge,
                chalk_exposure=chalk if chalk is not None else 0.0,
            )
        )

    balanced = max(scored, key=lambda s: s.score)
    safer_eligible = [s for s in scored if s.payout_score >= SAFER_PAYOUT_FLOOR]
    safer = (
        max(safer_eligible, key=lambda s: s.win_probability)
        if safer_eligible
        else max(scored, key=lambda s: s.score)
    )
    upside_eligible = [
        s for s in scored if s.win_probability >= UPSIDE_WIN_PROB_FLOOR
    ]
    upside = (
        max(upside_eligible, key=lambda s: s.payout_score)
        if upside_eligible
        else max(scored, key=lambda s: s.score)
    )

    return [
        _build_labeled_ticket(balanced, BALANCED_LABEL, BALANCED_TICKET_ID, legs),
        _build_labeled_ticket(safer, SAFER_LABEL, SAFER_TICKET_ID, legs),
        _build_labeled_ticket(upside, UPSIDE_LABEL, UPSIDE_TICKET_ID, legs),
    ]


def _simulate_candidates(
    legs: list[Race], candidates: list[Ticket]
) -> dict[str, TicketSimulationResult]:
    """Run the ranking simulation; return ``{ticket_id: TicketSimulationResult}``.

    The catch is broad because the contract is "must never break ticket
    construction" — but the fallback is logged at warning so a real
    sim-engine bug doesn't go silent in production. See
    error-handling-report finding F16.
    """
    try:
        from api import sim

        result = sim.simulate(
            legs,
            candidates,
            n_iterations=_DEFAULT_RANKING_ITERATIONS,
            seed=_DEFAULT_RANKING_SEED,
        )
        return {tr.ticket_id: tr for tr in result.tickets}
    except Exception as exc:
        _log.warning(
            "Candidate scoring sim failed; using cost-order fallback: %s", exc
        )
        return {}


def _compute_ticket_edge(
    selections: list[list[str]], horse_index: list[dict[str, Horse]]
) -> float:
    """Mean ``edge_score`` across every selected non-scratched horse.

    Defaults to ``0.0`` when no selected horse has an edge score (e.g.
    the edge model has not run on this card). Skipping ``None`` values
    keeps the average meaningful when only some horses are scored.
    """
    values: list[float] = []
    for leg_sel, by_id in zip(selections, horse_index):
        for hid in leg_sel:
            h = by_id.get(hid)
            if h is None or h.scratched:
                continue
            if h.edge_score is not None:
                values.append(h.edge_score)
    if not values:
        return 0.0
    return sum(values) / len(values)


def _generate_ticket_notes(
    selections: list[list[str]],
    legs: list[Race],
    horse_index: list[dict[str, Horse]],
    label: TicketLabel,
) -> str:
    """Build a short human-readable description of the ticket's character.

    Walks each leg looking for two notable conditions:

    - A single-horse leg where the chosen horse has
      ``confidence_score ≥ STRONG_SINGLE_CONFIDENCE_MIN`` →
      ``"Strong single in R{n}"``.
    - A leg whose race ``strategy`` is ``"MAX CHAOS"`` →
      ``"R{n} MAX CHAOS coverage"``.

    When neither condition matches anywhere on the ticket, falls back to
    ``"{label} coverage"`` so the field is always non-empty.
    """
    notes: list[str] = []
    for leg_sel, race, by_id in zip(selections, legs, horse_index):
        race_label = f"R{race.raceNumber}"
        if len(leg_sel) == 1:
            h = by_id.get(leg_sel[0])
            if (
                h is not None
                and h.confidence_score is not None
                and h.confidence_score >= STRONG_SINGLE_CONFIDENCE_MIN
            ):
                notes.append(f"Strong single in {race_label}")
        if race.strategy == MAX_CHAOS_STRATEGY:
            notes.append(f"{race_label} MAX CHAOS coverage")
    if not notes:
        return f"{label} coverage"
    return "; ".join(notes)


def _build_labeled_ticket(
    scored: _Scored,
    label: TicketLabel,
    ticket_id: str,
    legs: list[Race],
) -> Ticket:
    horse_index = [{h.id: h for h in race.horses} for race in legs]
    notes = _generate_ticket_notes(
        scored.candidate.selections, legs, horse_index, label
    )
    return Ticket(
        id=ticket_id,
        cost=scored.candidate.cost,
        selections=[list(s) for s in scored.candidate.selections],
        edge_score=scored.edge_score,
        confidence=scored.confidence,
        payout_score=scored.payout_score,
        chalk_exposure=scored.chalk_exposure,
        notes=notes,
        label=label,
        hit_rate_pct=scored.hit_rate_pct,
    )


__all__ = [
    "STANDARD_BUDGETS",
    "A_TAG",
    "B_TAG",
    "CHAOS_TAG",
    "BALANCED_LABEL",
    "SAFER_LABEL",
    "UPSIDE_LABEL",
    "BALANCED_TICKET_ID",
    "SAFER_TICKET_ID",
    "UPSIDE_TICKET_ID",
    "SAFER_PAYOUT_FLOOR",
    "UPSIDE_WIN_PROB_FLOOR",
    "STRONG_SINGLE_CONFIDENCE_MIN",
    "MAX_CHAOS_STRATEGY",
    "CLASSIFICATION_TARGET_COUNT",
    "CHAOS_TARGET_MIN",
    "CHAOS_TARGET_MAX",
    "CHAOS_ENTROPY_RATIO_LOW",
    "CHAOS_ENTROPY_RATIO_HIGH",
    "BudgetVariant",
    "build_tickets",
    "build_tickets_for_budgets",
]
