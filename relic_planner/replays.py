"""Look at solo dungeon replays to check how streaks work and that the simulator still matches.

A replay holds one entry per level, each with its rooms and a snapshot per round.
"""
from __future__ import annotations

from .sim import simulate_level


def _levels(replay: dict) -> list[dict]:
    lv = replay.get("levels") or replay.get("steps") or []
    return [x for x in lv if isinstance(x, dict) and isinstance(x.get("steps"), list)]


def _player(snap: dict) -> dict:
    ps = ((snap or {}).get("step_data") or {}).get("players") or []
    return ps[0] if ps else {}


def stats_from_replay(replay: dict) -> dict | None:
    for lv in _levels(replay):
        for st in lv["steps"]:
            for sn in st.get("snapshots") or []:
                p = _player(sn)
                if p:
                    return {k: p.get(k) for k in ("damage", "hp", "gather", "craft", "explore",
                                                  "weakness", "radiationProt")}
    return None


def analyse(items: list[dict]) -> list[str]:
    lines, refill, carry, same, differ, rooms, exact = [], 0, 0, 0, 0, 0, 0
    for it in items:
        rep, log = it.get("replay") or {}, it.get("log") or {}
        levels = _levels(rep)
        if not levels:
            continue
        rooms0 = [s.get("type") for s in levels[0]["steps"]]
        stats = stats_from_replay(rep)
        dungeon = {"steps": [{"step": s.get("stepIndex"), "type": s.get("type")} for s in levels[0]["steps"]],
                   "boss_weakness": rep.get("boss_weakness", log.get("boss_weakness")),
                   "difficulty_modifier": rep.get("difficulty_modifier", log.get("difficulty_modifier")) or 0}
        prev_end = None
        for lv in levels:
            types = [s.get("type") for s in lv["steps"]]
            if lv is not levels[0]:
                same += types == rooms0
                differ += types != rooms0
            snaps = [sn for s in lv["steps"] for sn in s.get("snapshots") or [] if _player(sn)]
            if snaps and prev_end is not None:
                first = _player(snaps[0])
                if first.get("hp", 0) + 1 >= first.get("maxhp", 0) or first.get("hp", 0) > prev_end:
                    refill += 1
                else:
                    carry += 1
            if snaps:
                prev_end = _player(snaps[-1]).get("hp")
            if stats:
                sim = simulate_level(stats, dungeon, None, lv.get("level"))
                for g, a in zip(sim["steps"], lv["steps"]):
                    sn = a.get("snapshots") or []
                    if a.get("type") == "prefight" or not sn:
                        continue
                    rooms += 1
                    exact += (g["status"], g["ticks_used"], g["hp_remaining"]) == \
                             (a.get("status"), len(sn), _player(sn[-1]).get("hp"))
        lines.append(f"run from level {log.get('starting_level')} to {log.get('level')}: {len(levels)} levels")
    if not levels_seen(refill, carry, same, differ, rooms):
        return lines + ["No replays with level data found. Save them with --save-replays, then run --check-replays on that file."]
    lines.append(f"HP between levels: refilled {refill} time(s), carried over {carry} time(s).")
    lines.append(f"Rooms on later levels: same as level one {same} time(s), different {differ} time(s).")
    if rooms:
        lines.append(f"Simulator vs replay, room by room: {exact} of {rooms} exact.")
    return lines


def levels_seen(*counts: int) -> bool:
    return any(counts)
