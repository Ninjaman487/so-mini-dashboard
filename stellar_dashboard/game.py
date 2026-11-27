"""Read-only game data: resources, materials, lab queues and market prices.

Everything here is a read. State is read from the open game window; market prices
come from the same GET endpoints the game's Market page uses, fetched from inside the
game window so the game's own sign-in is used and no password or cookie is copied out.
Nothing calls the game's socket actions (sendMessage), so nothing is bought, sold,
queued, claimed or cancelled.
"""
from __future__ import annotations

import threading
import time
from collections import deque

from . import cdp as cdplib
from .history import History

API_BASE = "https://steamgame.stellarodyssey.app"

CURRENCIES = ["ammonia", "argon", "carbon", "cobalt", "copper", "dark_matter", "diamond", "emerald", "gold",
              "helium", "hydrogen", "methane", "nitrogen", "platinum", "ruby", "sapphire", "silicon", "silver",
              "sulfur", "water", "stellar_tokens", "credits", "cosmic_dust", "quantum_cores", "catalyst_parts"]
# Priced in credits, so credits itself has no market row.
MARKET_DEFAULT = [c for c in CURRENCIES if c != "credits"]

STATE_EXPR = r"""(()=>{
  let app=null; const root=document.querySelector('#q-app');
  if(root&&root.__vue_app__) app=root.__vue_app__;
  if(!app){for(const n of document.querySelectorAll('body *')){if(n.__vue_app__){app=n.__vue_app__;break}}}
  if(!app) return {ok:false,why:'no_app',route:location.hash||location.pathname};
  const pinia=app.config.globalProperties.$pinia;
  if(!pinia) return {ok:false,why:'no_pinia',route:location.hash||location.pathname};
  const s=pinia.state.value;
  const flat=o=>{const r={};if(!o)return r;for(const k in o){const v=o[k];if(v===null||['number','string','boolean'].includes(typeof v))r[k]=v}return r};
  const cur={}; const C=s.CurrencyStore||{};
  for(const k in C){if(typeof C[k]==='number')cur[k]=C[k]}
  const mats=((s.MaterialsStore||{}).materialsList||[]).map(m=>({name:m&&m.item&&m.item.name,quantity:m&&m.quantity})).filter(m=>m.name);
  const L=s.LaboratoryStore||{};
  const bld=b=>({id:b&&b._id,name:b&&(b.building||b.name),level:b&&b.level,flat:flat(b)});
  const lab={buildings:(L.buildings||[]).map(bld),base:(L.base||[]).map(bld),
             queue:(L.labQueue||[]).map(q=>({building:q.building,total:q.total,ticksClaimed:q.ticksClaimed||0,
                     timer:q.timer,multiplier:q.multiplier||1,lastClaimDate:q.lastClaimDate,flat:flat(q)}))};
  const G=s.GatherStore||{}, B=s.BattleStore||{}, K=s.CraftStore||{}, E=s.ExploreStore||{},
        P=s.PremiumStore||{}, GB=s.GlobalBoostsStore||{}, BS=s.GalaxyBossStore||{}, V=s.Voyager||{}, GS=s.GameStore||{};
  const num=v=>typeof v==='number'&&isFinite(v)?v:null;
  // Timers only. Account details (UserStore: name, email, keys) are never read.
  const voyager=V=>{const q=(V.queue||[]).filter(j=>j&&j.status!=='reached'), etas=q.map(j=>num(j.eta)).filter(x=>x);
    return {timer:num(V.timer),queue:q.length,next_eta:etas.length?Math.min(...etas):null,last_eta:etas.length?Math.max(...etas):null,
            dust:q.reduce((a,j)=>a+(num(j.cosmic_dust_reward)||0),0),fuel:num(V.current_fuel),fuel_max:num(V.max_fuel),
            max_jumps:num(V.max_jumps),reward_bonus:num(V.reward_bonus)};};
  const timers={
    battle:{active:!!B.isBattling,offline_until:num(B.offlineActionsExpiresAt),level:num(B.battling_level),
            xp:num(B.battling_current_xp),xp_target:num(B.battling_target_xp)},
    gather:{active:!!G.isGathering,offline_until:num(G.offlineActionsExpiresAt),level:num(G.gathering_level),
            xp:num(G.gathering_current_xp),xp_target:num(G.gathering_target_xp)},
    craft:{active:!!K.isCrafting,level:num(K.crafting_level),xp:num(K.crafting_current_xp),xp_target:num(K.crafting_target_xp)},
    explore:{travelling:!!E.isTravelling,engine_ready_at:E.engineCooldownLoaded===false?null:num(E.engineCooldown),
             fuel:num(E.current_fuel),level:num(E.exploring_level),
             xp:num(E.exploring_current_xp),xp_target:num(E.exploring_target_xp)},
    premium:{active:!!P.active,end:num(P.endDate)},
    boosts:(GB.currentBoosts||[]).map(b=>({name:b&&b.boost&&b.boost.name,end:num(b&&b.timer)})).filter(b=>b.name),
    boss:{event:!!BS.currentEvent,joined:!!BS.hasJoined,fighting:!!BS.fightInProgress},
    voyager:voyager(V)};
  const PS=s.PetsStore||{}, petById={};
  for(const p of PS.pets||[]) if(p&&p._id) petById[p._id]=p;
  const pets={owned:(PS.pets||[]).length, slots:(PS.petSlots||[]).length,
              slotted:(PS.petSlots||[]).filter(x=>x&&x.pet).map(x=>{const p=(typeof x.pet==='object'?x.pet:petById[x.pet])||{};
                return {name:p.name||null,level:num(p.level),type:p.pet_type||x.pet_type||null,food:num(p.food),
                        enabled:x.enabled!==false,autofeed:!!x.autofeed};})};
  const gameinfo={patch:typeof GS.patchVersion==='string'?GS.patchVersion:null,online:num(GS.playersOnline),
                  ping:num(GS.ping),maintenance:!!GS.maintenance};
  const activity={gathering:timers.gather.active,gathering_level:timers.gather.level,
                  battling:timers.battle.active,battling_level:timers.battle.level,
                  offline_until:timers.gather.offline_until||timers.battle.offline_until};
  return {ok:true,route:location.hash||location.pathname,currency:cur,materials:mats,lab,activity,timers,pets,gameinfo,now:Date.now()};
})()"""


