"""Simulation-owned reservation handoff. Never opens an existing production safety store."""

import hashlib
from datetime import datetime
from decimal import Decimal, localcontext
from pathlib import Path

from ..risk import AccountSnapshot, Decision, Proposal, RiskEngine, RiskStore


def fingerprint(p: Proposal) -> str:
    with localcontext() as context:
        context.prec = 60
        assert p.price is not None and p.stop_loss is not None
        values = [
            str(p.instrument_id),
            str(p.units.normalize()),
            str(p.price.normalize()),
            str(p.stop_loss.normalize()),
            str((p.cost_buffer or Decimal(0)).normalize()),
        ]
        return hashlib.sha256("|".join(values).encode()).hexdigest()


class SimulationRisk(RiskEngine):
    def __init__(self, new_path: Path, *, killed: bool) -> None:
        store = RiskStore.initialize(new_path, "backtest-demo")
        super().__init__(store)
        with store.transaction() as db:
            db.execute(
                "CREATE TABLE simulated_tombstones(proposal TEXT, fingerprint TEXT, "
                "PRIMARY KEY(proposal,fingerprint))"
            )
        if not killed:
            store.set_kill_switch(False, acknowledged=True)

    def evaluate(self, proposal: Proposal, account: AccountSnapshot, *, now: datetime) -> Decision:
        # Check archived economic intents before unchanged production risk validation.
        with self.store.transaction() as db:
            duplicate = db.execute(
                "SELECT 1 FROM simulated_tombstones WHERE proposal=? OR fingerprint=?",
                (proposal.proposal_id, fingerprint(proposal)),
            ).fetchone()
        if duplicate:
            return Decision(False, ("DUPLICATE_PROPOSAL",))
        return super().evaluate(proposal, account, now=now)

    def retire(self, proposal_id: str) -> None:
        with self.store.transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO simulated_tombstones SELECT "
                "proposal,fingerprint FROM reservations WHERE proposal=?",
                (proposal_id,),
            )
            db.execute("DELETE FROM reservations WHERE proposal=?", (proposal_id,))

    def admit_fill(
        self, proposal: Proposal, account: AccountSnapshot, *, now: datetime
    ) -> Decision:
        # Current fill price/size/costs pass all original rules, excluding only its own reservation.
        with self.store.transaction() as db:
            old = db.execute(
                "SELECT proposal,fingerprint FROM reservations WHERE proposal=?",
                (proposal.proposal_id,),
            ).fetchone()
            if old is None:
                return Decision(False, ("MISSING_SIMULATION_RESERVATION",))
            db.execute("DELETE FROM reservations WHERE proposal=?", (proposal.proposal_id,))
            result = self.evaluate_in_transaction(db, proposal, account, now=now)
            db.execute("INSERT OR IGNORE INTO simulated_tombstones VALUES(?,?)", old)
            if result.passed:
                db.execute(
                    "INSERT OR IGNORE INTO simulated_tombstones SELECT "
                    "proposal,fingerprint FROM reservations WHERE proposal=?",
                    (proposal.proposal_id,),
                )
                db.execute("DELETE FROM reservations WHERE proposal=?", (proposal.proposal_id,))
            return result

    def observe(self, account: AccountSnapshot, iid: int, *, now: datetime) -> Decision:
        # RiskEngine validates account and latches daily loss BEFORE rejecting zero-size probe.
        p = Proposal(
            "equity-observation", iid, Decimal(0), Decimal(1), Decimal(".5"), now, Decimal(0)
        )
        return super().evaluate(p, account, now=now)
