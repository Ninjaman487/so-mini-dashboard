from __future__ import annotations

from relic_planner import formulas as F
from relic_planner.planner import evaluate, todays_plan
from relic_planner.relic_model import RelicModel, fit
from relic_planner.sim import simulate_run

STATS = {"damage": 5000, "hp": 4000, "gather": 2_000_000, "craft": 4000, "explore": 6000,
         "radiationProt": {}, "weakness": {"thermal": 50}}


def dungeon(rooms, rm=0, dm=0, weak="kinetic", **kw):
    steps = [{"step": i, "type": t} for i, t in enumerate(rooms)]
    steps += [{"step": len(rooms), "type": "prefight"}, {"step": len(rooms) + 1, "type": "boss"}]
    return {"_id": kw.pop("id", "d"), "steps": steps, "reward_modifier": rm, "difficulty_modifier": dm,
            "boss_weakness": weak, "system": {"name": kw.pop("name", "Sys")}, **kw}


def test_streak_from_level_one_jumps():
    run = simulate_run(STATS, dungeon(["battle"]), 1)
    assert run.levels_cleared[0] == 1
    assert run.levels_cleared[1] - run.levels_cleared[0] in (1, 2, 5, 10)
    assert run.failed_level is not None


def test_streak_above_one_steps_by_one():
    run = simulate_run(STATS, dungeon(["battle"]), 5)
    assert run.levels_cleared == list(range(5, 5 + len(run.levels_cleared)))


def test_weakness_and_reward_change_the_ranking():
    ds = [dungeon(["battle"] * 3, rm=0, weak="kinetic", id="a", name="A"),
          dungeon(["battle"] * 3, rm=0, weak="thermal", id="b", name="B"),
          dungeon(["battle"] * 3, rm=40, weak="thermal", id="c", name="C"),
          dungeon(["battle"] * 3, rm=40, weak="thermal", id="d", name="D", already_ran=True)]
    picks = evaluate(STATS, ds, RelicModel(), 10)
    assert [p.dungeon["_id"] for p in picks] == ["c", "b", "a", "d"]
    plan = todays_plan(picks, 2)
    assert [p.dungeon["_id"] for p in plan] == ["c", "b"]


def test_relics_are_without_powerups_and_best_powerup_is_extra():
    d = dungeon(["battle"] * 4)
    p = evaluate(STATS, [d], RelicModel(), 10, {"dungeonStrength": 0})[0]
    base = simulate_run(STATS, d, 10)
    assert p.run.levels_cleared == base.levels_cleared          # the plan never assumes a Power-Up
    assert p.relics == RelicModel().predict(base, 0)
    if p.powerup:
        assert p.powerup in ("lifeRestore", "dungeonStrength") and p.gain_from_powerup > 0
        with_pu = simulate_run(STATS, d, 10, p.powerup)
        assert abs(RelicModel().predict(with_pu, 0) - p.relics - p.gain_from_powerup) < 1e-6
    else:
        assert p.gain_from_powerup == 0


def test_relic_formula_matches_logged_levels():
    from relic_planner.relic_model import relics_for_level
    # (level, reward %, relics) taken from real replays
    for lv, rm, want in [(62, 40, 190), (72, 40, 221), (61, 36, 182), (61, 34, 179), (60, 30, 171), (72, 30, 205)]:
        assert relics_for_level(lv, rm) == want


def test_check_logs_counts_cleared_and_failed_levels():
    from relic_planner.relic_model import check_logs
    lvl = lambda L, st, r: {"level": L, "steps": [{"type": "boss", "status": st}], "rewards": {"dungeon_relics": r}}
    m = check_logs([{"reward_modifier": 40, "steps": [lvl(62, "cleared", 190), lvl(63, "failed", 0)]}])
    assert (m.checked, m.matched) == (2, 2)
    m = check_logs([{"reward_modifier": 40, "steps": [lvl(62, "cleared", 999)]}])
    assert m.matched == 0 and "Warning" in m.describe()


