"""Auth on the read endpoints: no token / user token / app token, scopes, last_used, rate limit."""
import pytest

from decktrackerAPI.config import settings

READ_ROUTES = ["/API/leaderboard", "/API/player/EU/Player%231/stats"]


@pytest.fixture()
def seeded(api, user):
    assert api.upload(user).status_code == 200


@pytest.mark.parametrize("route", READ_ROUTES)
def test_missing_or_invalid_token_is_401(api, seeded, route):
    assert api.get(route).status_code == 401
    assert api.get(route, {"Authorization": "Basic abc"}).status_code == 401
    assert api.get(route, {"Authorization": "Bearer "}).status_code == 401
    assert api.get(route, {"Authorization": "Bearer nope"}).status_code == 401


@pytest.mark.parametrize("route", READ_ROUTES)
def test_user_upload_token_cannot_read_403(api, user, seeded, route):
    assert api.get(route, user).status_code == 403


@pytest.mark.parametrize("route", READ_ROUTES)
def test_app_token_with_scope_reads_200(api, seeded, route):
    assert api.get(route, api.add_app_token()).status_code == 200


@pytest.mark.parametrize("route", READ_ROUTES)
def test_app_token_without_scope_403(api, seeded, route):
    assert api.get(route, api.add_app_token("noscope", scopes=())).status_code == 403
    assert api.get(route, api.add_app_token("other", scopes=("something:else",))).status_code == 403


@pytest.mark.parametrize("route", READ_ROUTES)
def test_disabled_app_token_is_401(api, seeded, route):
    assert api.get(route, api.add_app_token(enabled=False)).status_code == 401


def test_revocation_takes_effect_immediately(api, seeded):
    h = api.add_app_token()
    assert api.get("/API/leaderboard", h).status_code == 200
    api.db(lambda c: c.execute("UPDATE api_app_tokens SET enabled = false"))
    assert api.get("/API/leaderboard", h).status_code == 401


def test_last_used_is_updated_on_success_only(api, seeded):
    h = api.add_app_token()
    assert api.fetch("SELECT last_used_at FROM api_app_tokens")[0][0] is None
    api.get("/API/leaderboard", {"Authorization": "Bearer wrong"})
    assert api.fetch("SELECT last_used_at FROM api_app_tokens")[0][0] is None
    api.get("/API/leaderboard", h)
    assert api.fetch("SELECT last_used_at FROM api_app_tokens")[0][0] is not None


def test_user_token_last_used_still_updated_on_upload(api, user):
    api.upload(user)
    assert api.fetch("SELECT last_used_at FROM rank_api_tokens")[0][0] is not None


def test_rate_limit_per_token(api, seeded):
    settings.rate_limit_per_minute = 3
    a, b = api.add_app_token("a"), api.add_app_token("b")
    codes = [api.get("/API/leaderboard", a).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    limited = api.get("/API/leaderboard", a)
    assert int(limited.headers["retry-after"]) >= 1
    ok = api.get("/API/leaderboard", b)  # another token has its own window
    assert ok.status_code == 200 and ok.headers["x-ratelimit-remaining"] == "2"


def test_rate_limit_zero_disables(api, seeded):
    settings.rate_limit_per_minute = 0
    h = api.add_app_token()
    assert all(api.get("/API/leaderboard", h).status_code == 200 for _ in range(10))
