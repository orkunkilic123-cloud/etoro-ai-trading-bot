"""Read-only loopback presentation of generated shadow reports; never an order API."""

import re
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from .reports import load_summary
from .store import Runs

MAX_REPORT_BYTES = 8 * 1024 * 1024
REPORT_TYPES = {
    "summary.json": "application/json; charset=utf-8",
    "daily.md": "text/plain; charset=utf-8",
    "weekly.md": "text/plain; charset=utf-8",
    "periods.csv": "text/csv; charset=utf-8",
    "shadow-checksums.json": "application/json; charset=utf-8",
}
CSP = "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"


class LocalDashboardServer(HTTPServer):
    """No configurable bind address, filesystem browser, request logs or mutation routes."""

    def __init__(self, root: Path, *, port: int, refresh: Callable[[], None]) -> None:
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("INVALID_LOCAL_PORT")
        self.root = root.resolve(strict=True)
        self.refresh = refresh
        super().__init__(("127.0.0.1", port), _Handler)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"

    def handle_error(self, request: Any, client_address: Any) -> None:
        # No traceback, URL, filesystem path or external input in console logs.
        return


class _Handler(BaseHTTPRequestHandler):
    server: LocalDashboardServer
    server_version = "ShadowLocal"
    sys_version = ""

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        self._reply(code, b"Local report unavailable. Broker execution disabled.\n", "text/plain")

    def _reply(self, status: int, body: bytes, media_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self.close_connection = True

    def _allowed_origin(self) -> bool:
        # Literal host matching prevents DNS rebinding; do not trust forwarded headers.
        host = f"127.0.0.1:{self.server.server_port}"
        origins = self.headers.get_all("Origin", [])
        sites = self.headers.get_all("Sec-Fetch-Site", [])
        return (
            self.headers.get_all("Host", []) == [host]
            and (not origins or origins == [self.server.url])
            and (not sites or sites in (["none"], ["same-origin"]))
        )

    def do_GET(self) -> None:
        if not self._allowed_origin():
            self.send_error(403)
            return
        if self.path in ("/", "/dashboard.html"):
            relative, media_type = "dashboard.html", "text/html; charset=utf-8"
        else:
            match = re.fullmatch(r"/([0-9a-f]{24})/([a-z.-]+)", self.path)
            if match is None or match[2] not in REPORT_TYPES:
                self.send_error(404)
                return
            relative, media_type = self.path[1:], REPORT_TYPES[match[2]]
        try:
            if relative == "dashboard.html":
                self.server.refresh()
            else:
                run_id = relative.split("/", 1)[0]
                if not any(
                    row[0] == run_id and row[4] == "completed"
                    for row in Runs(self.server.root).rows()
                ):
                    raise ValueError("RUN_NOT_COMPLETED")
                payload, _ = load_summary(self.server.root / run_id)
                if payload.get("schema_version") != 1:
                    raise ValueError("EXPORT_INTEGRITY_UNVERIFIED")
            path = self.server.root
            for component in Path(relative).parts:
                path = path / component
                if path.is_symlink():
                    raise ValueError("SYMLINK_REPORT_FORBIDDEN")
            if not path.is_file() or not path.resolve().is_relative_to(self.server.root):
                raise ValueError("REPORT_UNAVAILABLE")
            with path.open("rb") as file:
                body = file.read(MAX_REPORT_BYTES + 1)
            if len(body) > MAX_REPORT_BYTES:
                raise ValueError("REPORT_TOO_LARGE")
        except Exception:
            self.send_error(503)
            return
        self._reply(200, body, media_type)

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_POST(self) -> None:
        self.send_error(405)

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST
    do_OPTIONS = do_POST
