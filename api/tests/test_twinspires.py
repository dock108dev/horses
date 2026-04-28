"""Tests for the TwinSpires program/odds adapter."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from api.sources import twinspires
from api.sources.twinspires import (
    HOMEPAGE_URL,
    ScratchEvent,
    TwinSpiresAdapter,
    odds_url,
    program_url,
    to_fractional_odds,
)


PROGRAM_PAYLOAD: dict[str, Any] = {
    "track": "CD",
    "date": "20260502",
    "raceNumber": 12,
    "raceName": "Kentucky Derby",
    "distance": "1 1/4 Miles",
    "surface": "Dirt",
    "postTime": "18:57",
    "runners": [
        {
            "programNumber": "1",
            "horseName": "Forever Young",
            "jockey": "R. Sakai",
            "trainer": "Y. Yahagi",
            "morningLineOdds": "5-1",
            "scratched": False,
            "scratch_reason": None,
        },
        {
            "programNumber": "2",
            "horseName": "Sierra Leone",
            "jockey": "T. Gaffalione",
            "trainer": "C. Brown",
            "morningLineOdds": "3/1",
            "scratched": False,
            "scratch_reason": None,
        },
        {
            "programNumber": "3",
            "horseName": "Mystik Dan",
            "jockey": "B. Hernandez",
            "trainer": "K. McPeek",
            "morningLineOdds": "10/1",
            "scratched": False,
            "scratch_reason": None,
        },
    ],
}


ODDS_PAYLOAD: dict[str, Any] = {
    "track": "CD",
    "race": 12,
    "mtp": 4,
    "runners": [
        {"programNumber": "1", "winOdds": "4.80", "favorite": True},
        {"programNumber": "2", "winOdds": "5/2"},
        {"programNumber": "3", "winOdds": "12-1"},
    ],
}


def _scratched_payload() -> dict[str, Any]:
    payload = json.loads(json.dumps(PROGRAM_PAYLOAD))  # deep copy
    payload["runners"][1]["scratched"] = True
    payload["runners"][1]["scratch_reason"] = "Veterinarian"
    return payload


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        json_body: Any = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._json = json_body
        self.text = text or (json.dumps(json_body) if json_body is not None else "")

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status {self.status_code}",
                request=httpx.Request("GET", "http://example/"),
                response=httpx.Response(self.status_code),
            )


class FakeHttp:
    """Records GETs and returns scripted responses in order."""

    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> FakeResponse:
        self.calls.append({"url": url, "headers": dict(headers), "timeout": timeout})
        if not self._responses:
            raise AssertionError(f"unexpected GET {url}")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


# ---------- URL helpers ----------


def test_program_url_format() -> None:
    assert program_url("2026-05-02", 12) == (
        "https://www.twinspires.com/ts-res/api/racing/program"
        "?track=CD&date=20260502&race=12"
    )


def test_odds_url_format() -> None:
    assert odds_url("2026-05-02", 12) == (
        "https://www.twinspires.com/ts-res/api/racing/odds"
        "?track=CD&date=20260502&race=12"
    )


def test_program_url_rejects_zero_race() -> None:
    with pytest.raises(ValueError):
        program_url("2026-05-02", 0)


# ---------- Fractional-odds helper ----------


def test_to_fractional_odds_normalizes_dash_to_slash() -> None:
    assert to_fractional_odds("5-1") == "5/1"
    assert to_fractional_odds("12-1") == "12/1"


def test_to_fractional_odds_passes_existing_slash_through() -> None:
    assert to_fractional_odds("5/2") == "5/2"


def test_to_fractional_odds_converts_decimal_to_fraction() -> None:
    # 4.80 -> 24/5 (limit_denominator(50))
    assert to_fractional_odds("4.80") == "24/5"
    assert to_fractional_odds("2.5") == "5/2"


def test_to_fractional_odds_handles_empty_and_none() -> None:
    assert to_fractional_odds(None) is None
    assert to_fractional_odds("") is None


# ---------- Session seeding ----------


def test_first_call_seeds_session_via_homepage_get() -> None:
    http = FakeHttp(
        [
            FakeResponse(json_body={}),  # homepage seed
            FakeResponse(json_body=PROGRAM_PAYLOAD),  # program API
        ]
    )
    adapter = TwinSpiresAdapter(http_client=http, fallback_client=None)
    adapter.fetch_program("2026-05-02", 12, day="saturday")

    assert len(http.calls) == 2
    assert http.calls[0]["url"] == HOMEPAGE_URL
    assert "/ts-res/api/racing/program" in http.calls[1]["url"]


def test_second_call_does_not_reseed_session() -> None:
    http = FakeHttp(
        [
            FakeResponse(json_body={}),  # homepage seed
            FakeResponse(json_body=PROGRAM_PAYLOAD),
            FakeResponse(json_body=ODDS_PAYLOAD),
        ]
    )
    adapter = TwinSpiresAdapter(
        http_client=http, fallback_client=None, min_odds_interval=0.0
    )
    adapter.fetch_program("2026-05-02", 12, day="saturday")
    adapter.fetch_odds("2026-05-02", 12)
    assert len(http.calls) == 3
    assert http.calls[0]["url"] == HOMEPAGE_URL


def test_request_headers_include_browser_signature() -> None:
    http = FakeHttp(
        [FakeResponse(json_body={}), FakeResponse(json_body=PROGRAM_PAYLOAD)]
    )
    adapter = TwinSpiresAdapter(http_client=http, fallback_client=None)
    adapter.fetch_program("2026-05-02", 12, day="saturday")

    headers = http.calls[1]["headers"]
    assert "Mozilla/5.0" in headers["User-Agent"]
    assert headers["Origin"] == "https://www.twinspires.com"
    assert headers["Referer"] == HOMEPAGE_URL
    assert headers["Sec-Fetch-Mode"] == "cors"
    assert "application/json" in headers["Accept"]


# ---------- Live odds ----------


def test_fetch_odds_returns_fractional_strings() -> None:
    http = FakeHttp(
        [FakeResponse(json_body={}), FakeResponse(json_body=ODDS_PAYLOAD)]
    )
    adapter = TwinSpiresAdapter(
        http_client=http, fallback_client=None, min_odds_interval=0.0
    )
    rows = adapter.fetch_odds("2026-05-02", 12)
    assert [r["programNumber"] for r in rows] == ["1", "2", "3"]
    odds = [r["winOdds"] for r in rows]
    assert odds == ["24/5", "5/2", "12/1"]
    # Every odds string has the canonical "num/den" shape.
    for value in odds:
        assert value is not None and "/" in value


# ---------- curl_cffi fallback on 403 ----------


def test_403_from_httpx_swaps_to_curl_cffi_fallback() -> None:
    primary = FakeHttp(
        [
            FakeResponse(json_body={}),  # homepage seed (httpx)
            FakeResponse(status_code=403, text="Cloudflare challenge"),  # blocked
        ]
    )
    fallback = FakeHttp(
        [
            FakeResponse(json_body={}),  # homepage re-seed (curl_cffi)
            FakeResponse(json_body=PROGRAM_PAYLOAD),  # retried call
        ]
    )
    adapter = TwinSpiresAdapter(http_client=primary, fallback_client=fallback)
    race = adapter.fetch_program("2026-05-02", 12, day="saturday")

    assert race is not None
    assert race.raceNumber == 12
    # First two calls hit the primary (seed + 403), then we swapped clients.
    assert len(primary.calls) == 2
    # Fallback re-seeded session and then served the program JSON.
    assert len(fallback.calls) == 2
    assert fallback.calls[0]["url"] == HOMEPAGE_URL
    assert "/ts-res/api/racing/program" in fallback.calls[1]["url"]


def test_404_returns_none_without_raising() -> None:
    """Pre-draw races return 404 from TwinSpires; treat as "no payload".

    Before entries are posted, ``/program`` returns 404 for every race.
    The adapter should surface that as ``None`` so callers can continue
    the card refresh from Equibase data alone, instead of crashing the
    whole refresh with an unhandled ``HTTPStatusError``.
    """
    http = FakeHttp(
        [
            FakeResponse(json_body={}),  # homepage seed
            FakeResponse(status_code=404, text="not found"),
        ]
    )
    adapter = TwinSpiresAdapter(http_client=http, fallback_client=None)
    assert adapter.fetch_program("2026-05-02", 12, day="saturday") is None


def test_404_on_odds_returns_empty_list() -> None:
    http = FakeHttp(
        [
            FakeResponse(json_body={}),  # homepage seed
            FakeResponse(status_code=404, text="not found"),
        ]
    )
    adapter = TwinSpiresAdapter(
        http_client=http, fallback_client=None, min_odds_interval=0.0
    )
    assert adapter.fetch_odds("2026-05-02", 12) == []


def test_403_without_fallback_raises() -> None:
    primary = FakeHttp(
        [
            FakeResponse(json_body={}),
            FakeResponse(status_code=403, text="Forbidden"),
        ]
    )
    adapter = TwinSpiresAdapter(http_client=primary, fallback_client=None)
    with pytest.raises(httpx.HTTPStatusError):
        adapter.fetch_program("2026-05-02", 12, day="saturday")


# ---------- Program parsing into Race ----------


def test_fetch_program_parses_into_race_model() -> None:
    http = FakeHttp(
        [FakeResponse(json_body={}), FakeResponse(json_body=PROGRAM_PAYLOAD)]
    )
    adapter = TwinSpiresAdapter(http_client=http, fallback_client=None)
    race = adapter.fetch_program("2026-05-02", 12, day="saturday")

    assert race is not None
    assert race.id == "CD-2026-05-02-R12"
    assert race.day == "saturday"
    assert race.track == "Churchill Downs"
    assert race.raceNumber == 12
    assert race.name == "Kentucky Derby"
    assert race.surface == "Dirt"
    assert race.postTime == "18:57"
    assert len(race.horses) == 3

    h1 = race.horses[0]
    assert h1.post == 1
    assert h1.name == "Forever Young"
    assert h1.jockey == "R. Sakai"
    assert h1.trainer == "Y. Yahagi"
    assert h1.morningLineOdds == "5-1"
    assert h1.scratched is False
    assert h1.source == "twinspires"


def test_fetch_program_returns_none_when_runners_missing() -> None:
    http = FakeHttp(
        [
            FakeResponse(json_body={}),
            FakeResponse(json_body={"raceNumber": 99, "runners": []}),
        ]
    )
    adapter = TwinSpiresAdapter(http_client=http, fallback_client=None)
    assert adapter.fetch_program("2026-05-02", 99, day="saturday") is None


# ---------- Scratch detection between polls ----------


def test_scratch_detected_between_consecutive_polls() -> None:
    http = FakeHttp(
        [
            FakeResponse(json_body={}),  # homepage seed
            FakeResponse(json_body=PROGRAM_PAYLOAD),  # poll 1: nobody scratched
            FakeResponse(json_body=_scratched_payload()),  # poll 2: #2 scratched
        ]
    )
    adapter = TwinSpiresAdapter(http_client=http, fallback_client=None)

    race1, events1 = adapter.poll_program("2026-05-02", 12, day="saturday")
    race2, events2 = adapter.poll_program("2026-05-02", 12, day="saturday")

    assert race1 is not None and events1 == []
    assert race2 is not None
    assert len(events2) == 1
    ev = events2[0]
    assert isinstance(ev, ScratchEvent)
    assert ev.programNumber == "2"
    assert ev.horseName == "Sierra Leone"
    assert ev.reason == "Veterinarian"
    assert ev.raceId == "CD-2026-05-02-R12"


def test_no_scratch_event_when_state_unchanged() -> None:
    http = FakeHttp(
        [
            FakeResponse(json_body={}),
            FakeResponse(json_body=PROGRAM_PAYLOAD),
            FakeResponse(json_body=PROGRAM_PAYLOAD),
        ]
    )
    adapter = TwinSpiresAdapter(http_client=http, fallback_client=None)
    adapter.poll_program("2026-05-02", 12, day="saturday")
    _, events = adapter.poll_program("2026-05-02", 12, day="saturday")
    assert events == []


def test_already_scratched_runner_not_re_emitted() -> None:
    http = FakeHttp(
        [
            FakeResponse(json_body={}),
            FakeResponse(json_body=_scratched_payload()),
            FakeResponse(json_body=_scratched_payload()),
        ]
    )
    adapter = TwinSpiresAdapter(http_client=http, fallback_client=None)
    _, first = adapter.poll_program("2026-05-02", 12, day="saturday")
    _, second = adapter.poll_program("2026-05-02", 12, day="saturday")
    # No prior poll on first call → was-scratched defaults to False, so the
    # transition false→true fires once.
    assert len(first) == 1
    # Second poll: previous was already scratched, so no new event.
    assert second == []


# ---------- 30s odds-poll floor ----------


def test_odds_polls_respect_30s_floor_per_race(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    fake_now = [1000.0]

    monkeypatch.setattr(twinspires.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(twinspires.time, "monotonic", lambda: fake_now[0])

    http = FakeHttp(
        [
            FakeResponse(json_body={}),  # seed
            FakeResponse(json_body=ODDS_PAYLOAD),  # poll 1
            FakeResponse(json_body=ODDS_PAYLOAD),  # poll 2
        ]
    )
    adapter = TwinSpiresAdapter(http_client=http, fallback_client=None)
    # Override default 30.0s to assert it's the floor that's enforced.
    assert adapter.min_odds_interval == 30.0

    adapter.fetch_odds("2026-05-02", 12)
    fake_now[0] = 1005.0  # only 5s elapsed
    adapter.fetch_odds("2026-05-02", 12)

    assert len(sleeps) == 1
    # Should sleep ~25s to reach the 30s floor.
    assert 24.5 <= sleeps[0] <= 30.0


def test_odds_floor_is_per_race_not_global(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    fake_now = [1000.0]

    monkeypatch.setattr(twinspires.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(twinspires.time, "monotonic", lambda: fake_now[0])

    http = FakeHttp(
        [
            FakeResponse(json_body={}),  # seed
            FakeResponse(json_body=ODDS_PAYLOAD),  # race 11
            FakeResponse(json_body=ODDS_PAYLOAD),  # race 12 — different race, no wait
        ]
    )
    adapter = TwinSpiresAdapter(http_client=http, fallback_client=None)
    adapter.fetch_odds("2026-05-02", 11)
    fake_now[0] = 1001.0
    adapter.fetch_odds("2026-05-02", 12)
    assert sleeps == []


def test_default_min_odds_interval_is_30_seconds() -> None:
    assert TwinSpiresAdapter.__dataclass_fields__[
        "min_odds_interval"
    ].default == 30.0
