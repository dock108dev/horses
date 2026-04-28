"""Tests for the Pick 5 leg-sequence resolver."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx
import pytest

from api.sources import pick5
from api.sources.equibase import EquibaseAdapter
from api.sources.pick5 import (
    MIN_FIRST_LEG,
    PICK5_SEQUENCES,
    get_pick5_legs,
    parse_pick5_first_leg,
    pick5_legs_heuristic,
)


# ---------- Tier 1: hardcoded constants ----------


def test_2026_friday_returns_oaks_sequence_from_constants() -> None:
    assert get_pick5_legs(2026, "friday") == [8, 9, 10, 11, 12]


def test_2026_saturday_returns_derby_sequence_from_constants() -> None:
    assert get_pick5_legs(2026, "saturday") == [9, 10, 11, 12, 13]


def test_2024_and_2025_constants_match_research() -> None:
    assert get_pick5_legs(2024, "friday") == [8, 9, 10, 11, 12]
    assert get_pick5_legs(2024, "saturday") == [9, 10, 11, 12, 13]
    assert get_pick5_legs(2025, "friday") == [8, 9, 10, 11, 12]
    assert get_pick5_legs(2025, "saturday") == [9, 10, 11, 12, 13]


def test_day_input_is_case_insensitive() -> None:
    assert get_pick5_legs(2026, "Friday") == [8, 9, 10, 11, 12]
    assert get_pick5_legs(2026, "SATURDAY") == [9, 10, 11, 12, 13]


def test_returned_list_is_a_copy_and_safe_to_mutate() -> None:
    legs = get_pick5_legs(2026, "saturday")
    legs.append(99)
    assert PICK5_SEQUENCES[(2026, "saturday")] == [9, 10, 11, 12, 13]


# ---------- parse_pick5_first_leg ----------


CARD_HTML_DATA_RACE = """
<html><body>
<div class="race-block" data-race="9">
  <h2>Race 9</h2>
  <ul class="wager-types">
    <li>Win</li><li>Place</li><li>Show</li>
    <li>Exacta</li><li>Trifecta</li>
    <li>Daily Double</li><li>Pick 4</li><li>Pick 5</li>
  </ul>
</div>
<div class="race-block" data-race="10">
  <h2>Race 10</h2>
  <ul class="wager-types">
    <li>Win</li><li>Place</li><li>Show</li>
  </ul>
</div>
<div class="race-block" data-race="11">
  <h2>Race 11</h2>
  <ul class="wager-types">
    <li>Win</li><li>Place</li><li>Pick 4</li>
  </ul>
</div>
</body></html>
"""


CARD_HTML_PLAINTEXT_HEADERS = """
<html><body>
<h2>Race 8</h2>
<p>Wagers: Win, Place, Show, Exacta, Trifecta, Daily Double, Pick 4</p>
<h2>Race 9</h2>
<p>Wagers: Win, Place, Show, Exacta, Trifecta, Daily Double, Pick 4, Pick 5</p>
<h2>Race 10</h2>
<p>Wagers: Win, Place, Show</p>
</body></html>
"""


CARD_HTML_EARLY_PICK5 = """
<html><body>
<div data-race="2">
  <h2>Race 2</h2>
  <ul><li>Pick 5</li></ul>
</div>
<div data-race="9">
  <h2>Race 9</h2>
  <ul><li>Pick 5</li></ul>
