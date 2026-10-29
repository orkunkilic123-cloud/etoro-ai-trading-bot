"""Offline P&L/journal diagnostics. No credentials, networking, or safety-state writes."""

import argparse
import hashlib
import json
import sqlite3
from collections import defaultdict
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Context, Decimal, localcontext
from pathlib import Path
from typing import Any

from .demo_cash import IncompleteDemoSnapshot, _amount, normalize_demo_pnl_response
from .risk import AccountSnapshot, Decision, Exposure, Proposal, RiskEngine, RiskStore
from .risk.models import identifier, money


class DiagnosticError(ValueError):
    """Fixed diagnostic code only, never a broker payload or SQLite message."""


def _id(value: Any, *, zero: bool = False) -> int:
    if type(value) is not int or value < (0 if zero else 1):
        raise DiagnosticError("INVALID_BROKER_IDENTIFIER")
    return value


def _signed(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str | int | Decimal):
        raise DiagnosticError("INVALID_PNL")
    try:
        number = Decimal(value)
        if not money(number.copy_abs()):
            raise ValueError
    except (ValueError, ArithmeticError):
        raise DiagnosticError("INVALID_PNL") from None
    return number


def _stamp(value: Any, now: datetime, *, no_later_than: datetime | None = None) -> datetime:
    try:
        stamp = datetime.fromisoformat(value)
        if (
            stamp.tzinfo is None
            or not 0 <= (now - stamp).total_seconds() <= 60
            or (no_later_than is not None and stamp > no_later_than)
        ):
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise DiagnosticError("STALE_OR_INVALID_OBSERVATION") from None
    return stamp


def _rows(data: Mapping[str, Any], name: str) -> list[dict[str, Any]]:
    value = data.get(name)
    if (
        not isinstance(value, list)
        or len(value) > 10000
        or any(not isinstance(item, dict) for item in value)
    ):
        raise DiagnosticError("MISSING_OR_INVALID_ENUMERATION")
    return value


@dataclass(frozen=True)
class InstrumentObservation:
    margin: Decimal = field(repr=False)
    pnl: Decimal = field(repr=False)
    units: Decimal = field(repr=False)


@dataclass(frozen=True)
class PnlObservation:
    cash: Decimal = field(repr=False)
    credit: Decimal = field(repr=False)
    invested: Decimal = field(repr=False)
    pnl: Decimal = field(repr=False)
    exposures: tuple[Exposure, ...] = field(repr=False)
    pending: dict[int, tuple[int, Decimal]] = field(repr=False)
    customer_ids: frozenset[int] = field(repr=False)
    position_count: int
    instruments: dict[int, InstrumentObservation] = field(repr=False)
    observed_at: datetime = field(repr=False)


def parse_pnl(data: dict[str, Any], *, observed_at: datetime, now: datetime) -> PnlObservation:
    """Validate the documented USD/manual/long/underlying subset; never attest Demo identity."""
    if now.tzinfo is None:
        raise DiagnosticError("INVALID_CLOCK")
    observed_at = _stamp(observed_at.isoformat(), now)
    with localcontext(Context(prec=60)):
        try:
            return _parse_pnl(data, now, observed_at)
        except (ValueError, TypeError, KeyError, ArithmeticError):
            pass
    # Outside handler: suppress source-bearing exception contexts.
    raise DiagnosticError("BROKER_OBSERVATION_REJECTED")


