"""Mocked v3/lookup regressions; no credentials or authenticated broker requests."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from test_execution import Harness

from etoro_demo_bot.execution import ExecutionError, OrderState
from etoro_demo_bot.execution.reconcile import reconcile_response


@pytest.mark.parametrize("status", [1, 2, 3, 4, 7, 8, 11, 12])
def test_contradictory_partial_quantities_remain_unknown(tmp_path: Path, status: int) -> None:
    h = Harness(tmp_path / "risk.sqlite")
    order = h.authorize()
    h.engine.submit(order, h.ticket, h.account)
    h.status_id, h.filled = status, 3  # 9 units requested; neither full nor zero.
    observed = h.engine.reconcile(order)
    assert observed.state == OrderState.UNKNOWN
    assert not observed.terminal
    assert observed.executed_units == 0
    assert h.post_count() == 1
    with h.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 1
    # Recovery never retries the original order, including after a restart.
    h.now += timedelta(seconds=4)
    h.engine = h.new_engine()
    h.engine.recover()
    assert h.post_count() == 1
    h.client.close()


@pytest.mark.parametrize("status", [5, 6, 9, 10])
def test_documented_partial_cancel_states_preserve_units(tmp_path: Path, status: int) -> None:
    h = Harness(tmp_path / "risk.sqlite")
    order = h.authorize()
    h.engine.submit(order, h.ticket, h.account)
    h.status_id, h.filled = status, 3
    observed = h.engine.reconcile(order)
    assert observed.executed_units == 3
    assert observed.terminal == (status in (9, 10))
    assert observed.state == (OrderState.PENDING if status == 6 else OrderState.PARTIALLY_FILLED)
    h.client.close()


def payload() -> dict[str, Any]:
    return {
        "accountId": 43,
        "orderId": 123,
        "action": "open",
        "transaction": "buy",
        "type": "mkt",
        "orderCurrency": "usd",
        "requestedUnits": 9,
        "asset": {
            "instrumentId": 1,
            "settlementType": "real",
            "leverage": 1,
            "side": "long",
            "currency": "USD",
        },
        "status": {"id": 5},
        "positionExecutions": [
            {"positionId": 99, "stopLossRate": 90, "openingData": {"orderId": 123, "units": 3}}
        ],
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "account",
        "instrument",
        "currency",
        "status",
        "item",
        "opening",
        "order_id",
        "negative",
        "duplicate",
    ],
)
def test_malformed_lookup_rejected_with_fixed_error(tmp_path: Path, mutation: str) -> None:
    import json

    h = Harness(tmp_path / "risk.sqlite")
    order = h.authorize()
    data = payload()
    if mutation == "account":
        data["accountId"] = Decimal(43)
    elif mutation == "instrument":
        data["asset"]["instrumentId"] = True
    elif mutation == "currency":
        data["orderCurrency"] = {"unexpected": "SYNTHETIC_PRIVATE_DATA"}
    elif mutation == "status":
        data["status"] = None
    elif mutation == "item":
        data["positionExecutions"] = [None]
    elif mutation == "opening":
        data["positionExecutions"][0]["openingData"] = None
    elif mutation == "order_id":
        data["positionExecutions"][0]["openingData"]["orderId"] = Decimal(123)
    elif mutation == "negative":
        data["positionExecutions"][0]["openingData"]["units"] = -1
    else:
        data["positionExecutions"] *= 2
    with pytest.raises(ExecutionError) as caught:
        reconcile_response(
            data, json.loads(h.ticket.canonical()), h.identity, h.engine.record(order)
        )
    assert "SYNTHETIC_PRIVATE_DATA" not in str(caught.value)
    assert not h.requests
    h.client.close()


def test_terminal_partial_cannot_be_reopened_by_parser(tmp_path: Path) -> None:
    import json

    h = Harness(tmp_path / "risk.sqlite")
    order = h.authorize()
    record = replace(
        h.engine.record(order),
        terminal=True,
        state=OrderState.PARTIALLY_FILLED,
        broker_id=123,
        broker_status=9,
        executed_units=Decimal(3),
    )
    with pytest.raises(ExecutionError, match="TERMINAL_STATE_CONFLICT"):
        reconcile_response(payload(), json.loads(h.ticket.canonical()), h.identity, record)
    h.client.close()
