"""Offline application integration, durable run ownership and safe local reporting."""

import ast
import json
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from etoro_demo_bot.backtest.engine import Backtest, Result
from etoro_demo_bot.shadow.app import run_once
from etoro_demo_bot.shadow.reports import dashboard, periods
from etoro_demo_bot.shadow.store import Runs, ShadowError

NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Offline shadow application must never connect to a service")

    monkeypatch.setattr(socket.socket, "connect", blocked)


@pytest.mark.parametrize(
    ("pipeline", "eur"), [("hourly", 500), ("hourly", 1000), ("orb", 500), ("orb", 1000)]
)
def test_existing_pipelines_end_to_end(tmp_path: Path, pipeline: str, eur: int) -> None:
    store = Runs.initialize(tmp_path / "shadow")
    identity = run_once(store, pipeline, eur, now=NOW)
    assert store.rows()[0][-1] == "completed"
    summary = json.loads((store.root / identity / "summary.json").read_text())
    assert summary["mode"] == "SHADOW" and summary["evidence"] == "SYNTHETIC"
    assert summary["execution_enabled"] is False
    assert summary["daily"] and summary["weekly"]
    assert summary["daily"][0]["valuation_currency"] == ("EUR" if pipeline == "orb" else "USD")
    full = json.loads((store.root / identity / "report" / "report.json").read_text())
    from decimal import Decimal as D

    expected_fees: D | int = sum(D(str(e.get("fx_cost", 0))) for e in full["events"])
    expected_fees += sum(
        D(str(e.get("commission", e.get("fee_usd", 0))))
        for e in full["events"]
        if e["kind"] == "entry_fill"
    )
    expected_fees += sum(D(str(t.get("commission", t.get("fee_usd", 0)))) for t in full["trades"])
    assert sum(D(p["attributed_fees_and_funding_usd"]) for p in summary["daily"]) == expected_fees
    expected_pnl = sum(D(t.get("pnl", t.get("pnl_usd"))) for t in full["trades"])
    assert sum(D(p["realized_exit_pnl_usd"]) for p in summary["daily"]) == expected_pnl
    assert sum(p["exit_fill_count"] for p in summary["daily"]) == len(full["trades"])
    assert summary["metrics"]["trading_costs_usd"] >= 0
    assert summary["improvement_proposals"]
    from etoro_demo_bot.shadow.reports import EXPORTS, load_summary

    verified, integrity = load_summary(store.root / identity)
    assert verified == summary and integrity.startswith("Local export checksums verified")
    for filename in (*EXPORTS, "shadow-checksums.json"):
        content = (store.root / identity / filename).read_bytes()
        assert b"\r\n" not in content
        content.decode("utf-8")
    import csv

    with (store.root / identity / "periods.csv").open(encoding="utf-8", newline="") as stream:
        csv_rows = list(csv.DictReader(stream))
    assert len(csv_rows) == len(summary["daily"]) + len(summary["weekly"])
    assert csv_rows[0]["ending_equity"] == summary["daily"][0]["ending_equity"]
    markdown = (store.root / identity / "daily.md").read_text(encoding="utf-8")
    assert "SHADOW / SYNTHETIC" in markdown and "UNVERIFIED" in markdown
    assert summary["daily"][0]["observed_start_at"] in markdown
    assert (store.root / identity / "state").is_dir()
    text = (store.root / "dashboard.html").read_text()
    assert "UNVERIFIED" in text and "broker execution disabled" in text
    assert "Daily replay periods" in text and "Proposed experiments" in text
    assert "daily.md" in text and "periods.csv" in text
    with pytest.raises(ShadowError, match="ALREADY_CLAIMED"):
        run_once(Runs(store.root), pipeline, eur, now=NOW)


def test_atomic_duplicate_claim_and_restart(tmp_path: Path) -> None:
    store = Runs.initialize(tmp_path / "shadow")

    def claim() -> str:
        try:
            return Runs(store.root).claim("orb", 500, NOW.date(), now=NOW)
        except ShadowError:
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as workers:
        values = list(workers.map(lambda _: claim(), range(2)))
    assert values.count("blocked") == 1
    assert Runs(store.root).rows()[0][-1] == "running"
    with pytest.raises(ShadowError, match="ALREADY_CLAIMED"):
        claim_id = Runs(store.root).claim("orb", 500, NOW.date(), now=NOW)
        pytest.fail(claim_id)


