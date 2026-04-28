"""Tests for the ticket builder — Balanced/Safer/Upside three-ticket family."""

from __future__ import annotations

import math

import pytest

from api.model import (
    FLAG_CHAOS_RACE,
    FLAG_USEFUL_VALUE,
    PICK5_LEG_ROLES,
    Horse,
    Race,
    RaceClassification,
    SequenceRole,
)
from api.sim import (
    DEFAULT_BASE_UNIT,
    PAYOUT_SCORE_EXPONENT,
    Ticket,
    compute_chalk_exposure,
    compute_payout_score,
)
from api.tickets import (
    BALANCED_LABEL,
    BALANCED_TICKET_ID,
    CHAOS_TARGET_MAX,
    CHAOS_TARGET_MIN,
    SAFER_LABEL,
    SAFER_PAYOUT_FLOOR,
    SAFER_TICKET_ID,
    STANDARD_BUDGETS,
    UPSIDE_LABEL,
    UPSIDE_TICKET_ID,
    UPSIDE_WIN_PROB_FLOOR,
    BudgetVariant,
    build_tickets,
    build_tickets_for_budgets,
)


# ---------------------------------------------------------------------------
# Card builders
# ---------------------------------------------------------------------------


def _horse(
    race_num: int,
    post: int,
    *,
    final: float | None = None,
    market: float | None = None,
    user_tag: str | None = None,
    flags: list[str] | None = None,
    scratched: bool = False,
    confidence_score: float | None = None,
) -> Horse:
    return Horse(
        id=f"R{race_num:02d}-p{post:02d}",
        raceId=f"R{race_num:02d}",
        post=post,
        name=f"H{race_num}-{post}",
        finalProbability=final,
        marketProbability=market if market is not None else final,
        morningLineProbability=final,
        userTag=user_tag,  # type: ignore[arg-type]
        flags=list(flags) if flags else [],
        scratched=scratched or None,
        confidence_score=confidence_score,
    )


def _race(race_num: int, role: SequenceRole, horses: list[Horse]) -> Race:
    return Race(
        id=f"R{race_num:02d}",
        day="saturday",
        raceNumber=race_num,
        sequenceRole=role,
        horses=horses,
    )


def _card_with_a_per_leg(
    *, n_a_horses: list[int] | None = None, n_total: int = 4
) -> list[Race]:
    """5 legs; ``n_a_horses[i]`` horses on leg i are A-tagged.

    Default: one A horse per leg. Untagged horses fill the remainder.
    Probabilities are uniform.
    """
    if n_a_horses is None:
        n_a_horses = [1, 1, 1, 1, 1]
    races: list[Race] = []
    for i, role in enumerate(PICK5_LEG_ROLES):
        race_num = 8 + i
        horses: list[Horse] = []
        prob = 1.0 / n_total
        for post in range(1, n_total + 1):
            tag = "A" if post <= n_a_horses[i] else None
            horses.append(
                _horse(race_num, post, final=prob, market=prob, user_tag=tag)
            )
        races.append(_race(race_num, role, horses))
    return races


def _card_with_ab(*, n_a: int = 1, n_b: int = 1, n_total: int = 4) -> list[Race]:
    """Card where each leg has ``n_a`` A horses, then ``n_b`` B horses."""
    races: list[Race] = []
    for i, role in enumerate(PICK5_LEG_ROLES):
        race_num = 8 + i
        horses: list[Horse] = []
        prob = 1.0 / n_total
        for post in range(1, n_total + 1):
            if post <= n_a:
                tag = "A"
            elif post <= n_a + n_b:
                tag = "B"
            else:
                tag = None
            horses.append(
                _horse(race_num, post, final=prob, market=prob, user_tag=tag)
            )
        races.append(_race(race_num, role, horses))
    return races


def _classified_card(
    classifications: list[RaceClassification],
    *,
    n_total: int = 8,
    entropies: list[float | None] | None = None,
) -> list[Race]:
    """Build a 5-leg card with explicit classifications and decreasing probs.

    Each leg has ``n_total`` horses with strictly descending
    ``finalProbability`` so the top-N selection is deterministic.
    Probabilities sum to 1.0 inside each leg.
    """
    races: list[Race] = []
    weights = [n_total - i for i in range(n_total)]
    weight_sum = float(sum(weights))
    probs = [w / weight_sum for w in weights]
    if entropies is None:
        entropies = [None] * len(classifications)
    for i, role in enumerate(PICK5_LEG_ROLES):
        race_num = 8 + i
        horses: list[Horse] = []
        for post in range(1, n_total + 1):
            p = probs[post - 1]
            horses.append(_horse(race_num, post, final=p, market=p))
        race = _race(race_num, role, horses)
        race.classification = classifications[i]
        race.entropy = entropies[i]
        races.append(race)
    return races


