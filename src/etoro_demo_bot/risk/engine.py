"""Deterministic proposal evaluation and atomic local capacity reservations."""

import hashlib
import sqlite3
from contextlib import nullcontext
from datetime import UTC, datetime
from decimal import Context, Decimal, DecimalException, localcontext

from .models import AccountSnapshot, Decision, Proposal, RiskPolicy, identifier, money
from .state import RiskStore, StateError


def fresh(stamp: datetime, now: datetime, max_age: int) -> bool:
    return stamp.tzinfo is not None and 0 <= (now - stamp).total_seconds() <= max_age


class RiskEngine:
    def __init__(self, store: RiskStore, policy: RiskPolicy | None = None) -> None:
        self.store = store
        self.policy = policy or RiskPolicy()

    def evaluate(self, proposal: Proposal, account: AccountSnapshot, *, now: datetime) -> Decision:
        """A PASS reserves capacity locally; it never authorizes execution."""
        try:
            with localcontext(Context(prec=60)):
                return self._evaluate(proposal, account, now)
        except (sqlite3.Error, StateError, OSError):
            return Decision(False, ("STATE_UNAVAILABLE",))
        except (ValueError, TypeError, AttributeError, DecimalException, OverflowError):
            return Decision(False, ("INVALID_INPUT",))

    def evaluate_in_transaction(
        self,
        db: sqlite3.Connection,
        proposal: Proposal,
        account: AccountSnapshot,
        *,
        now: datetime,
    ) -> Decision:
        """Use an existing safety transaction; caller owns commit/rollback."""
        with localcontext(Context(prec=60)):
            return self._evaluate(proposal, account, now, db)

    def _evaluate(
        self,
        p: Proposal,
        a: AccountSnapshot,
        now: datetime,
        connection: sqlite3.Connection | None = None,
    ) -> Decision:
        if now.tzinfo is None:
            return Decision(False, ("INVALID_TIME",))
        now = now.astimezone(UTC)
        if (
            a.demo is not True
            or a.currency != "USD"
            or not identifier(a.account_id)
            or a.complete is not True
            or a.cash_flows_reconciled is not True
        ):
            return Decision(False, ("INVALID_ACCOUNT",))
        if not fresh(a.observed_at, now, self.policy.max_age_seconds):
            return Decision(False, ("STALE_ACCOUNT",))
        if (
            not isinstance(a.equity, Decimal)
            or not money(a.equity.copy_abs())
            or not money(a.available_balance)
        ):
            return Decision(False, ("INVALID_BALANCE",))
        if type(a.exposures) is not tuple:
            return Decision(False, ("INVALID_EXPOSURE",))
        instruments: set[int] = set()
        for exposure in a.exposures:
            if (
                type(exposure.instrument_id) is not int
                or exposure.instrument_id <= 0
                or exposure.instrument_id in instruments
                or not money(exposure.notional, positive=True)
                or type(exposure.positions) is not int
                or exposure.positions < 1
            ):
                return Decision(False, ("INVALID_EXPOSURE",))
            instruments.add(exposure.instrument_id)
        with nullcontext(connection) if connection is not None else self.store.transaction() as db:
            row = db.execute("SELECT account, killed, last_seen FROM safety WHERE id=1").fetchone()
            if row is None or row[0] != a.account_id or row[1] not in (0, 1):
                raise StateError("Invalid account safety state.")
            day = now.date().isoformat()
            baseline = db.execute("SELECT equity, halted FROM days WHERE day=?", (day,)).fetchone()
            if baseline is None:
                return Decision(False, ("MISSING_DAILY_BASELINE",))
            opening = Decimal(baseline[0])
            if not money(opening, positive=True) or baseline[1] not in (0, 1):
                raise StateError("Invalid daily baseline.")
            if row[2] and now < datetime.fromisoformat(row[2]):
                return Decision(False, ("CLOCK_ROLLBACK",))
            db.execute("UPDATE safety SET last_seen=? WHERE id=1", (now.isoformat(),))
            halted = bool(baseline[1]) or a.equity <= opening * Decimal("0.97")
            if halted:
                db.execute("UPDATE days SET halted=1 WHERE day=?", (day,))
            reasons: list[str] = []
            if row[1]:
                reasons.append("KILL_SWITCH_ACTIVE")
            if halted:
                reasons.append("DAILY_LOSS_LIMIT")
            if reasons:
                return Decision(False, tuple(reasons))
            return self._proposal(db, p, a, now)

    def _proposal(
        self,
        db: sqlite3.Connection,
        p: Proposal,
        a: AccountSnapshot,
        now: datetime,
    ) -> Decision:
        reasons: list[str] = []
        if (
            not identifier(p.proposal_id)
            or type(p.instrument_id) is not int
            or p.instrument_id <= 0
            or not money(p.units, positive=True)
            or not money(p.cost_buffer)
        ):
            return Decision(False, ("INVALID_PROPOSAL",))
        if not money(p.leverage, positive=True) or p.leverage != 1:
            reasons.append("LEVERAGE_FORBIDDEN")
        if p.side != "buy" or p.settlement != "real" or p.underlying_verified is not True:
            reasons.append("INSTRUMENT_FORBIDDEN")
        if p.quote_type != "realtime" or not fresh(p.quoted_at, now, self.policy.max_age_seconds):
            reasons.append("STALE_MARKET_DATA")
        if not money(p.price, positive=True):
            reasons.append("INVALID_PRICE")
        if not money(p.stop_loss, positive=True):
            reasons.append("INVALID_STOP_LOSS")
        if reasons:
            return Decision(False, tuple(reasons))
        assert p.price is not None and p.stop_loss is not None
        if p.stop_loss >= p.price:
            return Decision(False, ("INVALID_STOP_LOSS",))
        notional = p.units * p.price
        risk = p.units * (p.price - p.stop_loss) + p.cost_buffer
        amount = notional + p.cost_buffer
        if not money(amount, positive=True) or not money(risk, positive=True):
            return Decision(False, ("INVALID_CALCULATION",))
        # Decimal canonicalization makes 1.0 and 1.00 the same economic intent.
        intent = "|".join(
            [
                str(p.instrument_id),
                str(p.units.normalize()),
                str(p.price.normalize()),
                str(p.stop_loss.normalize()),
                str((p.cost_buffer or Decimal(0)).normalize()),
            ]
        )
        fingerprint = hashlib.sha256(intent.encode()).hexdigest()
        reservations = db.execute(
            "SELECT proposal, fingerprint, instrument, amount FROM reservations"
        ).fetchall()
        reserved = Decimal(0)
        instrument_reserved = Decimal(0)
        for proposal_id, digest, instrument, raw_amount in reservations:
            value = Decimal(raw_amount)
            if (
                not money(value, positive=True)
                or not identifier(proposal_id)
                or not isinstance(digest, str)
                or len(digest) != 64
                or type(instrument) is not int
                or instrument <= 0
            ):
                raise StateError("Invalid reservation.")
            reserved += value
            if instrument == p.instrument_id:
                instrument_reserved += value
            if proposal_id == p.proposal_id or digest == fingerprint:
                reasons.append("DUPLICATE_PROPOSAL")
        if risk > a.equity * Decimal("0.01"):
            reasons.append("TRADE_RISK_LIMIT")
        if amount > a.equity * self.policy.max_position_fraction:
            reasons.append("POSITION_SIZE_LIMIT")
        exposure = sum((e.notional for e in a.exposures), Decimal(0))
        same_instrument = sum(
            (e.notional for e in a.exposures if e.instrument_id == p.instrument_id),
            Decimal(0),
        )
        if exposure + reserved + amount > a.equity * self.policy.max_exposure_fraction:
            reasons.append("TOTAL_EXPOSURE_LIMIT")
        if (
            same_instrument + instrument_reserved + amount
            > a.equity * self.policy.max_instrument_fraction
        ):
            reasons.append("INSTRUMENT_EXPOSURE_LIMIT")
        if (
            sum(e.positions for e in a.exposures) + len(reservations) + 1
            > self.policy.max_concurrent_positions
        ):
            reasons.append("CONCURRENT_POSITION_LIMIT")
        if amount + reserved > a.available_balance:
            reasons.append("INSUFFICIENT_BALANCE")
        if reasons:
            return Decision(False, tuple(dict.fromkeys(reasons)), risk, notional)
        db.execute(
            "INSERT INTO reservations VALUES (?, ?, ?, ?)",
            (p.proposal_id, fingerprint, p.instrument_id, str(amount)),
        )
        return Decision(True, ("RISK_PASS_EXECUTION_DISABLED",), risk, notional)
