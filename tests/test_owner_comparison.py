"""Offline owner comparison regression tests; synthetic data only."""

import pytest

from etoro_demo_bot.owner_comparison import (
    ComparisonUnavailable,
    compare_demo_observations,
)


def test_equal_values_do_not_grant_execution() -> None:
    result = compare_demo_observations(
        api_available_cash="100.00",
        interface_available_cash="100",
        api_position_count=2,
        interface_position_count=2,
    )
    assert result.matches
    assert result.differences == ()
    assert not result.verified_for_execution


def test_discrepancies_are_named_without_disclosing_values() -> None:
    result = compare_demo_observations(
        api_available_cash="100",
        interface_available_cash="99",
        api_position_count=2,
        interface_position_count=1,
    )
    assert not result.matches
    assert result.differences == ("available_cash_mismatch", "position_count_mismatch")
    assert not result.verified_for_execution


@pytest.mark.parametrize(
    ("api_cash", "ui_cash", "api_count", "ui_count"),
    [
        ("NaN", "100", 0, 0),
        ("100", "Infinity", 0, 0),
        ("-1", "0", 0, 0),
        ("", "0", 0, 0),
        ("100", "100", -1, 0),
        ("100", "100", 1, True),
        ("100", "100", 0, "0"),
    ],
)
def test_invalid_or_missing_values_block(
    api_cash: str, ui_cash: str, api_count: int, ui_count: int
) -> None:
    with pytest.raises(ComparisonUnavailable):
        compare_demo_observations(
            api_available_cash=api_cash,
            interface_available_cash=ui_cash,
            api_position_count=api_count,
            interface_position_count=ui_count,
        )
