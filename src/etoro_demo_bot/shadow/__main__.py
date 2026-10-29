"""Owner-operated synthetic shadow runner and read-only loopback viewer."""

import argparse
from datetime import UTC, datetime
from pathlib import Path

from ..news.archive import NewsSummary, summarize_archive
from ..news.events import NewsError
from .app import run_once
from .reports import dashboard
from .store import Runs
from .web import LocalDashboardServer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "run", "dashboard", "serve"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--pipeline", choices=("hourly", "orb"), default="hourly")
    parser.add_argument("--eur", type=int, choices=(500, 1000), default=500)
    parser.add_argument("--news-archive", type=Path, help="Optional existing offline SEC archive")
    parser.add_argument("--port", type=int, default=8765, help="Loopback browser port for serve")
    parser.add_argument("--open-browser", action="store_true", help="Open the local viewer")
    args = parser.parse_args()
    now = datetime.now(UTC)
    try:
        store = Runs.initialize(args.root) if args.command == "init" else Runs(args.root)

        def refresh() -> None:
            observed = datetime.now(UTC)
            news: NewsSummary | None = None
            if args.news_archive is not None:
                try:
                    news = summarize_archive(args.news_archive, as_of=observed)
                except NewsError:
                    news = NewsSummary("UNAVAILABLE", observed, None, (), 0, False)
            dashboard(store, now=observed, news=news)

        if args.command == "run":
            run_once(store, args.pipeline, args.eur, now=now)
            refresh()
        elif args.command == "serve":
            refresh()
            with LocalDashboardServer(store.root, port=args.port, refresh=refresh) as server:
                print(
                    f"SHADOW viewer: {server.url} — Ctrl+C stops. Broker execution disabled.",
                    flush=True,
                )
                if args.open_browser:
                    import webbrowser

                    webbrowser.open(server.url)
                try:
                    server.serve_forever(poll_interval=0.2)
                except KeyboardInterrupt:
                    pass
        else:
            refresh()
    except Exception:
        # Never expose arbitrary data, full paths or exception locals in CLI output.
        print("Shadow operation failed; inspect local run status. Execution disabled.")
        return 1
    print("SHADOW / SYNTHETIC reports ready locally. Broker execution disabled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
