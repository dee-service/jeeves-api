"""Admin CLI functions (token issuance and revocation)."""
from decktrackerAPI import admin_tokens


def _token(capsys):
    return capsys.readouterr().out.strip().splitlines()[-1]


def test_create_stores_only_the_hash_and_token_works(api, capsys):
    assert api.http.portal.call(admin_tokens.create, "web", ["rank:read"]) == 0
    token = _token(capsys)
    (row,) = api.fetch("SELECT * FROM api_app_tokens")
    assert row["name"] == "web" and row["scopes"] == ["rank:read"] and row["enabled"]
    assert token != row["token_hash"] and token not in row["token_hash"]
    assert api.get("/API/leaderboard", {"Authorization": f"Bearer {token}"}).status_code == 200


def test_duplicate_name_is_refused(api):
    assert api.http.portal.call(admin_tokens.create, "web", []) == 0
    assert api.http.portal.call(admin_tokens.create, "web", []) == 1
    assert len(api.fetch("SELECT 1 FROM api_app_tokens")) == 1


def test_revoke_and_enable(api, capsys):
    api.http.portal.call(admin_tokens.create, "web", ["rank:read"])
    h = {"Authorization": f"Bearer {_token(capsys)}"}
    assert api.http.portal.call(admin_tokens.set_enabled, "web", False) == 0
    assert api.get("/API/leaderboard", h).status_code == 401
    assert api.http.portal.call(admin_tokens.set_enabled, "web", True) == 0
    assert api.get("/API/leaderboard", h).status_code == 200
    assert api.http.portal.call(admin_tokens.set_enabled, "ghost", False) == 1
