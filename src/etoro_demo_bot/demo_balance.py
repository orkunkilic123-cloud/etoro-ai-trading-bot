"""Fail-closed Demo balance validation for the existing portfolio-only read.

eToro's official USD cash/equity formulas require the distinct Demo P&L
response. A successful Demo portfolio GET is not balance-schema attestation.
"""

from collections.abc import Mapping
from typing import Any

from .demo_cash import IncompleteDemoSnapshot


def display_demo_balance(data: Mapping[str, Any]) -> str:
    """Do not silently apply the P&L formula to a different API schema."""
    if not isinstance(data, Mapping) or not isinstance(data.get("clientPortfolio"), dict):
        raise IncompleteDemoSnapshot("Demo portfolio response is incomplete")
    raise IncompleteDemoSnapshot(
        "Demo cash, equity and currency cannot be verified from the portfolio schema; "
        "official eToro documentation requires the separately documented Demo P&L response"
    )
