"""TwinSpires React-SPA adapter for Churchill Downs program & live odds.

The page HTML returns no race data — entries and odds come from internal
XHR endpoints under ``/ts-res/api/racing``. The adapter seeds cookies via
a homepage GET, sends browser-like headers, throttles odds polls to a 30s
per-race floor, and auto-retries via ``curl_cffi`` when plain ``httpx``
gets 403'd. Scratches are detected by diffing successive program polls.

LOC note: ~526 LOC, over the 500-line guideline. Adapter construction,
JSON parsing, scratch diffing, the curl_cffi fallback wrapper, and HTTP
plumbing are tightly coupled to the same private state on
``TwinSpiresAdapter``. See ``docs/audits/cleanup-report.md`` "Files
still >500 LOC".
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date as _Date, datetime, timezone
from fractions import Fraction
from typing import Any

import httpx

from api.model import Day, Horse, Race

_log = logging.getLogger(__name__)

SOURCE_NAME = "twinspires"
DEFAULT_TRACK_CODE = "CD"
HOMEPAGE_URL = "https://www.twinspires.com/racing/"
API_BASE_URL = "https://www.twinspires.com/ts-res/api/racing"
DEFAULT_ODDS_INTERVAL_SECONDS = 30.0
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_IMPERSONATE = "chrome124"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_PROGRAM_DIGITS = re.compile(r"\d+")


@dataclass
class ScratchEvent:
    """A runner that transitioned from active to scratched between polls."""

    raceId: str
    programNumber: str
    horseName: str
    reason: str | None
    detectedAt: str


def _to_yyyymmdd(value: _Date | datetime | str) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, _Date):
        return value.strftime("%Y%m%d")
    cleaned = value.replace("-", "").strip()
    if len(cleaned) == 8 and cleaned.isdigit():
        return cleaned
    return datetime.strptime(value, "%Y-%m-%d").strftime("%Y%m%d")


def _to_iso_date(value: _Date | datetime | str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, _Date):
        return value.isoformat()
    if "-" in value and len(value) == 10:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    if len(value) == 8 and value.isdigit():
        return datetime.strptime(value, "%Y%m%d").date().isoformat()
    raise ValueError(f"unrecognized date string: {value!r}")


def program_url(
    date_in: _Date | datetime | str,
    race_number: int,
    *,
    track_code: str = DEFAULT_TRACK_CODE,
) -> str:
    """Build the TwinSpires program/entries XHR URL for a (track, date, race)."""
    if race_number < 1:
        raise ValueError("race_number must be >= 1")
    return (
        f"{API_BASE_URL}/program?track={track_code}"
        f"&date={_to_yyyymmdd(date_in)}&race={race_number}"
    )


def odds_url(
    date_in: _Date | datetime | str,
    race_number: int,
    *,
    track_code: str = DEFAULT_TRACK_CODE,
) -> str:
    """Build the TwinSpires live-odds XHR URL for a (track, date, race)."""
    if race_number < 1:
        raise ValueError("race_number must be >= 1")
    return (
        f"{API_BASE_URL}/odds?track={track_code}"
        f"&date={_to_yyyymmdd(date_in)}&race={race_number}"
    )


def to_fractional_odds(value: Any) -> str | None:
    """Normalize a TwinSpires win-odds value to fractional ``"num/den"`` form.

    Already-fractional inputs (``"5/1"``, ``"5-1"``) are returned with a ``/``
    separator. Decimal-to-1 inputs (``"4.80"``) go through Fraction with a
    denominator cap.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if "/" in s or "-" in s:
        return s.replace("-", "/")
    try:
        frac = Fraction(s).limit_denominator(50)
    except (ValueError, ZeroDivisionError, ArithmeticError):
        # Pass the original string through; odds_to_probability is the
        # canonical parser and will return None if it can't read it.
        # See finding F5.
        return s
    return f"{frac.numerator}/{frac.denominator}"


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def post_from_program_number(program_number: str) -> int | None:
    """Parse a program number like ``"1"`` or ``"1A"`` into a post int."""
    match = _PROGRAM_DIGITS.search(program_number)
    if not match:
        return None
    post = int(match.group(0))
    return post if post >= 1 else None


