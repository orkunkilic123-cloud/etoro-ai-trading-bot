"""Manual authorization, transactional risk checks, single-dispatch journal and recovery."""

import json
import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Context, DecimalException, localcontext
from typing import Any
from uuid import uuid4

from ..risk import AccountSnapshot, RiskEngine, StateError
from .client import CLOSE, CLOSE_LOOKUP, ELIGIBILITY, LOOKUP, OPEN, DemoExecutionClient
from .journal import read_record, ticket_data, transition
from .models import (
    ExecutionConfig,
    ExecutionError,
    OrderRecord,
    OrderState,
    PositionEvidence,
    RateLimited,
    Ticket,
)
from .reconcile import reconcile_response
from .validation import validate_eligibility

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


class ExecutionEngine:
    def __init__(
        self,
        risk: RiskEngine,
        client: DemoExecutionClient,
        *,
        config: ExecutionConfig | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.risk = risk
        self.store = risk.store
        self.client = client
        self.config = config or ExecutionConfig()
        self.clock = clock

    def propose(self, ticket: Ticket) -> str:
        order_id = str(uuid4())
        with self.store.transaction() as db:
            owner = db.execute("SELECT account FROM safety WHERE id=1").fetchone()
            if owner is None or owner[0] != ticket.account_id:
                raise ExecutionError("ACCOUNT_MISMATCH")
            db.execute(
                """INSERT INTO execution_orders
                (id,account,digest,ticket,reference,state) VALUES(?,?,?,?,?,?)""",
                (
                    order_id,
                    ticket.account_id,
                    ticket.digest,
                    ticket.canonical(),
                    str(uuid4()),
                    OrderState.PROPOSED.value,
                ),
            )
            transition(db, order_id, OrderState.PROPOSED)
        return order_id

    def authorize(
        self,
        order_id: str,
        exact_digest: str,
        *,
        expires_at: datetime,
        explicit_user_authorization: bool = False,
    ) -> None:
        """Call only from a trusted human approval interface, never an autonomous model."""
        now = self.clock()
        if (
            explicit_user_authorization is not True
            or expires_at.tzinfo is None
            or now.tzinfo is None
            or not now < expires_at <= now + timedelta(minutes=5)
        ):
            raise ExecutionError("EXPLICIT_EXPIRING_AUTHORIZATION_REQUIRED")
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT digest,state,consumed FROM execution_orders WHERE id=?", (order_id,)
            ).fetchone()
            if row != (exact_digest, OrderState.PROPOSED.value, 0):
                raise ExecutionError("APPROVAL_TICKET_MISMATCH")
            db.execute(
                "UPDATE execution_orders SET approval_expiry=? WHERE id=?",
                (expires_at.astimezone(UTC).isoformat(), order_id),
            )

    def record(self, order_id: str) -> OrderRecord:
        with self.store.transaction() as db:
            return read_record(db, order_id)

    def _authorization(self, db: sqlite3.Connection, order_id: str, ticket: Ticket) -> None:
        now = self.clock()
        if self.config.enabled is not True:
            raise ExecutionError("EXECUTION_DISABLED")
        self.client.confirm(ticket.account_id, now)
        row = db.execute(
            "SELECT digest,approval_expiry,consumed FROM execution_orders WHERE id=?", (order_id,)
        ).fetchone()
        if (
            row is None
            or row[0] != ticket.digest
            or row[1] is None
            or row[2] != 0
            or datetime.fromisoformat(row[1]) <= now
        ):
            raise ExecutionError("AUTHORIZATION_MISSING_EXPIRED_OR_CHANGED")

    def _network(
        self,
        db: sqlite3.Connection,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> tuple[int, dict[str, Any]]:
        group = (
            "lookup" if method == "GET" else ("eligibility" if path == ELIGIBILITY else "execution")
        )
        now = self.clock()
        row = db.execute("SELECT next_at FROM execution_throttle WHERE id=?", (group,)).fetchone()
        if row is None:
            raise ExecutionError("THROTTLE_STATE_MISSING")
        if row[0] and now < datetime.fromisoformat(row[0]):
            raise RateLimited("RATE_LIMITED")
        # Stored in the same serialized transaction as dispatch. Never sleep while holding DB lock.
        db.execute(
            "UPDATE execution_throttle SET next_at=? WHERE id=?",
            ((now + timedelta(seconds=3)).isoformat(), group),
        )
        status, body, cooldown = self.client._request(method, path, now=now, **kwargs)
        db.execute(
            "UPDATE execution_throttle SET next_at=? WHERE id=?",
            ((now + timedelta(seconds=cooldown)).isoformat(), group),
        )
        return status, body

    def submit(
        self,
        order_id: str,
        ticket: Ticket,
        account: AccountSnapshot,
        *,
        position: PositionEvidence | None = None,
    ) -> OrderRecord:
        """Never retry a mutation. Repeated invocation returns existing state only."""
        try:
            with localcontext(Context(prec=60)):
                return self._submit(order_id, ticket, account, position)
        except (
            sqlite3.Error,
            StateError,
            OSError,
            ValueError,
            TypeError,
            AttributeError,
            DecimalException,
        ):
            # A submitted marker committed before dispatch survives a later failed DB write.
            raise ExecutionError("EXECUTION_STATE_UNAVAILABLE") from None

    def _submit(
        self,
        order_id: str,
        ticket: Ticket,
        account: AccountSnapshot,
        position: PositionEvidence | None,
    ) -> OrderRecord:
        eligibility: dict[str, Any] = {}
        with self.store.transaction() as db:
            record = read_record(db, order_id)
            if record.state != OrderState.PROPOSED:
                return record
            self._authorization(db, order_id, ticket)
            if account.account_id != ticket.account_id:
                raise ExecutionError("ACCOUNT_MISMATCH")
            uncertain = db.execute("""SELECT 1 FROM execution_orders
                WHERE state IN ('submitted','unknown') LIMIT 1""").fetchone()
            if uncertain:
                raise ExecutionError("UNRESOLVED_ORDER_BLOCKS_EXECUTION")
            if ticket.action == "close":
                for raw, state in db.execute(
                    "SELECT ticket,state FROM execution_orders WHERE id<>?", (order_id,)
                ):
                    other = json.loads(raw)
                    if (
                        other["action"] == "close"
                        and other["position_id"] == ticket.position_id
                        and state != OrderState.PROPOSED.value
                    ):
                        raise ExecutionError("POSITION_CLOSE_ALREADY_RESERVED")
            try:
                status, eligibility = self._network(
                    db,
                    "POST",
                    ELIGIBILITY,
                    body={"instrumentIds": [ticket.proposal.instrument_id], "currency": "USD"},
                )
                if status != 200:
                    raise ExecutionError("ELIGIBILITY_UNAVAILABLE")
                validate_eligibility(
                    ticket,
                    eligibility,
                    position=position,
                    now=self.clock(),
                    max_age=self.risk.policy.max_age_seconds,
                )
                decision = self.risk.evaluate_in_transaction(
                    db, ticket.proposal, account, now=self.clock()
                )
                if not decision.passed:
                    raise ExecutionError("RISK_REJECTED:" + ",".join(decision.reasons))
                transition(db, order_id, OrderState.RISK_APPROVED)
            except ExecutionError as exc:
                transition(db, order_id, OrderState.REJECTED, str(exc))
                db.execute("UPDATE execution_orders SET terminal=1 WHERE id=?", (order_id,))
        if self.record(order_id).state != OrderState.RISK_APPROVED:
            return self.record(order_id)
        # Commit the may-have-been-sent marker before any mutation can leave the process.
        with self.store.transaction() as db:
            if read_record(db, order_id).state != OrderState.RISK_APPROVED:
                return read_record(db, order_id)
            self._authorization(db, order_id, ticket)
            transition(db, order_id, OrderState.SUBMITTED)
            db.execute("UPDATE execution_orders SET consumed=1 WHERE id=?", (order_id,))
        with self.store.transaction() as db:
            record = read_record(db, order_id)
            if record.state != OrderState.SUBMITTED:
                return record
            dispatch_attempted = False
            try:
                # Serialize the last kill/risk check with dispatch; a committed kill always wins.
                self.client.confirm(ticket.account_id, self.clock())
                auth = db.execute(
                    "SELECT approval_expiry FROM execution_orders WHERE id=?", (order_id,)
                ).fetchone()
                if (
                    self.config.enabled is not True
                    or auth is None
                    or datetime.fromisoformat(auth[0]) <= self.clock()
                ):
                    raise ExecutionError("AUTHORIZATION_EXPIRED_BEFORE_DISPATCH")
                # Other workers can discover uncertainty between preparation and dispatch.
                # Exclude only this order's durable may-have-been-sent marker.
                if db.execute(
                    "SELECT 1 FROM execution_orders WHERE id<>? "
                    "AND state IN ('submitted','unknown') LIMIT 1",
                    (order_id,),
                ).fetchone():
                    raise ExecutionError("UNRESOLVED_ORDER_BLOCKS_EXECUTION")
                validate_eligibility(
                    ticket,
                    eligibility,
                    position=position,
                    now=self.clock(),
                    max_age=self.risk.policy.max_age_seconds,
                )
                saved = db.execute(
                    "SELECT * FROM reservations WHERE proposal=?", (ticket.proposal.proposal_id,)
                ).fetchone()
                if saved is None:
                    raise ExecutionError("RESERVATION_MISSING")
                db.execute(
                    "DELETE FROM reservations WHERE proposal=?", (ticket.proposal.proposal_id,)
                )
                decision = self.risk.evaluate_in_transaction(
                    db, ticket.proposal, account, now=self.clock()
                )
                if not decision.passed:
                    db.execute("INSERT INTO reservations VALUES(?,?,?,?)", saved)
                    raise ExecutionError("FINAL_RISK_REJECTED:" + ",".join(decision.reasons))
                p = ticket.proposal
                if ticket.action == "open":
                    path = OPEN
                    body = {
                        "action": "open",
                        "transaction": "buy",
                        "instrumentId": p.instrument_id,
                        "settlementType": "real",
                        "orderType": "mkt",
                        "leverage": 1,
                        "units": p.units,
                        "stopLossRate": p.stop_loss,
                        "stopLossType": "fixed",
                        "orderCurrency": "usd",
                    }
                    expected = 202
                else:
                    path = CLOSE + str(ticket.position_id)
                    body = {"InstrumentID": p.instrument_id, "UnitsToDeduct": p.units}
                    expected = 200
                dispatch_attempted = True
                status, response = self._network(
                    db, "POST", path, reference=record.reference_id, body=body
                )
                if status != expected:
                    # Unexpected POST results are uncertain, including errors and redirects.
                    raise ExecutionError("SUBMISSION_UNCONFIRMED")
                if ticket.action == "open":
                    broker_id = response.get("orderId")
                    if response.get("referenceId") != record.reference_id:
                        raise ExecutionError("REFERENCE_MISMATCH")
                else:
                    close = response.get("orderForClose", {})
                    broker_id = close.get("orderID")
                    if (
                        close.get("positionID") != ticket.position_id
                        or close.get("instrumentID") != p.instrument_id
                        or close.get("CID") != self.client.identity.customer_id
                    ):
                        raise ExecutionError("CLOSE_IDENTITY_MISMATCH")
                if type(broker_id) is not int or broker_id <= 0:
                    raise ExecutionError("BROKER_ID_MISSING")
                db.execute(
                    "UPDATE execution_orders SET broker_id=? WHERE id=?", (broker_id, order_id)
                )
                transition(db, order_id, OrderState.PENDING)
            except RateLimited:
                transition(db, order_id, OrderState.REJECTED, "COOLDOWN_BLOCKED_DISPATCH")
                db.execute("UPDATE execution_orders SET terminal=1 WHERE id=?", (order_id,))
            except (ExecutionError, ValueError, TypeError, AttributeError, DecimalException):
                if dispatch_attempted:
                    transition(db, order_id, OrderState.UNKNOWN, "SUBMISSION_UNCERTAIN_NO_RETRY")
                else:
                    transition(db, order_id, OrderState.REJECTED, "FINAL_CHECK_BLOCKED_DISPATCH")
                    db.execute("UPDATE execution_orders SET terminal=1 WHERE id=?", (order_id,))
        result = self.record(order_id)
        logger.info(json.dumps({"event": "demo_execution_state", "state": result.state.value}))
        return result

    def reconcile(self, order_id: str) -> OrderRecord:
        """One bounded read; pending/unknown orders can be polled again, never re-POSTed."""
        try:
            with localcontext(Context(prec=60)), self.store.transaction() as db:
                record = read_record(db, order_id)
                if record.terminal or record.state in {
                    OrderState.PROPOSED,
                    OrderState.RISK_APPROVED,
                }:
                    return record
                try:
                    ticket = ticket_data(db, order_id)
                    self.client.confirm(str(ticket["account_id"]), self.clock())
                    if ticket["action"] == "close":
                        if record.broker_id is None:
                            raise ExecutionError("CLOSE_ID_REQUIRES_MANUAL_RECONCILIATION")
                        path, params = CLOSE_LOOKUP + str(record.broker_id), None
                    else:
                        path = LOOKUP
                        params = (
                            {"orderId": str(record.broker_id)}
                            if record.broker_id
                            else {"referenceId": record.reference_id}
                        )
                    status, data = self._network(db, "GET", path, params=params)
                    if status != 200:
                        raise ExecutionError("LOOKUP_UNCONFIRMED")
                    state, terminal, code, units, broker_id = reconcile_response(
                        data,
                        ticket,
                        self.client.identity,
                        record,
                        observed_at=self.clock(),
                    )
                    transition(db, order_id, state)
                    db.execute(
                        """UPDATE execution_orders SET terminal=?,broker_status=?,
                               executed=?,broker_id=? WHERE id=?""",
                        (int(terminal), code, str(units), broker_id, order_id),
                    )
                except RateLimited:
                    return record
                except (ExecutionError, ValueError, TypeError, AttributeError, DecimalException):
                    transition(db, order_id, OrderState.UNKNOWN, "RECONCILIATION_UNCONFIRMED")
                    db.execute("UPDATE execution_orders SET terminal=0 WHERE id=?", (order_id,))
                return read_record(db, order_id)
        except (sqlite3.Error, StateError, OSError):
            raise ExecutionError("EXECUTION_STATE_UNAVAILABLE") from None

    def recover(self) -> list[OrderRecord]:
        """Restart recovery never resumes dispatch or manufactures authorization."""
        with self.store.transaction() as db:
            ids = [
                r[0]
                for r in db.execute("""SELECT id FROM execution_orders
                WHERE state IN ('submitted','pending','partially-filled','unknown') AND terminal=0
                ORDER BY (SELECT MAX(sequence) FROM execution_events
                          WHERE order_id=execution_orders.id), rowid""")
            ]
        # A successful/uncertain poll appends a journal event, moving that order to the back.
        # Throttled polls append nothing. This survives restart without resetting broker quotas.
        return [self.reconcile(order_id) for order_id in ids]
