"""Pick 5 leg-sequence resolution for Churchill Downs Derby week.

Three-tier strategy:

1. **Hardcoded** year-keyed constants (primary). Five years of historical
   evidence show Oaks-day (Friday) Pick 5 = races 8-12 and Derby-day
   (Saturday) Pick 5 = races 9-13 at Churchill Downs. Verified annually.
2. **Equibase full-card scrape** (verification override). The first race
   whose wager menu lists "Pick 5" is the first leg. A sanity floor of
   ``MIN_FIRST_LEG = 7`` filters out an early Pick 5 if Churchill ever
   adds one. Scraped value that differs from the hardcoded constant
   logs a warning and is returned (assume Churchill changed the program).
3. **Last-5-races heuristic** (last resort). When ``total_races`` is
   known, return the final five races of the day.

``get_pick5_legs`` is the entry point and never raises — every code path
returns a list of exactly five integers.
"""

from __future__ import annotations

import logging
import re
from datetime import date as _Date, datetime
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup

from api.model import PICK5_LEG_COUNT

if TYPE_CHECKING:
    from api.sources.equibase import EquibaseAdapter

_log = logging.getLogger(__name__)

# (year, day) -> Pick 5 race numbers. Day is the canonical Day literal
# ("friday" = Oaks, "saturday" = Derby). 2024/2025 verified from research;
# 2026 mirrors the same 5-year-stable pattern.
PICK5_SEQUENCES: dict[tuple[int, str], list[int]] = {
    (2024, "friday"): [8, 9, 10, 11, 12],
    (2024, "saturday"): [9, 10, 11, 12, 13],
    (2025, "friday"): [8, 9, 10, 11, 12],
    (2025, "saturday"): [9, 10, 11, 12, 13],
    (2026, "friday"): [8, 9, 10, 11, 12],
    (2026, "saturday"): [9, 10, 11, 12, 13],
}

# Defaults used when the (year, day) pair is unknown and no scrape /
# total_races is available. Mirror the long-standing Churchill pattern.
_DEFAULT_BY_DAY: dict[str, list[int]] = {
    "friday": [8, 9, 10, 11, 12],
    "saturday": [9, 10, 11, 12, 13],
}
_FALLBACK_LEGS: list[int] = [9, 10, 11, 12, 13]

# Churchill Downs runs both an early Pick 5 (races ~1-5) and the featured
# late Pick 5 (races 8-12 Friday / 9-13 Saturday). This app targets only
# the late pool. Any scraped first-leg below MIN_FIRST_LEG is the early
# pool — discard it so we always resolve to the late sequence.
MIN_FIRST_LEG = 7

_RACE_HEADER_SPLIT_RE = re.compile(r"(?im)^\s*Race\s+(\d+)\b")
_PICK5_RE = re.compile(r"\bpick\s*5\b", re.IGNORECASE)


def pick5_legs_heuristic(total_races: int) -> list[int]:
    """Return the final five race numbers of a card.

    Used as a last-resort fallback. For Churchill Derby/Oaks days, this
    matches the historical sequence whenever the card has exactly 13
    races. Cards with fewer than 5 races fall through to a 1..5 range
    so the function still returns five integers.
    """
    if total_races < PICK5_LEG_COUNT:
        return list(range(1, PICK5_LEG_COUNT + 1))
    return list(range(total_races - 4, total_races + 1))


def parse_pick5_first_leg(card_html: str | None) -> int | None:
    """Find the first race whose wager menu lists "Pick 5".

    Returns ``None`` if no race block can be associated with a Pick 5
    wager (or the HTML is empty/malformed). Tries two strategies:

    1. Elements carrying a ``data-race`` attribute whose subtree mentions
       "Pick 5".
    2. Plain-text segmentation by "Race N" headers, checking each
       segment for a "Pick 5" mention.

    The lowest matching race number wins.
    """
    if not card_html:
        return None
    # html.parser tolerates malformed input (no exceptions on garbage),
    # so we don't wrap this in try/except — see error-handling-report
    # finding F1.
    soup = BeautifulSoup(card_html, "html.parser")

    candidates: list[int] = []

    for node in soup.find_all(attrs={"data-race": True}):
        try:
            race_num = int(str(node.get("data-race")).strip())
        except (TypeError, ValueError):
            # Non-numeric data-race attribute → skip this block. F12.
            continue
        if race_num < 1:
            continue
        if _PICK5_RE.search(node.get_text(" ", strip=True)):
            candidates.append(race_num)

    if not candidates:
        text = soup.get_text("\n", strip=True)
        parts = _RACE_HEADER_SPLIT_RE.split(text)
        # parts = [pre, num1, body1, num2, body2, ...]
        for i in range(1, len(parts) - 1, 2):
            try:
                race_num = int(parts[i])
            except (TypeError, ValueError):
                continue
            if race_num < 1:
                continue
            if _PICK5_RE.search(parts[i + 1] or ""):
                candidates.append(race_num)

    return min(candidates) if candidates else None


def _scrape_first_leg(
    adapter: "EquibaseAdapter",
    race_date: _Date | datetime | str,
) -> int | None:
    """Fetch the Equibase full-card HTML and locate the Pick 5 first leg."""
    from api.sources.equibase import card_url  # local import avoids cycle

    url = card_url(race_date, track_code=adapter.track_code)
    html = adapter.fetch_html(url)
    return parse_pick5_first_leg(html)


def get_pick5_legs(
    year: int,
    day: str,
    *,
    adapter: "EquibaseAdapter | None" = None,
    race_date: _Date | datetime | str | None = None,
    total_races: int | None = None,
) -> list[int]:
    """Resolve the five Pick 5 race numbers for a Churchill Derby-week day.

    Tier 1 (hardcoded), Tier 2 (Equibase scrape if ``adapter`` provided),
    Tier 3 (last-5-of-card heuristic if ``total_races`` provided). Always
    returns a list of exactly five integers; never raises.

    ``day`` is "friday" (Oaks) or "saturday" (Derby).
    """
    normalized_day = (day or "").strip().lower()
    hardcoded = PICK5_SEQUENCES.get((year, normalized_day))

    scraped: list[int] | None = None
    if adapter is not None and race_date is not None:
        try:
            first = _scrape_first_leg(adapter, race_date)
        except Exception as exc:
            # Tier-2 verification must never raise — Tier 1 (hardcoded)
            # is authoritative. See finding F9.
            _log.warning("Pick 5 scrape failed: %s", exc)
            first = None
        if first is not None:
            if first >= MIN_FIRST_LEG:
                scraped = list(range(first, first + PICK5_LEG_COUNT))
            else:
                _log.warning(
                    "Ignoring Pick 5 scrape: first leg %d below sanity floor %d",
                    first,
                    MIN_FIRST_LEG,
                )

    if scraped is not None:
        if hardcoded is not None and scraped != hardcoded:
            _log.warning(
                "Pick 5 mismatch: hardcoded=%s scraped=%s; using scraped",
                hardcoded,
                scraped,
            )
        return scraped

    if hardcoded is not None:
        return list(hardcoded)

    if total_races is not None:
        return pick5_legs_heuristic(total_races)

    if normalized_day in _DEFAULT_BY_DAY:
        return list(_DEFAULT_BY_DAY[normalized_day])
    return list(_FALLBACK_LEGS)


__all__ = [
    "MIN_FIRST_LEG",
    "PICK5_SEQUENCES",
    "get_pick5_legs",
    "parse_pick5_first_leg",
    "pick5_legs_heuristic",
]
