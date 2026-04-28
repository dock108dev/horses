"""Tests for the KentuckyDerby.com entries adapter."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from api.sources.kentuckyderby import (
    KentuckyDerbyAdapter,
    extract_jsonld_blocks,
    extract_next_data,
    jsonld_competitors,
    parse_entries,
)


def _next_data_html(data: dict[str, Any]) -> str:
    return (
        '<!DOCTYPE html><html><body>'
        '<script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(data)}"
        "</script></body></html>"
    )


def _jsonld_html(blocks: list[dict[str, Any]]) -> str:
    parts = [
        f'<script type="application/ld+json">{json.dumps(b)}</script>' for b in blocks
    ]
    return "<!DOCTYPE html><html><body>" + "".join(parts) + "</body></html>"


SAMPLE_RUNNERS = [
    {
        "programNumber": 1,
        "horseName": "Forever Young",
        "jockey": "R. Sakai",
        "trainer": "Y. Yahagi",
        "morningLineOdds": "5-1",
    },
    {
        "programNumber": 2,
        "horseName": "Sierra Leone",
        "jockey": "T. Gaffalione",
        "trainer": "C. Brown",
        "morningLineOdds": "3-1",
    },
]


# ---------- __NEXT_DATA__ extraction ----------


def test_extract_next_data_parses_json_blob() -> None:
    html = _next_data_html({"props": {"pageProps": {"foo": "bar"}}})
    parsed = extract_next_data(html)
    assert parsed == {"props": {"pageProps": {"foo": "bar"}}}


def test_extract_next_data_returns_none_when_absent() -> None:
    assert extract_next_data("<html><body><p>nothing</p></body></html>") is None
    assert extract_next_data("") is None


def test_extract_next_data_returns_none_on_invalid_json() -> None:
    html = (
        '<script id="__NEXT_DATA__" type="application/json">{not-json}</script>'
    )
    assert extract_next_data(html) is None


# ---------- JSON-LD helpers ----------


def test_extract_jsonld_blocks_returns_parsed_list() -> None:
    html = _jsonld_html(
        [{"@type": "SportsEvent", "name": "Kentucky Derby"}, {"@type": "Other"}]
    )
    blocks = extract_jsonld_blocks(html)
    assert len(blocks) == 2
    assert blocks[0]["@type"] == "SportsEvent"


def test_jsonld_competitors_extracts_string_and_object_names() -> None:
    html = _jsonld_html(
        [
            {
                "@type": "SportsEvent",
                "name": "Kentucky Derby",
                "competitor": [
                    {"@type": "Person", "name": "Forever Young"},
                    "Sierra Leone",
                    {"name": "Mystik Dan"},
                ],
            }
        ]
    )
    assert jsonld_competitors(html) == ["Forever Young", "Sierra Leone", "Mystik Dan"]


# ---------- parse_entries ----------


def test_parse_entries_uses_next_data_when_present() -> None:
    html = _next_data_html(
        {"props": {"pageProps": {"raceData": {"runners": SAMPLE_RUNNERS}}}}
    )
    entries = parse_entries(html)
    assert len(entries) == 2
    assert entries[0]["name"] == "Forever Young"
    assert entries[0]["jockey"] == "R. Sakai"
    assert entries[0]["trainer"] == "Y. Yahagi"
    assert entries[0]["morningLineOdds"] == "5-1"
    assert entries[0]["post"] == 1
    assert entries[1]["name"] == "Sierra Leone"


def test_parse_entries_falls_back_to_jsonld_competitors() -> None:
    html = _jsonld_html(
        [
            {
                "@type": "SportsEvent",
                "name": "Kentucky Derby",
                "competitor": [
                    {"name": "Forever Young"},
                    {"name": "Sierra Leone"},
                ],
            }
        ]
    )
    entries = parse_entries(html)
    assert entries == [{"name": "Forever Young"}, {"name": "Sierra Leone"}]


def test_parse_entries_returns_empty_list_when_no_data() -> None:
    html = "<!DOCTYPE html><html><body><p>nothing structured here</p></body></html>"
    assert parse_entries(html) == []


def test_parse_entries_returns_empty_when_next_data_has_no_runners() -> None:
    html = _next_data_html({"props": {"pageProps": {"copy": "marketing text"}}})
    assert parse_entries(html) == []


def test_parse_entries_finds_runners_under_alternative_keys() -> None:
    html = _next_data_html(
        {"props": {"pageProps": {"horseList": {"entries": SAMPLE_RUNNERS}}}}
    )
    entries = parse_entries(html)
    assert [e["name"] for e in entries] == ["Forever Young", "Sierra Leone"]


# ---------- Adapter HTTP behavior ----------


class FakeResponse:
    def __init__(self, *, status_code: int = 200, text: str = "") -> None:
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
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> FakeResponse:
        self.calls.append({"url": url, "headers": dict(headers), "timeout": timeout})
        return self._responses.pop(0)


def test_adapter_fetches_and_parses_entries() -> None:
    html = _next_data_html(
        {"props": {"pageProps": {"raceData": {"runners": SAMPLE_RUNNERS}}}}
    )
    http = FakeHttp([FakeResponse(text=html)])
    adapter = KentuckyDerbyAdapter(http_client=http)
    entries = adapter.fetch_entries()
    assert [e["name"] for e in entries] == ["Forever Young", "Sierra Leone"]
    assert http.calls[0]["url"].endswith("/horses")


def test_adapter_uses_browser_user_agent() -> None:
    html = "<html><body></body></html>"
    http = FakeHttp([FakeResponse(text=html)])
    adapter = KentuckyDerbyAdapter(http_client=http)
    adapter.fetch_entries()
    headers = http.calls[0]["headers"]
    assert "Mozilla/5.0" in headers["User-Agent"]
    assert "text/html" in headers["Accept"]


def test_adapter_returns_empty_when_page_is_unstructured() -> None:
    http = FakeHttp([FakeResponse(text="<html><body>marketing</body></html>")])
    adapter = KentuckyDerbyAdapter(http_client=http)
    assert adapter.fetch_entries() == []


def test_adapter_propagates_http_errors() -> None:
    http = FakeHttp([FakeResponse(status_code=500, text="server error")])
    adapter = KentuckyDerbyAdapter(http_client=http)
    with pytest.raises(httpx.HTTPStatusError):
        adapter.fetch_entries()