def _parse_pnl(data: dict[str, Any], now: datetime, observed_at: datetime) -> PnlObservation:
    cash = normalize_demo_pnl_response(data)
    p = data["clientPortfolio"]
    if type(p.get("accountCurrencyId")) is not int or p["accountCurrencyId"] != 1:
        raise DiagnosticError("ACCOUNT_CURRENCY_UNVERIFIED")
    # Their valuation/allocation semantics are not covered by this restricted adapter.
    for name in (
        "mirrors",
        "stockOrders",
        "entryOrders",
        "exitOrders",
        "ordersForClose",
        "ordersForCloseMultiple",
    ):
        if _rows(p, name):
            raise DiagnosticError("UNSUPPORTED_PORTFOLIO_ACTIVITY")
    if _amount(p.get("bonusCredit")) != 0:
        raise DiagnosticError("BONUS_CREDIT_UNSUPPORTED")
    pending: dict[int, tuple[int, Decimal]] = {}
    customers: set[int] = set()
    for name in ("orders", "ordersForOpen"):
        for item in _rows(p, name):
            oid, iid = _id(item.get("orderId")), _id(item.get("instrumentId"))
            if oid in pending:
                raise DiagnosticError("DUPLICATE_BROKER_ORDER")
            customers.add(_id(item.get("cid")))
            if (
                item.get("isBuy") is not True
                or type(item.get("leverage")) is not int
                or item["leverage"] != 1
            ):
                raise DiagnosticError("UNSUPPORTED_ORDER")
            if name == "ordersForOpen" and _id(item.get("mirrorId"), zero=True) != 0:
                raise DiagnosticError("COPY_ORDER_UNSUPPORTED")
            amount = _amount(item.get("amount"))
            # Units alone do not establish a bounded USD allocation or conversion rate.
            if amount <= 0:
                raise DiagnosticError("PENDING_CASH_ALLOCATION_UNVERIFIED")
            pending[oid] = (iid, amount)
    position_ids: set[int] = set()
    totals: dict[int, Decimal] = defaultdict(Decimal)
    counts: dict[int, int] = defaultdict(int)
    margins: dict[int, Decimal] = defaultdict(Decimal)
    pnls: dict[int, Decimal] = defaultdict(Decimal)
    units: dict[int, Decimal] = defaultdict(Decimal)
    investment = Decimal(0)
    pnl = Decimal(0)
    for item in _rows(p, "positions"):
        pid, iid = _id(item.get("positionID")), _id(item.get("instrumentID"))
        if pid in position_ids:
            raise DiagnosticError("DUPLICATE_BROKER_POSITION")
        position_ids.add(pid)
        customers.add(_id(item.get("CID")))
        if (
            item.get("isBuy") is not True
            or type(item.get("leverage")) is not int
            or item["leverage"] != 1
            or type(item.get("settlementTypeID")) is not int
            or item["settlementTypeID"] != 1
            or _id(item.get("mirrorID"), zero=True) != 0
        ):
            raise DiagnosticError("UNSUPPORTED_POSITION")
        position_units = _amount(item.get("units"))
        if position_units <= 0:
            raise DiagnosticError("INVALID_POSITION_UNITS")
        mark = item.get("unrealizedPnL")
        if not isinstance(mark, dict):
            raise DiagnosticError("POSITION_VALUATION_MISSING")
        _stamp(mark.get("timestamp"), now, no_later_than=observed_at)
        exposure = _amount(mark.get("exposureInAccountCurrency"))
        if exposure <= 0:
            raise DiagnosticError("INVALID_EXPOSURE")
        totals[iid] += exposure
        counts[iid] += 1
        margin = _amount(item.get("amount"))
        position_pnl = _signed(mark.get("pnL"))
        if "marginInAccountCurrency" in mark and _amount(mark["marginInAccountCurrency"]) != margin:
            raise DiagnosticError("POSITION_MARGIN_INCONSISTENT")
        investment += margin
        pnl += position_pnl
        margins[iid] += margin
        pnls[iid] += position_pnl
        units[iid] += position_units
    if len(customers) > 1 or pnl != _signed(p.get("unrealizedPnL")):
        raise DiagnosticError("INCONSISTENT_CUSTOMER_OR_PNL")
    return PnlObservation(
        cash.available_cash,
        cash.credit,
        investment,
        pnl,
        tuple(Exposure(i, totals[i], counts[i]) for i in sorted(totals)),
        pending,
        frozenset(customers),
        len(position_ids),
        {i: InstrumentObservation(margins[i], pnls[i], units[i]) for i in sorted(totals)},
        observed_at,
    )


