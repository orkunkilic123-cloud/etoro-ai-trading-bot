"""Durable local safety state. Missing/corrupt stores are never auto-recreated."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

from .models import identifier, money


class StateError(Exception):
    """Safety state is unavailable or invalid."""


class RiskStore:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()

    @classmethod
    def initialize(cls, path: Path, account_id: str) -> "RiskStore":
        if not identifier(account_id):
            raise ValueError("Invalid account identifier.")
        # Exclusive creation prevents accidental reset of a halted account.
        with path.open("xb"):
            pass
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript("""
                PRAGMA user_version=1;
                CREATE TABLE safety (
                    id INTEGER PRIMARY KEY CHECK(id=1), account TEXT NOT NULL,
                    killed INTEGER NOT NULL CHECK(killed IN (0,1)), last_seen TEXT NOT NULL
                );
                CREATE TABLE days (
                    day TEXT PRIMARY KEY, equity TEXT NOT NULL,
                    halted INTEGER NOT NULL CHECK(halted IN (0,1))
                );
                CREATE TABLE reservations (
                    proposal TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
                    instrument INTEGER NOT NULL, amount TEXT NOT NULL
                );
            """)
            db.execute("INSERT INTO safety VALUES(1, ?, 1, '')", (account_id,))
        return cls(path)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=2)
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            if db.execute("PRAGMA user_version").fetchone() != (1,):
                raise StateError("Unsupported safety state.")
            if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise StateError("Invalid safety state.")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def set_kill_switch(self, active: bool, *, acknowledged: bool = False) -> None:
        if type(active) is not bool or (not active and acknowledged is not True):
            raise ValueError("Clearing the emergency switch requires explicit acknowledgment.")
        with self.transaction() as db:
            if db.execute("UPDATE safety SET killed=? WHERE id=1", (int(active),)).rowcount != 1:
                raise StateError("Missing safety state.")

    def establish_day(self, day: date, opening_equity: Decimal) -> None:
        """Explicit trusted UTC start-of-day baseline, never first-observed equity."""
        if type(day) is not date or not money(opening_equity, positive=True):
            raise ValueError("A valid day and positive opening equity are required.")
        with self.transaction() as db:
            latest = db.execute("SELECT MAX(day) FROM days").fetchone()[0]
            if latest is not None and day.isoformat() <= latest:
                raise StateError("Daily baselines cannot be replaced or backdated.")
            db.execute("INSERT INTO days VALUES (?, ?, 0)", (day.isoformat(), str(opening_equity)))