def market_expr(currency: str) -> str:
    # Only plain names reach the URL; the request is a GET with the game's own cookies.
    if not currency.replace("_", "").replace(" ", "").isalnum():
        raise ValueError(f"bad currency name {currency!r}")
    url = f"{API_BASE}/api/market/listings/{currency}"
    return ("(async()=>{const r=await fetch(" + repr(url) + ",{credentials:'include',method:'GET'});"
            "if(!r.ok)return {ok:false,status:r.status};const d=await r.json();"
            "const top=a=>(a||[]).slice(0,5).map(o=>({price:o.price,"
            "quantity:(o.orders||[]).reduce((s,x)=>s+(Number(x.quantity)||0),0),orders:(o.orders||[]).length}));"
            "return {ok:true,buy:top(d.buyOrders),sell:top(d.sellOrders)}})()")


MINIGAMES = ("stellar-defense", "stellar-doom", "stellar-highway")


def leaderboard_expr(game: str) -> str:
    """Top five and your own entry from a minigame's leaderboard (the same GET the game makes)."""
    if game not in MINIGAMES:
        raise ValueError(f"unknown minigame {game!r}")
    url = f"{API_BASE}/api/minigames/{game}/leaderboard?page=1&rowsPerPage=5"
    return ("(async()=>{const r=await fetch(" + repr(url) + ",{credentials:'include',method:'GET'});"
            "if(!r.ok)return {ok:false,status:r.status};const d=await r.json();"
            "const row=e=>e&&({username:e.username,score:e.score,rank:e.rank??e.position??null,"
            "wave:e.metadata&&e.metadata.wave,kills:e.metadata&&e.metadata.kills,"
            "seconds:e.metadata&&(e.metadata.time??e.metadata.seconds??e.metadata.elapsed),when:e.relative_time});"
            "return {ok:true,top:(d.results||[]).slice(0,5).map(row),mine:row(d.myEntry),total:d.totalResults??null}})()")