def _runner_index(runners: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index raw runner dicts by ``programNumber`` (string)."""
    return {
        str(r["programNumber"]): r
        for r in runners
        if isinstance(r, dict) and r.get("programNumber") is not None
    }


def _parse_program(
    data: dict[str, Any] | None,
    *,
    date_in: _Date | datetime | str,
    race_number: int,
    day: Day,
    track_code: str,
) -> Race | None:
    """Parse a TwinSpires program JSON payload into a :class:`Race`."""
    if not isinstance(data, dict):
        return None
    race_id = f"{track_code}-{_to_iso_date(date_in)}-R{race_number:02d}"
    horses: list[Horse] = []
    for runner in data.get("runners") or []:
        if not isinstance(runner, dict):
            continue
        pn_raw = runner.get("programNumber")
        if pn_raw is None:
            continue
        pn = str(pn_raw)
        post = post_from_program_number(pn)
        if post is None:
            continue
        name = (runner.get("horseName") or runner.get("name") or "").strip()
        if not name:
            continue
        horses.append(
            Horse(
                id=f"{race_id}-{pn}",
                raceId=race_id,
                post=post,
                name=name,
                jockey=(runner.get("jockey") or None),
                trainer=(runner.get("trainer") or None),
                morningLineOdds=runner.get("morningLineOdds") or None,
                scratched=bool(runner.get("scratched", False)),
                source=SOURCE_NAME,
            )
        )
    if not horses:
        return None
    return Race(
        id=race_id,
        day=day,
        track="Churchill Downs",
        raceNumber=race_number,
        postTime=data.get("postTime") or None,
        name=data.get("raceName") or None,
        surface=data.get("surface") or None,
        distance=data.get("distance") or None,
        horses=horses,
    )


def _parse_odds(data: dict[str, Any] | None) -> list[dict[str, str | None]]:
    """Parse a TwinSpires odds JSON payload into per-runner ``{programNumber, winOdds}``."""
    if not isinstance(data, dict):
        return []
    out: list[dict[str, str | None]] = []
    for runner in data.get("runners") or []:
        if not isinstance(runner, dict):
            continue
        pn = runner.get("programNumber")
        if pn is None:
            continue
        out.append(
            {
                "programNumber": str(pn),
                "winOdds": to_fractional_odds(runner.get("winOdds")),
            }
        )
    return out


@dataclass
class TwinSpiresAdapter:
    """Fetches TwinSpires program & live-odds JSON for Churchill Downs races.

    Inject ``http_client`` for tests. When the primary client returns 403 and
    a ``fallback_client`` is configured, the adapter swaps to it and re-seeds
    cookies before retrying — the curl_cffi auto-upgrade path.
    """

    track_code: str = DEFAULT_TRACK_CODE
    http_client: Any = None
    fallback_client: Any = None
    user_agent: str = DEFAULT_USER_AGENT
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    impersonate: str = DEFAULT_IMPERSONATE
    min_odds_interval: float = DEFAULT_ODDS_INTERVAL_SECONDS

    _session_seeded: bool = field(default=False, init=False, repr=False)
    _owns_http_client: bool = field(default=False, init=False, repr=False)
    _owns_fallback_client: bool = field(default=False, init=False, repr=False)
    _last_odds_at: dict[str, float] = field(
        default_factory=dict, init=False, repr=False
    )
    _last_runners: dict[str, dict[str, dict[str, Any]]] = field(
        default_factory=dict, init=False, repr=False
    )

    def __post_init__(self) -> None:
        if self.http_client is None:
            self.http_client = httpx.Client()
            self._owns_http_client = True
        if self.fallback_client is None:
            built = _build_curl_cffi_client(
                impersonate=self.impersonate, timeout=self.timeout
            )
            if built is not None:
                self.fallback_client = built
                self._owns_fallback_client = True

    def __enter__(self) -> "TwinSpiresAdapter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_http_client and self.http_client is not None:
            _safe_close(self.http_client)
            self._owns_http_client = False
        if self._owns_fallback_client and self.fallback_client is not None:
            _safe_close(self.fallback_client)
            self._owns_fallback_client = False

    # ---- public API --------------------------------------------------------

    def fetch_program(
        self,
        date_in: _Date | datetime | str,
        race_number: int,
        *,
        day: Day,
    ) -> Race | None:
        """Fetch and parse the program/entries JSON for one race."""
        url = program_url(date_in, race_number, track_code=self.track_code)
        data = self._get_json(url)
        return _parse_program(
            data,
            date_in=date_in,
            race_number=race_number,
            day=day,
            track_code=self.track_code,
        )

    def fetch_odds(
        self,
        date_in: _Date | datetime | str,
        race_number: int,
    ) -> list[dict[str, str | None]]:
        """Fetch live odds for one race; returns one entry per runner.

        Enforces a per-race ``min_odds_interval`` floor (default 30s).
        """
        race_key = self._race_key(date_in, race_number)
        self._wait_odds_floor(race_key)
        url = odds_url(date_in, race_number, track_code=self.track_code)
        try:
            data = self._get_json(url)
        finally:
            # Record the attempt timestamp even on failure so a flapping
            # source can't bypass the 30s floor by raising. F13.
            self._last_odds_at[race_key] = time.monotonic()
        return _parse_odds(data)

    def poll_program(
        self,
        date_in: _Date | datetime | str,
        race_number: int,
        *,
        day: Day,
    ) -> tuple[Race | None, list[ScratchEvent]]:
        """Fetch program JSON and emit scratch events vs. the prior poll.

        A scratch event is emitted whenever a runner present in the previous
        poll has ``scratched`` flip from ``false`` to ``true``.
        """
        url = program_url(date_in, race_number, track_code=self.track_code)
        data = self._get_json(url)
        race = _parse_program(
            data,
            date_in=date_in,
            race_number=race_number,
            day=day,
            track_code=self.track_code,
        )
        race_key = self._race_key(date_in, race_number)
        race_id = race.id if race is not None else _race_id(
            self.track_code, date_in, race_number
        )
        current_runners = (
            _runner_index(data.get("runners") or [])
            if isinstance(data, dict)
            else {}
        )
        previous = self._last_runners.get(race_key, {})
        events = _diff_scratches(previous, current_runners, race_id=race_id)
        self._last_runners[race_key] = current_runners
        return race, events

    # ---- HTTP helpers ------------------------------------------------------

    def _race_key(
        self, date_in: _Date | datetime | str, race_number: int
    ) -> str:
        return f"{self.track_code}|{_to_yyyymmdd(date_in)}|{race_number}"

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": HOMEPAGE_URL,
            "Origin": "https://www.twinspires.com",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

    def _seed_session(self) -> None:
        if self._session_seeded:
            return
        self.http_client.get(
            HOMEPAGE_URL, headers=self._headers(), timeout=self.timeout
        )
        self._session_seeded = True

    def _wait_odds_floor(self, race_key: str) -> None:
        last = self._last_odds_at.get(race_key)
        if last is None or self.min_odds_interval <= 0:
            return
        elapsed = time.monotonic() - last
        delay = self.min_odds_interval - elapsed
        if delay > 0:
            time.sleep(delay)

    def _swap_to_fallback(self) -> None:
        if self.fallback_client is None:
            raise RuntimeError(
                "TwinSpires returned 403 but no curl_cffi fallback is "
                "configured; install curl_cffi or inject fallback_client"
            )
        if self._owns_http_client:
            _safe_close(self.http_client)
        self.http_client = self.fallback_client
        self._owns_http_client = self._owns_fallback_client
        self.fallback_client = None
        self._owns_fallback_client = False
        self._session_seeded = False

    def _get_json(self, url: str) -> Any:
        self._seed_session()
        resp = self.http_client.get(
            url, headers=self._headers(), timeout=self.timeout
        )
        if getattr(resp, "status_code", 200) == 403 and self.fallback_client:
            self._swap_to_fallback()
            self._seed_session()
            resp = self.http_client.get(
                url, headers=self._headers(), timeout=self.timeout
            )
        # Treat 404 as "no payload yet" rather than an error: TwinSpires
        # returns 404 for races that have not been drawn / posted, and the
        # parsers already handle a None payload by returning an empty result.
        # See docs/audits/error-handling-report.md F33.
        if getattr(resp, "status_code", 200) == 404:
            return None
        resp.raise_for_status()
        return resp.json()


def _race_id(
    track_code: str,
    date_in: _Date | datetime | str,
    race_number: int,
) -> str:
    return f"{track_code}-{_to_iso_date(date_in)}-R{race_number:02d}"


def _diff_scratches(
    previous: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
    *,
    race_id: str,
) -> list[ScratchEvent]:
    events: list[ScratchEvent] = []
    detected_at = _now_iso_utc()
    for pn, runner in current.items():
        was_scratched = bool((previous.get(pn) or {}).get("scratched", False))
        is_scratched = bool(runner.get("scratched", False))
        if not was_scratched and is_scratched:
            events.append(
                ScratchEvent(
                    raceId=race_id,
                    programNumber=pn,
                    horseName=str(
                        runner.get("horseName") or runner.get("name") or ""
                    ),
                    reason=runner.get("scratch_reason")
                    or runner.get("scratchReason")
                    or None,
                    detectedAt=detected_at,
                )
            )
    return events


def _safe_close(client: Any) -> None:
    # Teardown path — close failures must not propagate (would mask the
    # real error from the request itself), but we log at debug so a
    # systemic resource leak is still observable. See finding F2.
    closer = getattr(client, "close", None)
    if callable(closer):
        try:
            closer()
        except Exception as exc:
            _log.debug("HTTP client close failed: %s", exc)


def _build_curl_cffi_client(*, impersonate: str, timeout: float) -> Any:
    """Construct a wrapped curl_cffi client, or ``None`` if unavailable."""
    try:
        from curl_cffi import requests as cf_requests  # type: ignore
    except ImportError:
        # curl_cffi is optional; without it the 403-fallback path is
        # disabled but the primary httpx client still works. F15.
        return None
    return _CurlCffiClient(
        session=cf_requests.Session(impersonate=impersonate),
        timeout=timeout,
    )


@dataclass
class _CurlCffiClient:
    """Thin wrapper that adapts a curl_cffi Session to the _HttpClient shape."""

    session: Any
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    def get(
        self, url: str, *, headers: dict[str, str], timeout: float
    ) -> Any:
        return self.session.get(url, headers=headers, timeout=timeout)

    def close(self) -> None:
        closer = getattr(self.session, "close", None)
        if callable(closer):
            closer()


__all__ = [
    "API_BASE_URL",
    "DEFAULT_ODDS_INTERVAL_SECONDS",
    "DEFAULT_TRACK_CODE",
    "HOMEPAGE_URL",
    "SOURCE_NAME",
    "ScratchEvent",
    "TwinSpiresAdapter",
    "odds_url",
    "post_from_program_number",
    "program_url",
    "to_fractional_odds",
]
