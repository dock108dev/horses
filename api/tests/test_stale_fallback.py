"""Stale-fallback redaction guarantees for ``POST /api/cards/{day}/refresh``.

The companion test in ``test_main.py`` proves the cache-fallback path
returns ``stale=True`` and the previously-validated card. This module
adds the assertion that test does not make: the second element of
``errors`` — produced by ``api.main._redact_exc`` — must have all URLs
and multi-segment absolute filesystem paths replaced with the literal
tokens ``<url>`` and ``<path>``, while preserving the exception class
name. See ``docs/audits/security-report.md`` finding S3.
"""

from __future__ import annotations

from pathlib import Path

from api.main import LIVE_SOURCE_ERROR, app
from api.model import Race
from api.tests.conftest import (
    FakeTwinSpires,
    _client_with_overrides,
    _full_card,
    _seed_cache,
)


class _RaisingEquibase:
    """Equibase stub that raises a caller-supplied ``RuntimeError`` message.

    The shared ``FakeEquibase(fail=True)`` always raises the literal
    ``"equibase boom"`` — this stub instead lets each test pin the exact
    exception text so the redaction regexes have something concrete to
    strip.
    """

    def __init__(self, message: str) -> None:
        self._message = message

    def fetch_race(
        self, iso_date: str, race_number: int, *, day: str
    ) -> Race | None:
        raise RuntimeError(self._message)


def _drive_failing_refresh(
    tmp_data_dir: Path, exc_message: str
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Seed Friday cache, drive a failing refresh, return ``(body, expected)``.

    ``expected`` is the JSON form of the seeded card so callers can assert
    the stale envelope replays exactly what was previously stored.
    """
    seeded = _full_card("friday")
    _seed_cache("friday", seeded, data_dir=tmp_data_dir)
    fake_eq = _RaisingEquibase(exc_message)
    fake_ts = FakeTwinSpires([])
    expected = [r.model_dump(mode="json") for r in seeded]
    for tc in _client_with_overrides(
        tmp_data_dir, equibase=fake_eq, twinspires=fake_ts
    ):
        try:
            resp = tc.post("/api/cards/friday/refresh")
            assert resp.status_code == 200
            body = resp.json()
        finally:
            app.dependency_overrides.clear()
    return body, expected


def _assert_stale_envelope(
    body: dict[str, object], expected_data: list[dict[str, object]]
) -> str:
    """Common envelope-shape assertions; returns the redacted error string."""
    assert body["stale"] is True
    assert body["source"] == "cache"
    assert body["cached_at"] is not None
    assert body["data"] == expected_data
    errors = body["errors"]
    assert isinstance(errors, list)
    assert len(errors) >= 2
    assert errors[0] == LIVE_SOURCE_ERROR
    redacted = errors[1]
    assert isinstance(redacted, str)
    # Class-name prefix from ``_redact_exc`` must survive both substitutions.
    assert redacted.startswith("RuntimeError: ")
    # No raw URL scheme should ever leak through to the response, regardless
    # of which message variant produced this envelope.
    assert "http://" not in redacted
    assert "https://" not in redacted
    return redacted


def test_stale_fallback_redacts_url_in_error_message(
    tmp_data_dir: Path,
) -> None:
    body, expected = _drive_failing_refresh(
        tmp_data_dir,
        "GET https://www.equibase.com/static/entry/CD050126R08-EQB.html failed",
    )
    redacted = _assert_stale_envelope(body, expected)
    assert "<url>" in redacted
    assert "equibase.com" not in redacted


def test_stale_fallback_redacts_filesystem_path_in_error_message(
    tmp_data_dir: Path,
) -> None:
    body, expected = _drive_failing_refresh(
        tmp_data_dir,
        "file /data/odds_2026-05-01.db not found",
    )
    redacted = _assert_stale_envelope(body, expected)
    assert "<path>" in redacted
    # The ``(?:/[^\s'"]+){2,}`` pattern must consume the whole path; no
    # prefix of the on-disk SQLite filename should survive.
    assert "/data/odds_" not in redacted
    assert "odds_2026-05-01.db" not in redacted
