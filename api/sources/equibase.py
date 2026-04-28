"""Equibase static-HTML adapter for Churchill Downs race cards.

Equibase has no public API, so we scrape the static entry pages at
``/static/entry/{TRACK}{MMDDYY}R{NN}-EQB.html`` and parse race headers,
entries, morning-line odds, and scratched horses with BeautifulSoup.

Soft-404 protection (Equibase returns HTTP 200 with a "No data found"
body for unknown races), browser-like headers, a 3-second rate-limit
floor, and an on-disk cache for stable entry pages are all built in.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date as _Date, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx
from bs4 import BeautifulSoup, Tag

from api.model import Day, Horse, Race

SOURCE_NAME = "equibase"
DEFAULT_TRACK_CODE = "CD"  # Churchill Downs
BASE_URL = "https://www.equibase.com"
MIN_REQUEST_INTERVAL_SECONDS = 3.0
DEFAULT_MAX_RACES = 15
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_SOFT_404_MARKERS = ("no data found", "no data is available", "no entries available")
_COUNTRY_SUFFIX_RE = re.compile(r"\s*\(([A-Z]{2,4})\)\s*$")
_RACE_NUMBER_RE = re.compile(r"\bRace\s+(\d+)\b", re.IGNORECASE)
_DISTANCE_RE = re.compile(
    r"(\d+(?:[\s\xa0]?\d/\d)?\s*[¼-¾⅐-⅞]?\s*"
    r"(?:Furlongs?|Miles?|Yards?))",
    re.IGNORECASE,
)
_POST_TIME_RE = re.compile(
    r"Post\s*Time[:\s]*([0-9][0-9:apmAPM\.\s]+(?:E[TDS]T?|EDT|EST|ET))",
    re.IGNORECASE,
)
_SCRATCH_TEXTS = {"scr", "scratch", "scratched"}


class _Response(Protocol):
    status_code: int
    text: str

    def raise_for_status(self) -> None: ...


class _HttpGetter(Protocol):
    def get(
        self, url: str, *, headers: dict[str, str], timeout: float
    ) -> _Response: ...


def _to_date(value: _Date | datetime | str) -> _Date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, _Date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def entry_url(
    date_in: _Date | datetime | str,
    race_number: int,
    *,
    track_code: str = DEFAULT_TRACK_CODE,
) -> str:
    """Build the Equibase static entry URL for a (track, date, race)."""
    if race_number < 1:
        raise ValueError("race_number must be >= 1")
    mmddyy = _to_date(date_in).strftime("%m%d%y")
    return f"{BASE_URL}/static/entry/{track_code}{mmddyy}R{race_number:02d}-EQB.html"


def card_url(
    date_in: _Date | datetime | str,
    *,
    track_code: str = DEFAULT_TRACK_CODE,
) -> str:
    """Build the Equibase static full-card URL for a (track, date)."""
    mmddyy = _to_date(date_in).strftime("%m%d%y")
    return f"{BASE_URL}/static/card/{track_code}{mmddyy}-EQB.html"


def strip_country_suffix(name: str) -> str:
    """Drop trailing country-of-origin marker like '(IRE)' from a horse name."""
    return _COUNTRY_SUFFIX_RE.sub("", name).strip()


def is_soft_404(html: str | None) -> bool:
    """Equibase returns HTTP 200 with a "no data" body for unknown races."""
    if not html or not html.strip():
        return True
    blob = html.lower()
    return any(marker in blob for marker in _SOFT_404_MARKERS)


@dataclass
class EquibaseAdapter:
    """Fetches Equibase static-HTML entry pages and parses them into models.

    Pass ``cache_dir`` to persist fetched HTML to disk (entry pages are stable
    after the morning scratch window). Inject ``http_client`` to swap the
    transport in tests. The adapter enforces ``min_request_interval`` between
    consecutive live HTTP calls; cache hits are exempt.
    """

    track_code: str = DEFAULT_TRACK_CODE
    cache_dir: Path | None = None
    http_client: Any = None
    min_request_interval: float = MIN_REQUEST_INTERVAL_SECONDS
    user_agent: str = DEFAULT_USER_AGENT
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    _last_fetch_at: float = field(default=0.0, init=False, repr=False)
    _owns_client: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.cache_dir is not None:
            self.cache_dir = Path(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        if self.http_client is None:
            self.http_client = httpx.Client()
            self._owns_client = True

    def __enter__(self) -> "EquibaseAdapter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client and self.http_client is not None:
            self.http_client.close()
            self._owns_client = False

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"{BASE_URL}/",
        }

    def _cache_path(self, url: str) -> Path | None:
        if self.cache_dir is None:
            return None
        basename = url.rsplit("/", 1)[-1] or "index.html"
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", basename)
        return self.cache_dir / safe

    def _read_cache(self, url: str) -> str | None:
        path = self._cache_path(url)
        if path is not None and path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def _write_cache(self, url: str, html: str) -> None:
        path = self._cache_path(url)
        if path is not None:
            path.write_text(html, encoding="utf-8")

    def _wait_rate_limit(self) -> None:
        if self._last_fetch_at <= 0.0:
            return
        elapsed = time.monotonic() - self._last_fetch_at
        delay = self.min_request_interval - elapsed
        if delay > 0:
            time.sleep(delay)

    def fetch_html(self, url: str, *, use_cache: bool = True) -> str | None:
        """Fetch ``url`` with disk cache + rate limiting.

        Returns the HTML body, or ``None`` for HTTP 404 / soft-404. Other HTTP
        errors propagate via ``raise_for_status``.
        """
        if use_cache:
            cached = self._read_cache(url)
            if cached is not None:
                return None if is_soft_404(cached) else cached

        self._wait_rate_limit()
        try:
            resp = self.http_client.get(
                url, headers=self._headers(), timeout=self.timeout
            )
        finally:
            # Record the attempt even on failure so a flaking server
            # can't bypass the 3s floor by raising. F14.
            self._last_fetch_at = time.monotonic()

        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        html = resp.text
        if is_soft_404(html):
            return None
        if use_cache:
            self._write_cache(url, html)
        return html

    def fetch_race(
        self,
        date_in: _Date | datetime | str,
        race_number: int,
        *,
        day: Day,
    ) -> Race | None:
        """Fetch and parse one race; ``None`` if the race does not exist."""
        url = entry_url(date_in, race_number, track_code=self.track_code)
        html = self.fetch_html(url)
        if html is None:
            return None
        return parse_race_html(
            html,
            date_in=date_in,
            race_number=race_number,
            day=day,
            track_code=self.track_code,
        )

    def discover_races(
        self,
        date_in: _Date | datetime | str,
        *,
        day: Day,
        max_races: int = DEFAULT_MAX_RACES,
    ) -> list[Race]:
        """Probe sequential race numbers; stop at the first 404 / soft-404."""
        out: list[Race] = []
        for race_number in range(1, max_races + 1):
            race = self.fetch_race(date_in, race_number, day=day)
            if race is None:
                break
            out.append(race)
        return out


def parse_race_html(
    html: str,
    *,
    date_in: _Date | datetime | str,
    race_number: int,
    day: Day,
    track_code: str = DEFAULT_TRACK_CODE,
) -> Race | None:
    """Parse an Equibase entry HTML page into a `Race` (or ``None``)."""
    if html is None or is_soft_404(html):
        return None
    soup = BeautifulSoup(html, "html.parser")

    iso_date = _to_date(date_in).isoformat()
    race_id = f"{track_code}-{iso_date}-R{race_number:02d}"

    table = _find_entries_table(soup)
    if table is None:
        return None
    horses = _parse_entries(table, race_id=race_id)
    if not horses:
        return None

    header_text = _extract_header_text(soup)
    return Race(
        id=race_id,
        day=day,
        track="Churchill Downs",
        raceNumber=race_number,
        postTime=_parse_post_time(soup),
        name=_parse_race_name(header_text),
        surface=_parse_surface(soup, header_text),
        distance=_parse_distance(header_text),
        horses=horses,
    )


def _extract_header_text(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(" ", strip=True)
    for sel in (".race-info", ".raceHeader", ".race-header"):
        node = soup.select_one(sel)
        if node:
            return " ".join(node.stripped_strings)
    return ""


def _parse_distance(text: str) -> str | None:
    if not text:
        return None
    match = _DISTANCE_RE.search(text)
    return match.group(1).strip() if match else None


def _parse_surface(soup: BeautifulSoup, header_text: str) -> str | None:
    candidates = [header_text]
    for sel in (".surface", ".race-surface"):
        node = soup.select_one(sel)
        if node:
            candidates.append(node.get_text(" ", strip=True))
    candidates.append(soup.get_text(" ", strip=True))
    blob = " ".join(candidates).lower()
    for surface in ("all weather", "synthetic", "tapeta", "polytrack", "turf", "dirt"):
        if surface in blob:
            return surface.title()
    return None


def _parse_race_name(text: str) -> str | None:
    """Pull the most-likely race name out of a header like
    "Race 12 - The Kentucky Derby - 1 1/4 Miles"."""
    if not text:
        return None
    for raw_chunk in re.split(r"[-|·]", text):
        chunk = raw_chunk.strip()
        if not chunk:
            continue
        if _RACE_NUMBER_RE.match(chunk):
            continue
        if _DISTANCE_RE.match(chunk):
            continue
        lowered = chunk.lower()
        if "post time" in lowered or "purse" in lowered:
            continue
        return chunk
    return None


def _parse_post_time(soup: BeautifulSoup) -> str | None:
    text = soup.get_text(" ", strip=True)
    match = _POST_TIME_RE.search(text)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _find_entries_table(soup: BeautifulSoup) -> Tag | None:
    for sel in (
        "table.entries-table",
        "table.entries",
        "table#entries",
        "table.entry-table",
    ):
        table = soup.select_one(sel)
        if table:
            return table
    for table in soup.find_all("table"):
        headers = _table_header_cells(table)
        if not headers:
            continue
        joined = " | ".join(headers)
        has_post = any(h in headers for h in ("pp", "post", "post position", "#"))
        if has_post and "horse" in joined and "jockey" in joined:
            return table
    return None


def _table_header_cells(table: Tag) -> list[str]:
    head_row: Tag | None = None
    thead = table.find("thead")
    if isinstance(thead, Tag):
        head_row = thead.find("tr")
    if head_row is None:
        head_row = table.find("tr")
    if head_row is None:
        return []
    return [c.get_text(" ", strip=True).lower() for c in head_row.find_all(["th", "td"])]


def _column_index(headers: list[str], *aliases: str) -> int | None:
    for i, header in enumerate(headers):
        if header in aliases:
            return i
    return None


def _cell(cells: list[str], index: int | None) -> str | None:
    if index is None or index >= len(cells):
        return None
    value = cells[index].strip()
    return value or None


def _detect_scratched(row: Tag, cell_texts: list[str]) -> bool:
    if row.find(["s", "strike", "del"]):
        return True
    classes = " ".join(row.get("class") or []).lower()
    if "scratch" in classes:
        return True
    style = (row.get("style") or "").lower()
    if "line-through" in style:
        return True
    return any(text.strip().lower() in _SCRATCH_TEXTS for text in cell_texts)


def _parse_entries(table: Tag, *, race_id: str) -> list[Horse]:
    headers = _table_header_cells(table)
    if not headers:
        return []

    pp_idx = _column_index(headers, "pp", "post", "post position", "#")
    horse_idx = _column_index(headers, "horse", "horse name", "name")
    if pp_idx is None or horse_idx is None:
        return []
    jockey_idx = _column_index(headers, "jockey")
    trainer_idx = _column_index(headers, "trainer")
    ml_idx = _column_index(headers, "ml", "morning line", "m/l", "ml odds")
    med_idx = _column_index(headers, "medications", "med", "meds")

    body = table.find("tbody")
    if isinstance(body, Tag):
        body_rows: Iterable[Tag] = body.find_all("tr")
    else:
        body_rows = table.find_all("tr")[1:]

    horses: list[Horse] = []
    for row in body_rows:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        cell_texts = [c.get_text(" ", strip=True) for c in cells]

        post_raw = cell_texts[pp_idx] if pp_idx < len(cell_texts) else ""
        digits = re.sub(r"\D", "", post_raw)
        if not digits:
            continue
        post = int(digits)
        if post < 1:
            continue

        name_raw = cell_texts[horse_idx] if horse_idx < len(cell_texts) else ""
        if not name_raw.strip():
            continue
        name = strip_country_suffix(name_raw) or name_raw.strip()

        meds = _cell(cell_texts, med_idx)
        flags: list[str] = []
        if meds and meds.upper() not in {"-", "—"}:
            flags.append(f"meds:{meds}")

        horses.append(
            Horse(
                id=f"{race_id}-p{post:02d}",
                raceId=race_id,
                post=post,
                name=name,
                jockey=_cell(cell_texts, jockey_idx),
                trainer=_cell(cell_texts, trainer_idx),
                morningLineOdds=_cell(cell_texts, ml_idx),
                scratched=_detect_scratched(row, cell_texts),
                source=SOURCE_NAME,
                flags=flags,
            )
        )
    return horses


__all__ = [
    "BASE_URL",
    "DEFAULT_TRACK_CODE",
    "MIN_REQUEST_INTERVAL_SECONDS",
    "SOURCE_NAME",
    "EquibaseAdapter",
    "card_url",
    "entry_url",
    "is_soft_404",
    "parse_race_html",
    "strip_country_suffix",
]
