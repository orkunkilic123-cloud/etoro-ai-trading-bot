"""Additive execution journal on the same SQLite database as risk reservations."""

import hashlib
import json
import sqlite3
from decimal import Decimal

from ..risk import RiskStore
from .models import ExecutionError, OrderRecord, OrderState


def install_journal(store: RiskStore) -> None:
    """Explicit idempotent schema installation, preserving risk state and kill switch."""
    with store.transaction() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS execution_orders (
            id TEXT PRIMARY KEY, account TEXT NOT NULL, digest TEXT NOT NULL UNIQUE,
            ticket TEXT NOT NULL, reference TEXT NOT NULL UNIQUE, state TEXT NOT NULL,
            broker_id INTEGER, terminal INTEGER NOT NULL DEFAULT 0,
            broker_status INTEGER, executed TEXT NOT NULL DEFAULT '0',
            reason TEXT NOT NULL DEFAULT '', approval_expiry TEXT,
            consumed INTEGER NOT NULL DEFAULT 0
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS execution_events (
            sequence INTEGER PRIMARY KEY, order_id TEXT NOT NULL,
            state TEXT NOT NULL, reason TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS execution_throttle (
            id TEXT PRIMARY KEY, next_at TEXT NOT NULL
        )""")
        for group in ("execution", "eligibility", "lookup"):
            db.execute("INSERT OR IGNORE INTO execution_throttle VALUES (?, '')", (group,))


def transition(
    db: sqlite3.Connection,
    order_id: str,
    state: OrderState,
    reason: str = "",
) -> None:
    db.execute(
        "UPDATE execution_orders SET state=?, reason=? WHERE id=?", (state.value, reason, order_id)
    )
    db.execute(
        "INSERT INTO execution_events(order_id,state,reason) VALUES(?,?,?)",
        (order_id, state.value, reason),
    )


def read_record(db: sqlite3.Connection, order_id: str) -> OrderRecord:
    row = db.execute(
        """SELECT id,state,reference,broker_id,terminal,broker_status,executed,reason
                        FROM execution_orders WHERE id=?""",
        (order_id,),
    ).fetchone()
    if row is None:
        raise ValueError("Unknown journal entry.")
    return OrderRecord(
        row[0], OrderState(row[1]), row[2], row[3], bool(row[4]), row[5], Decimal(row[6]), row[7]
    )


def ticket_data(db: sqlite3.Connection, order_id: str) -> dict[str, object]:
    row = db.execute(
        "SELECT ticket,digest,account FROM execution_orders WHERE id=?", (order_id,)
    ).fetchone()
    owner = db.execute("SELECT account FROM safety WHERE id=1").fetchone()
    if (
        row is None
        or owner is None
        or not isinstance(row[0], str)
        or hashlib.sha256(row[0].encode()).hexdigest() != row[1]
        or row[2] != owner[0]
    ):
        raise ExecutionError("JOURNAL_TICKET_INTEGRITY_UNCONFIRMED")
    try:
        data: dict[str, object] = json.loads(row[0])
    except (ValueError, UnicodeError):
        raise ExecutionError("JOURNAL_TICKET_INTEGRITY_UNCONFIRMED") from None
    if not isinstance(data, dict) or data.get("account_id") != row[2]:
        raise ExecutionError("JOURNAL_TICKET_INTEGRITY_UNCONFIRMED")
    return data
