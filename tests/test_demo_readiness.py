"""Phase 17 readiness evidence must never create order authority."""

from dataclasses import fields

import pytest

from etoro_demo_bot.demo_readiness import DemoEvidence, assess


def test_default_blocks_everything() -> None:
    report = assess(DemoEvidence())
    assert not report.read_only_ready
    assert not report.trade_preparation_ready
    assert report.execution_authorized is False
    assert len(report.blockers) == len(fields(DemoEvidence))


def test_read_scope_does_not_authorize_orders() -> None:
    report = assess(
        DemoEvidence(
            official_contract_reviewed=True,
            demo_read_key_scope_verified=True,
            demo_identity_verified=True,
        )
    )
    assert report.read_only_ready
    assert not report.trade_preparation_ready
    assert "demo_portfolio_incomplete" in report.blockers
    assert report.execution_authorized is False


def test_even_all_attestations_do_not_authorize_orders() -> None:
    complete = {item.name: True for item in fields(DemoEvidence)}
    report = assess(DemoEvidence(**complete))
    assert report.read_only_ready
    assert report.trade_preparation_ready
    assert report.blockers == ()
    assert report.execution_authorized is False


@pytest.mark.parametrize("bad", [None, "yes", 1])
def test_invalid_evidence_fails_closed(bad: object) -> None:
    with pytest.raises(TypeError, match="explicit booleans"):
        assess(DemoEvidence(official_contract_reviewed=bad))  # type: ignore[arg-type]


def test_wrong_input_fails_closed() -> None:
    with pytest.raises(TypeError, match="DemoEvidence"):
        assess(None)  # type: ignore[arg-type]
