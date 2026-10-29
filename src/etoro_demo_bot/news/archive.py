"""Append-only local snapshots/revisions; queries use first observation, never hindsight."""

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from ..strategy.models import EarningsWindow
from .events import FilingEvent, NewsError, parse_atom, raw_checksum, timestamp


def _payload(event: FilingEvent) -> str:
    data = asdict(event)
    data.pop("observed_at")
    return json.dumps(
        data,
        default=lambda value: value.isoformat(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


class NewsArchive:
    def __init__(self, path: Path) -> None:
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            # Fail closed before any schema write when an owner points at another database.
            db.execute("BEGIN IMMEDIATE")
            objects = db.execute(
                "SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchall()
            expected = {"feed_snapshots", "filing_revisions", "filing_observations"}
            if objects and (
                {name for name, _ in objects} != expected
                or any(kind != "table" for _, kind in objects)
            ):
                raise NewsError("UNRELATED_OR_INCOMPLETE_ARCHIVE_SCHEMA")
            statements = (
                "CREATE TABLE IF NOT EXISTS feed_snapshots("
                "sequence INTEGER PRIMARY KEY, source TEXT NOT NULL, observed TEXT NOT NULL, "
                "sha256 TEXT NOT NULL, raw BLOB NOT NULL)",
                "CREATE TABLE IF NOT EXISTS filing_revisions("
                "sequence INTEGER PRIMARY KEY, source TEXT NOT NULL, identity TEXT NOT NULL, "
                "observed TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(source,identity,payload))",
                "CREATE TABLE IF NOT EXISTS filing_observations("
                "sequence INTEGER PRIMARY KEY, source TEXT NOT NULL, identity TEXT NOT NULL, "
                "observed TEXT NOT NULL, payload TEXT NOT NULL)",
            )
            for statement in statements:
                db.execute(statement)

    def ingest(self, raw: bytes, *, source: str, observed_at: datetime) -> int:
        events = parse_atom(raw, source=source, observed_at=observed_at)
        observed = timestamp(observed_at.isoformat()).isoformat()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            latest = db.execute("SELECT MAX(observed) FROM feed_snapshots").fetchone()[0]
            if latest is not None and observed < latest:
                raise NewsError("OBSERVATION_CLOCK_ROLLBACK")
            db.execute(
                "INSERT INTO feed_snapshots(source,observed,sha256,raw) VALUES(?,?,?,?)",
                (source, observed, raw_checksum(raw), raw),
            )
            inserted = 0
            for event in events:
                cursor = db.execute(
                    "INSERT OR IGNORE INTO filing_revisions(source,identity,observed,payload) "
                    "VALUES(?,?,?,?)",
                    (source, event.source_id, observed, _payload(event)),
                )
                inserted += cursor.rowcount
                db.execute(
                    "INSERT INTO filing_observations(source,identity,observed,payload) "
                    "VALUES(?,?,?,?)",
                    (source, event.source_id, observed, _payload(event)),
                )
        return inserted

    def facts(self, *, as_of: datetime) -> tuple[dict[str, Any], ...]:
        """Latest actually observed revision per source/id at the supplied instant."""
        stamp = timestamp(as_of.isoformat()).isoformat()
        with closing(sqlite3.connect(self.path)) as db, db:
            rows = db.execute(
                "SELECT source,identity,observed,payload FROM filing_observations "
                "WHERE observed<=? "
                "ORDER BY sequence",
                (stamp,),
            ).fetchall()
        latest = {}
        for source, identity, observed, payload in rows:
            data = json.loads(payload)
            data["source_feed"] = source
            data["observed_at"] = observed
            latest[(source, identity)] = data
        return tuple(latest[key] for key in sorted(latest))

    def window(self, instrument_id: int, *, as_of: datetime) -> EarningsWindow:
        """Protocol-compatible unknown calendar: filings are not scheduled announcements."""
        if type(instrument_id) is not int or instrument_id <= 0:
            raise NewsError("INVALID_INSTRUMENT")
        stamp = timestamp(as_of.isoformat())
        return EarningsWindow(
            instrument_id,
            stamp,
            stamp,
            stamp,
            (),
            "SEC_ATOM_NOT_AN_EARNINGS_CALENDAR",
            complete=False,
        )
