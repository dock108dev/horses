"""Fixture-backed end-to-end test for the Friday Pick 5 workflow.

BRAINDUMP §C calls this "the single most important test we don't have
yet": the full in-process loop — refresh card → refresh odds →
simulate → build tickets — exercised through the FastAPI
``TestClient`` against the committed fixture data, with no live network
calls. It is the canary for silent breakage in fixture loading,
probability normalization, blend math, sim setup, or ticket sizing.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.model import Race, blend_race
from api.tests.conftest import FRIDAY_LEGS

# Counted from ``fixtures/pick5/friday-card.json`` (no horse carries
# ``scratched: true`` today); the runner-count expression below uses
# ``not h.get("scratched", False)`` so adding scratches later does not
# silently invalidate the assertion.
EXPECTED_FRIDAY_RUNNER_COUNTS = [8, 9, 8, 14, 7]

# Mirrors ``api.tickets.STANDARD_BUDGETS``. One BudgetVariant per entry,
# three labeled tickets per variant on the happy path.
EXPECTED_BUDGETS = [48.0, 96.0, 144.0, 192.0]


def test_friday_pick5_e2e_fixture_workflow(client: TestClient) -> None:
    """Walk the full Pick 5 workflow against the Friday fixture data.

    Every step asserts ``errors=[]`` and ``stale=False`` so any
    regression that flips the envelope to the cache-fallback path will
    fail loudly here, rather than silently degrading the iPad UI.
    """
    # 1. Refresh card from fixture.
    card_resp = client.post("/api/cards/friday/refresh?source=fixture")
    assert card_resp.status_code == 200
    card_body = card_resp.json()
    assert card_body["errors"] == []
    assert card_body["stale"] is False
    assert card_body["source"] == "fixture"
    assert card_body["cached_at"] is not None
    assert len(card_body["data"]) == 5
    assert [r["raceNumber"] for r in card_body["data"]] == FRIDAY_LEGS

    # 2. Per-leg runner counts must match the fixture exactly.
    runner_counts = [
        sum(1 for h in race["horses"] if not h.get("scratched", False))
        for race in card_body["data"]
    ]
    assert runner_counts == EXPECTED_FRIDAY_RUNNER_COUNTS, (
        f"runner counts {runner_counts} do not match expected "
        f"{EXPECTED_FRIDAY_RUNNER_COUNTS}"
    )

    # 3. Refresh odds from fixture.
    odds_resp = client.post("/api/odds/friday/refresh?source=fixture")
    assert odds_resp.status_code == 200
    odds_body = odds_resp.json()
    assert odds_body["errors"] == []
    assert odds_body["stale"] is False
    assert odds_body["source"] == "fixture"
    assert len(odds_body["data"]) == 5

    # 4. Simulate — happy path returns the SimulationResult envelope.
    sim_resp = client.post("/api/simulate/friday", json={"n_iterations": 500})
    assert sim_resp.status_code == 200
    sim_body = sim_resp.json()
    assert sim_body["errors"] == []
    assert sim_body["stale"] is False
    assert sim_body["data"] is not None

    # 5. Probability sanity: per-race finalProbability must sum to ~1.0.
    # /api/simulate's response doesn't carry the cards, and simulate
    # mutates the cached card only in memory. Re-run the same in-process
    # blend the simulate handler applies on the GET /api/cards payload
    # so the assertion exercises the real pipeline output instead of a
    # stand-in. Without market odds joined onto the card, blend falls
    # through to morningLineProbability, which is normalized at fixture
    # load — so the sum should land at exactly 1.0 within float slop.
    refreshed = client.get("/api/cards/friday")
    assert refreshed.status_code == 200
    races = [Race.model_validate(r) for r in refreshed.json()["data"]]
    assert len(races) == 5
    for race in races:
        blend_race(race, has_model_prior=False)
        total = sum(
            (h.finalProbability or 0.0)
            for h in race.horses
            if not h.scratched
        )
        assert total == pytest.approx(1.0, abs=0.01), (
            f"race {race.raceNumber} finalProbability sum = {total!r}"
        )

    # 6. Build tickets — four standard budget variants, each non-empty.
    tickets_resp = client.post("/api/tickets/friday/build", json={})
    assert tickets_resp.status_code == 200
    tickets_body = tickets_resp.json()
    assert tickets_body["errors"] == []
    assert tickets_body["stale"] is False
    assert tickets_body["source"] == "tickets"
    variants = tickets_body["data"]["variants"]
    assert len(variants) == 4
    assert [v["budget_dollars"] for v in variants] == EXPECTED_BUDGETS
    assert all(len(v["tickets"]) > 0 for v in variants)


@pytest.mark.skip(
    reason=(
        "Golden snapshot of /simulate/friday deferred: SimulateRequest "
        "has no `seed` parameter, so estimated_hit_rate_pct / "
        "chalkiness_pct / chaos_coverage_pct / separator_coverage_pct "
        "are non-deterministic and would produce a flaky diff. Wire "
        "this back on once the request schema exposes `seed`, or once "
        "a deterministic blend-only endpoint is added that this test "
        "can snapshot instead."
    )
)
def test_friday_pick5_simulate_golden_snapshot(client: TestClient) -> None:
    """Diff the /simulate/friday body against a committed golden file.

    Currently skipped — see the marker reason above. The intended
    failure mode is: any drift in blend math (currently
    market×0.80 + ml×0.20 with no model prior) or sim setup will flip
    the snapshot, and the test fails loudly rather than letting the
    regression sail through to production tickets.
    """
