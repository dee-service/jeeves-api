"""POST /API: payload v1/v2 acceptance and the insert."""
import pytest

from conftest import payload

ROW = "SELECT * FROM rank_tracker_matches"


def test_v2_persists_season_stats(api, user):
    r = api.upload(user, seasonWins=107, seasonGames=199, winStreak=3)
    assert r.status_code == 200 and r.json()["status"] == "ok"
    (row,) = api.fetch(ROW)
    assert (row["schema_version"], row["season_wins"], row["season_games"], row["win_streak"]) == (2, 107, 199, 3)
    assert (row["star_level"], row["star_level_after"], row["stars_after"]) == (40, 41, 2)


def test_v1_accepted_and_season_columns_null(api, user):
    r = api.upload(user, schemaVersion=1, drop=("seasonWins", "seasonGames", "winStreak"))
    assert r.status_code == 200
    (row,) = api.fetch(ROW)
    assert row["schema_version"] == 1
    assert (row["season_wins"], row["season_games"], row["win_streak"]) == (None, None, None)


def test_season_fields_individually_optional(api, user):
    assert api.upload(user, drop=("winStreak",)).status_code == 200
    (row,) = api.fetch(ROW)
    assert row["season_wins"] == 10 and row["win_streak"] is None


def test_repost_same_game_id_is_noop(api, user):
    body = payload(seasonWins=5)
    assert api.http.post("/API", json=body, headers=user).status_code == 200
    again = dict(body, seasonWins=999, result="Loss")
    assert api.http.post("/API", json=again, headers=user).status_code == 200
    (row,) = api.fetch(ROW)  # still exactly one row, first values kept
    assert row["season_wins"] == 5 and row["result"] == "Win"


@pytest.mark.parametrize("region,stored", [("eu", "EU"), (" us ", "US"), ("UNKNOWN", "UNKNOWN"), ("mars", "MARS")])
def test_region_is_normalised(api, user, region, stored):
    assert api.upload(user, region=region).status_code == 200
    assert api.fetch(ROW)[0]["region"] == stored


@pytest.mark.parametrize("bad", [{"drop": ("region",)}, {"region": None}, {"region": ""}, {"region": "   "}])
def test_region_is_required(api, user, bad):
    r = api.upload(user, **bad)
    assert r.status_code == 400 and r.json()["status"] == "error"
    assert api.fetch(ROW) == []


@pytest.mark.parametrize("bad", [
    {"drop": ("gameId",)}, {"gameId": "not-a-uuid"}, {"wasConceded": "maybe"},
    {"seasonWins": "many"}, {"drop": ("rankAfter",)},
])
def test_malformed_payload_is_400(api, user, bad):
    assert api.upload(user, **bad).status_code == 400
    assert api.fetch(ROW) == []


def test_malformed_json_is_400(api, user):
    r = api.http.post("/API", content=b"{nope", headers={**user, "Content-Type": "application/json"})
    assert r.status_code == 400


def test_upload_auth(api, user):
    assert api.upload({}).status_code == 401
    assert api.upload({"Authorization": "Bearer wrong"}).status_code == 401
    revoked = api.add_user_token("old", revoked=True)
    assert api.upload(revoked).status_code == 401
    assert api.upload(user).status_code == 200


def test_app_token_cannot_upload(api):
    app_tok = api.add_app_token()
    assert api.upload(app_tok).status_code == 401
