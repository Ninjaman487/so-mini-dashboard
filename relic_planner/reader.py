"""Read solo dungeon data from the running game window. Read-only.

What it does, all from inside the game window over the local DevTools port:
  * reads the game's own DungeonStore (your solo dungeon stats, runs today, Dungeon Setup)
    and how much you hold of the currencies and materials that upgrades cost;
  * fetches the entrance list and your solo dungeon logs with the same GET requests the
    game's Dungeons page makes, so the game's own sign-in is used and nothing is copied out.

It never sends socket messages, never enters a dungeon, never clicks or types.
Your player id is only compared inside the page; it is not returned.
"""
from __future__ import annotations

import json

from . import cdp as cdplib

API_BASE = "https://steamgame.stellarodyssey.app"

READ_EXPR = r"""(async()=>{
  let app=null; const root=document.querySelector('#q-app');
  if(root&&root.__vue_app__) app=root.__vue_app__;
  if(!app){for(const n of document.querySelectorAll('body *')){if(n.__vue_app__){app=n.__vue_app__;break}}}
  if(!app) return {ok:false,why:'no_app'};
  const pinia=app.config.globalProperties.$pinia; if(!pinia) return {ok:false,why:'no_pinia'};
  const s=pinia.state.value, D=s.DungeonStore||{};
  let sys=null, uid=null, credits=null;
  for(const k in s){const v=s[k]||{};
    if(!sys&&v.currentSystem&&v.currentSystem._id) sys=v.currentSystem;
    if(!uid&&typeof v.uid==='string') uid=v.uid;}
  if(s.CurrencyStore&&typeof s.CurrencyStore.credits==='number') credits=s.CurrencyStore.credits;
  const get=async(path)=>{const r=await fetch(%(base)s+path,{credentials:'include',method:'GET'});
    if(!r.ok) throw new Error(path+' '+r.status); return r.json();};
  // Same distance as the game's Dungeons page: 10 light-years per map unit.
  const ly=(x1,y1,x2,y2)=>Math.sqrt((Math.abs(x1-x2)*10)**2+(Math.abs(y1-y2)*10)**2);
  let stations=[];
  for(const k in s){const v=s[k]||{}; if(Array.isArray(v.spaceStations)&&v.spaceStations.length){stations=v.spaceStations;break}}
  stations=stations.filter(t=>t&&t.system_parked).map(t=>({name:t.name||null,x:t.system_parked.coordinate_x,y:t.system_parked.coordinate_y}));
  const strip=d=>{const o=JSON.parse(JSON.stringify(d));
    const sx=o.system&&o.system.coordinate_x, sy=o.system&&o.system.coordinate_y;
    if(typeof sx==='number'&&typeof sy==='number'){
      if(sys&&typeof sys.coordinate_x==='number') o.dist_here=ly(sx,sy,sys.coordinate_x,sys.coordinate_y);
      let best=null; for(const t of stations){const dd=ly(sx,sy,t.x,t.y); if(!best||dd<best.d) best={d:dd,name:t.name};}
      if(best){o.dist_station=best.d; o.station_name=best.name;}}
    o.in_current_system=!!(sys&&o.system&&o.system._id===sys._id);
    o.voyager_access=!!(uid&&o.voyager_discovered_by===uid);
    o.already_ran=!!(uid&&Array.isArray(o.runners)&&o.runners.includes(uid));
    delete o.voyager_discovered_by; delete o.runners; return o;};
  let dungeons=[], logs=[], errors=[];
  try{dungeons=((await get('/api/dungeons/solodungeons')).dungeons||[]).map(strip)}catch(e){errors.push(String(e))}
  for(let page=1;page<=%(pages)d;page++){
    try{const d=await get('/api/dungeons/solodungeonlogs?page='+page+'&limit=50&sortBy=completedAt&descending=true');
      const rows=d.logs||d.rows||d.results||d.data||(Array.isArray(d)?d:[]);
      logs.push(...rows); if(rows.length<50) break;}catch(e){errors.push(String(e));break}}
  const st=D.soloPlayerStats?JSON.parse(JSON.stringify(D.soloPlayerStats)):null;
  const setupAll=D.setup?JSON.parse(JSON.stringify(D.setup)):{};
  const setup=setupAll.powerups||{};
  const C=s.CurrencyStore||{}, wallet={};
  for(const k of ['credits','cosmic_dust','quantum_cores']) if(typeof C[k]==='number') wallet[k]=C[k];
  const want=%(mats)s;
  for(const m of ((s.MaterialsStore||{}).materialsList||[])){const n=m&&m.item&&m.item.name;
    if(n&&want.includes(n)) wallet[n]=m.quantity;}
  for(const n of want) if(!(n in wallet)&&(s.MaterialsStore||{}).materialsList) wallet[n]=0;
  return {ok:true,stats:st,daily_runs:typeof D.soloDailyRuns==='number'?D.soloDailyRuns:null,
          relics:typeof D.soloRelics==='number'?D.soloRelics:null,powerups:setup,credits,setup:setupAll,wallet,
          current_system:sys?{name:sys.name||null,x:sys.coordinate_x,y:sys.coordinate_y}:null,
          dungeons,logs,errors,now:Date.now()/1000};
})()"""


