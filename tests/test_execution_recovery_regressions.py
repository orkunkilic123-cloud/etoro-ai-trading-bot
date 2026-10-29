"""Offline recovery fairness, immutable evidence and final-dispatch regressions."""

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_execution import Harness

from etoro_demo_bot.execution import ExecutionError, OrderState, PositionEvidence, Ticket
from etoro_demo_bot.execution.client import CLOSE, LOOKUP, OPEN
from etoro_demo_bot.execution.journal import transition
from etoro_demo_bot.execution.reconcile import reconcile_response


@pytest.fixture
def h(tmp_path: Path) -> Iterator[Harness]:
    harness = Harness(tmp_path / "risk.sqlite")
    yield harness
    harness.client.close()


@pytest.mark.parametrize("first_uncertain", [False, True])
def test_recovery_rotates_pending_orders_across_restarts_and_shared_quota(
    h: Harness, first_uncertain: bool
) -> None:
    first = h.authorize()
    assert h.engine.submit(first, h.ticket, h.account).state == OrderState.PENDING
    h.now += timedelta(seconds=4)
    h.order_id = 124
    h.ticket = replace(
        h.ticket, proposal=replace(h.ticket.proposal, proposal_id="intent-2", units=Decimal(8))
    )
    second = h.authorize()
    assert h.engine.submit(second, h.ticket, h.account).state == OrderState.PENDING
    h.client.close()

    def respond(request: httpx.Request) -> httpx.Response:
        response = h.handle(request)
        assert request.method == "GET" and request.url.path == LOOKUP
        broker_id = int(request.url.params["orderId"])
        if first_uncertain and broker_id == 123:
            raise httpx.ReadTimeout("SYNTHETIC_PRIVATE_DATA", request=request)
        data = response.json()
        data["orderId"] = broker_id
        data["requestedUnits"] = 9 if broker_id == 123 else 8
        return httpx.Response(200, json=data)

    from etoro_demo_bot.execution import DemoExecutionClient

    h.client = DemoExecutionClient(
        h.credentials, h.identity, transport=httpx.MockTransport(respond)
    )
    for _ in range(4):
        engine = h.new_engine(enabled=False)
        observations = engine.recover()
        assert len(observations) == 2
        for record in observations:
            expected = (
                OrderState.UNKNOWN
                if first_uncertain and record.ticket_id == first
                else OrderState.PENDING
            )
            assert record.state == expected
        requests_before = len(h.requests)
        engine.recover()  # No waiting or quota bypass, even through a different order.
        assert len(h.requests) == requests_before
        h.now += timedelta(seconds=4)
    observed_ids = [r.url.params["orderId"] for r in h.requests if r.method == "GET"]
    assert observed_ids == ["123", "124", "123", "124"]
    assert h.post_count() == 2