def _by_label(tickets: list[Ticket]) -> dict[str, Ticket]:
    return {t.label: t for t in tickets if t.label is not None}


# ---------------------------------------------------------------------------
# Output contract — exactly three labeled tickets
# ---------------------------------------------------------------------------


def test_build_returns_exactly_three_balanced_safer_upside_tickets() -> None:
    card = _card_with_ab(n_a=1, n_b=1)
    tickets = build_tickets(card, budget_dollars=192.0)
    assert len(tickets) == 3
    labels = [t.label for t in tickets]
    assert labels == [BALANCED_LABEL, SAFER_LABEL, UPSIDE_LABEL]
    ids = [t.id for t in tickets]
    assert ids == [BALANCED_TICKET_ID, SAFER_TICKET_ID, UPSIDE_TICKET_ID]


def test_build_three_tickets_have_required_non_null_fields() -> None:
    card = _card_with_ab(n_a=1, n_b=1)
    tickets = build_tickets(card, budget_dollars=192.0)
    for t in tickets:
        assert t.label is not None
        assert t.cost > 0
        assert t.hit_rate_pct is not None
        assert t.payout_score is not None
        assert t.confidence is not None
        assert t.edge_score is not None
        assert t.chalk_exposure is not None
        assert t.notes is not None and t.notes != ""


def test_build_returns_ticket_objects() -> None:
    card = _card_with_a_per_leg()
    tickets = build_tickets(card, budget_dollars=192.0)
    assert all(isinstance(t, Ticket) for t in tickets)


# ---------------------------------------------------------------------------
# Scoring formulas
# ---------------------------------------------------------------------------


def test_payout_score_higher_for_less_chalky_legs() -> None:
    # Two cards with the same shape; one stacks favorites in every leg, the
    # other spreads to longshots. The longshot card's Upside ticket must
    # have the higher payout_score.
    chalky = _classified_card(["KEY", "KEY", "KEY", "KEY", "KEY"], n_total=4)
    spread = _classified_card(["MID", "MID", "MID", "MID", "MID"], n_total=8)
    chalky_tickets = build_tickets(chalky, budget_dollars=192.0)
    spread_tickets = build_tickets(spread, budget_dollars=192.0)
    chalky_upside = _by_label(chalky_tickets)[UPSIDE_LABEL]
    spread_upside = _by_label(spread_tickets)[UPSIDE_LABEL]
    assert chalky_upside.payout_score is not None
    assert spread_upside.payout_score is not None
    assert spread_upside.payout_score > chalky_upside.payout_score


def test_chalk_exposure_matches_mean_per_leg_max_market_probability() -> None:
    card = _classified_card(["KEY", "KEY", "KEY", "KEY", "KEY"], n_total=4)
    tickets = build_tickets(card, budget_dollars=192.0)
    horse_index = [{h.id: h for h in race.horses} for race in card]
    for t in tickets:
        expected = compute_chalk_exposure(t.selections, horse_index)
        assert t.chalk_exposure == pytest.approx(expected)


def test_payout_score_matches_one_minus_chalk_to_exponent() -> None:
    card = _classified_card(["MID", "MID", "MID", "MID", "MID"], n_total=8)
    tickets = build_tickets(card, budget_dollars=192.0)
    for t in tickets:
        assert t.chalk_exposure is not None and t.payout_score is not None
        expected = max(0.0, 1.0 - t.chalk_exposure) ** PAYOUT_SCORE_EXPONENT
        assert t.payout_score == pytest.approx(expected)


def test_balanced_ticket_has_highest_score_among_returned() -> None:
    # Score = win_prob × payout × confidence. Balanced selects on this; with
    # any non-degenerate pool, Balanced's score must be ≥ Safer and Upside.
    card = _card_with_ab(n_a=2, n_b=2, n_total=5)
    tickets = build_tickets(card, budget_dollars=192.0)
    by = _by_label(tickets)
    balanced = by[BALANCED_LABEL]
    for other in (by[SAFER_LABEL], by[UPSIDE_LABEL]):
        b_score = (balanced.hit_rate_pct / 100.0) * (
            balanced.payout_score or 0.0
        ) * (balanced.confidence or 0.0)
        o_score = (other.hit_rate_pct / 100.0) * (
            other.payout_score or 0.0
        ) * (other.confidence or 0.0)
        assert b_score + 1e-9 >= o_score