def test_server_mode_matches_a_real_streak():
    # Stats, rooms and outcome of a real logged run (start 62, last clear 72, fails on 73).
    stats = {"damage": 28620, "hp": 191912, "gather": 710321, "craft": 41383, "explore": 65249,
             "weakness": {k: 60 for k in ["energy", "electromagnetic", "explosive", "incendiary", "kinetic", "chemical"]},
             "radiationProt": {"battling": 0, "gathering": 0, "crafting": 0, "exploring": 0}}
    d = dungeon(["explore", "craft", "explore", "craft"], dm=-11, weak="electromagnetic")
    run = simulate_run(stats, d, 62)
    assert run.levels_cleared == list(range(62, 73)) and run.failed_level == 73
    from relic_planner.sim import simulate_level
    end_hp = [simulate_level(stats, d, None, L)["steps"][-1]["hp_remaining"] for L in (62, 63, 72)]
    assert end_hp == [158447, 129911, 15557]
    assert RelicModel().predict(run, 40) == 2265


def test_entry_cost_and_start_level():
    assert F.entry_cost(10) == 1_000_000
    assert F.starting_level([30, 40, 51], 60) == 30
    assert F.starting_level([], 5) == 1


def test_replay_analysis_spots_refill_and_rooms():
    from relic_planner.replays import analyse
    def snap(hp):
        return {"step_data": {"players": [{"hp": hp, "maxhp": 100}]}}
    def lvl(L, hps):
        return {"level": L, "steps": [{"type": t, "stepIndex": i, "status": "cleared", "snapshots": [snap(h)]}
                                      for i, (t, h) in enumerate(zip(["battle", "gather", "boss"], hps))]}
    items = [{"log": {"starting_level": 5, "level": 6},
              "replay": {"steps": [lvl(5, [90, 85, 40]), lvl(6, [100, 90, 30]), lvl(7, [25, 20, 0])]}}]
    out = "\n".join(analyse(items))
    assert "refilled 1 time(s), carried over 1 time(s)" in out
    assert "same as level one 2 time(s)" in out


def test_upgrade_costs_match_game_formulas():
    from relic_planner.upgrades import Upgrade, cost, level_cost, radiation_cost
    assert level_cost(5, 10) == 185          # tetrahedral numbers: 220 - 35
    assert radiation_cost(50_000, 0, 10) == 1_625_000
    setup = {"battling": {"battle_boost": 5, "battle_tier": 45, "radiation_prot": 0, "obsidian_power": 537}}
    assert cost(setup, Upgrade("battling", "boost", 5)) == {"quantum_cores": 185}
    assert cost(setup, Upgrade("battling", "tier", 5)) == {"obsidian_power": level_cost(45, 50)}


def test_upgrades_scale_stats_and_protection():
    from relic_planner.upgrades import Upgrade, apply
    stats = {"damage": 28620, "hp": 191912, "radiationProt": {"battling": 0}}
    setup = {"battling": {"battle_boost": 5, "battle_tier": 45, "radiation_prot": 0}}
    st, su = apply(stats, setup, Upgrade("battling", "boost", 5))
    # base 18798.4384 x 1.10 x 1.45 = 29983.5
    assert st["damage"] == 29983 and su["battling"]["battle_boost"] == 10
    st, _ = apply(stats, setup, Upgrade("battling", "radiation", 8))
    assert st["radiationProt"]["battling"] == 80


def test_more_protection_never_hurts_a_deep_run():
    from relic_planner.upgrades import Upgrade, apply, relics_per_run
    stats = {"damage": 28620, "hp": 191912, "gather": 710321, "craft": 41383, "explore": 65249,
             "weakness": {"electromagnetic": 60}, "radiationProt": {"battling": 0}}
    setup = {"battling": {"battle_boost": 5, "battle_tier": 45, "radiation_prot": 0}}
    d = dungeon(["explore", "craft", "explore", "craft"], rm=40, dm=-11, weak="electromagnetic")
    before = relics_per_run(stats, [d], 62, RelicModel())
    st, _ = apply(stats, setup, Upgrade("battling", "radiation", 10))
    assert relics_per_run(st, [d], 62, RelicModel()) > before


