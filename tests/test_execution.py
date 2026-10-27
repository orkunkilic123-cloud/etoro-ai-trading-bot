import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from etoro_demo_bot.config import Credentials
from etoro_demo_bot.execution import (
    DemoExecutionClient,
    DemoIdentity,
    ExecutionConfig,
    ExecutionEngine,
    ExecutionError,
    OrderState,
    PositionEvidence,
    Ticket,
    credential_digest,
    install_journal,
)
from etoro_demo_bot.execution.client import CLOSE, CLOSE_LOOKUP, ELIGIBILITY, LOOKUP, OPEN
from etoro_demo_bot.risk import AccountSnapshot, Proposal, RiskEngine, RiskStore

D = Decimal
NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)


def eligibility() -> dict[str, Any]:
    return {
        "currency": "USD",
        "notFoundInstrumentIds": [],
        "notFoundSymbols": [],
        "eligibilities": [
            {
                "instrumentId": 1,
                "minPositionExposure": 10,
                "maxUnitsPerOrder": 100,
                "allowOpenPosition": True,
                "allowClosePosition": True,
                "allowPartialClosePosition": True,
                "tradeUnitType": "units",
                "unitsQuantityType": "fractional",
                "allowedOrderQuantityType": "all",
                "additionalBufferPercent": None,
                "leverageConfigs": [
                    {
                        "settlementType": "real",
                        "direction": "long",
                        "leverageValues": [1],
                        "isPotential": False,
                        "minPositionAmount": 10,
                        "allowStopLossTakeProfit": True,
                        "minStopLossPercentage": 1,
                        "maxStopLossPercentage": 99,
                    }
                ],
            }
        ],
    }


