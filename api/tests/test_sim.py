"""Tests for the Monte Carlo Pick 5 simulation engine."""

from __future__ import annotations

import time

import pytest

from api.model import (
    FLAG_LIKELY_SEPARATOR,
    PICK5_LEG_COUNT,
    PICK5_LEG_ROLES,
    Horse,
    Race,
    SequenceRole,
)
from api.sim import (
    CHAOS_USER_TAG,
    DEFAULT_BASE_UNIT,
    MAX_ITERATIONS,
    SimulationResult,
    Ticket,
    default_tickets_from_tags,
    simulate,
)


# ---------------------------------------------------------------------------
# Card builders
# ---------------------------------------------------------------------------


def _horse(
    race_num: int,
    post: int,
    *,
    final: float | None,
    market: float | None = None,
    ml: float | None = None,
    scratched: bool = False,
    user_tag: str | None = None,
    flags: list[str] | None = None,
) -> Horse:
    return Horse(
        id=f"R{race_num:02d}-p{post:02d}",
        raceId=f"R{race_num:02d}",
        post=post,
        name=f"H{race_num}-{post}",
        finalProbability=final,
        marketProbability=market if market is not None else final,
        morningLineProbability=ml if ml is not None else final,
        scratched=scratched or None,
        userTag=user_tag,  # type: ignore[arg-type]
        flags=list(flags) if flags else [],
    )


def _race(race_num: int, role: SequenceRole, horses: list[Horse]) -> Race:
    return Race(
        id=f"R{race_num:02d}",
        day="saturday",
        raceNumber=race_num,
        sequenceRole=role,
        horses=horses,
    )


def _uniform_card(
    *, n_per_leg: int = 4, market: float | None = None
) -> list[Race]:
    """Five legs with ``n_per_leg`` equally-probable horses each."""
    p = 1.0 / n_per_leg
    races: list[Race] = []
    for i, role in enumerate(PICK5_LEG_ROLES):
        race_num = 8 + i
        horses = [
            _horse(race_num, post, final=p, market=market if market is not None else p)
            for post in range(1, n_per_leg + 1)
        ]
        races.append(_race(race_num, role, horses))
    return races


def _two_horse_card() -> list[Race]:
    """Five legs of exactly two horses, 50/50 each — tractable for analytics."""
    races: list[Race] = []
    for i, role in enumerate(PICK5_LEG_ROLES):
        race_num = 8 + i
        horses = [
            _horse(race_num, 1, final=0.5, market=0.5),
            _horse(race_num, 2, final=0.5, market=0.5),
        ]
        races.append(_race(race_num, role, horses))
    return races


def _ticket_for_winners(card: list[Race], post: int = 1) -> Ticket:
    """Single ticket selecting horse at ``post`` for every leg."""
    selections: list[list[str]] = []
    for race in card:
        for h in race.horses:
            if h.post == post:
                selections.append([h.id])
                break
    return Ticket(id="t1", cost=DEFAULT_BASE_UNIT, selections=selections)


# ---------------------------------------------------------------------------
# Acceptance: hit rate accuracy
# ---------------------------------------------------------------------------


def test_simulate_hit_rate_matches_analytical_for_single_horse_per_leg() -> None:
    card = _two_horse_card()
    ticket = _ticket_for_winners(card, post=1)
    # Analytical: 0.5 ** 5 = 0.03125 → 3.125%
    result = simulate(card, [ticket], n_iterations=50_000, seed=42)
    assert result.n_iterations == 50_000
    assert len(result.tickets) == 1
    estimated = result.tickets[0].estimated_hit_rate_pct
    assert abs(estimated - 3.125) < 1.5


def test_simulate_full_field_ticket_hits_every_iteration() -> None:
    card = _uniform_card(n_per_leg=4)
    selections = [[h.id for h in race.horses] for race in card]
    ticket = Ticket(id="all", cost=4.0**5 * DEFAULT_BASE_UNIT, selections=selections)
    result = simulate(card, [ticket], n_iterations=2_000, seed=1)
    assert result.tickets[0].estimated_hit_rate_pct == 100.0


def test_simulate_disjoint_ticket_never_hits() -> None:
    card = _uniform_card(n_per_leg=4)
    # Build an id that won't exist in the card
    selections = [["NOT-A-HORSE"] for _ in range(PICK5_LEG_COUNT)]
    ticket = Ticket(id="miss", cost=DEFAULT_BASE_UNIT, selections=selections)
    result = simulate(card, [ticket], n_iterations=500, seed=7)
    assert result.tickets[0].estimated_hit_rate_pct == 0.0


# ---------------------------------------------------------------------------
# Acceptance: per-iteration metrics
# ---------------------------------------------------------------------------


