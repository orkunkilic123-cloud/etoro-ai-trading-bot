"""Local snapshot/revision storage and bounded, read-only point-in-time evidence views."""

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..strategy.models import EarningsWindow
from .events import FilingEvent, NewsError, parse_atom, raw_checksum, timestamp

MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_ROWS = 20000
_SCHEMA = {
    "feed_snapshots": (
        ("sequence", "INTEGER", 0, 1),
        ("source", "TEXT", 1, 0),
        ("observed", "TEXT", 1, 0),
        ("sha256", "TEXT", 1, 0),
        ("raw", "BLOB", 1, 0),
    ),
    "filing_revisions": (
        ("sequence", "INTEGER", 0, 1),
        ("source", "TEXT", 1, 0),
        ("identity", "TEXT", 1, 0),
        ("observed", "TEXT", 1, 0),
        ("payload", "TEXT", 1, 0),
    ),
    "filing_observations": (
        ("sequence", "INTEGER", 0, 1),
        ("source", "TEXT", 1, 0),
        ("identity", "TEXT", 1, 0),
        ("observed", "TEXT", 1, 0),
        ("payload", "TEXT", 1, 0),
    ),
}


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


def _schema(db: sqlite3.Connection, *, allow_empty: bool = False) -> None:
    objects = db.execute(
        "SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
    ).fetchall()
    if not objects and allow_empty:
        return
    if {name for name, _ in objects} != set(_SCHEMA) or any(t != "table" for _, t in objects):
        raise NewsError("UNRELATED_OR_INCOMPLETE_ARCHIVE_SCHEMA")
    for table, expected in _SCHEMA.items():
        rows = db.execute(f"PRAGMA table_info({table})").fetchall()
        if tuple((r[1], r[2], r[3], r[5]) for r in rows) != expected or any(r[4] for r in rows):
            raise NewsError("INVALID_ARCHIVE_COLUMNS")
    indexes = db.execute("PRAGMA index_list(filing_revisions)").fetchall()
    if len(indexes) != 1 or indexes[0][2] != 1 or indexes[0][3] != "u":
        raise NewsError("INVALID_ARCHIVE_UNIQUENESS")
    # Name is the SQLite-generated uniqueness index; never interpolate arbitrary input.
    columns = db.execute("PRAGMA index_info(sqlite_autoindex_filing_revisions_1)").fetchall()
    if tuple(r[2] for r in columns) != ("source", "identity", "payload"):
        raise NewsError("INVALID_ARCHIVE_UNIQUENESS")


def _connect(path: Path, mode: str) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=" + mode, uri=True)


def _history(
    db: sqlite3.Connection, as_of: datetime
) -> tuple[tuple[dict[str, Any], ...], datetime | None]:
    """Rebuild facts from bounded raw snapshots and verify both derived tables."""
    _schema(db)
    sizes = db.execute(
        "SELECT count(*),COALESCE(sum(length(raw)),0) FROM feed_snapshots"
    ).fetchone()
    if sizes[0] > 1000 or sizes[1] > MAX_ARCHIVE_BYTES:
        raise NewsError("ARCHIVE_REVIEW_BUDGET_EXCEEDED")
    for table in ("filing_observations", "filing_revisions"):
        if db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] > MAX_ARCHIVE_ROWS:
            raise NewsError("ARCHIVE_REVIEW_BUDGET_EXCEEDED")
    snapshots = db.execute(
        "SELECT source,observed,sha256,raw FROM feed_snapshots ORDER BY sequence"
    ).fetchall()
    observations: list[tuple[str, str, str, str]] = []
    revisions: dict[tuple[str, str, str], tuple[str, str, str, str]] = {}
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    through = None
    previous = None
    for source, observed, checksum, raw in snapshots:
        at = timestamp(observed)
        if observed != at.isoformat() or (previous is not None and at < previous):
            raise NewsError("INVALID_ARCHIVE_CLOCK")
        previous = at
        if not isinstance(raw, bytes) or raw_checksum(raw) != checksum:
            raise NewsError("ARCHIVE_CHECKSUM_MISMATCH")
        for event in parse_atom(raw, source=source, observed_at=at):
            payload = _payload(event)
            row = (source, event.source_id, observed, payload)
            if len(observations) >= MAX_ARCHIVE_ROWS:
                raise NewsError("ARCHIVE_REVIEW_BUDGET_EXCEEDED")
            observations.append(row)
            revisions.setdefault((source, event.source_id, payload), row)
            if at <= as_of:
                data = json.loads(payload)
                data["source_feed"], data["observed_at"] = source, observed
                latest[(source, event.source_id)] = data
        if at <= as_of:
            through = at
    actual_observations = db.execute(
        "SELECT source,identity,observed,payload FROM filing_observations ORDER BY sequence"
    ).fetchall()
    actual_revisions = db.execute(
        "SELECT source,identity,observed,payload FROM filing_revisions ORDER BY sequence"
    ).fetchall()
    if actual_observations != observations or actual_revisions != list(revisions.values()):
        raise NewsError("ARCHIVE_DERIVED_DATA_MISMATCH")
    return tuple(latest[key] for key in sorted(latest)), through


