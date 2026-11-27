"""Everything the Dungeons screen shows, as plain JSON, from one read of the game."""
from __future__ import annotations

import time

from . import formulas as F
from .planner import POWERUP_NAMES, evaluate, next_clears, sequential_plan
from .tracker import summary
from .relic_model import check_logs


def _name(d: dict) -> str:
    return str((d.get("system") or {}).get("name") or d.get("name") or d.get("_id", "?"))


def _coords(d: dict):
    sys_ = d.get("system") or {}
    x, y = sys_.get("coordinate_x"), sys_.get("coordinate_y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    f = lambda v: str(int(v)) if float(v).is_integer() else f"{v:.2f}".rstrip("0").rstrip(".")
    return f"{f(x)}, {f(y)}"


def _pu(p, owned: dict) -> dict:
    """The Power-Up that would add the most relics to this run, on top of the no-Power-Up figure."""
    if not p.powerup or p.gain_from_powerup <= 0:
        return {"powerup": None, "powerup_gain": 0, "powerup_owned": None}
    return {"powerup": POWERUP_NAMES.get(p.powerup, p.powerup), "powerup_gain": round(p.gain_from_powerup),
            "powerup_owned": owned.get(p.powerup)}


def build(data: dict, with_upgrades: bool = True, max_here: float | None = None,
          max_station: float | None = None, predictions: list[dict] | None = None) -> dict:
    stats = data.get("stats")
    out = {"ok": bool(stats), "read_at": data.get("now") or time.time(), "errors": data.get("errors") or []}
    if not stats:
        out["why"] = "Open Dungeons > Solo in the game once so it loads your solo stats."
        return out
    start = F.starting_level(stats.get("recent_clears"), stats.get("highest_cleared"))
    model = check_logs(data.get("logs") or [])
    owned = data.get("powerups") or {}
    picks = evaluate(stats, data.get("dungeons") or [], model, start, owned, now=data.get("now") or time.time(),
                     max_here=max_here, max_station=max_station)
    runs_done = data.get("daily_runs") or 0
    runs_left = max(0, F.SOLO_MAX_DAILY_RUNS - runs_done)
    seq = sequential_plan(stats, data.get("dungeons") or [], model, runs_left, owned,
                          now=data.get("now") or time.time(), max_here=max_here, max_station=max_station)
    in_plan = {id(st.pick.dungeon): i for i, st in enumerate(seq)}
    recent = stats.get("recent_clears") or []
    highest = stats.get("highest_cleared") or 0
    rows = []
    for p in picks:
        d = p.dungeon
        rows.append({
            "system": _name(d), "access": p.access, "usable": p.usable, "in_plan": id(d) in in_plan,
            "next_start": F.starting_level(next_clears(recent, p.run.highest_cleared), max(highest, p.run.highest_cleared))
                          if p.run.highest_cleared else start,
            "too_far": p.too_far, "dist_here": p.dist_here, "dist_station": p.dist_station,
            "station": d.get("station_name"), "coords": _coords(d),
            "expires_in": p.expires_in, "rooms": [s.get("type") for s in d.get("steps") or []],
            "reward_modifier": d.get("reward_modifier") or 0, "difficulty_modifier": d.get("difficulty_modifier") or 0,
            "boss_weakness": d.get("boss_weakness"), "levels": len(p.run.levels_cleared),
            "highest": p.run.highest_cleared, "ends": p.run.end_reason, "weak_stats": sorted(set(p.run.weak_stats)),
            "relics": round(p.relics), **_pu(p, owned),
        })
    out.update({
        "start_level": start, "entry_cost": F.entry_cost(start), "runs_done": runs_done,
        "runs_max": F.SOLO_MAX_DAILY_RUNS, "relics_held": data.get("relics"), "relic_check": model.describe(),
        "relic_check_ok": model.matched == model.checked, "entrances": rows,
        "plan_relics": round(sum(st.pick.relics for st in seq)),
        "plan": [{"system": _name(st.pick.dungeon), "access": st.pick.access, "start_level": st.start_level,
                  "next_start": st.next_start, "relics": round(st.pick.relics), "levels": len(st.pick.run.levels_cleared),
                  "highest": st.pick.run.highest_cleared, "expires_in": st.pick.expires_in,
                  "reward_modifier": st.pick.dungeon.get("reward_modifier") or 0,
                  "boss_weakness": st.pick.dungeon.get("boss_weakness"),
                  **_pu(st.pick, owned),
                  "dist_here": st.pick.dist_here, "dist_station": st.pick.dist_station,
                  "station": st.pick.dungeon.get("station_name"), "coords": _coords(st.pick.dungeon)} for st in seq],
        "start_after_plan": seq[-1].next_start if seq else start,
        "recent_clears": list(recent),
        "tracker": summary(data.get("logs") or [], predictions, now=data.get("now") or time.time()),
        "max_here": max_here, "max_station": max_station,
    })
    try:
        from .__main__ import streak_check
        out["streak_check"] = streak_check(stats, data.get("logs") or [])
    except Exception:  # noqa: BLE001 - informational only
        out["streak_check"] = None
    setup = {k: v for k, v in (data.get("setup") or {}).items() if isinstance(v, dict) and k != "powerups"}
    if with_upgrades and setup:
        out["upgrades"] = _upgrades(stats, setup, data, start, model)
    return out


def _upgrades(stats, setup, data, start, model) -> dict:
    from .upgrades import greedy_plan, options, sample_dungeons
    wallet = data.get("wallet") or {}
    sample = sample_dungeons(data.get("dungeons") or [], data.get("logs") or [])
    if not sample:
        return {"ok": False, "why": "No open entrances or logged runs to judge upgrades on."}
    base, opts = options(stats, setup, wallet, sample, start, model)
    plan, before, after, spent = greedy_plan(stats, setup, wallet, sample, start, model)
    rows = []
    for o in opts:
        if round(o.gain) <= 0 and rows:
            break
        qc = o.price.get("quantum_cores")
        rows.append({"label": o.up.label(), "activity": o.up.activity, "kind": o.up.kind, "points": o.up.points,
                     "after": round(o.after), "gain": round(o.gain), "can_afford": o.can_afford,
                     "cost": {k: v for k, v in o.price.items() if v},
                     "relic_cost": qc * F.QUANTUM_CORE_RELIC_COST if qc else None})
        if len(rows) >= 12:
            break
    return {"ok": True, "layouts": len(sample), "per_run": round(base), "setup": setup, "options": rows,
            "best": {"steps": [u.label() for u in plan], "before": round(before), "after": round(after), "cost": spent}}
