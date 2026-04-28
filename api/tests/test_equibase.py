"""Tests for the Equibase static-HTML race-card adapter."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from api.sources import equibase
from api.sources.equibase import (
    EquibaseAdapter,
    card_url,
    entry_url,
    is_soft_404,
    parse_race_html,
    strip_country_suffix,
)


SAMPLE_RACE_HTML = """
<!DOCTYPE html>
<html><body>
<div class="static-entry-wrapper">
  <div class="race-info">
    <h1>Race 1 - 5½ Furlongs - Maiden Claiming</h1>
    <p>Surface: Dirt | Purse: $30,000 | Post Time: 12:30 PM ET</p>
  </div>
  <table class="entries-table">
    <thead>
      <tr>
        <th>PP</th><th>Horse</th><th>Jockey</th><th>Trainer</th>
        <th>Weight</th><th>ML</th><th>Medications</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>1</td><td>FOREVER YOUNG (JPN)</td><td>Ryusei Sakai</td>
        <td>Yoshito Yahagi</td><td>126</td><td>5/2</td><td>L</td>
      </tr>
      <tr>
        <td>2</td><td>SIERRA LEONE</td><td>Tyler Gaffalione</td>
        <td>Chad Brown</td><td>126</td><td>3/1</td><td>L</td>
      </tr>
      <tr class="scratched">
        <td>3</td><td>FAST DREAMER</td><td>Jose Ortiz</td>
        <td>D. Wayne Lukas</td><td>126</td><td>15/1</td><td>SCR</td>
      </tr>
      <tr>
        <td>4</td><td><s>HIDDEN STASH</s></td><td>Brian Hernandez</td>
        <td>Kenny McPeek</td><td>126</td><td>20/1</td><td>LB</td>
      </tr>
      <tr>
        <td>5</td><td>MYSTIK DAN</td><td>Brian Hernandez</td>
        <td>Kenny McPeek</td><td>126</td><td>10/1</td><td></td>
      </tr>
    </tbody>
  </table>