def aggregate_equity(
    data: dict[str, Any], observation: PnlObservation, *, now: datetime
) -> Decimal:
    """Cross-check documented aggregate account totals; no inferred equity equation."""
    try:
        with localcontext(Context(prec=60)):
            if data.get("accountCurrency") != "USD":
                raise ValueError
            cid = _id(data.get("cid"))
            if observation.customer_ids and observation.customer_ids != frozenset({cid}):
                raise ValueError
            _stamp(data.get("timestamp"), now, no_later_than=observation.observed_at)
            if _rows(data, "mirrors"):
                raise ValueError
            totals = data["accountTotals"]
            available = _amount(totals.get("accountAvailableCash"))
            frozen = _amount(totals.get("accountFrozenCash"))
            balance = _amount(totals.get("accountBalance"))
            margin = _amount(totals.get("accountTotalUsedMargin"))
            pnl = _signed(totals.get("accountCurrentPnl"))
            equity = _amount(totals.get("accountTotalValue"))
            if (
                equity <= 0
                or balance != observation.credit
                or available != observation.cash
                or balance != available + frozen
                or margin != observation.invested + frozen
                or pnl != observation.pnl
                or equity != available + margin + pnl
            ):
                raise ValueError
            expected = {e.instrument_id: e.notional for e in observation.exposures}
            seen: set[int] = set()
            for item in _rows(data, "instrumentAggregates"):
                iid = _id(item.get("instrumentId"))
                if iid in seen or iid not in expected:
                    raise ValueError
                seen.add(iid)
                if _amount(item.get("netCurrentExposureAccountCurrency")) != expected[iid]:
                    raise ValueError
                instrument = observation.instruments[iid]
                # These meanings/formula are explicit in the aggregate schema. Do not
                # infer quantities from prices or fees, or accept contradictory extra data.
                for name, value in (
                    ("totalMarginAccountCurrency", instrument.margin),
                    ("accountCurrencyReturn", instrument.pnl),
                    ("netUnits", instrument.units),
                    ("liquidationValueAccountCurrency", instrument.margin + instrument.pnl),
                ):
                    if name in item and _signed(item[name]) != value:
                        raise ValueError
            if seen != set(expected):
                raise ValueError
            return equity
    except (ValueError, KeyError, TypeError, AttributeError, ArithmeticError):
        pass
    raise DiagnosticError("AGGREGATE_TOTALS_MISSING_STALE_OR_INCONSISTENT")


@dataclass(frozen=True)
class LocalState:
    account: str = field(repr=False)
    reservations: tuple[tuple[str, int, Decimal], ...] = field(repr=False)
    orders: dict[str, tuple[int | None, int, str, bool, str]] = field(repr=False)
    killed: bool
    daily_halted: bool
    baseline_present: bool
    unresolved: int


