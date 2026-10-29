"""Conservative presentation of eToro's documented Demo P&L USD cash formula."""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from .demo_cash import IncompleteDemoSnapshot, normalize_demo_cash


def display_demo_balance(data: Mapping[str, Any]) -> str:
    """Show verified P&L cash figures; do not infer total balance or equity."""
    if not isinstance(data, Mapping):
        raise IncompleteDemoSnapshot("Invalid Demo P&L response")
    # Official guide documents these fields on the P&L response itself.
    cash = normalize_demo_cash(data)
    reserved = cash.reserved_open + cash.reserved_orders

    # Values in the P&L cash formula are USD only. This does not establish
    # the user's separate base/account currency.
    def money(value: Decimal) -> str:
        result = format(value, "f")
        return result + (
            "." + "00" if "." not in result else "0" if len(result.split(".")[1]) == 1 else ""
        )

    return (
        "Cash denomination: USD (official P&L cash formula; account currency unverified)\n"
        "Total account balance: Unavailable (no independently verified field)\n"
        "Equity: Unavailable (invested capital and unrealized P&L not verified)\n"
        f"Credit (P&L field; not equity): USD {money(cash.credit)}\n"
        f"Reserved pending orders (calculated): USD {money(reserved)}\n"
        f"Available cash (calculated): USD {money(cash.available_cash)}\n"
        "Open positions: Unavailable (not independently verified)\n"
        "Read-only Demo observation; never trading or risk authorization."
    )
