"""Synthetic read-only cash fixtures; no broker access."""

from decimal import Decimal

import pytest

from etoro_demo_bot.demo_cash import IncompleteDemoSnapshot, normalize_demo_cash


def test_official_available_cash_example() -> None:
    observation = normalize_demo_cash({
        "credit": "1000",
        "ordersForOpen": [
            {"mirrorID": 0, "amount": "200"},
            {"mirrorID": 0, "amount": "200"},
            {"mirrorID": 42, "amount": "100"},
        ],
        "orders": [{"amount": "150"}],
    })
    assert observation.available_cash == Decimal("450")
    assert observation.reserved_open == Decimal("400")
    assert observation.trusted_for_risk is False


def test_zero_pending_is_explicit() -> None:
    observation = normalize_demo_cash({
        "credit": "25.10", "ordersForOpen": [], "orders": [],
    })
    assert observation.available_cash == Decimal("25.10")


@pytest.mark.parametrize("bad", [
    {},
    {"credit": 1000, "ordersForOpen": [], "orders": None},
    {"credit": 1000, "ordersForOpen": [{}], "orders": []},
    {"credit": "NaN", "ordersForOpen": [], "orders": []},
    {"credit": True, "ordersForOpen": [], "orders": []},
    {"credit": 10, "ordersForOpen": [], "orders": [{"amount": -1}]},
    {"credit": 10, "ordersForOpen": [{"mirrorID": True, "amount": 1}], "orders": []},
    {"credit": 10, "ordersForOpen": [], "orders": [{"amount": 11}]},
])
def test_incomplete_or_unsafe_snapshot_blocks(bad: dict[str, object]) -> None:
    with pytest.raises(IncompleteDemoSnapshot):
        normalize_demo_cash(bad)