def test_missed_slots_are_not_backfilled(tmp_path: Path) -> None:
    store = Runs.initialize(tmp_path / "shadow")
    identity = store.claim("orb", 500, NOW.date(), now=NOW)
    store.finish(identity, "completed")
    later = NOW + timedelta(days=3)
    store.claim("orb", 500, later.date(), now=later)
    assert [r[-1] for r in store.rows()] == ["completed", "missed", "missed", "running"]
    with pytest.raises(ShadowError, match="INVALID_OR_MISSED"):
        store.claim("orb", 500, NOW.date(), now=later)
    with pytest.raises(ShadowError, match="CLOCK_ROLLBACK"):
        store.claim("orb", 500, NOW.date(), now=NOW)


def test_failure_persisted_never_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etoro_demo_bot.shadow import app

    store = Runs.initialize(tmp_path / "shadow")

    def broken() -> Any:
        raise ValueError("Synthetic data adapter failed")

    monkeypatch.setattr(app, "hourly_dataset", broken)
    with pytest.raises(ValueError):
        run_once(store, "hourly", 500, now=NOW)
    assert store.rows()[0][-1] == "failed"
    assert "failed" in (store.root / "dashboard.html").read_text()
    with pytest.raises(ShadowError, match="ALREADY_CLAIMED"):
        run_once(store, "hourly", 500, now=NOW)


def test_missing_state_and_existing_initialization_block(tmp_path: Path) -> None:
    import sqlite3

    root = tmp_path / "shadow"
    with pytest.raises(sqlite3.OperationalError):
        Runs(root).rows()
    Runs.initialize(root)
    with pytest.raises(FileExistsError):
        Runs.initialize(root)


def test_reports_group_replay_days_and_weeks_without_double_counting() -> None:
    points = tuple(
        {"at": stamp, "equity": equity, "exposure": "10"}
        for stamp, equity in (
            ("2026-01-04T12:00:00+00:00", "100"),
            ("2026-01-04T16:00:00+00:00", "98"),
            ("2026-01-05T12:00:00+00:00", "97"),
            ("2026-01-05T16:00:00+00:00", "99"),
        )
    )
    result = Result(
        {"shadow_valuation_currency": "USD"},
        {"trading_costs_usd": 2},
        (
            {"at": points[0]["at"], "kind": "funding", "fx_cost": "1"},
            {"at": points[1]["at"], "kind": "signal_rejected"},
        ),
        points,
        (),
        (),
        {},
    )
    daily = periods(result, weekly=False)
    assert [p["net_equity_change"] for p in daily] == ["-2", "1"]
    assert daily[0]["rejected_or_missed"] == 1
    assert daily[0]["attributed_fees_and_funding_usd"] == "1"
    assert all(p["total_cost_usd"] is None for p in daily)
    assert [p["period"] for p in periods(result, weekly=True)] == ["2026-W01", "2026-W02"]


def test_dashboard_escapes_untrusted_database_text_and_stale_state(tmp_path: Path) -> None:
    store = Runs.initialize(tmp_path / "shadow")
    with store.connect() as db:
        db.execute(
            "INSERT INTO runs VALUES(?,?,?,?,?)",
            ('" onclick="alert(1)', "<script>alert(1)</script>", 500, "2026-01-01", "completed"),
        )
    dashboard(store, now=NOW)
    text = (store.root / "dashboard.html").read_text()
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert "onclick=" not in text and "STALE RUN" in text


