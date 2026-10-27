"""Fail-closed validation of published eToro eligibility fields."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from ..risk.engine import fresh
from ..risk.models import money
from .models import ExecutionError, PositionEvidence, Ticket


def number(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | Decimal):
        raise ExecutionError("INVALID_BROKER_NUMBER")
    result = Decimal(value)
    if not money(result):
        raise ExecutionError("INVALID_BROKER_NUMBER")
    return result


def validate_eligibility(
    ticket: Ticket,
    raw: dict[str, Any],
    *,
    position: PositionEvidence | None,
    now: datetime,
    max_age: int,
) -> None:
    p = ticket.proposal
    if (
        ticket.action not in {"open", "close"}
        or ticket.asset_currency != "USD"
        or p.side != "buy"
        or p.leverage != 1
        or p.settlement != "real"
        or p.underlying_verified is not True
        or not money(p.units, positive=True)
        or not money(p.price, positive=True)
    ):
        raise ExecutionError("INVALID_TICKET")
    if (
        raw.get("currency") != "USD"
        or raw.get("notFoundInstrumentIds")
        or raw.get("notFoundSymbols")
    ):
        raise ExecutionError("ELIGIBILITY_UNCONFIRMED")
    entries = raw.get("eligibilities")
    if not isinstance(entries, list) or len(entries) != 1:
        raise ExecutionError("ELIGIBILITY_UNCONFIRMED")
    e = entries[0]
    if (
        not isinstance(e, dict)
        or type(e.get("instrumentId")) is not int
        or e.get("instrumentId") != p.instrument_id
    ):
        raise ExecutionError("INSTRUMENT_MISMATCH")
    configs = e.get("leverageConfigs")
    if not isinstance(configs, list):
        raise ExecutionError("ELIGIBILITY_UNCONFIRMED")
    matching = [
        c
        for c in configs
        if isinstance(c, dict)
        and c.get("settlementType") == "real"
        and c.get("direction") == "long"
        and c.get("isPotential") is False
        and isinstance(c.get("leverageValues"), list)
        and any(type(v) is int and v == 1 for v in c["leverageValues"])
    ]
    if len(matching) != 1 or e.get("tradeUnitType") != "units":
        raise ExecutionError("LEVERAGE_CONFIGURATION_UNCONFIRMED")
    c = matching[0]
    if e.get("unitsQuantityType") not in {"whole", "fractional"}:
        raise ExecutionError("QUANTITY_TYPE_UNCONFIRMED")
    if e["unitsQuantityType"] == "whole" and p.units != p.units.to_integral_value():
        raise ExecutionError("WHOLE_UNITS_REQUIRED")
    if p.units > number(e.get("maxUnitsPerOrder")):
        raise ExecutionError("BROKER_SIZE_LIMIT")
    if ticket.action == "close":
        if (
            position is None
            or position.account_id != ticket.account_id
            or position.position_id != ticket.position_id
            or type(ticket.position_id) is not int
            or ticket.position_id <= 0
            or position.instrument_id != p.instrument_id
            or position.underlying_long_unleveraged is not True
            or not money(position.units, positive=True)
            or p.units > position.units
            or not fresh(position.observed_at, now, max_age)
            or e.get("allowClosePosition") is not True
            or (p.units < position.units and e.get("allowPartialClosePosition") is not True)
        ):
            raise ExecutionError("CLOSE_POSITION_UNCONFIRMED")
        return
    if ticket.position_id is not None or e.get("allowOpenPosition") is not True:
        raise ExecutionError("OPEN_NOT_ALLOWED")
    if e.get("allowedOrderQuantityType") not in {"unitsOnly", "all"}:
        raise ExecutionError("UNITS_NOT_ALLOWED")
    assert p.price is not None
    amount = p.units * p.price
    if amount < max(number(e.get("minPositionExposure")), number(c.get("minPositionAmount"))):
        raise ExecutionError("BELOW_MINIMUM_SIZE")
    buffer = e.get("additionalBufferPercent")
    if buffer is not None and number(buffer) > 0:
        # Percent convention is not sufficiently specified; never guess reserved funds.
        raise ExecutionError("BROKER_BUFFER_UNSUPPORTED")
    if c.get("allowStopLossTakeProfit") is not True or not money(p.stop_loss, positive=True):
        raise ExecutionError("STOP_LOSS_UNCONFIRMED")
    assert p.stop_loss is not None
    percentage = (p.price - p.stop_loss) / p.price * 100
    if (
        not number(c.get("minStopLossPercentage"))
        <= percentage
        <= number(c.get("maxStopLossPercentage"))
    ):
        raise ExecutionError("STOP_LOSS_OUT_OF_RANGE")