</div>
</body></html>
"""


def test_parse_pick5_first_leg_finds_data_race_attribute() -> None:
    assert parse_pick5_first_leg(CARD_HTML_DATA_RACE) == 9


def test_parse_pick5_first_leg_falls_back_to_text_segmentation() -> None:
    assert parse_pick5_first_leg(CARD_HTML_PLAINTEXT_HEADERS) == 9


def test_parse_pick5_first_leg_returns_lowest_when_multiple_match() -> None:
    # Both race 2 and race 9 mention Pick 5; the parser returns the lowest.
    # (The MIN_FIRST_LEG sanity filter is applied at the get_pick5_legs
    # layer, not in the raw parser.)
    assert parse_pick5_first_leg(CARD_HTML_EARLY_PICK5) == 2


def test_parse_pick5_first_leg_returns_none_for_empty_or_missing() -> None:
    assert parse_pick5_first_leg(None) is None
    assert parse_pick5_first_leg("") is None
    assert parse_pick5_first_leg("<html><body><p>no wagers</p></body></html>") is None


def test_parse_pick5_first_leg_ignores_invalid_data_race_values() -> None:
    html = """
    <html><body>
    <div data-race="not-a-number"><p>Pick 5</p></div>
    <div data-race="9"><p>Pick 5</p></div>
    </body></html>
    """
    assert parse_pick5_first_leg(html) == 9


# ---------- Tier 2: Equibase scrape integration ----------


class _FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "") -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status {self.status_code}",
                request=httpx.Request("GET", "http://example/"),
                response=httpx.Response(self.status_code),
            )


class _FakeHttp:
    def __init__(self, responses: list[_FakeResponse | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> _FakeResponse:
        self.calls.append({"url": url, "headers": dict(headers), "timeout": timeout})
        if not self._responses:
            raise AssertionError(f"unexpected GET {url}")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def _adapter_with_card(html: str | Exception) -> EquibaseAdapter:
    response: _FakeResponse | Exception = (
        html if isinstance(html, Exception) else _FakeResponse(text=html)
    )
    fake = _FakeHttp([response])
    return EquibaseAdapter(http_client=fake, min_request_interval=0.0)


def test_scrape_matches_hardcoded_returns_hardcoded_no_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter = _adapter_with_card(CARD_HTML_DATA_RACE)  # first leg = 9
    with caplog.at_level(logging.WARNING, logger=pick5.__name__):
        legs = get_pick5_legs(
            2026,
            "saturday",
            adapter=adapter,
            race_date=date(2026, 5, 2),
        )
    assert legs == [9, 10, 11, 12, 13]
    assert not any("mismatch" in r.message.lower() for r in caplog.records)


def test_scrape_differs_from_hardcoded_logs_warning_and_returns_scraped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Card says first Pick 5 leg = 10, but hardcoded for Saturday is 9.
    html = """
    <html><body>
    <div data-race="9"><p>Wagers: Win, Place, Pick 4</p></div>
    <div data-race="10"><p>Wagers: Win, Place, Pick 4, Pick 5</p></div>
    </body></html>
    """
    adapter = _adapter_with_card(html)
    with caplog.at_level(logging.WARNING, logger=pick5.__name__):
        legs = get_pick5_legs(
            2026,
            "saturday",
            adapter=adapter,
            race_date=date(2026, 5, 2),
        )
    assert legs == [10, 11, 12, 13, 14]
    assert any(
        "mismatch" in r.message.lower() and "scraped" in r.message.lower()
        for r in caplog.records
    )


def test_scrape_first_leg_below_floor_is_ignored(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # MIN_FIRST_LEG = 7; a "Pick 5" detected at race 2 must be ignored.
    adapter = _adapter_with_card(CARD_HTML_EARLY_PICK5)
    with caplog.at_level(logging.WARNING, logger=pick5.__name__):
        legs = get_pick5_legs(
            2026,
            "saturday",
            adapter=adapter,
            race_date=date(2026, 5, 2),
        )
    # Falls back to hardcoded because scraped value 2 < 7 was rejected.
    assert legs == [9, 10, 11, 12, 13]
    assert any(
        "sanity floor" in r.message.lower() for r in caplog.records
    )


def test_scrape_exception_falls_back_to_hardcoded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter = _adapter_with_card(httpx.ConnectError("network down"))
    with caplog.at_level(logging.WARNING, logger=pick5.__name__):
        legs = get_pick5_legs(
            2026,
            "saturday",
            adapter=adapter,
            race_date=date(2026, 5, 2),
        )
    assert legs == [9, 10, 11, 12, 13]
    assert any("scrape failed" in r.message.lower() for r in caplog.records)


def test_scrape_returning_none_falls_back_to_hardcoded() -> None:
    # Card has no Pick 5 wager anywhere: parse returns None, function
    # falls back to hardcoded.
    html = "<html><body><div data-race='9'><p>no exotics here</p></div></body></html>"
    adapter = _adapter_with_card(html)
    legs = get_pick5_legs(
        2026,
        "saturday",
        adapter=adapter,
        race_date=date(2026, 5, 2),
    )
    assert legs == [9, 10, 11, 12, 13]


# ---------- Tier 3: heuristic ----------


def test_heuristic_returns_last_five_races() -> None:
    assert pick5_legs_heuristic(13) == [9, 10, 11, 12, 13]
    assert pick5_legs_heuristic(14) == [10, 11, 12, 13, 14]
    assert pick5_legs_heuristic(11) == [7, 8, 9, 10, 11]


def test_heuristic_used_when_unknown_year_with_total_races() -> None:
    legs = get_pick5_legs(2099, "saturday", total_races=14)
    assert legs == [10, 11, 12, 13, 14]


def test_heuristic_short_card_still_returns_five_integers() -> None:
    legs = pick5_legs_heuristic(3)
    assert len(legs) == 5
    assert all(isinstance(x, int) for x in legs)


# ---------- Always-5-ints invariant ----------


def test_unknown_year_unknown_day_still_returns_five_integers() -> None:
    legs = get_pick5_legs(2099, "unknown-day")
    assert len(legs) == 5
    assert all(isinstance(x, int) for x in legs)


def test_unknown_year_known_day_falls_back_to_default_pattern() -> None:
    assert get_pick5_legs(2099, "friday") == [8, 9, 10, 11, 12]
    assert get_pick5_legs(2099, "saturday") == [9, 10, 11, 12, 13]


def test_min_first_leg_constant_matches_research() -> None:
    assert MIN_FIRST_LEG == 7