def test_compute_payout_score_helper_returns_value_in_unit_interval() -> None:
    card = _classified_card(["MID", "MID", "MID", "MID", "MID"], n_total=8)
    horse_index = [{h.id: h for h in race.horses} for race in card]
    selections = [[h.id for h in race.horses[:3]] for race in card]
    score = compute_payout_score(selections, horse_index)
    assert score is not None
    assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Safer / Upside selection rules
# ---------------------------------------------------------------------------


def test_safer_has_higher_win_probability_than_upside_when_floors_clear() -> None:
    # Mid-classification card with enough variety — both floors satisfiable.
    card = _classified_card(["MID", "MID", "MID", "MID", "MID"], n_total=8)
    tickets = build_tickets(card, budget_dollars=192.0)
    by = _by_label(tickets)
    safer = by[SAFER_LABEL]
    upside = by[UPSIDE_LABEL]
    # When both constraints clear, safer should not be lower-hit than upside.
    assert safer.hit_rate_pct >= upside.hit_rate_pct


def test_upside_has_higher_payout_score_than_balanced_when_floors_clear() -> None:
    card = _classified_card(["MID", "MID", "MID", "MID", "MID"], n_total=8)
    tickets = build_tickets(card, budget_dollars=192.0)
    by = _by_label(tickets)
    balanced = by[BALANCED_LABEL]
    upside = by[UPSIDE_LABEL]
    assert balanced.payout_score is not None and upside.payout_score is not None
    assert upside.payout_score >= balanced.payout_score


def test_safer_falls_back_to_top_score_when_no_candidate_clears_payout_floor() -> None:
    # Stack heavy favorites in every leg so every candidate's payout_score
    # comes in below SAFER_PAYOUT_FLOOR. The Safer slot must still be
    # populated by the highest-scoring candidate.
    races: list[Race] = []
    for i, role in enumerate(PICK5_LEG_ROLES):
        race_num = 8 + i
        horses = [
            _horse(race_num, 1, final=0.85, market=0.85),
            _horse(race_num, 2, final=0.05, market=0.05),
            _horse(race_num, 3, final=0.05, market=0.05),
            _horse(race_num, 4, final=0.05, market=0.05),
        ]
        race = _race(race_num, role, horses)
        race.classification = "KEY"
        races.append(race)
    tickets = build_tickets(races, budget_dollars=192.0)
    by = _by_label(tickets)
    safer = by[SAFER_LABEL]
    # Every candidate's payout_score < SAFER_PAYOUT_FLOOR for this card —
    # the slot should be the same selections as Balanced (best score).
    assert safer.payout_score is not None
    assert safer.payout_score < SAFER_PAYOUT_FLOOR
    assert safer.selections == by[BALANCED_LABEL].selections


def test_upside_falls_back_to_top_score_when_no_candidate_clears_win_floor() -> None:
    # Very wide chaos card — every candidate's hit_rate (win_probability)
    # comes in below UPSIDE_WIN_PROB_FLOOR after the simulator runs.
    n_total = 12
    max_entropy = math.log2(n_total)
    card = _classified_card(
        ["CHAOS", "CHAOS", "CHAOS", "CHAOS", "CHAOS"],
        n_total=n_total,
        entropies=[max_entropy * 0.95] * 5,
    )
    tickets = build_tickets(card, budget_dollars=192.0)
    by = _by_label(tickets)
    upside = by[UPSIDE_LABEL]
    # Every candidate's win_probability < UPSIDE_WIN_PROB_FLOOR — Upside
    # should fall back to the top-score candidate (same as Balanced).
    assert upside.hit_rate_pct / 100.0 < UPSIDE_WIN_PROB_FLOOR
    assert upside.selections == by[BALANCED_LABEL].selections


# ---------------------------------------------------------------------------
# Notes generation
# ---------------------------------------------------------------------------