def test_chalkiness_all_favorites_above_threshold() -> None:
    # Two horses per leg, both with marketProbability = 0.5 (> 0.30)
    card = _two_horse_card()
    ticket = _ticket_for_winners(card)
    result = simulate(card, [ticket], n_iterations=2_000, seed=3)
    # Every winner has marketProbability > 0.30 → chalkiness ≈ 100%
    assert result.tickets[0].chalkiness_pct == 100.0


def test_chalkiness_zero_when_no_favorite_above_threshold() -> None:
    # 5 horses per leg at 0.20 each → none > 0.30
    card = _uniform_card(n_per_leg=5)
    ticket = _ticket_for_winners(card)
    result = simulate(card, [ticket], n_iterations=2_000, seed=4)
    assert result.tickets[0].chalkiness_pct == 0.0


def test_chaos_coverage_when_chaos_tagged_horse_exists() -> None:
    card = _uniform_card(n_per_leg=2)
    # Tag horse at post=1 of leg-1 as chaos. Probability of leg-1 winner
    # being post-1 is 0.5, so chaos_coverage_pct should be ~50%.
    card[0].horses[0].userTag = CHAOS_USER_TAG  # type: ignore[assignment]
    ticket = _ticket_for_winners(card)
    result = simulate(card, [ticket], n_iterations=10_000, seed=5)
    assert 45.0 < result.tickets[0].chaos_coverage_pct < 55.0


def test_chaos_coverage_zero_when_no_chaos_tags() -> None:
    card = _uniform_card(n_per_leg=2)
    ticket = _ticket_for_winners(card)
    result = simulate(card, [ticket], n_iterations=1_000, seed=6)
    assert result.tickets[0].chaos_coverage_pct == 0.0


def test_separator_coverage_when_likely_separator_flagged() -> None:
    card = _uniform_card(n_per_leg=2)
    card[0].horses[0].flags = [FLAG_LIKELY_SEPARATOR]
    ticket = _ticket_for_winners(card)
    result = simulate(card, [ticket], n_iterations=10_000, seed=8)
    assert 45.0 < result.tickets[0].separator_coverage_pct < 55.0


def test_separator_coverage_zero_without_flag() -> None:
    card = _uniform_card(n_per_leg=2)
    ticket = _ticket_for_winners(card)
    result = simulate(card, [ticket], n_iterations=500, seed=9)
    assert result.tickets[0].separator_coverage_pct == 0.0


# ---------------------------------------------------------------------------
# Acceptance: scratched horses excluded
# ---------------------------------------------------------------------------


def test_scratched_horses_never_win() -> None:
    card = _uniform_card(n_per_leg=2)
    # Scratch post=1 in every leg. The remaining horse must win every leg.
    expected_winners: list[str] = []
    for race in card:
        race.horses[0].scratched = True
        race.horses[0].finalProbability = None
        expected_winners.append(race.horses[1].id)
    ticket = Ticket(
        id="survivors",
        cost=DEFAULT_BASE_UNIT,
        selections=[[hid] for hid in expected_winners],
    )
    result = simulate(card, [ticket], n_iterations=1_000, seed=11)
    assert result.tickets[0].estimated_hit_rate_pct == 100.0


# ---------------------------------------------------------------------------
# Acceptance: SimulationResult shape
# ---------------------------------------------------------------------------


def test_simulation_result_has_all_metric_fields_per_ticket() -> None:
    card = _two_horse_card()
    tickets = [
        _ticket_for_winners(card, post=1),
        _ticket_for_winners(card, post=2),
    ]
    tickets[1] = Ticket(
        id="t2", cost=DEFAULT_BASE_UNIT, selections=tickets[1].selections
    )
    result = simulate(card, tickets, n_iterations=500, seed=13)
    assert isinstance(result, SimulationResult)
    assert len(result.tickets) == 2
    expected = {
        "ticket_id",
        "cost",
        "estimated_hit_rate_pct",
        "chalkiness_pct",
        "chaos_coverage_pct",
        "separator_coverage_pct",
    }
    for tr in result.tickets:
        assert expected.issubset(tr.model_dump().keys())


def test_simulate_with_no_tickets_returns_empty_results() -> None:
    card = _two_horse_card()
    result = simulate(card, [], n_iterations=100, seed=14)
    assert result.tickets == []
    assert result.n_iterations == 100


# ---------------------------------------------------------------------------
# Iteration clamping and validation
# ---------------------------------------------------------------------------


def test_n_iterations_clamped_to_max() -> None:
    card = _two_horse_card()
    ticket = _ticket_for_winners(card)
    result = simulate(card, [ticket], n_iterations=MAX_ITERATIONS + 50_000, seed=15)
    assert result.n_iterations == MAX_ITERATIONS


def test_n_iterations_clamped_to_at_least_one() -> None:
    card = _two_horse_card()
    ticket = _ticket_for_winners(card)
    result = simulate(card, [ticket], n_iterations=0, seed=16)
    assert result.n_iterations == 1


