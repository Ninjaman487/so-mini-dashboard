"""Solo dungeon simulator.

simulate_level() plays one level of one entrance (deterministic). simulate_run() chains levels the way a streak works: after a
boss kill the run continues at a higher level until something fails.

Streaks, confirmed from recorded replays: HP is full again at the start of each level and the
same rooms repeat on every level. Assumed, not yet seen in a replay: an equipped Power-Up
triggers again on every level.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import formulas as F

MAX_STREAK_LEVELS = 300

# Measured from recorded replays (5 runs, 62 levels): each round the enemy hits first, then
# you if you are still alive, then radiation at the end of rounds 6, 11 and 16; gather rooms
# need formulas.server_node_amount.


def _rad_round(r: int) -> bool:
    return r > 1 and (r - 1) % F.RAD_EVERY == 0

POWERUPS = (None, "lifeRestore", "dungeonStrength", "blockChance")


def simulate_level(stats: dict, dungeon: dict, powerup: str | None = None,
                   level: int | None = None, start_hp: int | None = None) -> dict:
    """One level. Same result shape as a solo dungeon replay."""
    damage = stats.get("damage") or 0
    hp = stats.get("hp") or 0
    gather, craft, explore = stats.get("gather") or 0, stats.get("craft") or 0, stats.get("explore") or 0
    rad = stats.get("radiationProt") or {}
    weak = stats.get("weakness") or {}
    steps = dungeon.get("steps") or []
    boss_weak = dungeon.get("boss_weakness")
    w = level if level is not None else (dungeon.get("level") or 1)
    T = F.difficulty_factor(dungeon.get("difficulty_modifier") or 0)
    need = F.protection_needed(w)

    dmg, max_hp = damage, hp
    cur = hp if start_hp is None else start_hp
    fails, ended, reason, out = 0, False, None, []

    for st in steps:
        kind = st.get("type")
        idx = st.get("step")
        if ended:
            out.append({"stepIndex": idx, "type": kind, "status": "skipped", "ticks_used": 0,
                        "hp_remaining": cur, "failure_reason": None})
            continue
        if kind == "prefight":
            if powerup == "lifeRestore":
                cur = math.floor(max_hp / 2) if cur == 0 else min(max_hp, cur + math.floor(max_hp / 2))
            elif powerup == "dungeonStrength":
                dmg = math.floor(dmg * 1.1)
                max_hp = math.floor(max_hp * 1.1)
                cur = min(max_hp, cur + math.floor(max_hp * 0.1))
            out.append({"stepIndex": idx, "type": "prefight", "status": "cleared", "ticks_used": 0,
                        "hp_remaining": cur, "failure_reason": None})
        elif kind in ("battle", "boss"):
            mult = 1.25 if kind == "boss" else 1
            enemy = math.floor(F.boss_hp(w) * mult * T)
            hit = math.floor(F.boss_dmg(w) * mult * T)
            mine = math.floor(dmg * (1 + (weak.get(boss_weak, 0) or 0) / 100))
            radd = F.radiation_damage(max_hp, kind, rad, need)
            r = 0
            while enemy > 0 and cur > 0 and r < F.MAX_ROUNDS:
                r += 1
                # Server order: the enemy hits, then you (only if still alive), then radiation.
                cur = max(0, cur - hit)
                if cur <= 0:
                    break
                enemy = max(0, enemy - mine)
                if _rad_round(r):
                    cur = max(0, cur - radd)
            ok = enemy == 0
            why = None if ok else ("player_died" if cur <= 0 else "boss_survived")
            out.append({"stepIndex": idx, "type": kind, "status": "cleared" if ok else "failed",
                        "ticks_used": r, "hp_remaining": cur, "boss_hp_remaining": enemy,
                        "failure_reason": why})
            if not ok:
                if kind == "boss":
                    ended, reason = True, "boss_failed"
                elif cur <= 0:
                    ended, reason = True, "player_died"
                else:
                    fails += 1
                    if fails >= F.MAX_FAILS:
                        ended, reason = True, "too_many_fails"
        else:
            have = {"gather": gather, "craft": craft, "explore": explore}.get(kind, 0)
            node = F.server_node_amount
            target = math.floor({"gather": node, "craft": F.craft_amount,
                                 "explore": F.explore_amount}.get(kind, node)(w) * T)
            radd = F.radiation_damage(max_hp, kind, rad, need)
            done, r = 0, 0
            while done < target and cur > 0 and r < F.MAX_ROUNDS:
                r += 1
                done += have
                if _rad_round(r):
                    cur = max(0, cur - radd)
            ok = done >= target
            why = None if ok else ("player_died" if cur <= 0 else "stat_too_low")
            out.append({"stepIndex": idx, "type": kind, "status": "cleared" if ok else "failed",
                        "ticks_used": r, "hp_remaining": cur, "stat_value": have, "target": target,
                        "ticks_needed": math.ceil(target / have) if have else None,
                        "failure_reason": why})
            if not ok:
                if cur <= 0:
                    ended, reason = True, "player_died"
                else:
                    fails += 1
                    if fails >= F.MAX_FAILS:
                        ended, reason = True, "too_many_fails"

    cleared = sum(1 for s in out if s["status"] == "cleared")
    weak_stats = [s["type"] for s in out if s["status"] == "failed" and s["failure_reason"] == "stat_too_low"]
    return {"steps": out, "steps_cleared": cleared, "terminated_early": ended,
            "termination_reason": reason, "weak_stats": weak_stats}


@dataclass
class RunResult:
    start_level: int
    levels_cleared: list[int] = field(default_factory=list)   # every level whose boss died
    failed_level: int | None = None                           # level the run ended on
    failed_rooms_cleared: int = 0                             # rooms cleared on that level
    rooms_per_level: int = 0
    end_reason: str | None = None
    weak_stats: list[str] = field(default_factory=list)
    capped: bool = False

    @property
    def highest_cleared(self) -> int:
        return max(self.levels_cleared) if self.levels_cleared else 0


def _boss_cleared(res: dict) -> tuple[bool, int]:
    for s in res["steps"]:
        if s["type"] == "boss":
            return s["status"] == "cleared", s["ticks_used"]
    # No boss room: count a clean level as cleared.
    return not res["terminated_early"], F.MAX_ROUNDS


def simulate_run(stats: dict, dungeon: dict, start_level: int, powerup: str | None = None) -> RunResult:
    run = RunResult(start_level=start_level,
                    rooms_per_level=sum(1 for s in dungeon.get("steps") or [] if s.get("type") != "prefight"))
    level = start_level
    for _ in range(MAX_STREAK_LEVELS):
        res = simulate_level(stats, dungeon, powerup, level)
        ok, boss_rounds = _boss_cleared(res)
        if not ok:
            run.failed_level = level
            run.failed_rooms_cleared = sum(1 for s in res["steps"]
                                           if s["status"] == "cleared" and s["type"] != "prefight")
            run.end_reason = res["termination_reason"]
            run.weak_stats = res["weak_stats"]
            return run
        run.levels_cleared.append(level)
        level += F.streak_increment(boss_rounds) if start_level == 1 else 1
    run.capped = True
    run.end_reason = "level_cap"
    return run
