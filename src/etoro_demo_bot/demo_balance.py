"""Conservative formatting of a Demo portfolio observation; no broker requests.

Portfolio credit is NOT equity or total account balance. Reservation semantics
follow the official eToro available-cash guide and require complete order arrays.
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from .demo_cash import IncompleteDemoSnapshot, normalize_demo_cash


def display_demo_balance(data: Mapping[str, Any]) -> str:
    """Return only schema-supported USD cash observations, or fail closed."""
    portfolio = data.get("clientPortfolio")
    if not isinstance(portfolio, dict):
        raise IncompleteDemoSnapshot("Demo portfolio schema incomplete: clientPortfolio missing")
    # Currency identifiers are not universally documented across response versions.
    # Refuse to translate or guess an unknown currency ID.
    if portfolio.get("accountCurrencyId") != 1 or type(portfolio.get("accountCurrencyId")) is not int:
        raise IncompleteDemoSnapshot("Demo account currency could not be verified as USD")
    cash = normalize_demo_cash(portfolio)
    positions = portfolio.get("positions")
    mirrors = portfolio.get("mirrors")
    if not isinstance(positions, list) or not isinstance(mirrors, list):
        raise IncompleteDemoSnapshot("Demo position coverage is incomplete")
    if any(not isinstance(position, dict) for position in positions):
        raise IncompleteDemoSnapshot("Malformed Demo position")
    if mirrors:
        # Mirror position coverage cannot be certified from the direct positions list.
        position_text = "Not available (copy-trading coverage unverified)"
    else:
        position_text = str(len(positions))

    def amount(value: Decimal) -> str:
        return f"{value:.2f}"

    reserved = cash.reserved_open + cash.reserved_orders
    return (
        "Demo account currency: USD (accountCurrencyId=1)\n"
        "Total account balance: Not available (not established by portfolio credit)\n"
        "Equity: Not available (requires separate verified valuation)\n"
        f"Portfolio credit (before pending allocations): USD {amount(cash.credit)}\n"
        f"Available cash (calculated): USD {amount(cash.available_cash)}\n"
        f"Reserved cash (documented pending orders): USD {amount(reserved)}\n"
        f"Direct open positions: {position_text}\n"
        "Read-only Demo observation; not a risk or trading authorization."
    )
