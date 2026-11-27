"""Tells you when a newer release is out. One small GET to GitHub a few times a day; no data is sent."""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request

RELEASES = "https://github.com/Ninjaman487/so-mini-dashboard/releases/latest"
API = "https://api.github.com/repos/Ninjaman487/so-mini-dashboard/releases/latest"
EVERY = 6 * 3600


def parse(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3])


class UpdateCheck:
    def __init__(self, current: str, enabled: bool = True):
        self.current = current
        self.enabled = enabled
        self.latest: str | None = None
        self.url = RELEASES
        if enabled:
            threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json",
                                                           "User-Agent": "so-mini-dashboard"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    doc = json.load(r)
                self.latest = str(doc.get("tag_name") or "") or None
                self.url = doc.get("html_url") or RELEASES
            except Exception:
                pass
            time.sleep(EVERY)

    def state(self) -> dict:
        newer = bool(self.latest) and parse(self.latest) > parse(self.current)
        return {"current": self.current, "latest": self.latest, "newer": newer, "url": self.url}