def test_notes_call_out_strong_single() -> None:
    # KEY classification → 1 horse per leg. Pin a high confidence on the
    # leg-1 favorite so the notes call it out.
    card = _classified_card(["KEY", "KEY", "KEY", "KEY", "KEY"], n_total=4)
    card[0].horses[0].confidence_score = 0.9
    tickets = build_tickets(card, budget_dollars=DEFAULT_BASE_UNIT)
    by = _by_label(tickets)
    balanced = by[BALANCED_LABEL]
    assert balanced.notes is not None
    assert "Strong single" in balanced.notes
    assert f"R{card[0].raceNumber}" in balanced.notes


def test_notes_call_out_max_chaos_strategy() -> None:
    card = _classified_card(["KEY", "KEY", "KEY", "KEY", "KEY"], n_total=4)
    card[2].strategy = "MAX CHAOS"
    tickets = build_tickets(card, budget_dollars=DEFAULT_BASE_UNIT)
    notes = tickets[0].notes
    assert notes is not None
    assert "MAX CHAOS coverage" in notes
    assert f"R{card[2].raceNumber}" in notes


def test_notes_default_to_label_coverage_when_no_callouts() -> None:
    card = _card_with_a_per_leg()
    tickets = build_tickets(card, budget_dollars=192.0)
    for t in tickets:
        assert t.notes is not None
        # Default fallback contains the label name.
        if "Strong single" not in t.notes and "MAX CHAOS" not in t.notes:
            assert t.label in t.notes


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------


def test_all_three_tickets_respect_budget() -> None:
    # Wide pool that would otherwise blow past $48; each ticket must trim
    # to fit.
    card = _card_with_a_per_leg(n_a_horses=[5, 5, 5, 5, 5], n_total=5)
    tickets = build_tickets(card, budget_dollars=48.0)
    for t in tickets:
        assert t.cost <= 48.0


def test_all_three_tickets_respect_tight_budget_floor() -> None:
    card = _card_with_a_per_leg()
    tickets = build_tickets(card, budget_dollars=0.10)
    # Even when the budget can't afford a single combo, the irreducible
    # 1×1×1×1×1 minimum cost still fits.
    for t in tickets:
        assert t.cost == DEFAULT_BASE_UNIT
        assert all(len(s) == 1 for s in t.selections)


def test_cost_uses_custom_base_unit() -> None:
    card = _card_with_a_per_leg()
    tickets = build_tickets(card, budget_dollars=192.0, base_unit=2.0)
    for t in tickets:
        # Every leg has 1 selection → cost = 1 × base_unit.
        assert t.cost == 2.0


# ---------------------------------------------------------------------------
# Standard budget variants
# ---------------------------------------------------------------------------


def test_build_tickets_for_budgets_returns_all_four_standard_variants() -> None:
    card = _card_with_ab(n_a=1, n_b=1)
    variants = build_tickets_for_budgets(card)
    assert [v.budget_dollars for v in variants] == list(STANDARD_BUDGETS)
    for v in variants:
        assert isinstance(v, BudgetVariant)
        assert len(v.tickets) == 3


def test_build_tickets_for_budgets_appends_custom_budget() -> None:
    card = _card_with_ab(n_a=1, n_b=1)
    variants = build_tickets_for_budgets(
        card, budgets=list(STANDARD_BUDGETS) + [60.0]
    )
    assert [v.budget_dollars for v in variants] == [
        *STANDARD_BUDGETS,
        60.0,
    ]


def test_build_tickets_for_budgets_dedupes_repeated_budget() -> None:
    card = _card_with_ab(n_a=1, n_b=1)
    variants = build_tickets_for_budgets(
        card, budgets=[*STANDARD_BUDGETS, 96.0]
    )
    assert [v.budget_dollars for v in variants] == list(STANDARD_BUDGETS)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_returns_empty_when_card_missing_legs() -> None:
    card = _card_with_a_per_leg()[:3]
    assert build_tickets(card, budget_dollars=96.0) == []


def test_returns_empty_when_leg_has_no_eligible_horses() -> None:
    card = _card_with_a_per_leg()
    for h in card[0].horses:
        h.scratched = True
    assert build_tickets(card, budget_dollars=96.0) == []


def test_scratched_horses_not_included_in_any_ticket() -> None:
    card = _card_with_a_per_leg(n_a_horses=[2, 1, 1, 1, 1])
    card[0].horses[0].scratched = True
    tickets = build_tickets(card, budget_dollars=192.0)
    scratched_id = card[0].horses[0].id
    for t in tickets:
        assert scratched_id not in t.selections[0]


