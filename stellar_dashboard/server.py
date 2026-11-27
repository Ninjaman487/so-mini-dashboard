"""Local web server for the dashboard (127.0.0.1 only)."""
from __future__ import annotations

import argparse
import json
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl

from . import __version__
from .addons import AddonContext
from .game import GameReader
from .paths import home_dir
from .update import UpdateCheck

PAGE = Path(__file__).with_name("page.html")


def build_page(token: str, addons=()) -> str:
    page = PAGE.read_text(encoding="utf-8").replace("__SD_TOKEN__", token)
    extra = "".join(a.page() or "" for a in addons)
    return page.replace("</body>", extra + "\n</body>", 1) if extra else page


def make_handler(reader: GameReader, token: str, port: int, addons=(), updates=None):
    allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def _guard(self, api: bool) -> bool:
            # Only requests addressed to this machine (blocks DNS rebinding), and API calls
            # only with this session's token (blocks other web pages from reading data).
            if self.headers.get("Host", "") not in allowed:
                self.send_error(403)
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://{h}" for h in allowed}:
                self.send_error(403)
                return False
            if api:
                given = self.headers.get("X-SD-Token", "")
                if not given and "?" in self.path:
                    given = dict(parse_qsl(self.path.split("?", 1)[1])).get("token", "")
                if not secrets.compare_digest(given, token):
                    self.send_error(403)
                    return False
            return True

        def _send(self, body: bytes, ctype: str, code: int = 200):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                             "script-src 'self' 'unsafe-inline'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(json.dumps(obj, separators=(",", ":"), default=str).encode(), "application/json", code)

        def do_GET(self):
            path, _, qs = self.path.partition("?")
            if not self._guard(path.startswith("/api/")):
                return
            if path in ("/", "/index.html"):
                self._send(build_page(token, addons).encode(), "text/html; charset=utf-8")
            elif path == "/api/state":
                extra = {}
                for a in addons:
                    extra.update(a.state() or {})
                snap = reader.snapshot()
                snap.update(extra)
                snap.update(now=time.time(), version=__version__, update=updates.state() if updates else None)
                self._json(snap)
            else:
                query = dict(parse_qsl(qs))
                for a in addons:
                    out = a.handle_get(path, query)
                    if out is not None:
                        body, ctype, code = out
                        self._send(body, ctype, code)
                        return
                self.send_error(404)

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            if not self._guard(True):
                return
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(min(n, 65536)) or b"{}")
            except json.JSONDecodeError:
                body = {}
            if path == "/api/market/refresh":
                reader.refresh_market()
                self._json({"ok": True})
            elif path == "/api/market/list":
                reader.set_market_list([str(x) for x in body.get("names") or []])
                self._json({"ok": True})
            else:
                self.send_error(404)

        def log_message(self, *a):
            pass

    return Handler


def builtin_addons() -> list:
    from relic_planner.dashboard import DungeonsAddon
    return [DungeonsAddon()]


def main(argv=None, addons=()):
    """Start the dashboard. ``addons`` are extra add-ons, loaded after the built-in ones."""
    addons = builtin_addons() + list(addons)
    ap = argparse.ArgumentParser(prog="stellar_dashboard",
                                 description="Stellar Odyssey dashboard: read-only game data on a local page")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument("--port", type=int, default=8766, help="Dashboard port on 127.0.0.1 (default 8766)")
    ap.add_argument("--open", action="store_true", help="Open the dashboard in your browser")
    ap.add_argument("--game-port", type=int, help="The game's DevTools port, if it is not found automatically")
    ap.add_argument("--user-data", help="Folder containing the game's DevToolsActivePort file")
    ap.add_argument("--poll", type=float, default=5.0, help="Seconds between game reads (default 5)")
    ap.add_argument("--no-market", action="store_true", help="Do not fetch market prices")
    ap.add_argument("--market-minutes", type=float, default=10.0, help="Minutes between market price sweeps (default 10)")
    ap.add_argument("--data", help="Folder for saved price and net-worth history (default: per-user SOMiniDashboard folder)")
    ap.add_argument("--no-update-check", action="store_true", help="Do not check GitHub for a newer release")
    for a in addons:
        a.add_arguments(ap)
    args = ap.parse_args(argv)

    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), None)
    except OSError:
        # Already running (for example, started twice): just show the page.
        url = f"http://127.0.0.1:{args.port}/"
        print(f"The dashboard is already running at {url}")
        webbrowser.open(url)
        return
    home = Path(args.data) if args.data else home_dir()
    reader = GameReader(port=args.game_port, user_data=args.user_data, interval=args.poll,
                        market_minutes=args.market_minutes, market_enabled=not args.no_market,
                        data_dir=home / "dashboard")
    ctx = AddonContext(args, reader, home)
    for a in addons:
        a.start(ctx)
    reader.start()
    updates = UpdateCheck(__version__, enabled=not args.no_update_check)
    token = secrets.token_urlsafe(24)
    server.RequestHandlerClass = make_handler(reader, token, args.port, addons, updates)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"SO Mini Dashboard {__version__}: {url}")
    print("Read-only: it never buys, sells, queues, claims or sends game input.")
    print("Keep this window open while you use the dashboard. Close it to stop.")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        reader.stop.set()
        server.server_close()