class Harness:
    def __init__(self, path: Path) -> None:
        self.now = NOW
        self.credentials = Credentials(
            "synthetic-api-secret", "synthetic-user-secret", "demo", True
        )
        self.identity = DemoIdentity(
            "demo-account",
            42,
            43,
            credential_digest(self.credentials),
            NOW + timedelta(hours=1),
            True,
        )
        self.store = RiskStore.initialize(path, "demo-account")
        self.store.establish_day(NOW.date(), D("10000"))
        self.store.set_kill_switch(False, acknowledged=True)
        install_journal(self.store)
        self.ticket = Ticket(
            "demo-account",
            Proposal(
                "intent-1",
                1,
                D("9"),
                D("100"),
                D("90"),
                NOW,
                D("5"),
                underlying_verified=True,
            ),
            asset_currency="USD",
        )
        self.account = AccountSnapshot(
            "demo-account",
            D("10000"),
            D("10000"),
            (),
            NOW,
            demo=True,
            complete=True,
            cash_flows_reconciled=True,
        )
        self.eligibility = eligibility()
        self.requests: list[httpx.Request] = []
        self.mode = "ok"
        self.status_id = 1
        self.filled = 0
        self.order_id = 123
        self.mismatch = False
        self.client = DemoExecutionClient(
            self.credentials, self.identity, transport=httpx.MockTransport(self.handle)
        )
        self.engine = self.new_engine()

    def new_engine(self, *, enabled: bool = True) -> ExecutionEngine:
        return ExecutionEngine(
            RiskEngine(RiskStore(self.store.path)),
            self.client,
            config=ExecutionConfig(enabled),
            clock=lambda: self.now,
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.host == "public-api.etoro.com"
        assert request.url.scheme == "https"
        assert request.headers["x-api-key"] == "synthetic-api-secret"
        assert request.headers["x-user-key"] == "synthetic-user-secret"
        path = request.url.path
        if path == ELIGIBILITY:
            return httpx.Response(200, json=self.eligibility)
        if request.method == "POST":
            if self.mode == "timeout":
                raise httpx.ReadTimeout("synthetic-user-secret", request=request)
            if self.mode == "crash":
                raise KeyboardInterrupt()
            if self.mode == "redirect":
                return httpx.Response(307, headers={"Location": "https://evil.invalid"})
            if self.mode == "server-error":
                return httpx.Response(500, text="synthetic-user-secret")
            if self.mode == "rate-limit":
                return httpx.Response(429, headers={"Retry-After": "60"})
            if self.mode == "malformed":
                return httpx.Response(202, content=b"[]")
            if path == OPEN:
                return httpx.Response(
                    202,
                    json={"orderId": self.order_id, "referenceId": request.headers["x-request-id"]},
                )
            assert path == CLOSE + "99"
            return httpx.Response(
                200,
                json={
                    "orderForClose": {
                        "orderID": self.order_id,
                        "positionID": 99,
                        "instrumentID": 1,
                        "CID": 42,
                    }
                },
            )
        if self.mode == "lookup-404":
            return httpx.Response(404, json={})
        if path == LOOKUP:
            return httpx.Response(
                200,
                json={
                    "accountId": 999 if self.mismatch else 43,
                    "orderId": self.order_id,
                    "action": "open",
                    "transaction": "buy",
                    "type": "mkt",
                    "orderCurrency": "usd",
                    "asset": {
                        "instrumentId": 1,
                        "settlementType": "real",
                        "leverage": 1,
                        "side": "long",
                        "currency": "USD",
                    },
                    "status": {"id": self.status_id, "errorMessage": "synthetic-user-secret"},
                    "requestedUnits": 9,
                    "positionExecutions": [
                        {
                            "positionId": 99,
                            "stopLossRate": 90,
                            "openingData": {"orderId": self.order_id, "units": self.filled},
                        }
                    ]
                    if self.filled
                    else [],
                },
            )
        assert path == CLOSE_LOOKUP + str(self.order_id)
        return httpx.Response(
            200,
            json={
                "CID": 42,
                "instrumentID": 1,
                "orderID": self.order_id,
                "statusID": self.status_id,
                "positions": [
                    {
                        "positionID": 99,
                        "units": self.filled,
                        "occurred": self.now.isoformat(),
                        "rate": 100,
                    }
                ]
                if self.filled
                else [],
            },
        )

    def authorize(self) -> str:
        key = self.engine.propose(self.ticket)
        self.engine.authorize(
            key,
            self.ticket.digest,
            expires_at=self.now + timedelta(minutes=3),
            explicit_user_authorization=True,
        )
        return key

    def post_count(self) -> int:
        return sum(r.method == "POST" and r.url.path != ELIGIBILITY for r in self.requests)


@pytest.fixture
def h(tmp_path: Path) -> Harness:
    return Harness(tmp_path / "risk.sqlite")


def test_open_risk_approval_payload_and_lifecycle(h: Harness) -> None:
    key = h.authorize()
    assert h.engine.record(key).state == OrderState.PROPOSED
    result = h.engine.submit(key, h.ticket, h.account)
    assert result.state == OrderState.PENDING
    assert h.post_count() == 1
    payload = json.loads(h.requests[-1].content)
    assert payload == {
        "action": "open",
        "transaction": "buy",
        "instrumentId": 1,
        "settlementType": "real",
        "orderType": "mkt",
        "leverage": 1,
        "units": 9,
        "stopLossRate": 90,
        "stopLossType": "fixed",
        "orderCurrency": "usd",
    }
    with h.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM reservations").fetchone() == (1,)
        states = [r[0] for r in db.execute("SELECT state FROM execution_events ORDER BY sequence")]
    assert states == ["proposed", "risk-approved", "submitted", "pending"]
    h.status_id, h.filled = 3, 9
    result = h.engine.reconcile(key)
    assert result.state == OrderState.FILLED and result.terminal and result.executed_units == 9
    assert h.engine.submit(key, h.ticket, h.account) == result
    assert h.post_count() == 1


@pytest.mark.parametrize(
    ("status", "units", "state", "terminal"),
    [
        (1, 0, OrderState.PENDING, False),
        (2, 0, OrderState.PENDING, False),
        (3, 9, OrderState.FILLED, True),
        (4, 0, OrderState.REJECTED, True),
        (5, 4, OrderState.PARTIALLY_FILLED, False),
        (6, 0, OrderState.PENDING, False),
        (7, 0, OrderState.CANCELLED, True),
        (8, 0, OrderState.CANCELLED, True),
        (9, 4, OrderState.PARTIALLY_FILLED, True),
        (10, 4, OrderState.PARTIALLY_FILLED, True),
        (11, 0, OrderState.PENDING, False),
        (12, 0, OrderState.PENDING, False),
        (999, 0, OrderState.UNKNOWN, False),
        (3, 0, OrderState.UNKNOWN, False),
        (4, 3, OrderState.UNKNOWN, False),
        (5, 9, OrderState.UNKNOWN, False),
    ],
)
def test_documented_status_mapping(
    h: Harness,
    status: int,
    units: int,
    state: OrderState,
    terminal: bool,
) -> None:
    key = h.authorize()
    h.engine.submit(key, h.ticket, h.account)
    h.status_id, h.filled = status, units
    result = h.engine.reconcile(key)
    assert result.state == state and result.terminal is terminal
    with h.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM reservations").fetchone() == (1,)


@pytest.mark.parametrize("mode", ["timeout", "redirect", "server-error", "rate-limit", "malformed"])
def test_uncertain_post_never_retried_and_restart_lookup_by_reference(
    h: Harness, mode: str
) -> None:
    key = h.authorize()
    h.mode = mode
    result = h.engine.submit(key, h.ticket, h.account)
    assert result.state == OrderState.UNKNOWN
    assert h.engine.submit(key, h.ticket, h.account).state == OrderState.UNKNOWN
    assert h.post_count() == 1
    h.mode, h.status_id, h.filled = "ok", 3, 9
    restarted = h.new_engine(enabled=False)  # read-only recovery works with execution disabled
    recovered = restarted.recover()
    assert recovered[0].state == OrderState.FILLED
    assert h.requests[-1].url.params["referenceId"] == result.reference_id
    assert h.post_count() == 1


def test_crash_after_durable_submission_marker(h: Harness) -> None:
    key = h.authorize()
    h.mode = "crash"
    with pytest.raises(KeyboardInterrupt):
        h.engine.submit(key, h.ticket, h.account)
    assert h.engine.record(key).state == OrderState.SUBMITTED
    h.mode = "ok"
    restarted = h.new_engine()
    assert restarted.submit(key, h.ticket, h.account).state == OrderState.SUBMITTED
    assert restarted.recover()[0].state == OrderState.PENDING
    assert h.post_count() == 1


def test_lookup_not_found_is_unknown_not_rejection_or_retry(h: Harness) -> None:
    key = h.authorize()
    h.mode = "timeout"
    h.engine.submit(key, h.ticket, h.account)
    h.mode = "lookup-404"
    assert h.engine.reconcile(key).state == OrderState.UNKNOWN
    assert h.post_count() == 1


def test_partial_fill_monotonicity(h: Harness) -> None:
    key = h.authorize()
    h.engine.submit(key, h.ticket, h.account)
    h.status_id, h.filled = 5, 4
    assert h.engine.reconcile(key).executed_units == 4
    h.now += timedelta(seconds=4)
    h.filled = 2
    result = h.engine.reconcile(key)
    assert result.state == OrderState.UNKNOWN and result.executed_units == 4


def test_identity_mismatch_in_lookup_blocks_future_orders(h: Harness) -> None:
    key = h.authorize()
    h.engine.submit(key, h.ticket, h.account)
    h.mismatch = True
    assert h.engine.reconcile(key).state == OrderState.UNKNOWN
    h.ticket = replace(
        h.ticket, proposal=replace(h.ticket.proposal, proposal_id="different", units=D(8))
    )
    other = h.authorize()
    with pytest.raises(ExecutionError, match="UNRESOLVED"):
        h.engine.submit(other, h.ticket, h.account)
    assert h.post_count() == 1


def test_disabled_by_default(h: Harness) -> None:
    key = h.authorize()
    engine = ExecutionEngine(RiskEngine(h.store), h.client, clock=lambda: h.now)
    with pytest.raises(ExecutionError, match="DISABLED"):
        engine.submit(key, h.ticket, h.account)
    assert h.requests == []


def test_explicit_authorization_required_exact_and_expiring(h: Harness) -> None:
    key = h.engine.propose(h.ticket)
    with pytest.raises(ExecutionError, match="AUTHORIZATION"):
        h.engine.submit(key, h.ticket, h.account)
    with pytest.raises(ExecutionError):
        h.engine.authorize(key, h.ticket.digest, expires_at=NOW + timedelta(minutes=1))
    with pytest.raises(ExecutionError):
        h.engine.authorize(
            key,
            "other-digest",
            expires_at=NOW + timedelta(minutes=1),
            explicit_user_authorization=True,
        )
    h.engine.authorize(
        key,
        h.ticket.digest,
        expires_at=NOW + timedelta(minutes=1),
        explicit_user_authorization=True,
    )
    changed = replace(h.ticket, proposal=replace(h.ticket.proposal, units=D(8)))
    with pytest.raises(ExecutionError, match="CHANGED"):
        h.engine.submit(key, changed, h.account)
    h.now += timedelta(minutes=1)
    with pytest.raises(ExecutionError, match="EXPIRED"):
        h.engine.submit(key, h.ticket, h.account)
    assert h.requests == []


@pytest.mark.parametrize("change", ["unknown", "wrong-key", "expired", "wrong-account"])
def test_demo_binding_fails_closed(h: Harness, change: str) -> None:
    key = h.authorize()
    if change == "unknown":
        identity = replace(h.identity, demo_confirmed=False)
    elif change == "wrong-key":
        identity = replace(h.identity, credential_digest="unrelated")
    elif change == "expired":
        identity = replace(h.identity, expires_at=NOW)
    else:
        identity = replace(h.identity, account_id="other")
    h.client.identity = identity
    with pytest.raises(ExecutionError, match="UNCONFIRMED"):
        h.engine.submit(key, h.ticket, h.account)
    assert not h.requests


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v3/trading/execution/orders"),
        ("POST", "/api/v3/trading/execution/real/orders"),
        ("POST", OPEN + "?mode=real"),
        ("POST", OPEN + "/"),
        ("POST", "https://public-api.etoro.com" + OPEN),
        ("POST", CLOSE + "../1"),
        ("POST", CLOSE + "%31"),
        ("POST", CLOSE + "0"),
        ("DELETE", OPEN + "/123"),
        ("PATCH", "/api/v2/trading/demo/positions/1"),
        ("GET", "/api/v1/trading/info/portfolio"),
    ],
)
def test_exact_allowlist(h: Harness, method: str, path: str) -> None:
    with pytest.raises(ExecutionError, match="ENDPOINT_BLOCKED"):
        h.client._request(method, path)
    assert h.requests == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("minPositionExposure", 1000),
        ("maxUnitsPerOrder", 1),
        ("allowOpenPosition", False),
        ("tradeUnitType", "contracts"),
        ("allowedOrderQuantityType", "amountOnly"),
        ("additionalBufferPercent", 10),
        ("instrumentId", 999),
        ("unitsQuantityType", "unknown"),
    ],
)
def test_eligibility_rejections(h: Harness, field: str, value: Any) -> None:
    h.eligibility["eligibilities"][0][field] = value
    key = h.authorize()
    assert h.engine.submit(key, h.ticket, h.account).state == OrderState.REJECTED
    assert h.post_count() == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("isPotential", True),
        ("leverageValues", [2]),
        ("settlementType", "cfd"),
        ("allowStopLossTakeProfit", False),
        ("minStopLossPercentage", 11),
        ("maxStopLossPercentage", 9),
        ("minPositionAmount", 1000),
    ],
)
def test_configuration_rejections(h: Harness, field: str, value: Any) -> None:
    h.eligibility["eligibilities"][0]["leverageConfigs"][0][field] = value
    key = h.authorize()
    assert h.engine.submit(key, h.ticket, h.account).state == OrderState.REJECTED
    assert h.post_count() == 0