def test_dashboard_view_builds_from_a_snapshot():
    import json
    from pathlib import Path
    from relic_planner.view import build
    snap = json.loads((Path(__file__).resolve().parent / "example_snapshot.json").read_text())
    v = build(snap)
    assert v["ok"] and v["entrances"] and v["upgrades"]["ok"]
    assert sum(r["in_plan"] for r in v["entrances"]) == 2
    json.dumps(v)   # the page receives it as JSON
    assert not build({"stats": None})["ok"]


def test_travel_limits_drop_far_entrances_from_the_plan():
    near = dungeon(["battle"], rm=0, id="near", dist_here=500, dist_station=9000)
    far = dungeon(["battle"], rm=40, id="far", dist_here=30000, dist_station=20000)
    here = dungeon(["battle"], rm=10, id="here", in_current_system=True, dist_here=0, dist_station=50000)
    picks = evaluate(STATS, [near, far, here], RelicModel(), 10, max_here=5000, max_station=5000)
    by = {p.dungeon["_id"]: p for p in picks}
    assert by["far"].too_far and not by["near"].too_far and not by["here"].too_far
    assert [p.dungeon["_id"] for p in todays_plan(picks, 3)] == ["here", "near"]
    # either route is enough: close to a station but far from you
    p = evaluate(STATS, [dungeon(["battle"], dist_here=30000, dist_station=1000)], RelicModel(), 10,
                 max_here=5000, max_station=5000)[0]
    assert not p.too_far
    # no limits set: nothing is too far
    assert not evaluate(STATS, [far], RelicModel(), 10)[0].too_far


def test_sequential_plan_raises_start_level_between_runs():
    from relic_planner.planner import sequential_plan
    stats = dict(STATS, recent_clears=[30, 30, 30], highest_cleared=30)
    ds = [dungeon(["battle"], rm=20, id="a"), dungeon(["battle"], rm=10, id="b"), dungeon(["battle"], rm=0, id="c")]
    seq = sequential_plan(stats, ds, RelicModel(), 3)
    assert [s.pick.dungeon["_id"] for s in seq] == ["a", "b", "c"]
    assert seq[0].start_level == 20
    for a, b in zip(seq, seq[1:]):
        assert b.start_level == a.next_start
    assert all(s.pick.relics > 0 for s in seq)


def test_tracker_sums_days_and_matches_predictions(tmp_path):
    from relic_planner.tracker import PredictionLog, summary
    now = 1_800_000_000
    log = PredictionLog(tmp_path / "p.jsonl")
    log.record([{"reward_modifier": 40, "difficulty_modifier": -11, "boss_weakness": "em", "relics": 2200, "highest": 72}],
               62, now - 3000)
    import relic_planner.tracker as T
    T.KEEP_DAYS = 10**6
    logs = [{"completedAt": now - 1000, "starting_level": 62, "level": 72, "reward_modifier": 40,
             "difficulty_modifier": -11, "boss_weakness": "em", "rewards": {"dungeon_relics": 2265}},
            {"completedAt": now - 9 * 86400, "starting_level": 60, "level": 70, "reward_modifier": 0,
             "difficulty_modifier": 0, "boss_weakness": "em", "rewards": {"dungeon_relics": 1000}}]
    t = summary(logs, log.load(), now=now)
    assert t["today"] == 2265 and t["last_7_days"] == 2265
    assert t["matched"] == 1 and t["runs"][0]["predicted"] == 2200
    assert sum(v for _, v in t["per_day"]) == 3265
