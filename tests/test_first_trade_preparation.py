"""Offline first-trade gate regression tests; never authenticates or orders."""

from dataclasses import fields

import pytest

from etoro_demo_bot.first_trade_preparation import TradeEvidence, prepare_first_demo_trade


def test_no_evidence_denies_every_gate() -> None:
    result = prepare_first_demo_trade(TradeEvidence())
    assert len(result.blockers) == len(fields(TradeEvidence))
    assert not result.ready_to_request_owner_approval
    assert not result.execution_authorized


def test_each_missing_evidence_denies_approval() -> None:
    for missing in fields(TradeEvidence):
        values = {item.name: item.name != missing.name for item in fields(TradeEvidence)}
        result = prepare_first_demo_trade(TradeEvidence(**values))
        assert result.blockers == (missing.name,)
        assert not result.ready_to_request_owner_approval
        assert not result.execution_authorized


def test_complete_attestations_still_cannot_execute() -> None:
    values = {item.name: True for item in fields(TradeEvidence)}
    result = prepare_first_demo_trade(TradeEvidence(**values))
    assert result.ready_to_request_owner_approval
    assert not result.execution_authorized


@pytest.mark.parametrize("bad", [None, "yes", 1])
def test_non_boolean_evidence_rejected(bad: object) -> None:
    with pytest.raises(TypeError, match="explicit booleans"):
        prepare_first_demo_trade(TradeEvidence(demo_identity=bad))  # type: ignore[arg-type]


def test_wrong_object_rejected() -> None:
    with pytest.raises(TypeError, match="TradeEvidence"):
        prepare_first_demo_trade(None)  # type: ignore[arg-type]