</div>
</body></html>
"""

SOFT_404_HTML = (
    "<!DOCTYPE html><html><body>"
    "<p>No data found for the requested race.</p>"
    "</body></html>"
)


class FakeResponse:
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


class FakeHttp:
    """Records every GET and returns scripted responses."""

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


def test_entry_url_zero_pads_race_and_two_digit_year() -> None:
    assert (
        entry_url(date(2024, 5, 4), 1)
        == "https://www.equibase.com/static/entry/CD050424R01-EQB.html"
    )
    assert (
        entry_url("2024-05-04", 14)
        == "https://www.equibase.com/static/entry/CD050424R14-EQB.html"
    )


def test_entry_url_rejects_zero_race() -> None:
    with pytest.raises(ValueError):
        entry_url("2024-05-04", 0)


def test_card_url_format() -> None:
    assert (
        card_url(date(2026, 5, 2))
        == "https://www.equibase.com/static/card/CD050226-EQB.html"
    )


# ---------- Pure parsing helpers ----------


def test_strip_country_suffix_handles_common_suffixes() -> None:
    assert strip_country_suffix("FOREVER YOUNG (JPN)") == "FOREVER YOUNG"
    assert strip_country_suffix("Snowfall (IRE)") == "Snowfall"
    assert strip_country_suffix("Just A Touch (USA)") == "Just A Touch"
    assert strip_country_suffix("Mage") == "Mage"


def test_is_soft_404_recognises_no_data_marker() -> None:
    assert is_soft_404(SOFT_404_HTML) is True
    assert is_soft_404("") is True
    assert is_soft_404(None) is True
    assert is_soft_404(SAMPLE_RACE_HTML) is False


@pytest.mark.parametrize(
    "phrase",
    [
        "no data found",
        "no data is available",
        "no entries available",
        "entries are not available",
        "entry information is not available",
    ],
)
def test_is_soft_404_recognises_pre_publication_phrases(phrase: str) -> None:
    html = f"<html><body><p>{phrase.upper()} for this race.</p></body></html>"
    assert is_soft_404(html) is True


# ---------- parse_race_html ----------


def test_parse_race_html_extracts_full_card() -> None:
    race = parse_race_html(
        SAMPLE_RACE_HTML, date_in="2024-05-04", race_number=1, day="saturday"
    )

    assert race is not None
    assert race.id == "CD-2024-05-04-R01"
    assert race.day == "saturday"
    assert race.track == "Churchill Downs"
    assert race.raceNumber == 1
    assert race.surface == "Dirt"
    assert race.distance is not None and "Furlongs" in race.distance
    assert race.postTime is not None and "12:30" in race.postTime
    assert len(race.horses) == 5

    h1, h2, h3, h4, h5 = race.horses
    assert h1.post == 1
    assert h1.name == "FOREVER YOUNG"  # (JPN) suffix stripped
    assert h1.jockey == "Ryusei Sakai"
    assert h1.trainer == "Yoshito Yahagi"
    assert h1.morningLineOdds == "5/2"
    assert h1.source == "equibase"
    assert h1.scratched is False
    assert "meds:L" in h1.flags

    assert h2.name == "SIERRA LEONE"
    assert h2.morningLineOdds == "3/1"

    # SCR cell marks horse #3 scratched.
    assert h3.scratched is True
    # Strikethrough markup marks horse #4 scratched, name preserved.
    assert h4.scratched is True
    assert h4.name == "HIDDEN STASH"
    assert "meds:LB" in h4.flags

    # Empty meds cell yields no medications flag.
    assert h5.flags == []


def test_parse_race_html_returns_none_on_soft_404() -> None:
    assert (
        parse_race_html(
            SOFT_404_HTML, date_in="2024-05-04", race_number=99, day="saturday"
        )
        is None
    )


def test_parse_race_html_returns_none_when_no_entries_table() -> None:
    html = "<html><body><h1>Race 1</h1><p>No table here.</p></body></html>"
    assert (
        parse_race_html(html, date_in="2024-05-04", race_number=1, day="saturday")
        is None
    )


# ---------- EquibaseAdapter.fetch_html ----------


def _adapter(http: FakeHttp, **kwargs: Any) -> EquibaseAdapter:
    return EquibaseAdapter(http_client=http, min_request_interval=0.0, **kwargs)


def test_fetch_html_returns_none_on_http_404() -> None:
    http = FakeHttp([FakeResponse(status_code=404, text="Not Found")])
    adapter = _adapter(http)
    url = entry_url("2024-05-04", 1)
    assert adapter.fetch_html(url) is None
    assert len(http.calls) == 1


def test_fetch_html_returns_none_on_soft_404() -> None:
    http = FakeHttp([FakeResponse(text=SOFT_404_HTML)])
    adapter = _adapter(http)
    assert adapter.fetch_html(entry_url("2024-05-04", 1)) is None


def test_fetch_html_sends_browser_like_headers() -> None:
    http = FakeHttp([FakeResponse(text=SAMPLE_RACE_HTML)])
    adapter = _adapter(http)
    adapter.fetch_html(entry_url("2024-05-04", 1))
    headers = http.calls[0]["headers"]
    assert "Mozilla/5.0" in headers["User-Agent"]
    assert headers["Referer"].startswith("https://www.equibase.com")
    assert "text/html" in headers["Accept"]


def test_fetch_html_caches_to_disk_and_reuses_cache(tmp_path: Path) -> None:
    http = FakeHttp([FakeResponse(text=SAMPLE_RACE_HTML)])
    adapter = _adapter(http, cache_dir=tmp_path)
    url = entry_url("2024-05-04", 1)

    first = adapter.fetch_html(url)
    second = adapter.fetch_html(url)

    assert first == SAMPLE_RACE_HTML
    assert second == SAMPLE_RACE_HTML
    # Only one HTTP call — second call served from cache.
    assert len(http.calls) == 1
    cached_files = list(tmp_path.iterdir())
    assert len(cached_files) == 1


def test_fetch_html_does_not_cache_soft_404(tmp_path: Path) -> None:
    http = FakeHttp(
        [FakeResponse(text=SOFT_404_HTML), FakeResponse(text=SAMPLE_RACE_HTML)]
    )
    adapter = _adapter(http, cache_dir=tmp_path)
    url = entry_url("2024-05-04", 1)

    assert adapter.fetch_html(url) is None
    # Soft-404 should not have been cached, so the next call hits the network.
    assert adapter.fetch_html(url) == SAMPLE_RACE_HTML
    assert len(http.calls) == 2


# ---------- Rate limiting ----------


def test_rate_limit_sleeps_between_consecutive_fetches(monkeypatch) -> None:
    """Adapter must wait at least min_request_interval between live fetches."""
    sleeps: list[float] = []
    monkeypatch.setattr(equibase.time, "sleep", lambda s: sleeps.append(s))

    fake_now = [100.0]

    def fake_monotonic() -> float:
        return fake_now[0]

    monkeypatch.setattr(equibase.time, "monotonic", fake_monotonic)

    http = FakeHttp(
        [FakeResponse(text=SAMPLE_RACE_HTML), FakeResponse(text=SAMPLE_RACE_HTML)]
    )
    adapter = EquibaseAdapter(http_client=http, min_request_interval=3.0)

    adapter.fetch_html(entry_url("2024-05-04", 1))
    # Pretend only 0.5s has passed between calls.
    fake_now[0] = 100.5
    adapter.fetch_html(entry_url("2024-05-04", 2))

    # First fetch: no prior request, so no sleep.
    # Second fetch: must sleep ~2.5 to satisfy 3.0 interval.
    assert len(sleeps) == 1
    assert 2.4 <= sleeps[0] <= 3.0


def test_rate_limit_default_is_three_seconds() -> None:
    assert EquibaseAdapter().min_request_interval == 3.0


# ---------- Race discovery ----------


def test_discover_races_stops_at_first_miss() -> None:
    http = FakeHttp(
        [
            FakeResponse(text=SAMPLE_RACE_HTML),
            FakeResponse(text=SAMPLE_RACE_HTML),
            FakeResponse(text=SOFT_404_HTML),  # first miss → stop
        ]
    )
    adapter = _adapter(http)
    races = adapter.discover_races("2024-05-04", day="saturday")
    assert len(races) == 2
    assert [r.raceNumber for r in races] == [1, 2]
    # Adapter probed exactly until the miss; never tried race 4+.
    assert len(http.calls) == 3


def test_discover_races_respects_max_races_cap() -> None:
    # Always-200 responses; cap should bound exploration to max_races.
    http = FakeHttp([FakeResponse(text=SAMPLE_RACE_HTML) for _ in range(20)])
    adapter = _adapter(http)
    races = adapter.discover_races("2024-05-04", day="saturday", max_races=4)
    assert len(races) == 4
    assert len(http.calls) == 4


def test_discover_races_caps_at_default_fifteen() -> None:
    # Confirm the documented "scans up to 15" upper bound.
    http = FakeHttp([FakeResponse(text=SAMPLE_RACE_HTML) for _ in range(20)])
    adapter = _adapter(http)
    races = adapter.discover_races("2024-05-04", day="saturday")
    assert len(races) == 15


def test_fetch_race_returns_none_on_miss() -> None:
    http = FakeHttp([FakeResponse(text=SOFT_404_HTML)])
    adapter = _adapter(http)
    assert adapter.fetch_race("2024-05-04", 99, day="saturday") is None
