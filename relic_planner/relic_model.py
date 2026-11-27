"""How many relics a run pays.

Measured from your solo dungeon replays (62 cleared levels across 5 runs, every one exact):
each level you clear pays floor(2.2 * level * (1 + reward% / 100)) relics. The level you fail
pays nothing, and the number of rooms and the difficulty modifier make no difference.
The game computes this on the server, so check_logs() re-tests it on every run of the planner
and says so if a game update changes it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .sim import RunResult

RELICS_PER_LEVEL = 2.2


def relics_for_level(level: int, reward_modifier: float) -> int:
    return math.floor(RELICS_PER_LEVEL * level * (1 + (reward_modifier or 0) / 100))


@dataclass
class RelicModel:
    checked: int = 0      # logged levels compared against the formula
    matched: int = 0
    fitted: bool = True   # the numbers are real relic counts

    def predict(self, run: RunResult, reward_modifier: float) -> float:
        return float(sum(relics_for_level(lv, reward_modifier) for lv in run.levels_cleared))

    def describe(self) -> str:
        if not self.checked:
            return "Relic formula: not checked (no logs)."
        if self.matched == self.checked:
            return f"Relic formula: {self.checked}/{self.checked} levels exact."
        return f"Warning: relic formula {self.matched}/{self.checked} levels exact. The game may have changed."


def log_levels(row: dict) -> list[dict]:
    """The per-level entries of one solo log row (each has level, steps and rewards)."""
    return [x for x in row.get("steps") or [] if isinstance(x, dict) and "level" in x]


def check_logs(logs: list[dict]) -> RelicModel:
    m = RelicModel()
    for row in logs or []:
        rm = row.get("reward_modifier") or 0
        for lv in log_levels(row):
            got = (lv.get("rewards") or {}).get("dungeon_relics")
            boss = [s for s in lv.get("steps") or [] if s.get("type") == "boss"]
            if got is None or not boss:
                continue
            want = relics_for_level(lv["level"], rm) if boss[0].get("status") == "cleared" else 0
            m.checked += 1
            m.matched += int(got == want)
    return m


# Kept for callers of the earlier version.
def fit(logs: list[dict]) -> RelicModel:
    return check_logs(logs)
