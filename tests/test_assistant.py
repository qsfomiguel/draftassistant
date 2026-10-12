from draft_assistant import demo
from draft_assistant.app import App
from draft_assistant.config import Config, default_season, parse_punt
from draft_assistant.draft import DraftState, normalize, suggest
from draft_assistant.espn import find_my_team, parse_league, parse_picks, parse_players
from draft_assistant.models import Player
from draft_assistant.roster import fits_starting, starting_slots
from draft_assistant.valuation import value_players

# Trimmed-down shapes of real ESPN responses.
LEAGUE_JSON = {
    "settings": {
        "name": "Test League",
        "scoringSettings": {"scoringType": "H2H_CATEGORY", "scoringItems": [
            {"statId": 0, "points": 0}, {"statId": 19, "points": 0},
            {"statId": 11, "points": 0, "isReverseItem": True},
        ]},
        "rosterSettings": {"lineupSlotCounts": {"0": 1, "4": 1, "11": 2, "12": 1, "13": 1, "5": 0}},
        "draftSettings": {"type": "SNAKE", "pickOrder": [3, 1, 2]},
    },
    "teams": [
        {"id": 1, "abbrev": "ONE", "location": "Team", "nickname": "One", "owners": ["{abc-123}"]},
        {"id": 2, "abbrev": "TWO", "name": "Two Squad", "owners": ["{def}"]},
        {"id": 3, "abbrev": "THR", "name": "Three", "owners": []},
    ],
    "draftDetail": {"inProgress": True, "drafted": False, "picks": [
        {"overallPickNumber": 1, "teamId": 3, "playerId": 10},
        {"overallPickNumber": 2, "teamId": 1, "playerId": -1},
    ]},
}

PLAYERS_JSON = {"players": [
    {"id": 10, "player": {
        "id": 10, "fullName": "Nikola Jokić", "proTeamId": 7, "eligibleSlots": [4, 9, 10, 11, 12, 13],
        "injuryStatus": "ACTIVE", "ownership": {"averageDraftPosition": 1.4},
        "draftRanksByRankType": {"STANDARD": {"rank": 1}},
        "stats": [
            {"seasonId": 2026, "statSourceId": 0, "statSplitTypeId": 0,
             "stats": {"0": 2000, "42": 70}, "averageStats": {"0": 28.6, "42": 1}},
            {"seasonId": 2027, "statSourceId": 1, "statSplitTypeId": 0,
             "stats": {"0": 2100, "42": 75}, "averageStats": {"0": 28.0}},
        ]}},
    {"id": 11, "player": {
        "id": 11, "fullName": "Rookie Guy", "proTeamId": 0, "eligibleSlots": [0, 5, 11],
        "injuryStatus": "OUT",
        "stats": [{"seasonId": 2026, "statSourceId": 0, "statSplitTypeId": 0,
                   "stats": {"0": 300, "42": 30}}]}},
]}


def test_parse_league_and_picks():
    lg = parse_league(LEAGUE_JSON, 99, 2027)
    assert lg.name == "Test League"
    assert [c.name for c in lg.categories] == ["PTS", "FG%", "TO"]
    assert lg.categories[2].reverse
    assert lg.lineup_slots == {0: 1, 4: 1, 11: 2, 12: 1, 13: 1}
    assert lg.rounds == 5 and lg.num_teams == 3
    assert lg.teams[1].name == "Team One"
    assert find_my_team(lg, "{ABC-123}") == 1
    picks, in_progress, drafted = parse_picks(LEAGUE_JSON)
    assert [p.player_id for p in picks] == [10] and in_progress and not drafted


def test_parse_players_prefers_projection():
    jokic, rookie = parse_players(PLAYERS_JSON, 2027)
    assert jokic.name == "Nikola Jokić" and jokic.pro_team == "DEN"
    assert jokic.stat_source == "proj" and jokic.avg[0] == 28.0 and jokic.gp == 75
    assert jokic.positions == ["C"] and jokic.adp == 1.4 and jokic.espn_rank == 1 and jokic.injury is None
    assert rookie.stat_source == "last" and rookie.avg[0] == 10.0  # derived from totals / games
    assert rookie.injury == "OUT" and rookie.positions == ["PG"]


def test_snake_order_and_my_picks():
    lg = parse_league(LEAGUE_JSON, 99, 2027)
    state = DraftState(lg, parse_players(PLAYERS_JSON, 2027), my_team_id=1)
    state.update_from_espn(*parse_picks(LEAGUE_JSON))
    assert [state.team_for_overall(n) for n in range(1, 7)] == [3, 1, 2, 2, 1, 3]
    assert state.current_overall() == 2
    assert state.my_upcoming()[:3] == [2, 5, 8]


def test_valuation_ranks_good_players_first():
    players = demo.demo_players()
    v = value_players(players, demo.demo_league())
    top = v.rank()[:20]
    assert sum(players[pid - 1000].espn_rank <= 60 for pid in top) >= 15


def test_turnovers_are_reversed_and_punts_ignored():
    players = demo.demo_players()
    league = demo.demo_league()
    v = value_players(players, league)
    high_to = max(players, key=lambda p: p.avg[11])
    assert v.cats[high_to.id][11] < 0
    punted = value_players(players, league, punt=parse_punt("TO"))
    assert punted.value[high_to.id] > v.value[high_to.id]


def test_points_league_values():
    players = demo.demo_players()
    v = value_players(players, demo.demo_league(points=True))
    best = players[0]
    assert v.fpts[best.id] > 0 and v.value[v.rank()[0]] > 0


