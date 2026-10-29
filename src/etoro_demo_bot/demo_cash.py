"""Offline Demo P&L cash normalization, never a trusted account attestation.

The official eToro available-cash formula subtracts manual opening and all
pending MIT order allocations from credit. No outbound requests are made.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Context, Decimal, InvalidOperation, localcontext
from typing import Any


class IncompleteDemoSnapshot(ValueError):
    """Fail closed without embedding source data in error messages."""


@dataclass(frozen=True)
class DemoCashObservation:
    credit: Decimal
    reserved_open: Decimal
    reserved_orders: Decimal
    available_cash: Decimal
    # An observation does not attest account identity, equity or position completeness.
    trusted_for_risk: bool = False


def _amount(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str | int | Decimal):
        raise IncompleteDemoSnapshot("Invalid amount")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise IncompleteDemoSnapshot("Invalid amount") from None
    if (
        not number.is_finite()
        or number < 0
        or len(number.as_tuple().digits) > 24
        or abs(int(number.as_tuple().exponent)) > 12
    ):
        raise IncompleteDemoSnapshot("Invalid amount")
    return number


def _normalize_demo_cash(data: Mapping[str, Any]) -> DemoCashObservation:
    """Parse a complete P&L payload using documented conservative reservations."""
    if not isinstance(data, Mapping):
        raise IncompleteDemoSnapshot("Invalid Demo P&L snapshot")
    credit = _amount(data.get("credit"))
    opening = data.get("ordersForOpen")
    pending = data.get("orders")
    if not isinstance(opening, list) or not isinstance(pending, list):
        raise IncompleteDemoSnapshot("Pending orders missing")
    reserved_open = Decimal(0)
    reserved_orders = Decimal(0)
    for item in opening:
        if not isinstance(item, dict) or type(item.get("mirrorID")) is not int:
            raise IncompleteDemoSnapshot("Opening order incomplete")
        amount = _amount(item.get("amount"))
        if item["mirrorID"] == 0:
            reserved_open += amount
    for item in pending:
        if not isinstance(item, dict):
            raise IncompleteDemoSnapshot("Pending order incomplete")
        reserved_orders += _amount(item.get("amount"))
    remaining = credit - reserved_open - reserved_orders
    if not remaining.is_finite() or remaining < 0:
        raise IncompleteDemoSnapshot("Available cash cannot be established")
    return DemoCashObservation(credit, reserved_open, reserved_orders, remaining)


def normalize_demo_cash(data: Mapping[str, Any]) -> DemoCashObservation:
    """Isolate monetary arithmetic from the caller precision and rounding settings."""
    with localcontext(Context(prec=60)):
        return _normalize_demo_cash(data)


def normalize_demo_pnl_response(data: Mapping[str, Any]) -> DemoCashObservation:
    """Parse the documented PortfolioResponseWithPnl clientPortfolio envelope.

    JSON callers must decode numbers as Decimal, not binary floats. This only
    normalizes cash; it does not attest identity, positions or execution state.
    """
    if not isinstance(data, Mapping) or not isinstance(data.get("clientPortfolio"), Mapping):
        raise IncompleteDemoSnapshot("Demo P&L envelope missing")
    portfolio = data["clientPortfolio"]
    opening = portfolio.get("ordersForOpen")
    if not isinstance(opening, list):
        raise IncompleteDemoSnapshot("Opening orders missing")
    normalized = []
    for item in opening:
        if not isinstance(item, Mapping) or type(item.get("mirrorId")) is not int:
            raise IncompleteDemoSnapshot("Opening order incomplete")
        normalized.append({"mirrorID": item["mirrorId"], "amount": item.get("amount")})
    return normalize_demo_cash(
        {
            "credit": portfolio.get("credit"),
            "ordersForOpen": normalized,
            "orders": portfolio.get("orders"),
        }
    )
