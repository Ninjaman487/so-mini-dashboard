"""Dungeon powers a run pays (obsidian, ivory, iron, onyx).

Measured from your replays (67 levels, every one exact): each room you clear pays
floor(0.22 x level) of its power. Battle and boss rooms pay obsidian, gather ivory, craft iron,
explore onyx. The reward bonus does not change it. Rooms cleared on the level you fail still pay.
"""
from __future__ import annotations

import math

from .sim import RunResult

POWER_PER_LEVEL = 0.22
ROOM_POWER = {"battle": "obsidian", "boss": "obsidian", "gather": "ivory", "craft": "iron", "explore": "onyx"}
ORDER = ("obsidian", "ivory", "iron", "onyx")


def per_room(level: int) -> int:
    return math.floor(POWER_PER_LEVEL * level)


def for_run(run: RunResult, dungeon: dict) -> dict[str, int]:
    out = dict.fromkeys(ORDER, 0)
    rooms = [s.get("type") for s in dungeon.get("steps") or [] if s.get("type") in ROOM_POWER]
    for lv in run.levels_cleared:
        for r in rooms:
            out[ROOM_POWER[r]] += per_room(lv)
    if run.failed_level:
        for r in run.failed_cleared_types:
            if r in ROOM_POWER:
                out[ROOM_POWER[r]] += per_room(run.failed_level)
    return out


def check_logs(logs: list[dict]) -> tuple[int, int]:
    """(levels matched, levels checked) of the power formula against your logged runs."""
    from .relic_model import log_levels
    keys = {p: f"{p}_power" for p in ORDER}
    ok = n = 0
    for row in logs or []:
        for lv in log_levels(row):
            got = lv.get("rewards") or {}
            if not all(k in got for k in keys.values()):
                continue
            want = dict.fromkeys(ORDER, 0)
            for s in lv.get("steps") or []:
                if s.get("status") == "cleared" and s.get("type") in ROOM_POWER:
                    want[ROOM_POWER[s["type"]]] += per_room(lv["level"])
            n += 1
            ok += all(got[keys[p]] == want[p] for p in ORDER)
    return ok, n
