"""Immutable local evidence snapshots. Payloads are never included in error messages."""

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import cast

from .models import Source
from .providers import check_source


class Archive:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with closing(sqlite3.connect(path)) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS snapshots "
                "(id TEXT PRIMARY KEY, metadata TEXT NOT NULL, raw BLOB NOT NULL)"
            )

    def put(self, raw: bytes, source: Source) -> str:
        check_source(raw, source)
        metadata = json.dumps(asdict(source), default=str, sort_keys=True)
        identity = hashlib.sha256(metadata.encode() + raw).hexdigest()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute(
                "INSERT OR IGNORE INTO snapshots VALUES (?, ?, ?)", (identity, metadata, raw)
            )
            db.commit()
        return identity

    def get(self, identity: str) -> tuple[bytes, Source]:
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute(
                "SELECT metadata, raw FROM snapshots WHERE id=?", (identity,)
            ).fetchone()
        if row is None:
            raise ValueError("Historical snapshot not found.")
        metadata, raw = cast(tuple[str, bytes], row)
        if hashlib.sha256(metadata.encode() + raw).hexdigest() != identity:
            raise ValueError("Historical snapshot integrity failure.")
        value = json.loads(metadata)
        value["retrieved_at"] = datetime.fromisoformat(value["retrieved_at"])
        source = Source(**value)
        check_source(raw, source)
        return raw, source
