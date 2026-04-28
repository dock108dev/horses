"""KentuckyDerby.com adapter for entries (no live odds).

KentuckyDerby.com is a JS-rendered marketing site whose live odds widget is
loaded asynchronously, so a plain HTML fetch will not see odds. Two static
data shapes do appear in the page HTML and are usable without a headless
browser:

1. A ``<script id="__NEXT_DATA__" type="application/json">`` block carrying
   the Next.js page state — when present, it usually exposes ``runners`` /
   ``entries`` arrays under ``props.pageProps``.
2. A schema.org ``SportsEvent`` JSON-LD block with a ``competitor`` array
   that lists entered horses by name.

The adapter prefers ``__NEXT_DATA__`` and falls back to JSON-LD competitors.
If neither yields a usable list, it returns an empty list rather than
raising — empty is a valid "no entries published yet" answer.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

_log = logging.getLogger(__name__)

SOURCE_NAME = "kentuckyderby"
DEFAULT_HORSES_URL = "https://www.kentuckyderby.com/horses"
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_NEXT_DATA_RE = re.compile(
    r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_JSONLD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_RUNNER_KEYS = ("runners", "entries", "horses", "starters", "fields")
_NAME_KEYS = ("horseName", "name", "horse", "title")


class _Response(Protocol):
    status_code: int
    text: str

    def raise_for_status(self) -> None: ...


class _HttpClient(Protocol):
    def get(
        self, url: str, *, headers: dict[str, str], timeout: float
    ) -> _Response: ...


def extract_next_data(html: str) -> dict[str, Any] | None:
    """Extract and parse the ``__NEXT_DATA__`` JSON blob; ``None`` if absent."""
    if not html:
        return None
    match = _NEXT_DATA_RE.search(html)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(1).strip())
    except (ValueError, json.JSONDecodeError):
        # Malformed __NEXT_DATA__ → caller falls back to JSON-LD; the
        # adapter is best-effort by design. See finding F10.
        return None
    return parsed if isinstance(parsed, dict) else None


def extract_jsonld_blocks(html: str) -> list[Any]:
    """Return parsed JSON-LD blocks from ``<script type="application/ld+json">``."""
    if not html:
        return []
    out: list[Any] = []
    for match in _JSONLD_RE.finditer(html):
        try:
            parsed = json.loads(match.group(1).strip())
        except (ValueError, json.JSONDecodeError):
            # Skip malformed JSON-LD blocks — sites often ship multiple
            # blocks and one bad apple shouldn't drop the rest. F10.
            continue
        out.append(parsed)
    return out


def _iter_jsonld_objects(blocks: Iterable[Any]) -> Iterable[dict[str, Any]]:
    for block in blocks:
        if isinstance(block, dict):
            yield block
            graph = block.get("@graph")
            if isinstance(graph, list):
                for item in graph:
                    if isinstance(item, dict):
                        yield item
        elif isinstance(block, list):
            for item in block:
                if isinstance(item, dict):
                    yield item


def jsonld_competitors(html: str) -> list[str]:
    """Pull horse names from the schema.org ``competitor`` array, if present."""
    out: list[str] = []
    for obj in _iter_jsonld_objects(extract_jsonld_blocks(html)):
        competitors = obj.get("competitor")
        if not isinstance(competitors, list):
            continue
        for entry in competitors:
            name: str | None = None
            if isinstance(entry, str):
                name = entry
            elif isinstance(entry, dict):
                raw = entry.get("name") or entry.get("@id")
                if isinstance(raw, str):
                    name = raw
            if name and name.strip():
                out.append(name.strip())
    return out


def _find_runner_list(node: Any, *, depth: int = 0) -> list[dict[str, Any]] | None:
    """Walk a Next.js page-state tree for the first list of runner-like dicts."""
    if depth > 8:
        return None
    if isinstance(node, dict):
        for key in _RUNNER_KEYS:
            value = node.get(key)
            candidate = _runner_list(value)
            if candidate is not None:
                return candidate
        for value in node.values():
            found = _find_runner_list(value, depth=depth + 1)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_runner_list(item, depth=depth + 1)
            if found is not None:
                return found
    return None


def _runner_list(value: Any) -> list[dict[str, Any]] | None:
    """Return ``value`` if it looks like a list of runner dicts, else None."""
    if not isinstance(value, list) or not value:
        return None
    if not all(isinstance(item, dict) for item in value):
        return None
    if not any(any(k in item for k in _NAME_KEYS) for item in value):
        return None
    return value  # type: ignore[return-value]


def _entry_name(entry: dict[str, Any]) -> str | None:
    for key in _NAME_KEYS:
        raw = entry.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def parse_entries(html: str) -> list[dict[str, Any]]:
    """Best-effort entry list from KentuckyDerby.com page HTML.

    Returns a list of dicts shaped like
    ``{"name", "post"?, "jockey"?, "trainer"?, "morningLineOdds"?}``. Falls
    back to JSON-LD competitor names (name-only) when ``__NEXT_DATA__`` is
    absent. Returns ``[]`` when neither shape contains usable entries.
    """
    next_data = extract_next_data(html)
    if next_data is not None:
        runners = _find_runner_list(next_data)
        if runners:
            out: list[dict[str, Any]] = []
            for runner in runners:
                name = _entry_name(runner)
                if not name:
                    continue
                entry: dict[str, Any] = {"name": name}
                post = runner.get("post") or runner.get("postPosition") or runner.get(
                    "programNumber"
                )
                if post is not None:
                    entry["post"] = post
                for src, dst in (
                    ("jockey", "jockey"),
                    ("trainer", "trainer"),
                    ("morningLineOdds", "morningLineOdds"),
                    ("ml", "morningLineOdds"),
                ):
                    val = runner.get(src)
                    if isinstance(val, str) and val.strip() and dst not in entry:
                        entry[dst] = val.strip()
                out.append(entry)
            if out:
                return out

    return [{"name": name} for name in jsonld_competitors(html)]


@dataclass
class KentuckyDerbyAdapter:
    """Fetches KentuckyDerby.com pages and extracts entry lists from HTML."""

    horses_url: str = DEFAULT_HORSES_URL
    http_client: Any = None
    user_agent: str = DEFAULT_USER_AGENT
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    _owns_client: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.http_client is None:
            self.http_client = httpx.Client()
            self._owns_client = True

    def __enter__(self) -> "KentuckyDerbyAdapter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        # Teardown path — close failures logged at debug, never raised.
        # See finding F2 in error-handling-report.
        if self._owns_client and self.http_client is not None:
            closer = getattr(self.http_client, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception as exc:
                    _log.debug("HTTP client close failed: %s", exc)
            self._owns_client = False

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def fetch_html(self, url: str | None = None) -> str:
        target = url or self.horses_url
        resp = self.http_client.get(
            target, headers=self._headers(), timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.text

    def fetch_entries(self, url: str | None = None) -> list[dict[str, Any]]:
        """Fetch the horses page and parse entries; ``[]`` when none found."""
        return parse_entries(self.fetch_html(url))


__all__ = [
    "DEFAULT_HORSES_URL",
    "SOURCE_NAME",
    "KentuckyDerbyAdapter",
    "extract_jsonld_blocks",
    "extract_next_data",
    "jsonld_competitors",
    "parse_entries",
]