def test_lineup_fitting():
    slots = starting_slots({0: 1, 4: 1, 11: 1, 12: 3})
    pg = Player(1, "pg", "X", ["PG"], {0, 11, 12}, {})
    c = Player(2, "c", "X", ["C"], {4, 11, 12}, {})
    c2 = Player(3, "c2", "X", ["C"], {4, 11, 12}, {})
    c3 = Player(4, "c3", "X", ["C"], {4, 11, 12}, {})
    assert fits_starting([pg, c], c2, slots)  # goes to UT
    assert not fits_starting([pg, c, c2], c3, slots)  # only bench left


def demo_app():
    app = App(Config(), save=lambda cfg: None)
    app.load_demo()
    return app


def test_app_picks_undo_and_autodraft():
    app = demo_app()
    state = app.state
    app.autodraft()
    assert state.current_overall() == 4
    snap = app.snapshot()
    assert snap["clock"]["my_turn"] and snap["clock"]["next_after"] == 17
    top = snap["suggestions"][0]["id"]
    app.record_pick(top, mine=True)
    assert [p.id for p in state.roster(4)] == [top]
    app.undo()
    assert state.roster(4) == [] and state.current_overall() == 4
    app.record_pick(1199, mine=False)  # taken by someone else on my pick
    assert state.roster(4) == [] and state.current_overall() == 5
    try:
        app.record_pick(1199, mine=True)
        raise AssertionError("drafting the same player twice should fail")
    except ValueError:
        pass


def test_snapshot_standings_and_settings():
    app = demo_app()
    app.autodraft()
    app.record_pick(app.snapshot()["suggestions"][0]["id"], mine=True)
    snap = app.snapshot()
    assert set(snap["standings"]) == {str(c.stat_id) for c in app.state.league.categories}
    assert all(1 <= s["rank"] <= 10 for s in snap["standings"].values())
    app.update_settings({"punt": ["TO", "FT%"], "balance": 0})
    punted = {c["name"] for c in app.snapshot()["league"]["categories"] if c["punted"]}
    assert punted == {"TO", "FT%"}


def test_http_api():
    import json
    import threading
    import urllib.error
    import urllib.request

    from draft_assistant.server import serve

    app = demo_app()
    server = serve(app, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        state = json.load(urllib.request.urlopen(base + "/api/state"))
        assert state["mode"] == "demo" and state["suggestions"]
        unchanged = json.load(urllib.request.urlopen(f"{base}/api/state?v={state['version']}"))
        assert unchanged["unchanged"]
        req = urllib.request.Request(base + "/api/auto", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        after = json.load(urllib.request.urlopen(req))
        assert after["clock"]["my_turn"]
        evil = urllib.request.Request(base + "/api/undo", data=b"{}", method="POST",
                                      headers={"Content-Type": "application/json", "Origin": "https://evil.example"})
        try:
            urllib.request.urlopen(evil)
            raise AssertionError("cross-site POST should be refused")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        assert b"Draft Assistant" in urllib.request.urlopen(base + "/").read()
    finally:
        server.shutdown()


def test_espn_picks_override_manual():
    state = DraftState(demo.demo_league(), demo.demo_players(), my_team_id=4)
    state.record_manual(1000)
    state.update_from_espn([], False, False)
    assert 1000 in state.drafted_ids
    from draft_assistant.models import Pick
    state.update_from_espn([Pick(1, 1, 1001)], True, False)
    assert state.picks[1].player_id == 1001 and 1000 not in state.drafted_ids


def test_helpers():
    assert normalize("Luka Dončić") == "luka doncic"
    from datetime import date
    assert default_season(date(2026, 10, 12)) == 2027
    assert default_season(date(2027, 3, 1)) == 2027


def test_parse_players_accepts_bare_list():
    bare = [e["player"] for e in PLAYERS_JSON["players"]]
    assert [p.name for p in parse_players(bare, 2027)] == ["Nikola Jokić", "Rookie Guy"]


def test_cookie_cleanup():
    from draft_assistant.config import normalize_espn_s2, normalize_swid

    value = "AEB" + "x%2B" * 60
    row = f"espn_s2\t{value}\t.espn.com\t/\t2027-10-12T18:00:00.000Z\t260\t\t\t\tMedium"
    assert normalize_espn_s2(row) == value
    assert normalize_espn_s2(f"  {value}\n") == value
    assert normalize_espn_s2(f"espn_s2={value};") == value
    swid = "{1A2B3C4D-1A2B-1A2B-1A2B-1A2B3C4D5E6F}"
    assert normalize_swid(f"SWID\t{swid}\t.espn.com\t/") == swid
    assert normalize_swid(swid[1:-1]) == swid


def test_roto_counts_games_played():
    import copy

    players = demo.demo_players()
    h2h = demo.demo_league()
    roto = copy.copy(h2h)
    roto.scoring_type = "ROTO"
    # Same per-game line, one player plays far fewer games: roto should punish that harder.
    healthy, fragile = copy.deepcopy(players[0]), copy.deepcopy(players[0])
    healthy.id, fragile.id = 1, 2
    healthy.gp, fragile.gp = 80, 40
    pool = players + [healthy, fragile]
    gap = {}
    for lg in (h2h, roto):
        v = value_players(pool, lg)
        ranked = v.rank()
        gap[lg.scoring_type] = ranked.index(2) - ranked.index(1)
    assert gap["ROTO"] > gap["H2H_CATEGORY"] >= 0
