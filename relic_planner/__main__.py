"""python -m relic_planner  ->  which solo dungeons to run today for the most relics."""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

from . import formulas as F
from .planner import POWERUP_NAMES, evaluate, todays_plan
from .relic_model import check_logs
from .sim import simulate_run


def _dur(sec: float | None) -> str:
    if sec is None:
        return "?"
    if sec <= 0:
        return "expired"
    h, m = divmod(int(sec) // 60, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


def _num(v: float) -> str:
    for unit, div in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if abs(v) >= div:
            return f"{v / div:.1f}{unit}"
    return f"{v:.0f}"


def _ly(v) -> str:
    return "?" if v is None else f"{_num(v)} ly"


def _name(d: dict) -> str:
    sys_ = d.get("system") or {}
    return str(sys_.get("name") or d.get("name") or d.get("_id", "?"))[:22]


def _rooms(d: dict) -> str:
    letters = {"battle": "B", "gather": "G", "craft": "C", "explore": "E", "boss": "X", "prefight": ""}
    return "".join(letters.get(s.get("type"), "?") for s in d.get("steps") or [])


def streak_check(stats: dict, logs: list[dict], limit: int = 10) -> str | None:
    """Replay recent logged runs with your current stats and compare the level reached.

    Your stats may have grown since an old run, so small gaps are expected."""
    from .relic_model import log_levels
    diffs = []
    for row in logs[:limit]:
        levels = log_levels(row)
        start, top = row.get("starting_level"), row.get("level")
        if not levels or start is None or top is None:
            continue
        rooms = [s for s in levels[0].get("steps") or [] if s.get("type")]
        d = {"steps": [{"step": s.get("stepIndex", i), "type": s["type"]} for i, s in enumerate(rooms)],
             "boss_weakness": row.get("boss_weakness"),
             "difficulty_modifier": row.get("difficulty_modifier") or 0}
        diffs.append(simulate_run(stats, d, int(start)).highest_cleared - int(top))
    if not diffs:
        return None
    avg = sum(diffs) / len(diffs)
    msg = f"Simulator vs last {len(diffs)} runs: {avg:+.1f} levels (today's stats)."
    if avg < -2:
        msg += " Unexpectedly low."
    return msg


def _price(p: dict) -> str:
    return ", ".join(f"{_num(n)} {k.replace('_', ' ')}" for k, n in p.items() if n)


def show_upgrades(data: dict, stats: dict, start: int, model) -> int:
    from .upgrades import greedy_plan, options, sample_dungeons
    setup = {k: v for k, v in (data.get("setup") or {}).items() if isinstance(v, dict) and k != "powerups"}
    if not setup:
        print("Your Dungeon Setup is not loaded. In the game, open Dungeons > Setup once, then run this again.",
              file=sys.stderr)
        return 3
    wallet = data.get("wallet") or {}
    sample = sample_dungeons(data.get("dungeons") or [], data.get("logs") or [])
    if not sample:
        print("No open entrances or logged runs to judge upgrades on.", file=sys.stderr)
        return 3
    base, opts = options(stats, setup, wallet, sample, start, model)
    print(f"Judged on {len(sample)} layouts (open entrances and your recent runs), starting at level {start}.")
    print(f"Now: about {_num(base)} relics per run.\n")
    for act, s in setup.items():
        print(f"  {act:10} " + "  ".join(f"{k.replace('_', ' ')} {v}" for k, v in s.items()
                                          if isinstance(v, (int, float)) and k != "_id"))
    print()
    head = f"{'Upgrade':34} {'Relics/run':>10} {'Gain':>7}  {'Can buy':7}  Cost"
    print(head)
    print("-" * len(head))
    shown = [o for o in opts if o.gain > 0][:15] or opts[:5]
    for o in shown:
        buy = {True: "yes", False: "no", None: "?"}[o.can_afford]
        extra = ""
        qc = o.price.get("quantum_cores")
        if qc and o.gain > 0:
            extra = f"  (= {_num(qc * F.QUANTUM_CORE_RELIC_COST)} relics at the vendor, pays back in ~{math.ceil(qc * F.QUANTUM_CORE_RELIC_COST / o.gain)} runs)"
        print(f"{o.up.label():34} {_num(o.after):>10} {('+' + _num(o.gain)) if o.gain > 0 else '0':>7}  {buy:7}  {_price(o.price)}{extra}")
    if not any(o.gain > 0 for o in opts):
        print("None of these single upgrades change the outcome; your limit is elsewhere.")
    plan, before, after, spent = greedy_plan(stats, setup, wallet, sample, start, model)
    print()
    if plan:
        print(f"Best use of what you hold now: {', '.join(u.label() for u in plan)}")
        print(f"  about {_num(before)} -> {_num(after)} relics per run, costs {_price(spent)}")
    else:
        print("Nothing you can afford right now adds relics.")
    print("\nA stronger setup also raises your future start level (10 below your median clear), "
          "so the gain compounds over the following days.")
    return 0


def _print_tracker(data: dict) -> None:
    from .tracker import PredictionLog, summary
    preds = []
    try:
        from stellar_dashboard.paths import home_dir
        preds = PredictionLog(home_dir() / "dungeons" / "predictions.jsonl").load()
    except Exception:  # noqa: BLE001 - the dashboard is optional
        pass
    t = summary(data.get("logs") or [], preds, now=data.get("now"))
    if not t["complete"]:
        return
    line = f"\nRelics: {_num(t['today'])} today, {_num(t['last_7_days'])} last 7 days"
    if t["matched"]:
        line += f", actual/predicted {t['actual_vs_predicted'] * 100:.0f}% ({t['matched']} runs)"
    print(line)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="relic_planner", description=__doc__)
    ap.add_argument("--from-file", help="Plan from a saved snapshot instead of the running game")
    ap.add_argument("--save", help="Also save what was read to this JSON file")
    ap.add_argument("--game-port", type=int, help="Game DevTools port, if not found automatically")
    ap.add_argument("--user-data", help="Game profile folder, if not found automatically")
    ap.add_argument("--avoid-travel", action="store_true", help="Only plan entrances you can enter from here")
    ap.add_argument("--max-travel", type=float, metavar="LY",
                    help="Skip entrances farther than this from where you are (unless a station is close enough)")
    ap.add_argument("--max-station-travel", type=float, metavar="LY",
                    help="Skip entrances farther than this from your nearest station (unless you are close enough)")
    ap.add_argument("--all", action="store_true", help="List every entrance, not just the top 10")
    ap.add_argument("--json", action="store_true", help="Print the ranking as JSON")
    ap.add_argument("--upgrades", action="store_true",
                    help="Show how many more relics per run each Dungeon Setup upgrade would bring")
    ap.add_argument("--check-replays", type=int, metavar="N",
                    help="Read your last N solo replays and report how streaks handle HP and rooms")
    ap.add_argument("--save-replays", metavar="FILE", help="With --check-replays, also save the replays")
    a = ap.parse_args(argv)

    if a.check_replays:
        from .reader import read_replays
        from .replays import analyse
        try:
            items = read_replays(a.check_replays, a.game_port, a.user_data)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            print(f"Could not read replays: {exc}", file=sys.stderr)
            return 2
        if a.save_replays:
            Path(a.save_replays).write_text(json.dumps(items, indent=1), encoding="utf-8")
        for line in analyse(items):
            print(line)
        return 0

    if a.from_file:
        data = json.loads(Path(a.from_file).read_text(encoding="utf-8"))
    else:
        from .reader import read_game
        try:
            data = read_game(a.game_port, a.user_data)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            print(f"Could not read the game: {exc}", file=sys.stderr)
            return 2
    if a.save:
        Path(a.save).write_text(json.dumps(data, indent=1), encoding="utf-8")

    stats = data.get("stats")
    if not stats:
        print("Your solo dungeon stats are not loaded yet. In the game, open Dungeons > Solo once, "
              "then run this again.", file=sys.stderr)
        return 3
    for err in data.get("errors") or []:
        print(f"note: {err}", file=sys.stderr)

    start = F.starting_level(stats.get("recent_clears"), stats.get("highest_cleared"))
    model = check_logs(data.get("logs") or [])
    if a.upgrades:
        return show_upgrades(data, stats, start, model)
    picks = evaluate(stats, data.get("dungeons") or [], model, start, data.get("powerups") or {},
                     now=data.get("now") or time.time(), max_here=a.max_travel, max_station=a.max_station_travel)
    runs_done = data.get("daily_runs") or 0
    runs_left = max(0, F.SOLO_MAX_DAILY_RUNS - runs_done)
    from .planner import sequential_plan
    seq = sequential_plan(stats, data.get("dungeons") or [], model, runs_left, data.get("powerups") or {},
                          now=data.get("now") or time.time(), max_here=a.max_travel,
                          max_station=a.max_station_travel, avoid_travel=a.avoid_travel)
    plan = [st.pick for st in seq]
    plan_ids = {id(p.dungeon) for p in plan}

    if a.json:
        print(json.dumps([{
            "system": _name(p.dungeon), "id": p.dungeon.get("_id"), "relics": round(p.relics, 1),
            "levels_cleared": len(p.run.levels_cleared), "highest": p.run.highest_cleared,
            "ends": p.run.end_reason, "best_powerup": p.powerup, "powerup_gain": round(p.gain_from_powerup, 1),
            "access": p.access,
            "expires_in_s": p.expires_in, "usable": p.usable, "in_plan": id(p.dungeon) in plan_ids,
            "dist_here_ly": p.dist_here, "dist_station_ly": p.dist_station, "too_far": p.too_far,
        } for p in picks], indent=1))
        return 0

    unit = "relics" if model.fitted else "score"
    print(f"Start level {start}   entry cost {_num(F.entry_cost(start))} credits   "
          f"runs today {runs_done}/{F.SOLO_MAX_DAILY_RUNS}   relics held {_num(data.get('relics') or 0)}")
    print(model.describe())
    check = streak_check(stats, data.get("logs") or [])
    if check:
        print(check)
    print()
    if not picks:
        print("No solo dungeon entrances are open. Explore new systems (or send the Voyager) to find some.")
        return 0
    head = f"{'#':>2}  {'System':22} {'Access':8} {'From you':>9} {'From stn':>9} {'Expires':>8} {'Rooms':11} {'Rwd':>4} {'Diff':>4} {'Weak':10} " \
           f"{'Lvls':>4} {'Top':>4} {'Ends on':15} {unit.capitalize():>8}  Best Power-Up (extra)"
    print(head)
    print("-" * len(head))
    for i, p in enumerate(picks if a.all else picks[:10], 1):
        d = p.dungeon
        mark = "*" if id(p.dungeon) in plan_ids else ("x" if not p.usable else ("-" if p.too_far else " "))
        end = "cap" if p.run.capped else (p.run.end_reason or "").replace("_", " ")
        if p.run.weak_stats:
            end += f" ({'/'.join(sorted(set(p.run.weak_stats)))})"
        pu = f"{POWERUP_NAMES.get(p.powerup, p.powerup)} (+{_num(p.gain_from_powerup)})" if p.powerup else "-"
        print(f"{i:>2}{mark} {_name(d):22} {p.access:8} {_ly(p.dist_here):>9} {_ly(p.dist_station):>9} {_dur(p.expires_in):>8} {_rooms(d):11} "
              f"{d.get('reward_modifier', 0):>+4} {d.get('difficulty_modifier', 0):>+4} "
              f"{str(d.get('boss_weakness') or '-')[:10]:10} {len(p.run.levels_cleared):>4} "
              f"{p.run.highest_cleared:>4} {end[:15]:15} {_num(p.relics):>8}  {pu}")
    print()
    if runs_left == 0:
        print("No runs left today (reset 00:00 UTC).")
    elif not plan:
        print("Nothing worth running right now" + (" without travelling." if a.avoid_travel else "."))
    else:
        print(f"Run today ({runs_left} left):")
        for i, st in enumerate(seq, 1):
            p = st.pick
            dist = f"  {_ly(p.dist_here)} / {_ly(p.dist_station)} stn" if p.access == "travel" else ""
            owned = (data.get("powerups") or {}).get(p.powerup) if p.powerup else None
            pu = (f"  {POWERUP_NAMES[p.powerup]} +{_num(p.gain_from_powerup)}"
                  f" (have {owned if owned is not None else '?'})") if p.powerup else ""
            from .view import _coords
            print(f"  {i}. {_name(p.dungeon):22} [{_coords(p.dungeon) or '?'}] {_num(p.relics):>6} relics  lvl {st.start_level}->{p.run.highest_cleared}"
                  f"  closes {_dur(p.expires_in)}  {p.access}{dist}{pu}")
        print(f"Next start after these: {seq[-1].next_start} (now {start})")
    _print_tracker(data)
    print("\nB battle  G gather  C craft  E explore  X boss  |  * plan  x ran/expired  - too far")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
