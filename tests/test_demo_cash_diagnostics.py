"""Offline field-only diagnostics: no account details are emitted."""

import pytest

from etoro_demo_bot.demo_cash import IncompleteDemoSnapshot, normalize_demo_cash


@pytest.mark.parametrize(
    ("payload", "field", "category"),
    [
        ({}, "credit", "missing"),
        ({"credit": None}, "credit", "missing"),
        ({"credit": []}, "credit", "invalid type"),
        ({"credit": "not-a-number"}, "credit", "invalid value"),
        ({"credit": 1}, "ordersForOpen", "missing"),
        ({"credit": 1, "ordersForOpen": {}}, "orders", "missing"),
        ({"credit": 1, "ordersForOpen": (), "orders": []}, "ordersForOpen", "invalid type"),
        ({"credit": 1, "ordersForOpen": [], "orders": {}}, "orders", "invalid type"),
        ({"credit": 1, "ordersForOpen": [1], "orders": []}, "ordersForOpen", "incompatible structure"),
        ({"credit": 1, "ordersForOpen": [{}], "orders": []}, "mirrorID", "missing"),
        ({"credit": 1, "ordersForOpen": [{"mirrorID": "0"}], "orders": []}, "mirrorID", "invalid type"),
        ({"credit": 1, "ordersForOpen": [{"mirrorID": 0}], "orders": []}, "amount", "missing"),
        ({"credit": 1, "ordersForOpen": [{"mirrorID": 0, "amount": "bad"}], "orders": []}, "amount", "invalid value"),
        ({"credit": 1, "ordersForOpen": [], "orders": [None]}, "orders", "incompatible structure"),
        ({"credit": 1, "ordersForOpen": [], "orders": [{"amount": 2}]}, "availableCash", "invalid value"),
    ],
)
def test_exact_diagnostic(payload: dict[str, object], field: str, category: str) -> None:
    with pytest.raises(IncompleteDemoSnapshot) as caught:
        normalize_demo_cash(payload)
    assert (caught.value.field, caught.value.category) == (field, category)
    assert str(caught.value) == f"{field}: {category}"


def test_untrusted_field_name_never_printed() -> None:
    with pytest.raises(IncompleteDemoSnapshot) as caught:
        normalize_demo_cash({
            "credit": 1,
            "ordersForOpen": [],
            "orders": [{"amount": {"PRIVATE_ACCOUNT_IDENTIFIER": "SECRET"}}],
        })
    assert caught.value.field == "amount"
    assert "PRIVATE" not in str(caught.value)
    assert "SECRET" not in str(caught.value)
