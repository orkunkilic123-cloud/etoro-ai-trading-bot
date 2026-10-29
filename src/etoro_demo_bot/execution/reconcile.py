"""Strict documented status interpretation; partial terminal outcomes retain exposure."""

from decimal import Decimal
from typing import Any

from .models import DemoIdentity, ExecutionError, OrderRecord, OrderState
from .validation import number


def reconcile_response(
    data: dict[str, Any],
    ticket: dict[str, Any],
    identity: DemoIdentity,
    record: OrderRecord,
) -> tuple[OrderState, bool, int, Decimal, int]:
    p = ticket["proposal"]
    units = Decimal(p["units"])
    instrument = p["instrument_id"]
    close = ticket["action"] == "close"
    order_id = data.get("orderID" if close else "orderId")
    if (
        type(order_id) is not int
        or order_id <= 0
        or (record.broker_id is not None and order_id != record.broker_id)
    ):
        raise ExecutionError("ORDER_ID_MISMATCH")
    total = Decimal(0)
    seen: set[int] = set()
    if close:
        if (
            type(data.get("CID")) is not int
            or data.get("CID") != identity.customer_id
            or type(data.get("instrumentID")) is not int
            or data.get("instrumentID") != instrument
        ):
            raise ExecutionError("ORDER_IDENTITY_MISMATCH")
        status = data.get("statusID")
        positions = data.get("positions")
        if not isinstance(positions, list):
            raise ExecutionError("EXECUTIONS_MISSING")
        for item in positions:
            if (
                not isinstance(item, dict)
                or type(item.get("positionID")) is not int
                or item.get("positionID") != ticket["position_id"]
            ):
                raise ExecutionError("POSITION_MISMATCH")
            position_id = item["positionID"]
            if position_id in seen:
                raise ExecutionError("DUPLICATE_EXECUTION")
            seen.add(position_id)
            if item.get("occurred") is not None:
                if number(item.get("rate")) <= 0:
                    raise ExecutionError("INVALID_EXECUTION_RATE")
                total += number(item.get("units"))
    else:
        asset = data.get("asset", {})
        if (
            type(data.get("accountId")) is not int
            or data.get("accountId") != identity.broker_account_id
            or data.get("action") != "open"
            or data.get("transaction") != "buy"
            or data.get("type") != "mkt"
            or data.get("orderCurrency") not in ("usd", "USD")
            or not isinstance(asset, dict)
            or type(asset.get("instrumentId")) is not int
            or asset.get("instrumentId") != instrument
            or asset.get("settlementType") != "real"
            or type(asset.get("leverage")) is not int
            or asset.get("leverage") != 1
            or asset.get("side") != "long"
            or asset.get("currency") != "USD"
            or number(data.get("requestedUnits")) != units
        ):
            raise ExecutionError("ORDER_IDENTITY_MISMATCH")
        status_data = data.get("status")
        if not isinstance(status_data, dict):
            raise ExecutionError("UNKNOWN_BROKER_STATUS")
        status = status_data.get("id")
        positions = data.get("positionExecutions")
        if not isinstance(positions, list):
            raise ExecutionError("EXECUTIONS_MISSING")
        for item in positions:
            if not isinstance(item, dict):
                raise ExecutionError("POSITION_MISMATCH")
            position_id = item.get("positionId")
            if type(position_id) is not int or position_id <= 0 or position_id in seen:
                raise ExecutionError("POSITION_MISMATCH")
            seen.add(position_id)
            opening = item.get("openingData", {})
            if (
                not isinstance(opening, dict)
                or type(opening.get("orderId")) is not int
                or opening.get("orderId") != order_id
            ):
                raise ExecutionError("EXECUTION_ORDER_MISMATCH")
            total += number(opening.get("units"))
            if number(item.get("stopLossRate")) != Decimal(p["stop_loss"]):
                raise ExecutionError("STOP_LOSS_MISMATCH")
    if type(status) is not int or status not in range(1, 13) or (close and status == 12):
        raise ExecutionError("UNKNOWN_BROKER_STATUS")
    if total > units or total < record.executed_units:
        raise ExecutionError("EXECUTION_QUANTITY_MISMATCH")
    if status in {3, 5, 9, 10} and total <= 0:
        raise ExecutionError("EXECUTION_EVIDENCE_MISSING")
    if status in {1, 2, 4, 7, 8, 11, 12} and total != 0:
        raise ExecutionError("CONTRADICTORY_EXECUTION")
    if status in {5, 9, 10} and total >= units:
        raise ExecutionError("CONTRADICTORY_PARTIAL_FILL")
    if status == 3 and total != units:
        raise ExecutionError("INCOMPLETE_FILLED_ORDER")
    terminal = status in {3, 4, 7, 8, 9, 10}
    if status == 3:
        state = OrderState.FILLED
    elif status in {5, 9, 10}:
        state = OrderState.PARTIALLY_FILLED
    elif status == 4:
        state = OrderState.REJECTED
    elif status in {7, 8}:
        state = OrderState.CANCELLED
    else:
        state = OrderState.PENDING
    if record.terminal and (
        not terminal or state != record.state or total != record.executed_units
    ):
        raise ExecutionError("TERMINAL_STATE_CONFLICT")
    return state, terminal, status, total, order_id
