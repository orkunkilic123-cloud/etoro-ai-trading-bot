"""Offline owner comparison of Demo observations; cannot enable trading.

Only compare explicitly supplied and independently reviewed observations.
Do not accept raw broker response objects as authoritative input.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class ComparisonUnavailable(ValueError):
    """Generic, non-sensitive reason for missing comparison evidence."""


@dataclass(frozen=True)
class OwnerComparison:
    matches: bool
    differences: tuple[str, ...]
    verified_for_execution: bool = False


def _money(value: str) -> Decimal:
    if type(value) is not str or not value or len(value) > 50:
        raise ComparisonUnavailable("Invalid comparison amount")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ComparisonUnavailable("Invalid comparison amount") from None
    if not result.is_finite() or result < 0 or -12 > result.as_tuple().exponent:
        raise ComparisonUnavailable("Invalid comparison amount")
    return result


def compare_demo_observations(
    *,
    api_available_cash: str,
    interface_available_cash: str,
    api_position_count: int,
    interface_position_count: int,
) -> OwnerComparison:
    """Check synthetic or manually reviewed values; never authorize orders."""
    if (
        type(api_position_count) is not int
        or type(interface_position_count) is not int
        or api_position_count < 0
        or interface_position_count < 0
    ):
        raise ComparisonUnavailable("Position count missing or invalid")
    api_cash = _money(api_available_cash)
    ui_cash = _money(interface_available_cash)
    differences = []
    if api_cash != ui_cash:
        differences.append("available_cash_mismatch")
    if api_position_count != interface_position_count:
        differences.append("position_count_mismatch")
    return OwnerComparison(not differences, tuple(differences))
