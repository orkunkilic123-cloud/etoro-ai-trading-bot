"""Separate disposable analysis cache and persistent shared request pacing state."""

import json
import math
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .models import ScanError


class ScanStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS scan_cache(
                    key TEXT PRIMARY KEY, created REAL NOT NULL, expires REAL NOT NULL,
                    value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scan_quota(
                    name TEXT PRIMARY KEY, next REAL NOT NULL, last REAL NOT NULL,
                    spacing REAL NOT NULL);
            """)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def get(self, key: str, now: float) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT created,expires,value FROM scan_cache WHERE key=?", (key,)
            ).fetchone()
        if row is None or not row[0] <= now < row[1]:
            return None
        try:
            value = json.loads(row[2])
        except (ValueError, TypeError):
            raise ScanError("CACHE_INVALID") from None
        if not isinstance(value, dict):
            raise ScanError("CACHE_INVALID")
        return value

    def put(self, key: str, value: dict[str, Any], now: float, ttl: float) -> None:
        if not math.isfinite(ttl) or ttl <= 0:
            raise ScanError("INVALID_CACHE_TTL")
        encoded = json.dumps(value, allow_nan=False)
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO scan_cache VALUES(?,?,?,?)", (key, now, now + ttl, encoded)
            )

    def claim(self, group: str, now: float, spacing: float) -> float:
        """Return required wait, or reserve a slot atomically; no burst on restart."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT next,last,spacing FROM scan_quota WHERE name=?", (group,)
            ).fetchone()
            if row is not None:
                if now < row[1]:
                    raise ScanError("QUOTA_CLOCK_ROLLBACK")
                if now < row[0]:
                    return float(row[0] - now)
                spacing = max(spacing, row[2])
            db.execute(
                "INSERT OR REPLACE INTO scan_quota VALUES(?,?,?,?)",
                (group, now + spacing, now, spacing),
            )
        return 0.0

    def cooldown(self, group: str, now: float, delay: float, spacing: float) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT next,last,spacing FROM scan_quota WHERE name=?", (group,)
            ).fetchone()
            if row is not None:
                if now < row[1]:
                    raise ScanError("QUOTA_CLOCK_ROLLBACK")
                spacing = max(spacing, row[2])
                delay = max(delay, row[0] - now)
            db.execute(
                "INSERT OR REPLACE INTO scan_quota VALUES(?,?,?,?)",
                (group, now + delay, now, spacing),
            )