def _stack_chaos_value_leg(
    race: Race, value_horse_idx: int, *, value_tag: str | None, value_flag: str | None
) -> None:
    """Configure leg ``race`` so the chaos candidate dominates by payout AND hit-rate.

    Marks the race chaos-flagged via post-1, sets the leg's "value" horse
    with a high ``finalProbability`` (drives hit rate) and a low
    ``marketProbability`` (drives payout), and starves the other horses
    of finalProbability so the simulator picks the value horse most of
    the time.
    """
    race.horses[0].flags = [FLAG_CHAOS_RACE]
    if value_tag is not None:
        race.horses[value_horse_idx].userTag = value_tag  # type: ignore[assignment]
    if value_flag is not None:
        race.horses[value_horse_idx].flags = [value_flag]
    # Value horse: dominant finalProb, low marketProb.
    race.horses[value_horse_idx].finalProbability = 0.70
    race.horses[value_horse_idx].marketProbability = 0.10
    # Public favorite: low finalProb but high marketProb so it's the chalk
    # leg in the main candidate.
    race.horses[0].finalProbability = 0.10
    race.horses[0].marketProbability = 0.50
    # Remaining horses: enough finalProb to keep the leg sum > 0.
    for j, h in enumerate(race.horses):
        if j in (0, value_horse_idx):
            continue
        h.finalProbability = 0.10
        h.marketProbability = 0.20


def test_upside_picks_chaos_candidate_when_payout_score_wins() -> None:
    # Stack leg 0 so the chaos candidate dominates the main on both
    # payout (lower chalk) and hit rate (higher finalProbability on the
    # chaos horse). Upside must select the chaos selections.
    card = _card_with_a_per_leg()
    _stack_chaos_value_leg(card[0], value_horse_idx=2, value_tag="chaos", value_flag=None)
    tickets = build_tickets(card, budget_dollars=192.0)
    chaos_id = card[0].horses[2].id
    by = _by_label(tickets)
    assert chaos_id in by[UPSIDE_LABEL].selections[0]


def test_useful_value_horses_can_appear_in_upside() -> None:
    card = _card_with_a_per_leg()
    _stack_chaos_value_leg(
        card[0], value_horse_idx=3, value_tag=None, value_flag=FLAG_USEFUL_VALUE
    )
    tickets = build_tickets(card, budget_dollars=192.0)
    value_id = card[0].horses[3].id
    by = _by_label(tickets)
    assert value_id in by[UPSIDE_LABEL].selections[0]


def test_simulation_failure_still_returns_three_labeled_tickets() -> None:
    # Stripping finalProbability from leg 1 breaks the simulator; the
    # output contract still demands three labeled tickets.
    card = _card_with_ab(n_a=2, n_b=2, n_total=4)
    for h in card[0].horses:
        h.finalProbability = None
    tickets = build_tickets(card, budget_dollars=192.0)
    assert len(tickets) == 3
    labels = [t.label for t in tickets]
    assert labels == [BALANCED_LABEL, SAFER_LABEL, UPSIDE_LABEL]


def test_ticket_pydantic_validation_still_enforced() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        Ticket(id="bad", cost=0.0, selections=[["a"], ["b"]])


# ---------------------------------------------------------------------------
# Classification-driven leg widths surface in the output pool
# ---------------------------------------------------------------------------


def test_balanced_picks_top_horse_per_leg_for_all_key_classification() -> None:
    card = _classified_card(["KEY", "KEY", "KEY", "KEY", "KEY"])
    tickets = build_tickets(card, budget_dollars=DEFAULT_BASE_UNIT)
    balanced = _by_label(tickets)[BALANCED_LABEL]
    for leg_sel in balanced.selections:
        assert len(leg_sel) == 1


def test_balanced_picks_top_three_per_leg_for_all_mid_classification() -> None:
    card = _classified_card(["MID", "MID", "MID", "MID", "MID"])
    # 3^5 × 0.50 = $121.50; pick a budget at exactly that cost so no add.
    tickets = build_tickets(card, budget_dollars=121.50)
    balanced = _by_label(tickets)[BALANCED_LABEL]
    for leg_sel in balanced.selections:
        assert len(leg_sel) == 3


