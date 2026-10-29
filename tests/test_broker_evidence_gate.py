"""Synthetic Phase 20 safety tests; no broker calls."""

from dataclasses import fields

import pytest

from etoro_demo_bot.broker_evidence_gate import BrokerEvidence, verify_evidence


def test_defaults_block_every_prerequisite() -> None:
    result = verify_evidence(BrokerEvidence())
    assert len(result.missing) == len(fields(BrokerEvidence))
    assert not result.valid_evidence
    assert not result.may_submit


def test_individual_missing_evidence_blocks() -> None:
    for missing in fields(BrokerEvidence):
        values = {field.name: field.name != missing.name for field in fields(BrokerEvidence)}
        result = verify_evidence(BrokerEvidence(**values))
        assert result.missing == (missing.name,)
        assert not result.may_submit


def test_complete_external_assertions_still_cannot_submit() -> None:
    values = {field.name: True for field in fields(BrokerEvidence)}
    result = verify_evidence(BrokerEvidence(**values))
    assert result.valid_evidence
    assert result.missing == ()
    assert not result.may_submit


@pytest.mark.parametrize("bad", [1, None, "true"])
def test_untrusted_types_rejected(bad: object) -> None:
    with pytest.raises(TypeError, match="booleans"):
        verify_evidence(BrokerEvidence(demo_key_scope_verified=bad))  # type: ignore[arg-type]
