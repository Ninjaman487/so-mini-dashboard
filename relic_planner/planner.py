"""Rank the solo dungeon entrances you can see by expected relics."""
from __future__ import annotations

import time
from dataclasses import dataclass

from . import formulas as F
from .relic_model import RelicModel
from .sim import RunResult, simulate_run

POWERUP_NAMES = {None: "none", "lifeRestore": "Life restore", "dungeonStrength": "Dungeon strength",
                 "blockChance": "Block chance"}


# Power-Ups the simulator can model. Block chance is not modelled, so it is never suggested.
MODELLED_POWERUPS = ("lifeRestore", "dungeonStrength")


@dataclass
class Pick:
    """One entrance. relics and run are WITHOUT a Power-Up (the default); powerup is the
    Power-Up that would add the most, with its extra relics in gain_from_powerup."""
    dungeon: dict
    run: RunResult
    relics: float
    powerup: str | None
    gain_from_powerup: float
    access: str           # "here", "voyager", "travel"
    already_ran: bool
    expires_in: float | None   # seconds
    options: dict = None       # powerup -> (relics, RunResult), "none" key for no Power-Up
    too_far: bool = False      # outside the travel limits you set

    @property
    def usable(self) -> bool:
        return not self.already_ran and (self.expires_in is None or self.expires_in > 0)

    @property
    def dist_here(self):
        return self.dungeon.get("dist_here")

    @property
    def dist_station(self):
        return self.dungeon.get("dist_station")


def within_reach(d: dict, access: str, max_here: float | None, max_station: float | None) -> bool:
    """No travel needed, or close enough by either route: from where you are, or from your nearest station."""
    if access != "travel" or (max_here is None and max_station is None):
        return True
    here, st = d.get("dist_here"), d.get("dist_station")
    ok_here = max_here is not None and here is not None and here <= max_here
    ok_station = max_station is not None and st is not None and st <= max_station
    unknown = (max_here is None or here is None) and (max_station is None or st is None)
    return ok_here or ok_station or unknown


def _access(d: dict) -> str:
    if d.get("in_current_system"):
        return "here"
    if d.get("voyager_access"):
        return "voyager"
    return "travel"


def evaluate(stats: dict, dungeons: list[dict], model: RelicModel, start_level: int,
             powerups_owned: dict | None = None, now: float | None = None,
             max_here: float | None = None, max_station: float | None = None) -> list[Pick]:
    now = time.time() if now is None else now
    picks = []
    for d in dungeons:
        rm = d.get("reward_modifier") or 0
        base_run = simulate_run(stats, d, start_level, None)
        base = model.predict(base_run, rm)
        best = (base, None, base_run)
        opts = {None: (base, base_run)}
        for pu in MODELLED_POWERUPS:
            r = simulate_run(stats, d, start_level, pu)
            v = model.predict(r, rm)
            opts[pu] = (v, r)
            if v > best[0] + 1e-9:
                best = (v, pu, r)
        closes = d.get("closesAt")
        picks.append(Pick(dungeon=d, run=base_run, relics=base, powerup=best[1],
                          gain_from_powerup=best[0] - base, access=_access(d),
                          already_ran=bool(d.get("already_ran")),
                          expires_in=(closes - now) if closes else None, options=opts,
                          too_far=not within_reach(d, _access(d), max_here, max_station)))
    # Usable first, then most relics; entrances you can enter without travelling win ties.
    order = {"here": 0, "voyager": 1, "travel": 2}
    picks.sort(key=lambda p: (not p.usable, p.too_far, -round(p.relics, 6), order[p.access]))
    return picks


def todays_plan(picks: list[Pick], runs_left: int, avoid_travel: bool = False,
                powerups_owned: dict | None = None) -> list[Pick]:
    """Best entrances for the runs left, ranked without Power-Ups."""
    pool = [p for p in picks if p.usable and not p.too_far and (p.access != "travel" or not avoid_travel)]
    return pool[:max(0, runs_left)]


@dataclass
class PlanStep:
    pick: Pick
    start_level: int
    next_start: int        # start level of the run after this one (estimate)


def next_clears(recent: list[int] | None, highest_reached: int) -> list[int]:
    """Recent clears after a run. The server's window is not known, so this keeps every
    clear it has listed and adds the new one (an estimate; see README)."""
    return list(recent or []) + [highest_reached]


def sequential_plan(stats: dict, dungeons: list[dict], model: RelicModel, runs_left: int,
                    powerups_owned: dict | None = None, now: float | None = None,
                    max_here: float | None = None, max_station: float | None = None,
                    avoid_travel: bool = False, only: set | None = None) -> list[PlanStep]:
    """Today's runs in order, without Power-Ups. Each run changes your recent clears, and so the start level of
    the next run, so every run is planned at the start level it will actually have.
    With `only` (entrance ids you picked), the plan uses just those, whatever the travel limits."""
    recent = list(stats.get("recent_clears") or [])
    highest = stats.get("highest_cleared") or 0
    used: set = set()
    steps: list[PlanStep] = []
    for _ in range(max(0, runs_left)):
        start = F.starting_level(recent, highest)
        picks = evaluate(stats, [d for d in dungeons if id(d) not in used], model, start, None, now,
                         max_here, max_station)
        if only is not None:
            pool = [p for p in picks if p.usable and p.dungeon.get("_id") in only]
        else:
            pool = [p for p in picks if p.usable and not p.too_far and (p.access != "travel" or not avoid_travel)]
        if not pool:
            break
        best = pool[0]
        used.add(id(best.dungeon))
        if best.run.highest_cleared:
            recent = next_clears(recent, best.run.highest_cleared)
            highest = max(highest, best.run.highest_cleared)
        steps.append(PlanStep(best, start, F.starting_level(recent, highest)))
    return steps
