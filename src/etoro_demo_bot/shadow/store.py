"""Durable at-most-once scheduled research runs, independent of safety databases."""

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path


class ShadowError(ValueError):
    """Fixed user-facing failure codes; never contains input payloads or exception text."""


class Runs:
    def __init__(self, root: Path) -> None:
        self.root = root

    @classmethod
    def initialize(cls, root: Path) -> "Runs":
        root.mkdir(parents=True, exist_ok=False)
        with closing(sqlite3.connect(root / "runs.sqlite")) as db:
            db.execute(
                "CREATE TABLE runs (id TEXT PRIMARY KEY, pipeline TEXT NOT NULL, "
                "eur INTEGER NOT NULL, slot TEXT NOT NULL, status TEXT NOT NULL, "
                "UNIQUE(pipeline,eur,slot))"
            )
            db.commit()
        return cls(root)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        # Opening a missing journal must never silently recreate it.
        db = sqlite3.connect(
            (self.root / "runs.sqlite").resolve().as_uri() + "?mode=rw", uri=True, timeout=5
        )
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def claim(self, pipeline: str, eur: int, slot: date, *, now: datetime) -> str:
        if (
            pipeline not in ("hourly", "orb")
            or type(eur) is not int
            or eur not in (500, 1000)
            or type(slot) is not date
            or now.tzinfo is None
            or slot != now.astimezone(UTC).date()
        ):
            raise ShadowError("INVALID_OR_MISSED_SLOT")
        identity = hashlib.sha256(f"{pipeline}:{eur}:{slot.isoformat()}".encode()).hexdigest()[:24]
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT MAX(slot) FROM runs WHERE pipeline=? AND eur=?", (pipeline, eur)
            ).fetchone()[0]
            if previous is not None:
                last = date.fromisoformat(previous)
                if slot < last:
                    raise ShadowError("CLOCK_ROLLBACK")
                gap = (slot - last).days
                if gap > 366:
                    raise ShadowError("SCHEDULE_GAP_REQUIRES_REVIEW")
                for offset in range(1, gap):
                    missed = last + timedelta(days=offset)
                    missing_id = hashlib.sha256(
                        f"{pipeline}:{eur}:{missed.isoformat()}".encode()
                    ).hexdigest()[:24]
                    db.execute(
                        "INSERT INTO runs VALUES(?,?,?,?,?)",
                        (missing_id, pipeline, eur, missed.isoformat(), "missed"),
                    )
            try:
                db.execute(
                    "INSERT INTO runs VALUES(?,?,?,?,?)",
                    (identity, pipeline, eur, slot.isoformat(), "running"),
                )
            except sqlite3.IntegrityError:
                raise ShadowError("SLOT_ALREADY_CLAIMED") from None
        return identity

    def finish(self, identity: str, status: str) -> None:
        if status not in ("completed", "failed", "blocked"):
            raise ShadowError("INVALID_RUN_STATUS")
        with self.connect() as db:
            changed = db.execute(
                "UPDATE runs SET status=? WHERE id=? AND status='running'", (status, identity)
            ).rowcount
            if changed != 1:
                raise ShadowError("RUN_STATE_CONFLICT")

    def rows(self) -> list[tuple[str, str, int, str, str]]:
        with self.connect() as db:
            return list(db.execute("SELECT id,pipeline,eur,slot,status FROM runs ORDER BY slot,id"))