def read_local_state(path: Path, *, now: datetime) -> LocalState:
    """Consistent read-only SQLite snapshot; never create missing state or clear holds."""
    result = None
    try:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError
        with closing(
            sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        ) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise ValueError
            if db.execute("PRAGMA user_version").fetchone() != (1,):
                raise ValueError
            account, killed, last_seen = db.execute(
                "SELECT account,killed,last_seen FROM safety WHERE id=1"
            ).fetchone()
            if not identifier(account) or killed not in (0, 1):
                raise ValueError
            if last_seen:
                seen_at = datetime.fromisoformat(last_seen)
                if seen_at.tzinfo is None or seen_at > now:
                    raise ValueError
            rows = db.execute("SELECT proposal,instrument,amount FROM reservations").fetchall()
            reservations = tuple((r[0], _id(r[1]), _amount(r[2])) for r in rows)
            if any(not identifier(r[0]) for r in reservations) or len(
                {r[0] for r in reservations}
            ) != len(reservations):
                raise ValueError
            orders: dict[str, tuple[int | None, int, str, bool, str]] = {}
            broker_intents: set[tuple[str, int]] = set()
            unresolved = 0
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "execution_orders" not in tables:
                raise ValueError
            for ticket, owner, broker_id, state, terminal, ticket_digest in db.execute(
                "SELECT ticket,account,broker_id,state,terminal,digest FROM execution_orders"
            ):
                if owner != account or terminal not in (0, 1):
                    raise ValueError
                data = json.loads(ticket, object_pairs_hook=_unique)
                if (
                    data.get("account_id") != account
                    or data.get("action") not in ("open", "close")
                    or hashlib.sha256(ticket.encode()).hexdigest() != ticket_digest
                ):
                    raise ValueError
                proposal = data["proposal"]
                proposal_id = proposal["proposal_id"]
                if not identifier(proposal_id) or proposal_id in orders:
                    raise ValueError
                iid = _id(proposal["instrument_id"])
                if broker_id is not None:
                    _id(broker_id)
                    intent = (data["action"], broker_id)
                    if intent in broker_intents:
                        raise ValueError
                    broker_intents.add(intent)
                if state not in {
                    "proposed",
                    "risk-approved",
                    "submitted",
                    "pending",
                    "filled",
                    "partially-filled",
                    "rejected",
                    "cancelled",
                    "unknown",
                }:
                    raise ValueError
                terminal_states = {"filled", "rejected", "cancelled"}
                if (state in terminal_states and not terminal) or (
                    terminal and state not in terminal_states | {"partially-filled"}
                ):
                    raise ValueError
                if state in {"submitted", "unknown"} or (not terminal and state != "proposed"):
                    unresolved += 1
                orders[proposal_id] = (broker_id, iid, state, bool(terminal), data["action"])
            baseline = db.execute(
                "SELECT equity,halted FROM days WHERE day=?",
                (now.astimezone(UTC).date().isoformat(),),
            ).fetchone()
            if baseline is not None and (_amount(baseline[0]) <= 0 or baseline[1] not in (0, 1)):
                raise ValueError
            result = LocalState(
                account,
                reservations,
                orders,
                bool(killed),
                bool(baseline and baseline[1]),
                baseline is not None,
                unresolved,
            )
    except (
        OSError,
        sqlite3.Error,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        ArithmeticError,
        RecursionError,
    ):
        pass
    if result is None:
        raise DiagnosticError("LOCAL_SAFETY_STATE_UNAVAILABLE")
    return result


@dataclass(frozen=True)
class Diagnostic:
    snapshot: AccountSnapshot = field(repr=False)
    decision: Decision
    matched_reservations: int
    unmatched_reservations: int
    local: LocalState = field(repr=False)
    position_count: int

    def summary(self) -> dict[str, Any]:
        return {
            "mode": "DEMO_OBSERVATION_UNVERIFIED",
            "execution_authorized": False,
            "broker_compatibility_verified": False,
            "risk_passed": self.decision.passed,
            "risk_reasons": self.decision.reasons,
            "positions": self.position_count,
            "potential_reservation_overlaps": self.matched_reservations,
            "unmatched_reservations": self.unmatched_reservations,
            "unresolved_orders": self.local.unresolved,
            "kill_switch_active": self.local.killed,
            "daily_halt_latched": self.local.daily_halted,
            "daily_baseline_present": self.local.baseline_present,
            "blockers": [
                "DEMO_IDENTITY_UNVERIFIED",
                "SOURCE_COMPLETENESS_UNVERIFIED",
                "CASH_FLOWS_UNRECONCILED",
                "RESERVATION_OWNERSHIP_UNVERIFIED",
                "READ_ONLY_DIAGNOSTIC",
            ],
        }


