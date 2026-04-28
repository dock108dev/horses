"""SQLite odds-snapshot cache (per-day DB, WAL journal).

A single SQLite file per calendar day at ``{data_dir}/odds_{day}.db`` holds:

1. ``odds_snapshots`` — point-in-time per-horse odds for drift charts and
   stale-fallback "latest known odds" lookups.
2. ``card_snapshots`` — serialized :class:`Race` lists for stale-card
   fallback when the live source is unavailable.

The cache is opened in WAL mode with ``synchronous=NORMAL`` per
``odds-snapshot-storage-backend.md`` — durable enough for intra-day data,
~3× faster than the FULL sync default. Inserts are batched in a single
transaction so a 50-horse poll cycle commits in milliseconds rather than
the ~50 ms an autocommit loop would cost.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from api.model import Race

DEFAULT_DATA_DIR = Path("data")


@dataclass(frozen=True)
class OddsSnapshotRecord:
    """One row destined for ``odds_snapshots``.

    Columns mirror the SQLite schema (snake_case), separate from the
    wire-level :class:`api.model.OddsSnapshot` (camelCase) so the cache
    can be exercised independently of the serialization model.
    """

    race_id: str
    horse_id: str
    horse_name: str
    odds: str
    implied_probability: float
    source: str
    captured_at_ms: int


@dataclass(frozen=True)
class CachedCard:
    """A persisted card returned by :meth:`OddsCache.get_last_good_card`."""

    races: list[Race]
    captured_at_ms: int


class OddsCache:
    """Per-day SQLite cache for odds snapshots and serialized cards.

    Open with a day identifier (typically ``YYYY-MM-DD``) — this picks
    the file name. Reopening the same day reuses the existing DB so all
    prior-session data is queryable immediately.
    """

    def __init__(
        self,
        day: str,
        *,
        data_dir: Path | str | None = None,
    ) -> None:
        self.day = day
        self.data_dir = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / f"odds_{day}.db"
        # isolation_level=None → autocommit; transactions are managed
        # explicitly with BEGIN/COMMIT around the batched insert.
        self._conn = sqlite3.connect(str(self.path), isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS odds_snapshots (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                race_id             TEXT    NOT NULL,
                horse_id            TEXT    NOT NULL,
                horse_name          TEXT    NOT NULL,
                odds                TEXT    NOT NULL,
                implied_probability REAL    NOT NULL,
                source              TEXT    NOT NULL,
                captured_at_ms      INTEGER NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_odds_race_horse_time
                ON odds_snapshots (race_id, horse_id, captured_at_ms)
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS card_snapshots (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                day            TEXT    NOT NULL,
                card_json      TEXT    NOT NULL,
                captured_at_ms INTEGER NOT NULL,
                validated      INTEGER NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_card_day_time
                ON card_snapshots (day, captured_at_ms)
            """
        )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> OddsCache:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Odds snapshots
    # ------------------------------------------------------------------

    def store_odds_batch(self, snapshots: Iterable[OddsSnapshotRecord]) -> None:
        """Insert a batch of records inside a single transaction.

        Wrapping the batch in BEGIN/COMMIT is the single biggest
        performance lever for SQLite writes (~50× speedup vs autocommit
        per the storage research note).
        """
        rows = [
            (
                s.race_id,
                s.horse_id,
                s.horse_name,
                s.odds,
                s.implied_probability,
                s.source,
                s.captured_at_ms,
            )
            for s in snapshots
        ]
        if not rows:
            return
        cur = self._conn.cursor()
        cur.execute("BEGIN")
        try:
            cur.executemany(
                """
                INSERT INTO odds_snapshots
                    (race_id, horse_id, horse_name, odds,
                     implied_probability, source, captured_at_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            cur.execute("COMMIT")
        except Exception:
            # Roll back so a partial batch isn't visible, then re-raise
            # — never swallow. See finding F6.
            cur.execute("ROLLBACK")
            raise

    def get_latest_odds(self, race_id: str) -> list[OddsSnapshotRecord]:
        """Return the most recent snapshot per horse in ``race_id``.

        Uses the standard ``GROUP BY horse_id`` + ``MAX(captured_at_ms)``
        idiom joined back to the table to recover the full row. Order of
        the returned list is unspecified — callers that need ordering
        should sort by ``horse_name`` or post number themselves.
        """
        cur = self._conn.execute(
            """
            SELECT s.race_id, s.horse_id, s.horse_name, s.odds,
                   s.implied_probability, s.source, s.captured_at_ms
            FROM odds_snapshots AS s
            INNER JOIN (
                SELECT horse_id, MAX(captured_at_ms) AS latest
                FROM odds_snapshots
                WHERE race_id = ?
                GROUP BY horse_id
            ) AS m
              ON s.horse_id        = m.horse_id
             AND s.captured_at_ms  = m.latest
            WHERE s.race_id = ?
            """,
            (race_id, race_id),
        )
        return [
            OddsSnapshotRecord(
                race_id=row[0],
                horse_id=row[1],
                horse_name=row[2],
                odds=row[3],
                implied_probability=row[4],
                source=row[5],
                captured_at_ms=row[6],
            )
            for row in cur.fetchall()
        ]

    def get_drift_series(
        self, race_id: str, horse_id: str
    ) -> list[tuple[int, str, float]]:
        """Return ``(captured_at_ms, odds, implied_probability)`` rows in
        ascending time order for the drift chart.
        """
        cur = self._conn.execute(
            """
            SELECT captured_at_ms, odds, implied_probability
            FROM odds_snapshots
            WHERE race_id = ? AND horse_id = ?
            ORDER BY captured_at_ms ASC
            """,
            (race_id, horse_id),
        )
        return [(row[0], row[1], row[2]) for row in cur.fetchall()]

    # ------------------------------------------------------------------
    # Card snapshots
    # ------------------------------------------------------------------

    def store_card(
        self,
        day: str,
        races: list[Race],
        validated: bool,
        *,
        captured_at_ms: int | None = None,
    ) -> int:
        """Persist a serialized list of races for stale-fallback display.

        Returns the assigned ``captured_at_ms`` so callers can correlate
        what they just wrote with what they later read back. Pass an
        explicit ``captured_at_ms`` to keep tests deterministic.
        """
        ts = captured_at_ms if captured_at_ms is not None else int(time.time() * 1000)
        card_json = json.dumps([race.model_dump(mode="json") for race in races])
        self._conn.execute(
            """
            INSERT INTO card_snapshots (day, card_json, captured_at_ms, validated)
            VALUES (?, ?, ?, ?)
            """,
            (day, card_json, ts, 1 if validated else 0),
        )
        return ts

    def get_last_good_card(self, day: str) -> CachedCard | None:
        """Return the most recent ``validated=True`` card for ``day``.

        ``None`` if no validated card has ever been stored — callers
        should treat that as "no fallback available, surface the error".
        """
        cur = self._conn.execute(
            """
            SELECT card_json, captured_at_ms
            FROM card_snapshots
            WHERE day = ? AND validated = 1
            ORDER BY captured_at_ms DESC
            LIMIT 1
            """,
            (day,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        races = [Race.model_validate(d) for d in json.loads(row[0])]
        return CachedCard(races=races, captured_at_ms=row[1])


__all__ = [
    "DEFAULT_DATA_DIR",
    "CachedCard",
    "OddsCache",
    "OddsSnapshotRecord",
]