def test_balanced_picks_chaos_min_width_for_low_entropy() -> None:
    n_total = 8
    max_entropy = math.log2(n_total)
    low_entropy = max_entropy * 0.50
    card = _classified_card(
        ["CHAOS", "CHAOS", "CHAOS", "CHAOS", "CHAOS"],
        n_total=n_total,
        entropies=[low_entropy] * 5,
    )
    tickets = build_tickets(card, budget_dollars=1562.50)
    balanced = _by_label(tickets)[BALANCED_LABEL]
    for leg_sel in balanced.selections:
        assert len(leg_sel) == CHAOS_TARGET_MIN


def test_balanced_picks_chaos_max_width_for_high_entropy() -> None:
    n_total = 8
    max_entropy = math.log2(n_total)
    high_entropy = max_entropy * 0.95
    card = _classified_card(
        ["CHAOS", "CHAOS", "CHAOS", "CHAOS", "CHAOS"],
        n_total=n_total,
        entropies=[high_entropy] * 5,
    )
    tickets = build_tickets(card, budget_dollars=8403.50)
    balanced = _by_label(tickets)[BALANCED_LABEL]
    for leg_sel in balanced.selections:
        assert len(leg_sel) == CHAOS_TARGET_MAX


def test_balanced_excludes_dead_bucket_horses_from_classified_picks() -> None:
    card = _classified_card(["TIGHT", "KEY", "KEY", "KEY", "KEY"])
    card[0].horses[0].computedBucket = "DEAD"
    tickets = build_tickets(card, budget_dollars=1.0)
    balanced = _by_label(tickets)[BALANCED_LABEL]
    expected = {card[0].horses[1].id, card[0].horses[2].id}
    assert set(balanced.selections[0]) == expected


def test_balanced_caps_classified_target_at_eligible_pool_size() -> None:
    card = _classified_card(
        ["CHAOS", "KEY", "KEY", "KEY", "KEY"],
        n_total=4,
        entropies=[1.0, None, None, None, None],
    )
    tickets = build_tickets(card, budget_dollars=2.0)
    balanced = _by_label(tickets)[BALANCED_LABEL]
    assert len(balanced.selections[0]) == 4


def test_balanced_falls_back_to_favorite_when_no_classification_or_a_tag() -> None:
    card = _card_with_a_per_leg(n_a_horses=[0, 1, 1, 1, 1])
    card[0].horses[1].finalProbability = 0.7
    card[0].horses[1].marketProbability = 0.7
    card[0].horses[0].finalProbability = 0.1
    card[0].horses[2].finalProbability = 0.1
    card[0].horses[3].finalProbability = 0.1
    tickets = build_tickets(card, budget_dollars=192.0)
    balanced = _by_label(tickets)[BALANCED_LABEL]
    # Leg-1 favorite must appear; the A-tag fallback path doesn't grow the
    # leg, so the favorite is the lone selection.
    assert card[0].horses[1].id in balanced.selections[0]


# ---------------------------------------------------------------------------
# Efficiency-ratio trim (regression check via output)
# ---------------------------------------------------------------------------


def test_efficiency_trim_drops_lowest_ratio_horse_globally() -> None:
    card = _classified_card(["KEY", "KEY", "KEY", "KEY", "KEY"])
    leg0_probs = [0.30, 0.20, 0.15, 0.10, 0.05]
    leg0_horses: list[Horse] = []
    for post, p in enumerate(leg0_probs, start=1):
        leg0_horses.append(_horse(8, post, final=p, market=p))
    card[0].horses = leg0_horses
    leg1_probs = [0.50, 0.04]
    leg1_horses = [
        _horse(9, post, final=p, market=p)
        for post, p in enumerate(leg1_probs, start=1)
    ]
    card[1].horses = leg1_horses
    card[0].classification = "CHAOS"
    card[0].entropy = math.log2(5) * 0.5
    card[1].classification = "TIGHT"
    tickets = build_tickets(card, budget_dollars=4.50)
    balanced = _by_label(tickets)[BALANCED_LABEL]
    leg1_ids = set(balanced.selections[1])
    leg0_ids = set(balanced.selections[0])
    assert card[1].horses[1].id not in leg1_ids
    assert card[0].horses[4].id in leg0_ids
    assert balanced.cost == 5 * DEFAULT_BASE_UNIT


def test_classification_main_no_greedy_add_when_initial_cost_meets_budget() -> None:
    card = _classified_card(["MID", "MID", "MID", "MID", "MID"])
    tickets = build_tickets(card, budget_dollars=121.50)
    balanced = _by_label(tickets)[BALANCED_LABEL]
    assert balanced.cost == 121.50
    for leg_sel in balanced.selections:
        assert len(leg_sel) == 3