class NewsArchive:
    def __init__(self, path: Path) -> None:
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            _schema(db, allow_empty=True)
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
        now = timestamp(observed_at.isoformat())
        observed = now.isoformat()
        with closing(_connect(self.path, "rw")) as db, db:
            db.execute("BEGIN IMMEDIATE")
            _history(db, now)
            latest = db.execute(
                "SELECT observed FROM feed_snapshots ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            if latest is not None and now < timestamp(latest[0]):
                raise NewsError("OBSERVATION_CLOCK_ROLLBACK")
            db.execute(
                "INSERT INTO feed_snapshots(source,observed,sha256,raw) VALUES(?,?,?,?)",
                (source, observed, raw_checksum(raw), raw),
            )
            inserted = 0
            for event in events:
                row = (source, event.source_id, observed, _payload(event))
                cursor = db.execute(
                    "INSERT OR IGNORE INTO filing_revisions(source,identity,observed,payload) "
                    "VALUES(?,?,?,?)",
                    row,
                )
                inserted += cursor.rowcount
                db.execute(
                    "INSERT INTO filing_observations(source,identity,observed,payload) "
                    "VALUES(?,?,?,?)",
                    row,
                )
            # Reject budget overflow before committing an archive that could not be read.
            _history(db, now)
        return inserted

    def facts(self, *, as_of: datetime) -> tuple[dict[str, Any], ...]:
        stamp = timestamp(as_of.isoformat())
        with closing(_connect(self.path, "ro")) as db, db:
            db.execute("BEGIN")
            return _history(db, stamp)[0]

    def window(self, instrument_id: int, *, as_of: datetime) -> EarningsWindow:
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


@dataclass(frozen=True)
class NewsItemSummary:
    title: str
    form: str
    source_feed: str
    source_url: str
    published_at: datetime | None
    updated_at: datetime
    observed_at: datetime
    revision_sha256: str
    keyword_tags: tuple[str, ...]


@dataclass(frozen=True)
class NewsSummary:
    status: str
    as_of: datetime
    observed_through: datetime | None
    items: tuple[NewsItemSummary, ...]
    total_events: int
    truncated: bool
    earnings_coverage: str = "UNKNOWN"
    source_verification: str = "UNVERIFIED"
    execution_authorized: bool = False


def summarize_archive(path: Path, *, as_of: datetime, limit: int = 20) -> NewsSummary:
    """Read-only bounded dashboard view; never creates archives or prints private paths."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise NewsError("INVALID_SUMMARY_LIMIT")
    stamp = timestamp(as_of.isoformat())
    result = None
    try:
        with closing(_connect(path, "ro")) as db, db:
            db.execute("BEGIN")
            facts, through = _history(db, stamp)
        ordered = sorted(
            facts, key=lambda f: (f["observed_at"], f["source_feed"], f["source_id"]), reverse=True
        )
        items = tuple(
            NewsItemSummary(
                row["title"],
                row["form"],
                urlsplit(row["source_feed"])._replace(query="", fragment="").geturl(),
                urlsplit(row["source_url"])._replace(query="", fragment="").geturl(),
                timestamp(row["published_at"]) if row["published_at"] else None,
                timestamp(row["updated_at"]),
                timestamp(row["observed_at"]),
                raw_checksum(
                    json.dumps(
                        {k: v for k, v in row.items() if k not in ("source_feed", "observed_at")},
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode()
                ),
                tuple(row["keyword_tags"]),
            )
            for row in ordered[:limit]
        )
        status = (
            "EMPTY"
            if through is None
            else "STALE"
            if (stamp - through).total_seconds() > 86400
            else "AVAILABLE"
        )
        result = NewsSummary(status, stamp, through, items, len(facts), len(facts) > limit)
    except (sqlite3.Error, OSError, ValueError, TypeError):
        pass
    if result is None:
        raise NewsError("NEWS_ARCHIVE_UNAVAILABLE_OR_INVALID")
    return result
