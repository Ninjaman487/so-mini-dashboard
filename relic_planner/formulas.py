"""Solo dungeon formulas."""
from __future__ import annotations

import math

SOLO_MAX_DAILY_RUNS = 3
SOLO_DUNGEON_MIN_BATTLING_LEVEL = 70
MAX_ROUNDS = 20          # rounds per room
MAX_FAILS = 2            # failed rooms that end a solo run
RAD_EVERY = 5            # radiation hits every 5 rounds
RAD_PCT = {"battle": 8, "gather": 5, "craft": 5, "explore": 5, "boss": 10, "prefight": 0}
ANOMALY_RELIC_COST = 50_000
QUANTUM_CORE_RELIC_COST = 50


def boss_hp(level: int) -> int:
    return math.floor(1400 * 1.083 ** level)


def boss_dmg(level: int) -> int:
    return math.floor(5 * level * 1.049 ** level)


# Gather room size, measured on 41 gather rooms in recorded replays (levels 60-74, every one
# exact).
SERVER_NODE_BASE = 75685.904
SERVER_NODE_GROWTH = 1.057


def server_node_amount(level: int) -> int:
    return math.floor(SERVER_NODE_BASE * SERVER_NODE_GROWTH ** level)


def craft_amount(level: int) -> int:
    return math.floor(1200 * 1.07 ** level)


def explore_amount(level: int) -> int:
    return math.floor(1800 * 1.07 ** level)


def protection_needed(level: int) -> int:
    return max(0, level * 2 - 50)


def entry_cost(level: int) -> int:
    """Credits to enter a solo dungeon at this starting level."""
    if level <= 25:
        return 100_000 * max(1, level)
    if level <= 60:
        return 10_000_000 * level
    if level <= 100:
        return 20_000_000 * level
    return 35_000_000 * level


def streak_increment(boss_rounds: int) -> int:
    """Levels gained after a boss kill, for runs that started at Level 1."""
    if boss_rounds <= 5:
        return 10
    if boss_rounds <= 10:
        return 5
    if boss_rounds <= 15:
        return 2
    return 1


def starting_level(recent_clears: list[int] | None, highest_cleared: int | None) -> int:
    """10 below the median of recent clears, else 10 below the best clear; at least 1."""
    if not recent_clears:
        return max(1, (highest_cleared or 0) - 10)
    n = sorted(recent_clears)
    mid = len(n) // 2
    med = (n[mid - 1] + n[mid]) // 2 if len(n) % 2 == 0 else n[mid]
    return max(1, med - 10)


ROOM_ACTIVITY = {"battle": "battling", "boss": "battling", "gather": "gathering",
                 "craft": "crafting", "explore": "exploring"}


def radiation_damage(max_hp: int, room: str, prot: dict | None, needed: int) -> int:
    prot = prot or {}
    have = prot.get(room)
    if have is None:
        have = prot.get(ROOM_ACTIVITY.get(room, ""), 0)
    have = have or 0
    if have >= needed:
        return 0
    left = 100 - have * 100 / needed
    return math.floor(max_hp * (RAD_PCT.get(room, 0) / 100) * (left / 100))


def difficulty_factor(difficulty_modifier: float) -> float:
    # JS: Number((1 + C/100).toFixed(2))
    return float(f"{1 + (difficulty_modifier or 0) / 100:.2f}")
