"""What-if for Dungeon Setup upgrades: how many more relics each one would bring.

Upgrade effects (wiki "Dungeon Formulas", checked against recorded replays, where
final = base x (1 + boost/100) x (1 + tier/100) to the unit):
  battling  boost/tier -> damage and HP (battle and boss rooms)
  gathering boost/tier -> gather power
  crafting  boost/tier -> craft power
  exploring boost/tier -> explore power
  radiation protection, per activity -> 10 protection per point (wiki; not yet seen in a replay
  because yours are all at 0). Boss rooms use the battling value.

Costs:
  boost: quantum cores; tier: that activity's dungeon power; both cost
    T(to) - T(from) with T(n) = n(n+1)(n+2)/6
  radiation: base/4 x points x (from + to + 3) of each listed resource.

Read-only: this only calculates. You buy upgrades yourself in the game.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass

from . import formulas as F
from .relic_model import RelicModel
from .sim import simulate_run

ACTIVITIES = {
    "battling": {"boost": "battle_boost", "tier": "battle_tier", "power": "obsidian_power", "stats": ("damage", "hp")},
    "gathering": {"boost": "gather_boost", "tier": "gather_tier", "power": "ivory_power", "stats": ("gather",)},
    "crafting": {"boost": "craft_boost", "tier": "craft_tier", "power": "iron_power", "stats": ("craft",)},
    "exploring": {"boost": "explore_boost", "tier": "explore_tier", "power": "onyx_power", "stats": ("explore",)},
}
NPC, LAB = 50_000, 200_000
RADIATION_COSTS = {   # resource -> base
    "battling": {"bones": NPC, "cog": NPC, "credits": 3_000_000_000, "aerolite": LAB},
    "gathering": {"condensed sand": NPC, "horn": NPC, "argoflux": 1_000, "cryovita": LAB},
    "crafting": {"ectoplasm": NPC, "frost shard": NPC, "metal scrap": 1_000_000, "ferricrystal": LAB},
    "exploring": {"flame": NPC, "slime": NPC, "cosmic_dust": 250_000, "luminaris": LAB},
}
PROTECTION_PER_POINT = 10


def _tet(n: int) -> float:
    return n * (n + 1) * (n + 2) / 6


def level_cost(frm: int, to: int) -> int:
    return 0 if to <= frm else math.floor(_tet(to) - _tet(frm))


def radiation_cost(base: float, frm: int, to: int) -> int:
    return 0 if to <= frm else math.floor(base / 4 * (to - frm) * (frm + to + 3))


@dataclass
class Upgrade:
    activity: str
    kind: str          # "boost", "tier" or "radiation"
    points: int

    def label(self) -> str:
        name = {"boost": "boost", "tier": "tier", "radiation": "radiation protection"}[self.kind]
        return f"{self.activity} {name} +{self.points}"


def cost(setup: dict, up: Upgrade) -> dict[str, int]:
    act = setup.get(up.activity) or {}
    if up.kind == "radiation":
        cur = int(act.get("radiation_prot") or 0)
        return {res: radiation_cost(base, cur, cur + up.points) for res, base in RADIATION_COSTS[up.activity].items()}
    key = ACTIVITIES[up.activity][up.kind]
    cur = int(act.get(key) or 0)
    pay = "quantum_cores" if up.kind == "boost" else ACTIVITIES[up.activity]["power"]
    return {pay: level_cost(cur, cur + up.points)}


def affordable(price: dict[str, int], wallet: dict[str, float], setup: dict) -> bool | None:
    """True/False, or None when we could not read how much you hold of something."""
    for res, n in price.items():
        have = wallet.get(res)
        if have is None:
            for act in setup.values():
                if isinstance(act, dict) and res in act:
                    have = act[res]
        if have is None:
            return None
        if have < n:
            return False
    return True


def apply(stats: dict, setup: dict, up: Upgrade) -> tuple[dict, dict]:
    """New (stats, setup) after an upgrade."""
    st, su = copy.deepcopy(stats), copy.deepcopy(setup)
    act = su.setdefault(up.activity, {})
    if up.kind == "radiation":
        cur = int(act.get("radiation_prot") or 0)
        act["radiation_prot"] = cur + up.points
        prot = st.setdefault("radiationProt", {})
        prot[up.activity] = act["radiation_prot"] * PROTECTION_PER_POINT
        if up.activity == "battling" and "boss" in prot:
            prot["boss"] = prot[up.activity]
        room = {"battling": "battle", "gathering": "gather", "crafting": "craft", "exploring": "explore"}[up.activity]
        if room in prot:
            prot[room] = prot[up.activity]
        return st, su
    key = ACTIVITIES[up.activity][up.kind]
    cur = int(act.get(key) or 0)
    act[key] = cur + up.points
    ratio = (1 + (cur + up.points) / 100) / (1 + cur / 100)
    for s in ACTIVITIES[up.activity]["stats"]:
        # Final stats are rounded down by the game; add back half a unit before scaling.
        st[s] = math.floor(((st.get(s) or 0) + 0.5) * ratio)
    return st, su


def sample_dungeons(dungeons: list[dict], logs: list[dict], limit_logs: int = 10) -> list[dict]:
    """Layouts to judge upgrades on: open entrances plus your recent runs' layouts."""
    from .relic_model import log_levels
    out = [d for d in dungeons or [] if d.get("steps")]
    for row in (logs or [])[:limit_logs]:
        levels = log_levels(row)
        if not levels:
            continue
        rooms = [s for s in levels[0].get("steps") or [] if s.get("type")]
        out.append({"steps": [{"step": s.get("stepIndex", i), "type": s["type"]} for i, s in enumerate(rooms)],
                    "boss_weakness": row.get("boss_weakness"),
                    "difficulty_modifier": row.get("difficulty_modifier") or 0,
                    "reward_modifier": row.get("reward_modifier") or 0})
    return out


