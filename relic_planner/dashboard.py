"""Dungeons tab for the dashboard, as a built-in add-on. Read-only.

Shows today's solo dungeon picks, every open entrance, the upgrade what-if and a relic
tracker. The game is read when the tab is opened and at most once a minute after that.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from stellar_dashboard.addons import Addon

PANEL = Path(__file__).resolve().with_name("dungeons_panel.html")
CACHE_SECONDS = 60


def _json(obj, code=200):
    return json.dumps(obj, separators=(",", ":"), default=str).encode(), "application/json", code


class DungeonsAddon(Addon):
    name = "dungeons"

    def __init__(self):
        self.lock = threading.Lock()
        self.data = None
        self.predictions = None
        self.error = None
        self.at = 0.0
        self.args = None

    def add_arguments(self, ap):
        ap.add_argument("--dungeon-log-pages", type=int, default=2,
                        help="Pages of 50 solo dungeon logs to read for the Dungeons tab")

    def start(self, ctx):
        from .tracker import PredictionLog
        self.args = ctx.args
        self.reader = ctx.reader
        self.predictions = PredictionLog(Path(ctx.data_home) / "dungeons" / "predictions.jsonl")

    def _read(self) -> dict:
        from .reader import read_game
        r = self.reader
        return read_game(getattr(r, "port", None) or getattr(r, "port_arg", None), getattr(r, "user_data", None),
                         log_pages=getattr(self.args, "dungeon_log_pages", 2))

    def handle_get(self, path, query):
        if path != "/api/dungeons":
            return None
        from .view import build

        def limit(key):
            try:
                v = float(query.get(key) or "")
                return v if v >= 0 else None
            except ValueError:
                return None
        fresh = query.get("refresh") == "1"
        with self.lock:
            if fresh or self.data is None or time.time() - self.at > CACHE_SECONDS:
                try:
                    self.data, self.error = self._read(), None
                except Exception as exc:  # noqa: BLE001 - shown on the page
                    self.data, self.error = None, str(exc)
                self.at = time.time()
            if self.data is None:
                return _json({"ok": False, "why": self.error or "No data yet."})
            try:
                v = build(self.data, max_here=limit("max_here"), max_station=limit("max_station"),
                          predictions=self.predictions.load(),
                          chosen=[c for c in (query.get("pick") or "").split(",") if c])
                if v.get("ok"):
                    self.predictions.record([r for r in v["entrances"] if r["usable"]], v["start_level"],
                                            self.data.get("now"))
                return _json(v)
            except Exception as exc:  # noqa: BLE001 - shown on the page
                return _json({"ok": False, "why": f"Could not plan: {exc}"})

    def page(self):
        return PANEL.read_text(encoding="utf-8")


def main(argv=None):
    from stellar_dashboard.server import main as dashboard_main
    return dashboard_main(argv)


if __name__ == "__main__":
    main()
