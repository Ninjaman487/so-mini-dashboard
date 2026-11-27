import pytest

from stellar_dashboard import game

def test_lab_rows_finish_time_and_idle():
    now = 1_000_000_000
    lab = {"buildings": [{"id": "a", "name": "Refinery", "level": 3}, {"id": "b", "name": "Forge", "level": 1}],
           "base": [],
           "queue": [{"building": "a", "total": 10, "ticksClaimed": 2, "timer": 60, "multiplier": 2,
                      "lastClaimDate": now - 45_000}]}
    rows = game.lab_rows(lab, now)
    assert rows[0]["name"] == "Refinery" and rows[0]["queued"]
    # 8 ticks left of 30 s each from the last claim
    assert rows[0]["finish_ms"] == now - 45_000 + 8 * 30_000
    assert rows[0]["ready_to_claim"] == 1
    assert rows[1]["name"] == "Forge" and not rows[1]["queued"]


def test_market_expr_is_get_only_and_rejects_odd_names():
    e = game.market_expr("dark_matter")
    assert "/api/market/listings/dark_matter" in e and "method:'GET'" in e
    with pytest.raises(ValueError):
        game.market_expr("x');alert(1);('")


def test_no_action_calls_in_dashboard_code():
    import pathlib
    root = pathlib.Path(game.__file__).parents[1]
    src = "".join(p.read_text(encoding="utf-8") for d in ("stellar_dashboard", "relic_planner")
                  for p in (root / d).glob("*.py"))
    for word in ("sendMessage(", ".sendMessage", "Input.dispatch", "Debugger.setBreakpoint", "method:'POST'"):
        assert word not in src


def test_lab_rows_mark_unbuilt_and_sort_them_last():
    lab = {"buildings": [{"id": "z", "name": "Fuel Lab", "level": 0}, {"id": "b", "name": "Forge", "level": 3}],
           "base": [{"id": "a", "name": "Prism", "level": 9}],
           "queue": [{"building": "a", "total": 4, "ticksClaimed": 0, "timer": 10, "multiplier": 1, "lastClaimDate": 0}]}
    rows = game.lab_rows(lab, 1000)
    assert [r["name"] for r in rows] == ["Prism", "Forge", "Fuel Lab"]
    assert rows[0]["kind"] == "base" and rows[1]["built"] and not rows[2]["built"]


def test_skill_view_counts_xp_across_a_level_up(tmp_path, monkeypatch):
    from stellar_dashboard import history
    h = history.History(tmp_path)
    t = [10_000.0]
    monkeypatch.setattr(history.time, "time", lambda: t[0])
    for lvl, xp, target in ((5, 800, 1000), (6, 300, 1200)):
        h.maybe_record_skills({"battle": {"level": lvl, "xp": xp, "xp_target": target, "active": True}})
        t[0] += 1800
    view = h.skill_view({"battle": {"level": 6, "xp": 300, "xp_target": 1200, "active": True}})["battle"]
    # 200 to finish level 5, then 300 into level 6, over half an hour
    assert view["xp_per_hour"] == 1000
    assert round(view["eta_s"]) == 900 * 3.6
    assert history.History(tmp_path).skills.last()["battle"] == [6, 300, 1200]


def test_price_trends_and_worth(tmp_path, monkeypatch):
    from stellar_dashboard import history
    h = history.History(tmp_path)
    t = [200_000.0]
    monkeypatch.setattr(history.time, "time", lambda: t[0])
    for bid in (100, 110):
        h.record_price("cobalt", {"ok": True, "buy": [{"price": bid}], "sell": []})
        h.maybe_record_worth(bid * 10, {"cobalt": bid * 10})
        t[0] += history.DAY
    t[0] -= history.DAY
    tr = h.price_trends()["cobalt"]
    assert abs(tr["change_24h"] - 0.1) < 1e-9 and tr["low"] == 100
    assert h.worth_view()["change_24h"] == 100


def test_leaderboard_expr_is_get_only():
    e = game.leaderboard_expr("stellar-doom")
    assert "/api/minigames/stellar-doom/leaderboard" in e and "method:'GET'" in e
    with pytest.raises(ValueError):
        game.leaderboard_expr("../user")



def test_addon_hooks_extend_page_state_and_routes():
    from stellar_dashboard import server
    from stellar_dashboard.addons import Addon

    class Extra(Addon):
        def state(self):
            return {"extra": 1}

        def handle_get(self, path, query):
            return (b"hi", "text/plain", 200) if path == "/api/extra" else None

        def page(self):
            return "<script>/*extra*/</script>"

    page = server.build_page("tok", [Extra()])
    assert page.index("/*extra*/") < page.index("</body>") and '"tok"' in page
    assert server.build_page("tok") .count("/*extra*/") == 0
    assert Extra().handle_get("/api/other", {}) is None


def test_update_check_compares_versions_numerically():
    from stellar_dashboard.update import UpdateCheck, parse
    assert parse("v1.10.0") > parse("1.9.3")
    u = UpdateCheck("1.0.0", enabled=False)
    assert not u.state()["newer"]
    u.latest = "v1.0.1"
    assert u.state()["newer"]
    u.latest = "v1.0.0"
    assert not u.state()["newer"]