def relics_per_run(stats: dict, sample: list[dict], start: int, model: RelicModel) -> float:
    if not sample:
        return 0.0
    return sum(model.predict(simulate_run(stats, d, start), d.get("reward_modifier") or 0) for d in sample) / len(sample)


@dataclass
class Option:
    up: Upgrade
    price: dict
    can_afford: bool | None
    before: float
    after: float

    @property
    def gain(self) -> float:
        return self.after - self.before


def options(stats: dict, setup: dict, wallet: dict, sample: list[dict], start: int, model: RelicModel,
            steps=(1, 5, 10)) -> tuple[float, list[Option]]:
    base = relics_per_run(stats, sample, start, model)
    out = []
    for act in ACTIVITIES:
        for kind in ("boost", "tier", "radiation"):
            for n in steps:
                up = Upgrade(act, kind, n)
                st, _ = apply(stats, setup, up)
                price = cost(setup, up)
                out.append(Option(up, price, affordable(price, wallet, setup), base,
                                  relics_per_run(st, sample, start, model)))
    out.sort(key=lambda o: -o.gain)
    return base, out


def greedy_plan(stats: dict, setup: dict, wallet: dict, sample: list[dict], start: int, model: RelicModel,
                max_steps: int = 40) -> tuple[list[Upgrade], float, float, dict]:
    """Spend what you hold, one affordable upgrade at a time, always the one that adds the most relics."""
    wallet = dict(wallet)
    stats, setup = copy.deepcopy(stats), copy.deepcopy(setup)
    start_val = cur = relics_per_run(stats, sample, start, model)
    plan, spent = [], {}
    for _ in range(max_steps):
        best = None
        for act in ACTIVITIES:
            for kind in ("boost", "tier", "radiation"):
                for n in (1, 2, 5, 10):
                    up = Upgrade(act, kind, n)
                    price = cost(setup, up)
                    if affordable(price, wallet, setup) is not True:
                        continue
                    st, su = apply(stats, setup, up)
                    v = relics_per_run(st, sample, start, model)
                    score = (v - cur) / n
                    if v > cur + 1e-9 and (best is None or score > best[0]):
                        best = (score, up, st, su, v, price)
        if best is None:
            break
        _, up, stats, setup_new, cur, price = best
        for res, n in price.items():
            spent[res] = spent.get(res, 0) + n
            if res in wallet:
                wallet[res] -= n
            else:
                for a in setup_new.values():
                    if isinstance(a, dict) and res in a:
                        a[res] -= n
        setup = setup_new
        same = next((u for u in plan if u.activity == up.activity and u.kind == up.kind), None)
        if same:
            same.points += up.points
        else:
            plan.append(up)
    return plan, start_val, cur, spent