@pytest.mark.parametrize("condition", ["daily-loss", "cash", "kill", "stale", "risk", "leverage"])
def test_risk_cannot_be_bypassed(h: Harness, condition: str) -> None:
    if condition == "daily-loss":
        h.account = replace(h.account, equity=D(9700))
    elif condition == "cash":
        h.account = replace(h.account, available_balance=D(1))
    elif condition == "kill":
        h.store.set_kill_switch(True)
    elif condition == "stale":
        h.account = replace(h.account, observed_at=NOW - timedelta(seconds=61))
    elif condition == "risk":
        h.ticket = replace(h.ticket, proposal=replace(h.ticket.proposal, units=D(11)))
    else:
        h.ticket = replace(h.ticket, proposal=replace(h.ticket.proposal, leverage=D(2)))
    key = h.authorize()
    assert h.engine.submit(key, h.ticket, h.account).state == OrderState.REJECTED
    assert h.post_count() == 0


def test_close_and_partial_close_reconcile(h: Harness) -> None:
    h.ticket = replace(h.ticket, action="close", position_id=99)
    position = PositionEvidence("demo-account", 99, 1, D(10), NOW, True)
    key = h.authorize()
    assert h.engine.submit(key, h.ticket, h.account, position=position).state == OrderState.PENDING
    assert json.loads(h.requests[-1].content) == {"InstrumentID": 1, "UnitsToDeduct": 9}
    h.status_id, h.filled = 9, 4
    result = h.engine.reconcile(key)
    assert result.state == OrderState.PARTIALLY_FILLED and result.terminal
    assert result.executed_units == 4