def test_no_broker_or_credential_imports() -> None:
    root = Path(__file__).parents[1] / "src/etoro_demo_bot/shadow"
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [n.name for n in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not any(
                p in n.split(".")
                for n in names
                for p in ("client", "execution", "config", "httpx", "requests", "os")
            )


def test_blocked_replay_is_recorded_and_fails_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Runs.initialize(tmp_path / "shadow")
    blocked = Result(
        {"status": "blocked", "limitations": ["SYNTHETIC_BLOCKER"]}, {}, (), (), (), (), {}
    )
    monkeypatch.setattr(Backtest, "run", lambda self, directory: blocked)
    with pytest.raises(ShadowError, match="RESEARCH_BLOCKED"):
        run_once(store, "hourly", 500, now=NOW)
    assert store.rows()[0][-1] == "blocked"
    assert "blocked" in (store.root / "dashboard.html").read_text()


def test_hourly_decisions_risk_rejections_and_no_duplicate_journal_counts() -> None:
    from etoro_demo_bot.shadow.reports import recommendations

    stamp = NOW.isoformat()
    result = Result(
        {"shadow_valuation_currency": "USD"},
        {},
        (
            {"at": stamp, "kind": "strategy_decision", "status": "rejected"},
            {"at": stamp, "kind": "strategy_decision", "status": "missed"},
            {"at": stamp, "kind": "strategy_decision", "status": "proposed"},
            {"at": stamp, "kind": "risk_review", "passed": False},
        ),
        ({"at": stamp, "equity": "500", "exposure": "0"},),
        (),
        ({"at": stamp, "status": "rejected"}, {"at": stamp, "status": "missed"}),
        {},
    )
    row = periods(result, weekly=False)[0]
    assert row["rejected_or_missed"] == 3
    assert row["decision_counts"] == {
        "proposal_rejected": 1,
        "proposal_missed": 1,
        "risk_rejected": 1,
    }
    assert recommendations(result)[1]["observation"].startswith("Journal contains 3")
    assert row["observed_start_at"] == row["observed_end_at"] == stamp
    assert row["coverage_status"] == "partial"
    assert row["period_start_at"] == "2026-10-29T00:00:00+00:00"
    assert row["period_end_at_exclusive"] == "2026-10-30T00:00:00+00:00"


def test_orb_proposal_risk_and_fill_failures_count_disjoint_stages() -> None:
    from etoro_demo_bot.shadow.reports import recommendations

    stamp = NOW.isoformat()
    result = Result(
        {"model": "orb-event-replay-v1", "shadow_valuation_currency": "EUR"},
        {},
        (
            {"at": stamp, "kind": "signal_rejected"},
            {"at": stamp, "kind": "entry_cancelled", "reason": "FILL_REVALIDATION"},
            {"at": stamp, "kind": "entry_cancelled", "reason": "EXPIRY_OR_RISK_HALT"},
            {"at": stamp, "kind": "entry_cancelled", "reason": "UNRECOGNIZED"},
        ),
        ({"at": stamp, "equity": "500", "exposure": "0"},),
        (),
        (
            {"at": stamp, "status": "blocked"},
            {"at": stamp, "status": "proposed"},
            {"at": stamp, "status": "proposed"},
            {"at": stamp, "status": "waiting"},
        ),
        {},
    )
    row = periods(result, weekly=True)[0]
    assert row["rejected_or_missed"] == 4
    assert row["decision_counts"] == {
        "proposal_rejected": 1,
        "signal_rejected": 1,
        "fill_rejected": 1,
        "entry_missed": 1,
        "unknown_cancelled_entries": 1,
    }
    assert row["reason_counts"]["entry_cancelled: FILL_REVALIDATION"] == 1
    assert row["reason_counts"]["proposal: UNSPECIFIED_REASON"] == 1
    assert recommendations(result)[1]["observation"].startswith("Journal contains 4")
    assert row["period_start_at"] == "2026-10-26T00:00:00+00:00"
    assert row["period_end_at_exclusive"] == "2026-11-02T00:00:00+00:00"
    assert row["coverage_status"] == "partial"


@pytest.mark.parametrize(
    "name", ("summary.json", "daily.md", "weekly.md", "periods.csv", "shadow-checksums.json")
)
def test_corrupt_exports_are_unavailable_and_never_reset_run(tmp_path: Path, name: str) -> None:
    store = Runs.initialize(tmp_path / "shadow")
    identity = run_once(store, "orb", 500, now=NOW)
    path = store.root / identity / name
    path.write_bytes(b"corrupt")
    rows = store.rows()
    dashboard(store, now=NOW)
    text = (store.root / "dashboard.html").read_text(encoding="utf-8")
    assert "REPORT UNAVAILABLE" in text
    assert f'href="{identity}/' not in text
    assert store.rows() == rows


def test_legacy_report_remains_visible_with_unverified_export_integrity(tmp_path: Path) -> None:
    store = Runs.initialize(tmp_path / "shadow")
    identity = run_once(store, "hourly", 500, now=NOW)
    path = store.root / identity / "summary.json"
    data = json.loads(path.read_bytes())
    del data["schema_version"]
    path.write_text(json.dumps(data), encoding="utf-8")
    dashboard(store, now=NOW)
    text = (store.root / "dashboard.html").read_text(encoding="utf-8")
    assert "LEGACY — export integrity unverified" in text
    assert f'href="{identity}/summary.json"' not in text
    assert f'href="{identity}/daily.md"' not in text


def test_atomic_publish_failure_preserves_previous_view_and_removes_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from etoro_demo_bot.shadow.reports import atomic_text

    path = tmp_path / "dashboard.html"
    path.write_text("previous complete view", encoding="utf-8")

    def fail_replace(self: Path, target: Path) -> Path:
        raise OSError("Synthetic replacement failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError):
        atomic_text(path, "new complete view")
    assert path.read_text(encoding="utf-8") == "previous complete view"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["dashboard.html"]


def test_incomplete_export_marks_failed_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from etoro_demo_bot.shadow import reports

    store = Runs.initialize(tmp_path / "shadow")
    original = reports.atomic_text

    def fail_weekly(path: Path, content: str) -> None:
        if path.name == "weekly.md":
            raise OSError("Synthetic write failure")
        original(path, content)

    monkeypatch.setattr(reports, "atomic_text", fail_weekly)
    with pytest.raises(OSError):
        run_once(store, "orb", 500, now=NOW)
    assert store.rows()[0][-1] == "failed"
    text = (store.root / "dashboard.html").read_text(encoding="utf-8")
    assert "Failed — preserved state requires review" in text
    assert "summary.json" not in text
    with pytest.raises(ShadowError, match="ALREADY_CLAIMED"):
        run_once(store, "orb", 500, now=NOW)


def test_interrupted_run_remains_visible_and_claimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from etoro_demo_bot.shadow import app

    store = Runs.initialize(tmp_path / "shadow")

    def interrupted() -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(app, "orb_dataset", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run_once(store, "orb", 500, now=NOW)
    assert store.rows()[0][-1] == "running"
    text = (store.root / "dashboard.html").read_text(encoding="utf-8")
    assert "Active or interrupted" in text
    with pytest.raises(ShadowError, match="ALREADY_CLAIMED"):
        run_once(Runs(store.root), "orb", 500, now=NOW)


def test_missing_uniqueness_constraint_is_blocked_without_database_writes(tmp_path: Path) -> None:
    import sqlite3

    root = tmp_path / "shadow"
    root.mkdir()
    path = root / "runs.sqlite"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE runs(id TEXT PRIMARY KEY,pipeline TEXT,eur INTEGER,slot TEXT,status TEXT)"
    )
    db.commit()
    db.close()
    before = path.read_bytes()
    with pytest.raises(ShadowError, match="UNIQUENESS_INVALID"):
        Runs(root).claim("orb", 500, NOW.date(), now=NOW)
    assert path.read_bytes() == before


def test_saved_news_rendering_is_escaped_and_not_replay_evidence(tmp_path: Path) -> None:
    from etoro_demo_bot.news.archive import NewsItemSummary, NewsSummary

    store = Runs.initialize(tmp_path / "shadow")
    item = NewsItemSummary(
        title="<script>alert(1)</script>",
        form="8-K",
        source_feed="SEC saved feed",
        source_url="javascript:alert(1)",
        published_at=NOW,
        updated_at=NOW,
        observed_at=NOW,
        revision_sha256="0" * 64,
        keyword_tags=("earnings",),
    )
    news = NewsSummary("AVAILABLE", NOW, NOW, (item,), 1, False)
    dashboard(store, now=NOW, news=news)
    text = (store.root / "dashboard.html").read_text(encoding="utf-8")
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert 'href="javascript:' not in text
    assert "earnings coverage UNKNOWN" in text
    assert "never enters historical strategy decisions" in text
    assert store.rows() == []


def test_monitoring_state_connection_is_readonly(tmp_path: Path) -> None:
    import sqlite3

    store = Runs.initialize(tmp_path / "shadow")
    identity = store.claim("orb", 500, NOW.date(), now=NOW)
    before = (store.root / "runs.sqlite").read_bytes()
    with store.connect(readonly=True) as db:
        assert db.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM runs")
    assert store.rows()[0][0] == identity
    assert (store.root / "runs.sqlite").read_bytes() == before


def test_csv_text_formulas_blocked_but_negative_decimal_values_remain_numeric() -> None:
    import csv
    import io

    from etoro_demo_bot.shadow.reports import periods_csv

    payload = {
        "daily": [{"period": "=1+1", "net_equity_change": "-2.50", "decision_counts": {}}],
        "weekly": [],
    }
    row = next(csv.DictReader(io.StringIO(periods_csv(payload))))
    assert row["period"] == "'=1+1"
    assert row["net_equity_change"] == "-2.50"
    assert row["total_cost_usd"] == "unavailable"
