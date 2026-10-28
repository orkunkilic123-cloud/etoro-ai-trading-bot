"""Durable proposal claims and structured analysis events, separate from broker state."""

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from .models import Candidate, StrategyError


def encode(value: Any) -> str:
    def default(item: Any) -> Any:
        if isinstance(item, Decimal):
            return format(item, "f")
        if isinstance(item, datetime):
            return item.astimezone(UTC).isoformat()
        if isinstance(item, Enum):
            return item.value
        raise TypeError("Unsupported journal type")

    return json.dumps(
        value, default=default, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value: Any) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def initialize(cls, path: Path) -> "Journal":
        # Explicit exclusive creation: a missing journal is not silently reset.
        with path.open("xb"):
            pass
        journal = cls(path)
        with journal.connect() as db:
            db.executescript("""
                CREATE TABLE decisions(
                    sequence INTEGER PRIMARY KEY, at TEXT NOT NULL, status TEXT NOT NULL,
                    signal TEXT NOT NULL, details TEXT NOT NULL);
                CREATE TABLE claims(
                    signal TEXT PRIMARY KEY, proposal TEXT UNIQUE NOT NULL, payload TEXT NOT NULL,
                    state TEXT NOT NULL);
                CREATE TABLE watermark(id INTEGER PRIMARY KEY CHECK(id=1), at TEXT NOT NULL);
            """)
        return journal

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=rw", uri=True, timeout=5)
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _time(db: sqlite3.Connection, now: datetime) -> None:
        row = db.execute("SELECT at FROM watermark WHERE id=1").fetchone()
        if row is not None and now < datetime.fromisoformat(row[0]):
            raise StrategyError("CLOCK_ROLLBACK")
        db.execute("INSERT OR REPLACE INTO watermark VALUES(1,?)", (now.isoformat(),))

    def record(
        self,
        signal: str,
        status: str,
        details: dict[str, Any],
        now: datetime,
        candidate: Candidate | None = None,
    ) -> bool:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._time(db, now)
            if candidate is not None:
                if db.execute("SELECT 1 FROM claims WHERE signal=?", (signal,)).fetchone():
                    status, details = "rejected", {"reasons": ["DUPLICATE_SIGNAL"]}
                    candidate = None
                else:
                    db.execute(
                        "INSERT INTO claims VALUES(?,?,?,?)",
                        (
                            signal,
                            candidate.proposal.proposal_id,
                            encode(asdict(candidate)),
                            "proposed",
                        ),
                    )
            db.execute(
                "INSERT INTO decisions(at,status,signal,details) VALUES(?,?,?,?)",
                (now.isoformat(), status, signal, encode(details)),
            )
        return candidate is not None

    def begin_review(self, candidate: Candidate, now: datetime) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._time(db, now)
            row = db.execute(
                "SELECT payload,state FROM claims WHERE signal=?", (candidate.signal_id,)
            ).fetchone()
            if row is None or row != (encode(asdict(candidate)), "proposed"):
                raise StrategyError("UNJOURNALED_CHANGED_OR_REVIEWED_PROPOSAL")
            db.execute(
                "UPDATE claims SET state=? WHERE signal=?", ("reviewing", candidate.signal_id)
            )
            db.execute(
                "INSERT INTO decisions(at,status,signal,details) VALUES(?,?,?,?)",
                (now.isoformat(), "risk_review_started", candidate.signal_id, "{}"),
            )

    def finish_review(
        self, candidate: Candidate, passed: bool, reasons: tuple[str, ...], now: datetime
    ) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._time(db, now)
            status = "risk_pass" if passed else "risk_rejected"
            db.execute("UPDATE claims SET state=? WHERE signal=?", (status, candidate.signal_id))
            db.execute(
                "INSERT INTO decisions(at,status,signal,details) VALUES(?,?,?,?)",
                (now.isoformat(), status, candidate.signal_id, encode({"reasons": reasons})),
            )

    def events(self) -> tuple[dict[str, Any], ...]:
        with self.connect() as db:
            return tuple(
                {
                    "sequence": row[0],
                    "at": row[1],
                    "status": row[2],
                    "signal": row[3],
                    "details": json.loads(row[4]),
                }
                for row in db.execute("SELECT * FROM decisions ORDER BY sequence")
            )

    def claim_research(
        self, signal: str, proposal: str, payload: dict[str, Any], now: datetime
    ) -> bool:
        """Separate research claims; never insert an executable Candidate claim."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._time(db, now)
            db.execute(
                "CREATE TABLE IF NOT EXISTS research_claims("
                "signal TEXT PRIMARY KEY, proposal TEXT UNIQUE NOT NULL, "
                "payload TEXT NOT NULL, state TEXT NOT NULL)"
            )
            if db.execute("SELECT 1 FROM research_claims WHERE signal=?", (signal,)).fetchone():
                return False
            db.execute(
                "INSERT INTO research_claims VALUES(?,?,?,?)",
                (signal, proposal, encode(payload), "proposed"),
            )
            db.execute(
                "INSERT INTO decisions(at,status,signal,details) VALUES(?,?,?,?)",
                (now.isoformat(), "orb_proposed", signal, encode(payload)),
            )
        return True

    def begin_research_review(self, signal: str, payload: dict[str, Any], now: datetime) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._time(db, now)
            row = db.execute(
                "SELECT payload,state FROM research_claims WHERE signal=?", (signal,)
            ).fetchone()
            if row != (encode(payload), "proposed"):
                raise StrategyError("UNJOURNALED_CHANGED_OR_REVIEWED_RESEARCH")
            db.execute("UPDATE research_claims SET state='reviewing' WHERE signal=?", (signal,))

    def finish_research_review(
        self, signal: str, passed: bool, reasons: tuple[str, ...], now: datetime
    ) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._time(db, now)
            state = "risk_pass" if passed else "risk_rejected"
            if (
                db.execute(
                    "UPDATE research_claims SET state=? WHERE signal=? AND state='reviewing'",
                    (state, signal),
                ).rowcount
                != 1
            ):
                raise StrategyError("RESEARCH_REVIEW_STATE_UNAVAILABLE")
            db.execute(
                "INSERT INTO decisions(at,status,signal,details) VALUES(?,?,?,?)",
                (now.isoformat(), "orb_" + state, signal, encode({"reasons": reasons})),
            )