def test_new_uncertainty_between_preflight_and_dispatch_blocks_second_order(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = h.authorize()
    h.engine.submit(first, h.ticket, h.account)
    h.now += timedelta(seconds=4)
    h.ticket = replace(
        h.ticket, proposal=replace(h.ticket.proposal, proposal_id="intent-2", units=Decimal(8))
    )
    second = h.authorize()
    authorization = h.engine._authorization
    calls = 0

    def concurrent_reconciliation(db: sqlite3.Connection, order_id: str, ticket: Ticket) -> None:
        nonlocal calls
        authorization(db, order_id, ticket)
        calls += 1
        if calls == 2:
            # Models another worker discovering ambiguity after preparation committed.
            transition(db, first, OrderState.UNKNOWN, "RECONCILIATION_UNCONFIRMED")

    monkeypatch.setattr(h.engine, "_authorization", concurrent_reconciliation)
    result = h.engine.submit(second, h.ticket, h.account)
    assert result.state == OrderState.REJECTED and result.terminal
    assert h.post_count() == 1
    assert h.engine.record(first).state == OrderState.UNKNOWN
    with h.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM reservations").fetchone() == (2,)
    h.new_engine(enabled=False).recover()
    assert h.post_count() == 1


@pytest.mark.parametrize(
    "damage", ["units", "row_account", "safety_account", "digest", "invalid_json", "not_object"]
)
def test_recovery_rejects_drifted_journal_before_lookup(h: Harness, damage: str) -> None:
    key = h.authorize()
    h.engine.submit(key, h.ticket, h.account)
    with h.store.transaction() as db:
        if damage == "units":
            raw = json.loads(h.ticket.canonical())
            raw["proposal"]["units"] = "4"
            db.execute("UPDATE execution_orders SET ticket=? WHERE id=?", (json.dumps(raw), key))
        elif damage == "row_account":
            db.execute("UPDATE execution_orders SET account='different-account' WHERE id=?", (key,))
        elif damage == "safety_account":
            db.execute("UPDATE safety SET account='different-account' WHERE id=1")
        elif damage == "digest":
            db.execute("UPDATE execution_orders SET digest=? WHERE id=?", ("0" * 64, key))
        else:
            raw_text = "{SYNTHETIC_PRIVATE_DATA" if damage == "invalid_json" else "[]"
            db.execute(
                "UPDATE execution_orders SET ticket=?,digest=? WHERE id=?",
                (raw_text, hashlib.sha256(raw_text.encode()).hexdigest(), key),
            )
    requests_before = len(h.requests)
    result = h.new_engine(enabled=False).recover()[0]
    assert result.state == OrderState.UNKNOWN and not result.terminal
    assert result.executed_units == 0
    assert result.reason == "RECONCILIATION_UNCONFIRMED"
    assert len(h.requests) == requests_before
    with h.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM reservations").fetchone() == (1,)


def test_damaged_partial_order_retains_last_known_execution_and_reservation(h: Harness) -> None:
    key = h.authorize()
    h.engine.submit(key, h.ticket, h.account)
    h.status_id, h.filled = 5, 4
    assert h.engine.reconcile(key).executed_units == 4
    h.now += timedelta(seconds=4)
    with h.store.transaction() as db:
        db.execute("UPDATE execution_orders SET digest=? WHERE id=?", ("0" * 64, key))
    requests_before = len(h.requests)
    result = h.new_engine(enabled=False).recover()[0]
    assert result.state == OrderState.UNKNOWN and not result.terminal
    assert result.executed_units == 4
    assert result.broker_status == 5
    assert len(h.requests) == requests_before and h.post_count() == 1
    with h.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM reservations").fetchone() == (1,)


@pytest.mark.parametrize(
    "occurred",
    [
        True,
        {},
        "SYNTHETIC_PRIVATE_DATA",
        "2026-10-27T12:00:00",
        "2026-10-27",
        "2026-10-27T12:00:01+00:00",
    ],
)
def test_malformed_close_execution_time_stays_unknown(
    h: Harness, occurred: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    h.ticket = replace(h.ticket, action="close", position_id=99)
    key = h.authorize()
    position = PositionEvidence("demo-account", 99, 1, Decimal(10), h.now, True)
    h.engine.submit(key, h.ticket, h.account, position=position)
    original_request = h.client._request

    def request(method: str, path: str, **kwargs: Any) -> tuple[int, dict[str, Any], int]:
        status, data, cooldown = original_request(method, path, **kwargs)
        data["positions"][0]["occurred"] = occurred
        return status, data, cooldown

    monkeypatch.setattr(h.client, "_request", request)
    h.status_id, h.filled = 3, 9
    result = h.new_engine(enabled=False).recover()[0]
    assert result.state == OrderState.UNKNOWN and not result.terminal
    assert result.executed_units == 0
    assert result.reason == "RECONCILIATION_UNCONFIRMED"
    assert h.post_count() == 1


@pytest.mark.parametrize("clock", ["missing", "naive", "before", "equal"])
def test_direct_close_parser_requires_aware_execution_observation(h: Harness, clock: str) -> None:
    h.ticket = replace(h.ticket, action="close", position_id=99)
    key = h.authorize()
    payload = {
        "CID": 42,
        "instrumentID": 1,
        "orderID": 123,
        "statusID": 3,
        "positions": [{"positionID": 99, "units": 9, "rate": 100, "occurred": h.now.isoformat()}],
    }
    observed_at = {
        "missing": None,
        "naive": h.now.replace(tzinfo=None),
        "before": h.now - timedelta(microseconds=1),
        "equal": h.now,
    }[clock]
    if clock == "equal":
        result = reconcile_response(
            payload,
            json.loads(h.ticket.canonical()),
            h.identity,
            h.engine.record(key),
            observed_at=observed_at,
        )
        assert result[:2] == (OrderState.FILLED, True)
    else:
        with pytest.raises(ExecutionError, match="INVALID_EXECUTION_TIME"):
            reconcile_response(
                payload,
                json.loads(h.ticket.canonical()),
                h.identity,
                h.engine.record(key),
                observed_at=observed_at,
            )
    assert not h.requests


@pytest.mark.parametrize("missing", ["occurred", "rate", "units"])
def test_incomplete_close_execution_cannot_become_terminal_rejection(
    h: Harness, missing: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    h.ticket = replace(h.ticket, action="close", position_id=99)
    key = h.authorize()
    position = PositionEvidence("demo-account", 99, 1, Decimal(10), h.now, True)
    h.engine.submit(key, h.ticket, h.account, position=position)
    original_request = h.client._request

    def request(method: str, path: str, **kwargs: Any) -> tuple[int, dict[str, Any], int]:
        status, data, cooldown = original_request(method, path, **kwargs)
        data["positions"][0][missing] = None
        return status, data, cooldown

    monkeypatch.setattr(h.client, "_request", request)
    h.status_id, h.filled = 4, 9
    result = h.engine.reconcile(key)
    assert result.state == OrderState.UNKNOWN and not result.terminal
    assert result.executed_units == 0
    with h.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM reservations").fetchone() == (1,)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("DELETE", OPEN + "/123"),
        ("DELETE", CLOSE.replace("/positions/", "/") + "123"),
        ("POST", "/api/v1/trading/execution/demo/limit-orders"),
        ("POST", "/api/v2/trading/execution/demo/orders"),
    ],
)
def test_documented_but_unintegrated_mutations_remain_blocked(
    h: Harness, method: str, path: str
) -> None:
    with pytest.raises(ExecutionError, match="ENDPOINT_BLOCKED"):
        h.client._request(method, path, now=h.now)
    assert not h.requests
