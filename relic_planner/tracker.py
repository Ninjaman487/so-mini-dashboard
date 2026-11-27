"""Relics earned per day and week from your solo logs, and predicted vs actual per run.

Predictions are saved when the planner reads the game (predictions.jsonl next to the
dashboard's data, or wherever you point it). A logged run is matched to the prediction made
for the same entrance settings (start level, reward and difficulty modifiers, boss weakness)
in the day before it finished.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

KEEP_DAYS = 60


def _key(start, rm, dm, weak) -> str:
    return f"{start}|{rm}|{dm}|{weak}"


class PredictionLog:
    def __init__(self, path: Path | None):
        self.path = Path(path) if path else None
        self.seen: dict[str, float] = {}

    def record(self, rows: list[dict], start_level: int, now: float | None = None) -> None:
        """Append one line per entrance the first time it is seen with these settings."""
        if not self.path:
            return
        now = now or time.time()
        lines = []
        for r in rows:
            k = _key(start_level, r.get("reward_modifier"), r.get("difficulty_modifier"), r.get("boss_weakness"))
            if now - self.seen.get(k, 0) < 3600:
                continue
            self.seen[k] = now
            lines.append(json.dumps({"t": now, "key": k, "relics": r.get("relics"), "highest": r.get("highest")}))
        if lines:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

    def load(self) -> list[dict]:
        if not self.path or not self.path.exists():
            return []
        cut = time.time() - KEEP_DAYS * 86400
        out = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                x = json.loads(line)
            except json.JSONDecodeError:
                continue
            if x.get("t", 0) >= cut:
                out.append(x)
        return out


def summary(logs: list[dict], predictions: list[dict] | None = None, days: int = 14,
            now: float | None = None) -> dict:
    now = now or time.time()
    today = datetime.fromtimestamp(now, timezone.utc).date()
    per_day = {(today - timedelta(days=i)).isoformat(): 0 for i in range(days)}
    runs = []
    preds = sorted(predictions or [], key=lambda p: p["t"])
    for row in logs or []:
        t = row.get("completedAt")
        relics = (row.get("rewards") or {}).get("dungeon_relics") or 0
        if not isinstance(t, (int, float)):
            continue
        day = datetime.fromtimestamp(t, timezone.utc).date().isoformat()
        if day in per_day:
            per_day[day] += relics
        k = _key(row.get("starting_level"), row.get("reward_modifier"), row.get("difficulty_modifier"),
                 row.get("boss_weakness"))
        match = [p for p in preds if p["key"] == k and t - 86400 <= p["t"] <= t]
        pred = match[-1] if match else None
        runs.append({"t": t, "start": row.get("starting_level"), "top": row.get("level"),
                     "reward_modifier": row.get("reward_modifier"), "relics": relics,
                     "predicted": pred and pred.get("relics"), "predicted_top": pred and pred.get("highest")})
    runs.sort(key=lambda r: -r["t"])
    week = sum(v for d, v in per_day.items() if d > (today - timedelta(days=7)).isoformat())
    matched = [r for r in runs if r["predicted"]]
    acc = None
    if matched:
        acc = sum(r["relics"] for r in matched) / max(1, sum(r["predicted"] for r in matched))
    return {"per_day": sorted(per_day.items()), "last_7_days": week, "today": per_day[today.isoformat()],
            "runs": runs[:20], "matched": len(matched), "actual_vs_predicted": acc,
            "complete": len(logs or []) > 0}