def test_simulate_raises_when_pick5_card_incomplete() -> None:
    # Only 3 legs present
    card = _two_horse_card()[:3]
    ticket = Ticket(
        id="x",
        cost=0.0,
        selections=[["a"]] * PICK5_LEG_COUNT,
    )
    with pytest.raises(ValueError, match="Pick 5 card must have 5 legs"):
        simulate(card, [ticket], n_iterations=10)


def test_simulate_raises_when_leg_has_no_eligible_runners() -> None:
    card = _two_horse_card()
    # Strip finalProbability from leg-1 horses
    for h in card[0].horses:
        h.finalProbability = None
    ticket = Ticket(
        id="x",
        cost=0.0,
        selections=[["a"]] * PICK5_LEG_COUNT,
    )
    with pytest.raises(ValueError, match="no horses eligible"):
        simulate(card, [ticket], n_iterations=10)


def test_ticket_validation_requires_five_legs() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        Ticket(id="bad", cost=0.0, selections=[["a"], ["b"]])


# ---------------------------------------------------------------------------
# default_tickets_from_tags helper
# ---------------------------------------------------------------------------


def test_default_tickets_from_tags_falls_back_to_favorite_when_untagged() -> None:
    card = _uniform_card(n_per_leg=3)
    # Make leg 1 horse #2 the clear favorite
    card[0].horses[1].finalProbability = 0.6
    card[0].horses[0].finalProbability = 0.2
    card[0].horses[2].finalProbability = 0.2
    tickets = default_tickets_from_tags(card)
    assert len(tickets) == 1
    t = tickets[0]
    assert t.id == "default"
    assert len(t.selections) == PICK5_LEG_COUNT
    # Each leg has one selection (favorite) → cost = 1 × base_unit
    assert t.cost == DEFAULT_BASE_UNIT
    # Leg 1 favorite is post=2
    assert card[0].horses[1].id in t.selections[0]


def test_default_tickets_from_tags_uses_tagged_horses() -> None:
    card = _uniform_card(n_per_leg=3)
    card[0].horses[0].userTag = "A"  # type: ignore[assignment]
    card[0].horses[1].userTag = "B"  # type: ignore[assignment]
    # Other legs get a single A-tag → 1 × 1 × 1 × 1 × 2 selections
    for race in card[1:]:
        race.horses[0].userTag = "A"  # type: ignore[assignment]
    tickets = default_tickets_from_tags(card)
    assert len(tickets) == 1
    t = tickets[0]
    assert len(t.selections[0]) == 2
    for leg in t.selections[1:]:
        assert len(leg) == 1
    # Cost = 2 * 1 * 1 * 1 * 1 * 0.50 = 1.00
    assert t.cost == 2 * DEFAULT_BASE_UNIT


def test_default_tickets_from_tags_skips_toss_and_fade() -> None:
    card = _uniform_card(n_per_leg=3)
    card[0].horses[0].userTag = "toss"  # type: ignore[assignment]
    card[0].horses[1].userTag = "fade"  # type: ignore[assignment]
    card[0].horses[2].userTag = "A"  # type: ignore[assignment]
    for race in card[1:]:
        race.horses[0].userTag = "A"  # type: ignore[assignment]
    tickets = default_tickets_from_tags(card)
    assert len(tickets[0].selections[0]) == 1
    assert tickets[0].selections[0][0] == card[0].horses[2].id


def test_default_tickets_from_tags_returns_empty_for_incomplete_card() -> None:
    card = _two_horse_card()[:3]
    assert default_tickets_from_tags(card) == []


def test_default_tickets_from_tags_skips_scratched_horses() -> None:
    card = _uniform_card(n_per_leg=3)
    # Tag a scratched horse — it should NOT make the ticket; we should
    # fall back to the favorite among non-scratched runners on that leg.
    card[0].horses[0].scratched = True
    card[0].horses[0].userTag = "A"  # type: ignore[assignment]
    tickets = default_tickets_from_tags(card)
    assert len(tickets) == 1
    assert card[0].horses[0].id not in tickets[0].selections[0]


# ---------------------------------------------------------------------------
# Performance acceptance criterion
# ---------------------------------------------------------------------------


def test_50k_iterations_complete_under_10_seconds() -> None:
    card = _uniform_card(n_per_leg=10)
    selections = [[card[i].horses[0].id] for i in range(PICK5_LEG_COUNT)]
    ticket = Ticket(id="perf", cost=DEFAULT_BASE_UNIT, selections=selections)
    start = time.perf_counter()
    result = simulate(card, [ticket], n_iterations=50_000, seed=99)
    elapsed = time.perf_counter() - start
    assert elapsed < 10.0, f"50k iterations took {elapsed:.2f}s"
    assert result.n_iterations == 50_000