def diagnose(
    data: dict[str, Any],
    state_path: Path,
    *,
    aggregate: dict[str, Any],
    observed_at: datetime,
    now: datetime,
) -> Diagnostic:
    observation = parse_pnl(data, observed_at=observed_at, now=now)
    equity = aggregate_equity(aggregate, observation, now=now)
    local = read_local_state(state_path, now=now)
    with localcontext(Context(prec=60)):
        additional = Decimal(0)
        matched = 0
        seen_broker: set[int] = set()
        for proposal, instrument, amount in local.reservations:
            match = local.orders.get(proposal)
            if match and instrument != match[1]:
                raise DiagnosticError("RESERVATION_INSTRUMENT_MISMATCH")
            if match and match[0] in observation.pending:
                assert match[0] is not None
                broker_id = match[0]
                if (
                    broker_id in seen_broker
                    or instrument != match[1]
                    or match[3]
                    or match[4] != "open"
                    or match[2] not in {"submitted", "pending", "partially-filled", "unknown"}
                ):
                    raise DiagnosticError("AMBIGUOUS_LOCAL_RESERVATION")
                seen_broker.add(broker_id)
                broker_instrument, _ = observation.pending[broker_id]
                if instrument != broker_instrument:
                    raise DiagnosticError("RESERVATION_INSTRUMENT_MISMATCH")
                # IDs alone cannot prove broker/local customer ownership; retain the hold.
                matched += 1
            additional += amount
        available = observation.cash - additional
        if available < 0:
            raise DiagnosticError("INSUFFICIENT_CASH_AFTER_LOCAL_RESERVATIONS")
        snapshot = AccountSnapshot(
            local.account,
            equity,
            available,
            observation.exposures,
            observed_at,
            demo=False,
            complete=False,
            cash_flows_reconciled=False,
        )
        # Incomplete observation is rejected before RiskEngine opens a write transaction.
        probe = Proposal(
            "offline-diagnostic",
            1,
            Decimal(1),
            Decimal(1),
            Decimal(".9"),
            now,
            Decimal(0),
            underlying_verified=False,
        )
        decision = RiskEngine(RiskStore(state_path)).evaluate(probe, snapshot, now=now)
        return Diagnostic(
            snapshot,
            decision,
            matched,
            len(local.reservations) - matched,
            local,
            observation.position_count,
        )


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DiagnosticError("DUPLICATE_JSON_FIELD")
        result[key] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pnl-file", type=Path, required=True)
    parser.add_argument("--risk-state", type=Path, required=True)
    parser.add_argument("--aggregate-file", type=Path, required=True)
    parser.add_argument(
        "--observed-at",
        required=True,
        help="Actual read observation timestamp with timezone; never re-date old data",
    )
    args = parser.parse_args()
    try:
        with args.pnl_file.open("rb") as file:
            raw = file.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError
        data = json.loads(raw, parse_float=Decimal, object_pairs_hook=_unique)
        if not isinstance(data, dict):
            raise ValueError
        with args.aggregate_file.open("rb") as file:
            raw_aggregate = file.read(4 * 1024 * 1024 + 1)
        if len(raw_aggregate) > 4 * 1024 * 1024:
            raise ValueError
        aggregate = json.loads(raw_aggregate, parse_float=Decimal, object_pairs_hook=_unique)
        if not isinstance(aggregate, dict):
            raise ValueError
        result = diagnose(
            data,
            args.risk_state,
            aggregate=aggregate,
            observed_at=datetime.fromisoformat(args.observed_at),
            now=datetime.now(UTC),
        )
    except (
        OSError,
        ValueError,
        TypeError,
        ArithmeticError,
        RecursionError,
        IncompleteDemoSnapshot,
    ):
        print('{"status":"blocked","code":"DIAGNOSTIC_INPUT_OR_STATE_REJECTED"}')
        return 1
    print(json.dumps(result.summary(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
