# SO Mini Dashboard

A read-only dashboard for Stellar Odyssey. It shows your resources, lab queues, market
prices, skills, leaderboards and the best solo dungeons to run today, on one page in your
browser.

It only reads. It never buys, sells, queues, claims, enters dungeons or presses keys in the
game.

## Install and run (Windows)

1. Download `SO-Mini-Dashboard.exe` from the
   [latest release](https://github.com/Ninjaman487/so-mini-dashboard/releases/latest).
2. Start Stellar Odyssey.
3. Double-click `SO-Mini-Dashboard.exe`. The dashboard opens in your browser.

Keep the black window open while you use it; close it to stop the dashboard.

The first time, Windows may show "Windows protected your PC", because the file is not
code-signed. Click **More info**, then **Run anyway**.

## Updating

Your version is shown next to the title (for example `v1.0.0`). When a newer release is
out, a green **Update available** badge appears there. Click it, download the new `.exe`
and replace the old one. Your saved history is kept.

## Tabs

- **Overview**: only what needs you now (finished or idle lab, engine ready, offline actions
  running out, ...) with a "Coming up" line, running lab queues, skills with XP per hour,
  ship and account, and resource value by group.
- **Resources**: every currency and resource by node type, and materials in the game's
  categories, with change per hour and value at market price.
- **Lab**: every building's queue, time left and finish time in your local time.
- **Market**: best buy and sell price, spread, depth and 7-day trend for each resource.
- **Progress**: net worth over time, income per hour, and the weekly minigame leaderboards.
- **Dungeons**: which solo dungeon entrances pay the most relics today, with coordinates,
  distances, an upgrade what-if and a relic tracker. Open **Dungeons > Solo** in the game
  once first so it has your stats.

**Compact** gives a narrow layout for a side monitor. **Alerts** turns on desktop
notifications when a queue finishes or a timer runs out.

## Privacy

Everything stays on your PC. The page is served only to your own computer
(`127.0.0.1:8766`). Market prices, leaderboards and dungeon data are read with the same
requests the game itself makes, using the game's own sign-in; your login is never read or
copied. The only other connection is a check for new releases on GitHub a few times a day
(turn it off with `--no-update-check`). Saved history is in `%LOCALAPPDATA%\SOMiniDashboard`.

## Troubleshooting

- **"Game not connected"**: start Stellar Odyssey; the dashboard finds it within a few seconds.
- **Port already in use**: run it with another port, for example `SO-Mini-Dashboard.exe --port 8777`.
- **Antivirus removed the file**: unsigned programs built with PyInstaller are sometimes
  flagged by mistake. You can check the download against the `.sha256` file on the release
  page, or run it from source (below).

## Run from source

Needs Python 3.10 or newer.

```powershell
pip install -r requirements.txt
python -m stellar_dashboard --open
```

Options: `--port`, `--poll` (seconds between reads), `--no-market`, `--market-minutes`,
`--game-port` / `--user-data` (if the game is not found), `--data` (history folder),
`--no-update-check`, `--version`. `python -m relic_planner` prints the dungeon plan in the
terminal instead.

Tests: `python -m pytest -q tests`. Build the exe: `pip install pyinstaller`, then
`python build_exe.py`. Pushing a tag like `v1.0.1` (matching `__version__` in
`stellar_dashboard/__init__.py`) makes GitHub build the exe and publish a release.

Extra panels can be added with the small interface in `stellar_dashboard/addons.py`.

Fan-made; not affiliated with the makers of Stellar Odyssey. MIT licence.
