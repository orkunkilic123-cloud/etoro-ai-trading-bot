"""Loopback HTTP integration, browser-origin boundaries and filesystem isolation."""

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from etoro_demo_bot.shadow.web import LocalDashboardServer

RUN = hashlib.sha256(b"hourly:500:2026-10-29").hexdigest()[:24]


@pytest.fixture
def viewer(tmp_path: Path) -> Iterator[LocalDashboardServer]:
    from etoro_demo_bot.shadow.store import Runs

    store = Runs.initialize(tmp_path / "shadow")
    now = datetime(2026, 10, 29, 18, tzinfo=UTC)
    identity = store.claim("hourly", 500, now.date(), now=now)
    assert identity == RUN
    store.finish(identity, "completed")
    (store.root / "dashboard.html").write_text("<h1>SHADOW / SYNTHETIC</h1>", encoding="utf-8")
    (store.root / RUN).mkdir()
    payload = {
        "schema_version": 1,
        "mode": "SHADOW",
        "evidence": "SYNTHETIC",
        "execution_enabled": False,
        "metrics": {},
        "daily": [],
        "weekly": [],
        "improvement_proposals": [],
    }
    contents = {
        "summary.json": json.dumps(payload).encode(),
        "daily.md": b"Synthetic report\n",
        "weekly.md": b"Synthetic report\n",
        "periods.csv": b"cadence,period\n",
    }
    for name, raw in contents.items():
        (store.root / RUN / name).write_bytes(raw)
    (store.root / RUN / "shadow-checksums.json").write_text(
        json.dumps({name: hashlib.sha256(raw).hexdigest() for name, raw in contents.items()}),
        encoding="utf-8",
    )
    with LocalDashboardServer(store.root, port=0, refresh=lambda: None) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=2)


def request(
    server: LocalDashboardServer,
    path: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def test_viewer_origin_and_response_headers(viewer: LocalDashboardServer) -> None:
    assert viewer.server_address[0] == "127.0.0.1"
    status, headers, body = request(viewer, "/")
    assert status == 200 and b"SHADOW / SYNTHETIC" in body
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["Cache-Control"] == "no-store"
    assert "Access-Control-Allow-Origin" not in headers
    assert request(viewer, "/", method="HEAD")[2] == b""
    assert request(viewer, "/", headers={"Origin": viewer.url})[0] == 200
    assert request(viewer, f"/{RUN}/daily.md")[2] == b"Synthetic report\n"


@pytest.mark.parametrize(
    "path",
    [
        "/runs.sqlite",
        "/.env",
        "/",
        "/../runs.sqlite",
        "/%2e%2e/.env",
        "/dashboard.html?path=.env",
        "/dashboard.html/",
        "/api/orders",
        f"/{RUN}/state/simulation-risk.sqlite",
        f"/{RUN}/report/report.json",
        f"/{RUN}/..%2f.env",
        f"/{RUN}\\daily.md",
    ],
)
def test_no_private_files_or_unlisted_routes(viewer: LocalDashboardServer, path: str) -> None:
    if path == "/":
        # An absolute request-target is rejected even when it names this same origin.
        path = viewer.url + "/dashboard.html"
    status, _, body = request(viewer, path)
    assert status == 404 and b"private-local-state" not in body


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "CONNECT"])
def test_no_mutation_routes(viewer: LocalDashboardServer, method: str) -> None:
    before = (viewer.root / "runs.sqlite").read_bytes()
    assert request(viewer, "/", method=method)[0] in (405, 501)
    assert (viewer.root / "runs.sqlite").read_bytes() == before


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "evil.example"},
        {"Host": "localhost"},
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
    ],
)
def test_rebinding_and_cross_origin_blocked(
    viewer: LocalDashboardServer, headers: dict[str, str]
) -> None:
    assert request(viewer, "/", headers=headers)[0] == 403