def lab_rows(lab: dict, now_ms: float) -> list[dict]:
    """One row per lab or base building, with its queue's progress and finish time."""
    queues = {q.get("building"): q for q in lab.get("queue") or []}
    rows = []
    for kind in ("buildings", "base"):
        for b in lab.get(kind) or []:
            q = queues.get(b.get("id"))
            row = {"id": b.get("id"), "name": b.get("name") or "?", "level": b.get("level"),
                   "kind": "lab" if kind == "buildings" else "base", "queued": bool(q),
                   "built": not (isinstance(b.get("level"), (int, float)) and b.get("level") <= 0)}
            if q:
                try:
                    tick_ms = int(float(q["timer"]) / float(q.get("multiplier") or 1) * 1000)
                    left = max(0, int(q["total"]) - int(q.get("ticksClaimed") or 0))
                    finish = float(q["lastClaimDate"]) + left * tick_ms
                    done_ticks = min(left, int(max(0.0, now_ms - float(q["lastClaimDate"])) // max(1, tick_ms)))
                    row.update({"total": q["total"], "claimed": q.get("ticksClaimed") or 0,
                                "ready_to_claim": done_ticks, "multiplier": q.get("multiplier"),
                                "tick_seconds": tick_ms / 1000.0, "finish_ms": finish,
                                "remaining_s": max(0.0, (finish - now_ms) / 1000.0),
                                "progress": 1.0 - (max(0.0, finish - now_ms) / max(1.0, int(q["total"]) * tick_ms))})
                except (KeyError, TypeError, ValueError):
                    row["queue_unreadable"] = True
            rows.append(row)
    if not rows:  # queue entries for buildings the store did not list
        for q in queues.values():
            rows.append({"id": q.get("building"), "name": str(q.get("building")), "queued": True, "built": True})
    rows.sort(key=lambda r: (not r["queued"], not r.get("built", True), r.get("remaining_s") or 0, r["name"]))
    return rows


class GameReader(threading.Thread):
    """Polls the game window in the background and keeps the latest data."""

    def __init__(self, *, port: int | None = None, user_data: str | None = None, interval: float = 5.0,
                 market_minutes: float = 10.0, market_enabled: bool = True, data_dir=None,
                 leaderboard_minutes: float = 15.0):
        super().__init__(daemon=True)
        self.port_arg, self.user_data = port, user_data
        self.interval = interval
        self.market_minutes = market_minutes
        self.market_enabled = market_enabled
        self.market_list = list(MARKET_DEFAULT)
        self.lock = threading.Lock()
        self.session: cdplib.Session | None = None
        self.port = None
        self.target = None
        self.data: dict = {"connected": False, "why": "starting"}
        self.market: dict = {}
        self.market_next = 0.0
        self.market_queue: deque = deque()
        self.history: deque = deque(maxlen=720)   # (t, {currency: amount}) once a minute, 12 h
        self.slow = False                         # set by an add-on: read less often
        self.saved = History(data_dir) if data_dir else None
        self.leaderboards: dict = {}
        self.leaderboard_minutes = leaderboard_minutes
        self.board_next = 0.0
        self.board_queue: deque = deque()
        self.stop = threading.Event()

    # -- connection
    def _connect(self):
        self.port = cdplib.find_port(self.user_data, self.port_arg)
        if not self.port:
            raise cdplib.CDPError("Stellar Odyssey is not running (no DevTools port found)")
        self.target = cdplib.pick_game_target(cdplib.page_targets(self.port))
        if not self.target:
            raise cdplib.CDPError("The game window was not found")
        self.session = cdplib.Session(self.target["webSocketDebuggerUrl"])

    def _session(self) -> cdplib.Session:
        if self.session is None or self.session.closed:
            self.session = None
            self._connect()
        return self.session

    def refresh_market(self):
        with self.lock:
            self.market_next = 0.0

    def set_market_list(self, names: list[str]):
        clean = [n for n in names if n in CURRENCIES and n != "credits"]
        with self.lock:
            self.market_list = clean or list(MARKET_DEFAULT)
            self.market_queue.clear()
            self.market_next = 0.0

    # -- loop
    def run(self):
        last_hist = 0.0
        while not self.stop.is_set():
            t0 = time.time()
            try:
                s = self._session()
                state = s.evaluate(STATE_EXPR, timeout=3.0)
                if not isinstance(state, dict):
                    raise cdplib.CDPError("unexpected reply from the game window")
                state["connected"] = True
                state["port"] = self.port
                state["target_title"] = self.target.get("title")
                state["updated_at"] = t0
                if state.get("ok"):
                    state["lab_rows"] = lab_rows(state.get("lab") or {}, float(state.get("now") or t0 * 1000))
                    if t0 - last_hist >= 60:
                        self.history.append((t0, dict(state.get("currency") or {}),
                                             {m["name"]: m["quantity"] for m in state.get("materials") or []}))
                        last_hist = t0
                with self.lock:
                    self.data = state
                if state.get("ok") and self.market_enabled:
                    self._market_step(s, t0)
                if state.get("ok"):
                    self._board_step(s, t0)
                    if self.saved:
                        self.saved.maybe_record_skills(state.get("timers") or {})
                        total, by = self.worth(state)
                        if self.market_has_prices():
                            self.saved.maybe_record_worth(total, by)
            except Exception as exc:
                with self.lock:
                    keep = {k: v for k, v in self.data.items() if k not in ("connected", "why")}
                    self.data = {**keep, "connected": False, "why": str(exc)}
                if self.session is not None and self.session.closed:
                    self.session = None
            wait = self.interval * (3 if self.slow else 1)
            self.stop.wait(max(0.5, wait - (time.time() - t0)))

    def _market_step(self, s, now):
        # One price request per poll (every few seconds), so a full sweep is spread out.
        with self.lock:
            if not self.market_queue and now >= self.market_next:
                self.market_queue.extend(self.market_list)
                self.market_next = now + self.market_minutes * 60
            name = self.market_queue.popleft() if self.market_queue else None
        if not name:
            return
        try:
            r = s.evaluate(market_expr(name), timeout=6.0)
        except Exception as exc:
            r = {"ok": False, "error": str(exc)}
        r = r if isinstance(r, dict) else {"ok": False}
        r["at"] = time.time()
        with self.lock:
            old = self.market.get(name) or {}
            if not r.get("ok") and old.get("ok"):
                old["stale_error"] = r.get("error") or f"HTTP {r.get('status')}"
                r = old
            self.market[name] = r
        if self.saved and r.get("ok") and r.get("at", 0) >= now:
            self.saved.record_price(name, r)

    def _board_step(self, s, now):
        with self.lock:
            if not self.board_queue and now >= self.board_next:
                self.board_queue.extend(MINIGAMES)
                self.board_next = now + self.leaderboard_minutes * 60
            game = self.board_queue.popleft() if self.board_queue else None
        if not game:
            return
        try:
            r = s.evaluate(leaderboard_expr(game), timeout=6.0)
        except Exception as exc:
            r = {"ok": False, "error": str(exc)}
        r = r if isinstance(r, dict) else {"ok": False}
        r["at"] = time.time()
        with self.lock:
            if r.get("ok") or game not in self.leaderboards:
                self.leaderboards[game] = r

    def bid(self, name: str):
        m = self.market.get(name) or {}
        return m["buy"][0]["price"] if m.get("ok") and m.get("buy") else None

    def market_has_prices(self) -> bool:
        return sum(1 for v in self.market.values() if v.get("ok")) >= max(1, len(self.market_list) // 2)

    def worth(self, state: dict):
        """Total value in credits: credits plus every resource at its best buy order."""
        by = {}
        for k, v in (state.get("currency") or {}).items():
            if not isinstance(v, (int, float)):
                continue
            price = 1.0 if k == "credits" else self.bid(k)
            if price:
                by[k] = v * price
        return sum(by.values()), by

    # -- views
    def rates(self) -> dict:
        """Change per hour over the last hour (or what history there is, at least 10 minutes)."""
        if len(self.history) < 2:
            return {}
        t1, cur1, mat1 = self.history[-1]
        old = next((h for h in self.history if t1 - h[0] <= 3600), self.history[0])
        t0, cur0, mat0 = old
        hours = (t1 - t0) / 3600.0
        if hours < 1 / 6:
            return {}
        out = {}
        for a, b in ((cur0, cur1), (mat0, mat1)):
            for k, v in b.items():
                if isinstance(v, (int, float)) and isinstance(a.get(k), (int, float)):
                    out[k] = (v - a[k]) / hours
        return out

    def snapshot(self) -> dict:
        with self.lock:
            data = dict(self.data)
            market = {k: dict(v) for k, v in self.market.items()}
            queue_left = len(self.market_queue)
            nxt = self.market_next
            mlist = list(self.market_list)
            boards = {k: dict(v) for k, v in self.leaderboards.items()}
        rates = self.rates()
        income = {}
        for k, r in rates.items():
            price = 1.0 if k == "credits" else self.bid(k)
            if price and r:
                income[k] = r * price
        out = {"game": data, "market": {"rows": market, "next_sweep_at": nxt, "in_progress": queue_left,
                                        "enabled": self.market_enabled, "list": mlist,
                                        "minutes": self.market_minutes},
               "rates": rates, "income": income, "leaderboards": boards}
        if self.saved:
            out["skills"] = self.saved.skill_view(data.get("timers") or {})
            out["trends"] = self.saved.price_trends()
            out["worth"] = self.saved.worth_view()
        return out
