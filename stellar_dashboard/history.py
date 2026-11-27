"""Saved history for trends: market prices, net worth and skill XP.

Plain JSON-lines files in the dashboard's data folder, one line per sample. Old lines are
dropped when the dashboard starts, so the files stay small.
"""
from __future__ import annotations

import json
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

KEEP_DAYS = 90
DAY = 86400.0


class Series:
    def __init__(self, path: Path, keep_days: float = KEEP_DAYS, maxlen: int = 200_000):
        self.path = path
        self.keep = keep_days * DAY
        self.rows: deque = deque(maxlen=maxlen)
        self.lock = threading.Lock()
        self._load()

    def _load(self):
        cutoff = time.time() - self.keep
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        kept = []
        for raw in lines:
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict) and rec.get("t", 0) >= cutoff:
                kept.append(rec)
        self.rows.extend(kept)
        if len(kept) < len(lines):               # rewrite without the old lines
            try:
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in kept), encoding="utf-8")
                tmp.replace(self.path)
            except OSError:
                pass

    def add(self, rec: dict):
        rec = {"t": round(time.time(), 1), **rec}
        with self.lock:
            self.rows.append(rec)
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
            except OSError:
                pass

    def since(self, seconds: float) -> list[dict]:
        cutoff = time.time() - seconds
        with self.lock:
            return [r for r in self.rows if r["t"] >= cutoff]

    def last(self):
        with self.lock:
            return self.rows[-1] if self.rows else None


def downsample(points: list, n: int = 60) -> list:
    if len(points) <= n:
        return points
    step = len(points) / n
    return [points[int(i * step)] for i in range(n)] + [points[-1]]


def value_at(points: list, t: float):
    """Value of the last point at or before t (points are [t, v] in time order)."""
    best = None
    for pt in points:
        if pt[0] <= t:
            best = pt[1]
        else:
            break
    return best


class History:
    def __init__(self, folder: Path):
        self.folder = folder
        self.prices = Series(folder / "prices.jsonl")
        self.networth = Series(folder / "networth.jsonl")
        self.skills = Series(folder / "skills.jsonl", keep_days=30)
        self._last_worth = 0.0
        self._last_skill = 0.0

    # ---- recording
    def record_price(self, name: str, quote: dict):
        if not quote.get("ok"):
            return
        bid = quote["buy"][0]["price"] if quote.get("buy") else None
        ask = quote["sell"][0]["price"] if quote.get("sell") else None
        if bid is None and ask is None:
            return
        self.prices.add({"k": name, "bid": bid, "ask": ask})

    def maybe_record_worth(self, total: float, by: dict, every: float = 600):
        if total and time.time() - self._last_worth >= every:
            self._last_worth = time.time()
            self.networth.add({"total": round(total), "by": {k: round(v) for k, v in by.items() if v}})

    def maybe_record_skills(self, timers: dict, every: float = 300):
        if time.time() - self._last_skill < every:
            return
        rec = {}
        for k in ("battle", "gather", "craft", "explore"):
            t = timers.get(k) or {}
            if isinstance(t.get("level"), (int, float)):
                rec[k] = [t.get("level"), t.get("xp"), t.get("xp_target")]
        if rec:
            self._last_skill = time.time()
            self.skills.add(rec)

    # ---- views
    def price_trends(self, days: float = 7) -> dict:
        by = defaultdict(list)
        for r in self.prices.since(days * DAY):
            v = r.get("bid") if r.get("bid") is not None else r.get("ask")
            if v is not None:
                by[r["k"]].append([r["t"], v])
        now = time.time()
        out = {}
        for k, pts in by.items():
            old = value_at(pts, now - DAY)
            cur = pts[-1][1]
            out[k] = {"series": downsample(pts), "change_24h": ((cur - old) / old) if old else None,
                      "low": min(p[1] for p in pts), "high": max(p[1] for p in pts)}
        return out

    def worth_view(self) -> dict:
        rows = self.networth.since(KEEP_DAYS * DAY)
        daily = {}
        for r in rows:
            daily[time.strftime("%Y-%m-%d", time.localtime(r["t"]))] = [r["t"], r["total"]]
        series = sorted(daily.values())
        recent = [[r["t"], r["total"]] for r in rows if r["t"] >= time.time() - 2 * DAY]
        old = value_at(recent, time.time() - DAY)
        cur = rows[-1]["total"] if rows else None
        return {"daily": series[-90:], "recent": downsample(recent, 96), "current": cur,
                "change_24h": (cur - old) if (cur is not None and old) else None}

    def skill_view(self, timers: dict) -> dict:
        """Level, XP bar, XP per hour over the last hours of samples, and time to next level."""
        rows = self.skills.since(6 * 3600)
        out = {}
        for k in ("battle", "gather", "craft", "explore"):
            t = timers.get(k) or {}
            lvl, xp, target = t.get("level"), t.get("xp"), t.get("xp_target")
            if not isinstance(lvl, (int, float)):
                continue
            pts = [(r["t"], *r[k]) for r in rows if k in r and None not in r[k]]
            rate = None
            if len(pts) >= 2 and pts[-1][0] - pts[0][0] >= 600:
                gained = 0.0
                for (t0, l0, x0, g0), (t1, l1, x1, g1) in zip(pts, pts[1:]):
                    gained += (x1 - x0) if l1 == l0 else max(0.0, (g0 or 0) - x0) + x1
                rate = gained / ((pts[-1][0] - pts[0][0]) / 3600.0)
            need = (target - xp) if isinstance(target, (int, float)) and isinstance(xp, (int, float)) else None
            out[k] = {"level": lvl, "xp": xp, "target": target,
                      "pct": (xp / target) if (isinstance(xp, (int, float)) and target) else None,
                      "xp_per_hour": rate, "eta_s": (need / rate * 3600) if (need is not None and rate) else None,
                      "active": t.get("active", t.get("travelling"))}
        return out