def test_close_timeout_without_id_requires_manual_recovery(h: Harness) -> None:
    h.ticket = replace(h.ticket, action="close", position_id=99)
    key = h.authorize()
    h.mode = "timeout"
    position = PositionEvidence("demo-account", 99, 1, D(10), NOW, True)
    assert h.engine.submit(key, h.ticket, h.account, position=position).state == OrderState.UNKNOWN
    h.mode = "ok"
    assert h.new_engine().recover()[0].state == OrderState.UNKNOWN
    assert h.post_count() == 1
    assert all(r.method != "GET" for r in h.requests)


@pytest.mark.parametrize("kind", ["missing", "too-large", "wrong-owner", "stale", "leveraged"])
def test_close_position_verification(h: Harness, kind: str) -> None:
    h.ticket = replace(h.ticket, action="close", position_id=99)
    base_position = PositionEvidence("demo-account", 99, 1, D(10), NOW, True)
    position: PositionEvidence | None = base_position
    if kind == "missing":
        position = None
    elif kind == "too-large":
        position = replace(base_position, units=D(1))
    elif kind == "wrong-owner":
        position = replace(base_position, account_id="other")
    elif kind == "stale":
        position = replace(base_position, observed_at=NOW - timedelta(seconds=61))
    else:
        position = replace(base_position, underlying_long_unleveraged=False)
    key = h.authorize()
    assert h.engine.submit(key, h.ticket, h.account, position=position).state == OrderState.REJECTED
    assert h.post_count() == 0


def test_atomic_duplicate_dispatch(h: Harness) -> None:
    key = h.authorize()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: h.new_engine().submit(key, h.ticket, h.account), range(2)))
    assert h.post_count() == 1


def test_structured_logs_have_no_secrets_or_account_data(
    h: Harness,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="etoro_demo_bot.execution.engine")
    key = h.authorize()
    h.mode = "server-error"
    h.engine.submit(key, h.ticket, h.account)
    records = [r.message for r in caplog.records if r.name == "etoro_demo_bot.execution.engine"]
    assert records and json.loads(records[-1])["state"] == "unknown"
    for sensitive in ["synthetic-user-secret", "synthetic-api-secret", "demo-account"]:
        assert sensitive not in caplog.text
        assert sensitive not in h.engine.record(key).reason


def test_missing_journal_fail_closed(h: Harness) -> None:
    key = h.authorize()
    h.store.path.unlink()
    with pytest.raises(ExecutionError, match="STATE_UNAVAILABLE"):
        h.engine.submit(key, h.ticket, h.account)
    assert not h.requests


def test_final_kill_switch_recheck(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlite3

    original = h.engine._authorization
    calls = 0

    def authorization(db: sqlite3.Connection, order_id: str, ticket: Ticket) -> None:
        nonlocal calls
        original(db, order_id, ticket)
        calls += 1
        if calls == 2:
            db.execute("UPDATE safety SET killed=1 WHERE id=1")

    monkeypatch.setattr(h.engine, "_authorization", authorization)
    key = h.authorize()
    result = h.engine.submit(key, h.ticket, h.account)
    assert result.state == OrderState.REJECTED
    assert h.post_count() == 0
    with h.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM reservations").fetchone() == (1,)


def test_authorization_expires_during_preparation(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = h.client._request

    def request(method: str, path: str, **kwargs: Any) -> tuple[int, dict[str, Any], int]:
        result = original(method, path, **kwargs)
        h.now += timedelta(minutes=4)
        return result

    monkeypatch.setattr(h.client, "_request", request)
    key = h.authorize()
    assert h.engine.submit(key, h.ticket, h.account).state == OrderState.REJECTED
    assert h.post_count() == 0


def test_commit_failure_before_dispatch(h: Harness) -> None:
    key = h.authorize()
    with h.store.transaction() as db:
        db.execute("""CREATE TRIGGER reject_submitted BEFORE UPDATE ON execution_orders
                   WHEN NEW.state='submitted' BEGIN SELECT RAISE(ABORT,'disk failure'); END""")
    with pytest.raises(ExecutionError, match="STATE_UNAVAILABLE"):
        h.engine.submit(key, h.ticket, h.account)
    assert h.post_count() == 0
    assert h.engine.record(key).state == OrderState.RISK_APPROVED
    assert h.new_engine().submit(key, h.ticket, h.account).state == OrderState.RISK_APPROVED
    assert h.post_count() == 0


def test_commit_failure_after_dispatch_uses_durable_reference(h: Harness) -> None:
    key = h.authorize()
    with h.store.transaction() as db:
        db.execute("""CREATE TRIGGER reject_pending BEFORE UPDATE ON execution_orders
                   WHEN NEW.state='pending' BEGIN SELECT RAISE(ABORT,'disk failure'); END""")
    with pytest.raises(ExecutionError, match="STATE_UNAVAILABLE"):
        h.engine.submit(key, h.ticket, h.account)
    assert h.post_count() == 1
    assert h.engine.record(key).state == OrderState.SUBMITTED
    h.status_id, h.filled = 3, 9
    assert h.new_engine().recover()[0].state == OrderState.FILLED
    assert h.post_count() == 1


def test_risk_reservation_duplicate_with_new_execution_ticket(h: Harness) -> None:
    first = h.authorize()
    h.engine.submit(first, h.ticket, h.account)
    h.now += timedelta(seconds=4)
    h.ticket = replace(h.ticket, proposal=replace(h.ticket.proposal, proposal_id="new-id"))
    second = h.authorize()
    result = h.engine.submit(second, h.ticket, h.account)
    assert result.state == OrderState.REJECTED
    assert "DUPLICATE_PROPOSAL" in result.reason
    assert h.post_count() == 1


def test_unknown_currency_and_missing_eligibility_fail_closed(h: Harness) -> None:
    h.ticket = replace(h.ticket, asset_currency="unknown")
    key = h.authorize()
    assert h.engine.submit(key, h.ticket, h.account).state == OrderState.REJECTED
    assert h.post_count() == 0


def test_partial_close_permission_missing(h: Harness) -> None:
    h.ticket = replace(h.ticket, action="close", position_id=99)
    h.eligibility["eligibilities"][0]["allowPartialClosePosition"] = False
    key = h.authorize()
    position = PositionEvidence("demo-account", 99, 1, D(10), NOW, True)
    assert h.engine.submit(key, h.ticket, h.account, position=position).state == OrderState.REJECTED
    assert h.post_count() == 0


def test_journal_install_preserves_halt_and_reservations(h: Harness) -> None:
    key = h.authorize()
    h.engine.submit(key, h.ticket, h.account)
    h.store.set_kill_switch(True)
    install_journal(h.store)
    with h.store.transaction() as db:
        assert db.execute("SELECT killed FROM safety").fetchone() == (1,)
        assert db.execute("SELECT COUNT(*) FROM reservations").fetchone() == (1,)
    assert h.engine.record(key).state == OrderState.PENDING


def test_decimal_wire_values_are_numeric_and_exact(h: Harness) -> None:
    from etoro_demo_bot.execution.client import encode_body

    raw = encode_body({"units": D("0.123456789123"), "stopLossRate": D("90.000000000001")})
    assert json.loads(raw, parse_float=Decimal) == {
        "units": D("0.123456789123"),
        "stopLossRate": D("90.000000000001"),
    }


def test_reconciliation_cooldown_does_not_demote_known_pending(h: Harness) -> None:
    key = h.authorize()
    h.engine.submit(key, h.ticket, h.account)
    first = h.engine.reconcile(key)
    count = len(h.requests)
    assert h.engine.reconcile(key) == first
    assert len(h.requests) == count
    h.now += timedelta(seconds=4)
    h.status_id, h.filled = 3, 9
    assert h.engine.reconcile(key).state == OrderState.FILLED


def test_low_level_client_rejects_unknown_identity(h: Harness) -> None:
    h.client.identity = replace(h.identity, demo_confirmed=False)
    with pytest.raises(ExecutionError, match="UNCONFIRMED"):
        h.client._request("POST", OPEN, now=NOW)
    assert not h.requests