def read_game(port: int | None = None, user_data: str | None = None, log_pages: int = 4) -> dict:
    p = cdplib.find_port(user_data, port)
    if not p:
        raise cdplib.CDPError("Stellar Odyssey is not running (no DevTools port found)")
    target = cdplib.pick_game_target(cdplib.page_targets(p))
    if not target:
        raise cdplib.CDPError("The game window was not found")
    s = cdplib.Session(target["webSocketDebuggerUrl"])
    try:
        from .upgrades import RADIATION_COSTS
        mats = sorted({r for c in RADIATION_COSTS.values() for r in c} - {"credits", "cosmic_dust"})
        expr = READ_EXPR % {"base": json.dumps(API_BASE), "pages": int(log_pages), "mats": json.dumps(mats)}
        data = s.evaluate(expr, timeout=20.0)
    finally:
        s.close()
    if not isinstance(data, dict) or not data.get("ok"):
        raise cdplib.CDPError(f"Could not read the game: {data!r}")
    return data


REPLAY_EXPR = r"""(async()=>{
  const get=async(path)=>{const r=await fetch(%(base)s+path,{credentials:'include',method:'GET'});
    if(!r.ok) throw new Error(path+' '+r.status); return r.json();};
  const d=await get('/api/dungeons/solodungeonlogs?page=1&limit=%(n)d&sortBy=completedAt&descending=true');
  const rows=d.results||d.logs||d.rows||d.data||(Array.isArray(d)?d:[]);
  const out=[];
  for(const row of rows){ if(!row||!row._id) continue;
    try{out.push({log:row,replay:await get('/api/dungeons/solodungeonreplay/'+encodeURIComponent(row._id))})}
    catch(e){out.push({log:row,error:String(e)})} }
  return {ok:true,replays:out};
})()"""


def read_replays(n: int = 5, port: int | None = None, user_data: str | None = None) -> list[dict]:
    """Your last n solo runs with their replays (the same GETs the Logs tab's replay button makes)."""
    p = cdplib.find_port(user_data, port)
    if not p:
        raise cdplib.CDPError("Stellar Odyssey is not running (no DevTools port found)")
    target = cdplib.pick_game_target(cdplib.page_targets(p))
    if not target:
        raise cdplib.CDPError("The game window was not found")
    s = cdplib.Session(target["webSocketDebuggerUrl"])
    try:
        data = s.evaluate(REPLAY_EXPR % {"base": json.dumps(API_BASE), "n": max(1, min(int(n), 20))},
                          timeout=60.0)
    finally:
        s.close()
    if not isinstance(data, dict) or not data.get("ok"):
        raise cdplib.CDPError(f"Could not read replays: {data!r}")
    return data["replays"]