def test_symlink_escape_and_refresh_failure_are_sanitized(
    viewer: LocalDashboardServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "private.txt"
    target.write_text("synthetic-private-value", encoding="utf-8")
    try:
        (viewer.root / RUN / "weekly.md").unlink()
        (viewer.root / RUN / "weekly.md").symlink_to(target)
    except OSError:
        pytest.skip("Host does not permit creating symbolic links")
    assert request(viewer, f"/{RUN}/weekly.md")[0] == 503

    def broken() -> None:
        raise ValueError("synthetic-private-value")

    viewer.refresh = broken
    status, _, body = request(viewer, "/")
    assert status == 503 and b"synthetic-private-value" not in body
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("file", ["summary.json", "daily.md", "shadow-checksums.json"])
def test_corrupt_exports_block_direct_download(viewer: LocalDashboardServer, file: str) -> None:
    (viewer.root / RUN / file).write_bytes(b"altered synthetic data")
    status, _, body = request(viewer, f"/{RUN}/{file}")
    assert status == 503 and b"altered synthetic data" not in body


def test_unfinished_run_cannot_export(viewer: LocalDashboardServer) -> None:
    from etoro_demo_bot.shadow.store import Runs

    with Runs(viewer.root).connect() as db:
        db.execute("UPDATE runs SET status='running' WHERE id=?", (RUN,))
    assert request(viewer, f"/{RUN}/summary.json")[0] == 503


def test_duplicate_host_header_rejected(viewer: LocalDashboardServer) -> None:
    connection = HTTPConnection("127.0.0.1", viewer.server_port, timeout=5)
    try:
        connection.putrequest("GET", "/")
        connection.putheader("Host", f"127.0.0.1:{viewer.server_port}")
        connection.endheaders()
        assert connection.getresponse().status == 403
    finally:
        connection.close()


def test_cli_serve_invalid_archive_shows_unavailable_without_recreating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    from etoro_demo_bot.shadow import __main__ as cli
    from etoro_demo_bot.shadow.store import Runs

    root = tmp_path / "shadow"
    Runs.initialize(root)
    missing = tmp_path / "missing-news.sqlite"
    monkeypatch.setattr(
        sys,
        "argv",
        ["shadow", "serve", "--root", str(root), "--port", "0", "--news-archive", str(missing)],
    )
    seen = []

    def serve(self: LocalDashboardServer, **kwargs: Any) -> None:
        seen.append(self.url)

    monkeypatch.setattr(LocalDashboardServer, "serve_forever", serve)
    assert cli.main() == 0 and len(seen) == 1
    assert not missing.exists()
    assert "UNAVAILABLE" in (root / "dashboard.html").read_text(encoding="utf-8")


def test_real_shadow_run_is_viewable_without_exposing_journals(tmp_path: Path) -> None:
    from etoro_demo_bot.news.archive import NewsArchive, summarize_archive
    from etoro_demo_bot.shadow.app import run_once
    from etoro_demo_bot.shadow.reports import dashboard
    from etoro_demo_bot.shadow.store import Runs

    now = datetime(2026, 10, 29, 18, tzinfo=UTC)
    store = Runs.initialize(tmp_path / "shadow")
    identity = run_once(store, "hourly", 500, now=now)
    news_path = tmp_path / "news.sqlite"
    archive = NewsArchive(news_path)
    archive.ingest(
        b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>urn:synthetic:1</id>'
        b"<title>Synthetic &lt;b&gt;results&lt;/b&gt;</title>"
        b'<updated>2026-10-29T17:00:00Z</updated><category term="8-K"/>'
        b'<link href="https://www.sec.gov/Archives/edgar/data/1/synthetic.html"/>'
        b"</entry></feed>",
        source="https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&output=atom",
        observed_at=now,
    )
    news_before, state_before = news_path.read_bytes(), (store.root / "runs.sqlite").read_bytes()

    def refresh() -> None:
        dashboard(store, now=now, news=summarize_archive(news_path, as_of=now))

    with LocalDashboardServer(store.root, port=0, refresh=refresh) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            status, _, page = request(server, "/")
            assert status == 200 and b"Synthetic &lt;b&gt;results&lt;/b&gt;" in page
            assert b"earnings coverage UNKNOWN" in page
            assert request(server, f"/{identity}/summary.json")[0] == 200
            assert request(server, f"/{identity}/daily.md")[0] == 200
            assert request(server, f"/{identity}/periods.csv")[0] == 200
            assert request(server, f"/{identity}/state/simulation-risk.sqlite")[0] == 404
        finally:
            server.shutdown()
            thread.join(timeout=2)
    assert news_path.read_bytes() == news_before
    assert (store.root / "runs.sqlite").read_bytes() == state_before
