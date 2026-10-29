"""Fail-closed parsing of documented Demo P&L available-cash fields."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

FIELDS = frozenset(
    {"response", "credit", "ordersForOpen", "orders", "mirrorID", "mirrorId", "amount", "availableCash"}
)


class IncompleteDemoSnapshot(ValueError):
    """Only fixed error categories and allowlisted field identifiers are retained."""

    def __init__(self, field: str = "response", category: str = "incompatible structure") -> None:
        self.field = field if field in FIELDS else "response"
        self.category = category if category in {
            "missing", "invalid type", "invalid value", "incompatible structure"
        } else "incompatible structure"
        super().__init__(f"{self.field}: {self.category}")


@dataclass(frozen=True)
class DemoCashObservation:
    credit: Decimal
    reserved_open: Decimal
    reserved_orders: Decimal
    available_cash: Decimal
    trusted_for_risk: bool = False


def _amount(value: Any, field: str) -> Decimal:
    if value is None:
        raise IncompleteDemoSnapshot(field, "missing")
    if isinstance(value, bool) or not isinstance(value, str | int | float | Decimal):
        raise IncompleteDemoSnapshot(field, "invalid type")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise IncompleteDemoSnapshot(field, "invalid value") from None
    if not number.is_finite() or number < 0 or len(number.as_tuple().digits) > 24:
        raise IncompleteDemoSnapshot(field, "invalid value")
    return number


def _required(data: Mapping[str, Any], field: str) -> Any:
    if field not in data:
        raise IncompleteDemoSnapshot(field, "missing")
    return data[field]


def normalize_demo_cash(data: Mapping[str, Any]) -> DemoCashObservation:
    """Calculate only verified cash amounts, never equity or account balance."""
    if not isinstance(data, Mapping):
        raise IncompleteDemoSnapshot("response", "invalid type")
    credit = _amount(_required(data, "credit"), "credit")
    opening = _required(data, "ordersForOpen")
    pending = _required(data, "orders")
    if not isinstance(opening, list):
        raise IncompleteDemoSnapshot("ordersForOpen", "invalid type")
    if not isinstance(pending, list):
        raise IncompleteDemoSnapshot("orders", "invalid type")
    reserved_open = Decimal(0)
    reserved_orders = Decimal(0)
    for item in opening:
        if not isinstance(item, dict):
            raise IncompleteDemoSnapshot("ordersForOpen", "incompatible structure")
        if "mirrorID" in item and "mirrorId" in item:
            raise IncompleteDemoSnapshot("mirrorID", "incompatible structure")
        mirror_key = "mirrorID" if "mirrorID" in item else "mirrorId"
        mirror_id = _required(item, mirror_key)
        if type(mirror_id) is not int:
            raise IncompleteDemoSnapshot("mirrorID", "invalid type")
        amount = _amount(_required(item, "amount"), "amount")
        if mirror_id == 0:
            reserved_open += amount
    for item in pending:
        if not isinstance(item, dict):
            raise IncompleteDemoSnapshot("orders", "incompatible structure")
        reserved_orders += _amount(_required(item, "amount"), "amount")
    available = credit - reserved_open - reserved_orders
    if not available.is_finite() or available < 0:
        raise IncompleteDemoSnapshot("availableCash", "invalid value")
    return DemoCashObservation(credit, reserved_open, reserved_orders, available)
