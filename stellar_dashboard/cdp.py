"""Minimal read-only Chrome DevTools Protocol client for the Stellar Odyssey window.

The dashboard only reads: it evaluates read-only expressions and captures screenshots.
It never sends input events, never sets breakpoints and never calls the game's own
actions. Connections are refused unless the endpoint is on this machine.
"""
from __future__ import annotations

import json
import os
import platform
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

try:
    import websocket
except ImportError:  # reported to the user by the server
    websocket = None

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def candidate_roots() -> list[Path]:
    home = Path.home()
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", home / "AppData/Roaming"))
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
        names = ("Stellar Odyssey Game", "stellarodyssey", "Stellar Odyssey")
        return [base / n for n in names] + [local / n for n in names]
    if system == "Darwin":
        base = home / "Library/Application Support"
        return [base / "Stellar Odyssey Game", base / "stellarodyssey", base / "Stellar Odyssey"]
    cfg = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    return [cfg / "Stellar Odyssey Game", cfg / "stellarodyssey", cfg / "Stellar Odyssey"]


def get_json(url: str, timeout: float = 2.0):
    host = urlparse(url).hostname
    if host not in LOCAL_HOSTS:
        raise RuntimeError(f"Refusing non-local DevTools endpoint {host!r}")
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def find_port(user_data: str | None = None, port: int | None = None) -> int | None:
    """Return the live DevTools port of the game, or None. The port file can be stale."""
    if port:
        return port
    roots = [Path(user_data).expanduser()] if user_data else candidate_roots()
    for root in roots:
        f = root / "DevToolsActivePort"
        try:
            first = f.read_text(errors="replace").splitlines()[0].strip()
        except (OSError, IndexError):
            continue
        if first.isdigit():
            try:
                get_json(f"http://127.0.0.1:{first}/json/version", timeout=1.0)
            except Exception:
                continue
            return int(first)
    return None


def page_targets(port: int) -> list[dict]:
    return [t for t in get_json(f"http://127.0.0.1:{port}/json/list")
            if t.get("type") == "page" and t.get("webSocketDebuggerUrl")
            and not t.get("url", "").startswith("devtools://")]


def pick_game_target(targets: list[dict], target_id: str | None = None) -> dict | None:
    if target_id:
        for t in targets:
            if t.get("id") == target_id:
                return t
    for t in targets:
        if "stellar" in (t.get("title", "") + " " + t.get("url", "")).lower():
            return t
    return targets[0] if targets else None


class CDPError(RuntimeError):
    pass


class Session:
    """One websocket to one page target. Thread-safe; every call has a deadline."""

    def __init__(self, ws_url: str):
        if websocket is None:
            raise CDPError("Install websocket-client: pip install websocket-client")
        if urlparse(ws_url).hostname not in LOCAL_HOSTS:
            raise CDPError("Refusing non-local DevTools endpoint")
        self.ws = websocket.create_connection(ws_url, timeout=1.0, suppress_origin=True,
                                              skip_utf8_validation=True)
        self.seq = 0
        self.lock = threading.Lock()
        self.ws_url = ws_url

    def call(self, method: str, params: dict | None = None, timeout: float = 3.0) -> dict:
        with self.lock:
            self.seq += 1
            ident = self.seq
            self.ws.send(json.dumps({"id": ident, "method": method, "params": params or {}}))
            deadline = time.monotonic() + timeout
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    # Drop the socket: a late reply would otherwise answer the next call.
                    self.close()
                    raise CDPError(f"{method} timed out (the game may be paused)")
                self.ws.settimeout(min(0.5, left))
                try:
                    msg = json.loads(self.ws.recv())
                except websocket.WebSocketTimeoutException:
                    continue
                except Exception as exc:
                    self.close()
                    raise CDPError(f"DevTools connection lost: {exc}") from exc
                if msg.get("id") == ident:
                    if "error" in msg:
                        raise CDPError(str(msg["error"].get("message", msg["error"])))
                    return msg.get("result", {})

    def evaluate(self, expression: str, timeout: float = 3.0):
        r = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                           "awaitPromise": True, "silent": True}, timeout=timeout)
        if r.get("exceptionDetails"):
            raise CDPError(r["exceptionDetails"].get("text", "evaluation failed"))
        return r.get("result", {}).get("value")

    def screenshot_jpeg(self, quality: int = 60, scale: float = 0.6, timeout: float = 2.0) -> bytes:
        import base64
        size = self.evaluate("[innerWidth,innerHeight]", timeout=timeout) or [1280, 720]
        r = self.call("Page.captureScreenshot", {
            "format": "jpeg", "quality": int(quality), "fromSurface": True,
            "clip": {"x": 0, "y": 0, "width": size[0], "height": size[1], "scale": scale},
        }, timeout=timeout)
        return base64.b64decode(r.get("data", ""))

    @property
    def closed(self) -> bool:
        return not getattr(self.ws, "connected", False)

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass
