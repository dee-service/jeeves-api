"""GET /API/leaderboard (latest row per player via DISTINCT ON, sorting, pagination) and player stats."""
import pytest

# (battletag, wins, games, streak) of each player's LATEST row
PLAYERS = [("A#1", 11, 21, 2), ("B#2", 30, 40, 5), ("C#3", 5, 6, 0), ("D#4", 20, 100, 3), ("E#5", 8, 10, 8)]


@pytest.fixture()
def board(api, user):
    """Standard/EU board. A#1 also has an older row that must be ignored, plus a v1 row and Wild/US rows."""
    m = 0

    def up(**kw):
        nonlocal m
        m += 1
        assert api.upload(user, minutes=m, **kw).status_code == 200

    up(playerBattleTag="A#1", seasonWins=1, seasonGames=2, winStreak=1)  # older A#1 row
    for bt, w, g, s in PLAYERS:
        up(playerBattleTag=bt, seasonWins=w, seasonGames=g, winStreak=s)
    up(playerBattleTag="V#1", schemaVersion=1, drop=("seasonWins", "seasonGames", "winStreak"))  # no stats
    up(playerBattleTag="W#1", format="Wild", seasonWins=2, seasonGames=3, winStreak=1)
    up(playerBattleTag="U#1", region="US", seasonWins=9, seasonGames=9, winStreak=9)
    return api.add_app_token()


def items(api, tok, query=""):
    r = api.get(f"/API/leaderboard{query}", tok)
    assert r.status_code == 200, r.text
    return r.json()


def names(body):
    return [i["battleTag"] for i in body["items"]]


def test_latest_row_per_player_and_stats_only(api, board):
    body = items(api, board)
    assert body["format"] == "Standard" and body["total"] == 6  # A..E + U (US); V (v1) and W (Wild) excluded
    a = next(i for i in body["items"] if i["battleTag"] == "A#1")
    assert (a["seasonWins"], a["seasonGames"], a["winStreak"]) == (11, 21, 2)  # not the older 1/2 row
    assert a["winRate"] == round(11 / 21, 4)
    assert (a["starLevel"], a["stars"], a["legendRank"], a["region"]) == (41, 2, 0, "EU")


@pytest.mark.parametrize("sort,expected", [
    ("wins", ["B#2", "D#4", "A#1", "U#1", "E#5", "C#3"]),
    ("games", ["D#4", "B#2", "A#1", "E#5", "U#1", "C#3"]),
    ("streak", ["U#1", "E#5", "B#2", "D#4", "A#1", "C#3"]),
    ("winrate", ["U#1", "C#3", "E#5", "B#2", "A#1", "D#4"]),
])
def test_sorting(api, board, sort, expected):
    assert names(items(api, board, f"?sort={sort}")) == expected


def test_default_sort_is_wins(api, board):
    assert names(items(api, board)) == names(items(api, board, "?sort=wins"))


def test_pagination_covers_everything_exactly_once(api, board):
    full = names(items(api, board, "?sort=wins"))
    pages = [items(api, board, f"?sort=wins&limit=2&offset={o}") for o in (0, 2, 4, 6)]
    assert [len(p["items"]) for p in pages] == [2, 2, 2, 0]
    assert all(p["total"] == 6 and p["limit"] == 2 for p in pages)
    assert [n for p in pages for n in names(p)] == full


def test_filters(api, board):
    assert names(items(api, board, "?region=us")) == ["U#1"]
    assert names(items(api, board, "?region=EU&limit=100")) == ["B#2", "D#4", "A#1", "E#5", "C#3"]
    assert names(items(api, board, "?format=Wild")) == ["W#1"]
    assert items(api, board, "?format=Twist")["total"] == 0


def test_tie_break_is_deterministic(api, user):
    for i, bt in enumerate(["Z#1", "M#1", "A#1"]):
        api.upload(user, minutes=i, playerBattleTag=bt, seasonWins=5, seasonGames=10, winStreak=1)
    tok = api.add_app_token()
    assert names(items(api, tok, "?sort=wins")) == ["A#1", "M#1", "Z#1"]


def test_battletag_case_is_one_player(api, user):
    api.upload(user, minutes=1, playerBattleTag="Dee#1", seasonWins=1, seasonGames=2)
    api.upload(user, minutes=2, playerBattleTag="dee#1", seasonWins=2, seasonGames=3)
    body = items(api, api.add_app_token())
    assert body["total"] == 1 and body["items"][0]["seasonGames"] == 3


@pytest.mark.parametrize("query", ["?sort=bogus", "?format=Arena", "?limit=0", "?limit=101", "?offset=-1", "?limit=x"])
def test_bad_query_is_400(api, board, query):
    assert api.get(f"/API/leaderboard{query}", board).status_code == 400


def test_empty_leaderboard(api, app_tok):
    assert items(api, app_tok) == {
        "format": "Standard", "region": None, "sort": "wins", "total": 0, "limit": 50, "offset": 0, "items": []}


# -- player stats ------------------------------------------------------------

def test_player_stats_latest_and_history(api, board):
    r = api.get("/API/player/EU/A%231/stats?limit=1", board)
    assert r.status_code == 200
    body = r.json()
    assert body["battleTag"] == "A#1" and body["region"] == "EU"
    assert [(x["format"], x["seasonWins"]) for x in body["latest"]] == [("Standard", 11)]
    h = body["history"]
    assert h["total"] == 2 and h["limit"] == 1 and len(h["items"]) == 1
    assert h["items"][0]["seasonWins"] == 11  # newest first
    older = api.get("/API/player/EU/A%231/stats?limit=1&offset=1", board).json()["history"]["items"]
    assert older[0]["seasonWins"] == 1


def test_player_stats_is_case_insensitive_and_filters_format(api, user, board):
    api.upload(user, minutes=50, playerBattleTag="A#1", format="Wild", seasonWins=4, seasonGames=5, winStreak=2)
    body = api.get("/API/player/eu/a%231/stats", board).json()
    assert sorted(x["format"] for x in body["latest"]) == ["Standard", "Wild"]
    wild = api.get("/API/player/EU/A%231/stats?format=Wild", board).json()
    assert [x["format"] for x in wild["latest"]] == ["Wild"] and wild["history"]["total"] == 1


def test_player_history_includes_v1_rows_with_null_stats(api, user, app_tok):
    api.upload(user, minutes=1, schemaVersion=1, drop=("seasonWins", "seasonGames", "winStreak"))
    body = api.get("/API/player/EU/Player%231/stats", app_tok).json()
    assert body["latest"] == [] and body["history"]["items"][0]["seasonWins"] is None


def test_player_not_found_is_404(api, board):
    assert api.get("/API/player/EU/Nobody%239/stats", board).status_code == 404
    assert api.get("/API/player/US/A%231/stats", board).status_code == 404  # right name, wrong region
