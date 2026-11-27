"""
Test fixtures. The tests run the real FastAPI app against a real PostgreSQL database
(the SQL, DISTINCT ON and token logic are the point), configured through the usual
POSTGRES_* variables. Defaults point at a local throwaway database, see docs/testing.md.

The tables are TRUNCATEd before every test, so the database name must contain "test".
"""
import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "jeeves_test")
os.environ["RATE_LIMIT_PER_MINUTE"] = "1000"  # the rate-limit test sets its own

if "test" not in os.environ["POSTGRES_DB"]:
    raise RuntimeError(
        f"Refusing to run: POSTGRES_DB={os.environ['POSTGRES_DB']!r} must contain 'test' "
        "(the tests truncate the tables)."
    )

from fastapi.testclient import TestClient  # noqa: E402

from decktrackerAPI import ratelimit  # noqa: E402
from decktrackerAPI.config import settings  # noqa: E402
from decktrackerAPI.db import get_db  # noqa: E402
from decktrackerAPI.main import app  # noqa: E402

T0 = datetime(2026, 11, 27, 10, 0, tzinfo=timezone.utc)


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Api:
    """TestClient plus small helpers (DB access runs on the app's own event loop)."""

    def __init__(self, client: TestClient):
        self.http = client

    def db(self, fn, *args):
        async def run():
            async with get_db() as conn:
                return await fn(conn, *args)
        return self.http.portal.call(run)

    def fetch(self, sql, *args):
        return self.db(lambda conn, *a: conn.fetch(sql, *a), *args)

    def add_user_token(self, token="user-token", revoked=False):
        self.db(lambda c: c.execute(
            "INSERT INTO rank_api_tokens (discord_id, token_hash, revoked_at) "
            "VALUES ('d', $1, CASE WHEN $2 THEN now() END)", _sha(token), revoked))
        return {"Authorization": f"Bearer {token}"}

    def add_app_token(self, name="app", scopes=("rank:read",), token=None, enabled=True):
        token = token or f"app-token-{name}"
        self.db(lambda c: c.execute(
            "INSERT INTO api_app_tokens (name, token_hash, scopes, enabled) VALUES ($1, $2, $3, $4)",
            name, _sha(token), list(scopes), enabled))
        return {"Authorization": f"Bearer {token}"}

    def upload(self, headers, **kw):
        return self.http.post("/API", json=payload(**kw), headers=headers)

    def get(self, path, headers=None):
        return self.http.get(path, headers=headers or {})


def payload(*, drop=(), minutes=0, **overrides):
    """A valid schemaVersion 2 upload; `overrides` replace fields, `drop` removes them."""
    body = {
        "schemaVersion": 2,
        "gameId": str(uuid.uuid4()),
        "startTime": (T0 + timedelta(minutes=minutes)).isoformat(),
        "endTime": (T0 + timedelta(minutes=minutes, seconds=300)).isoformat(),
        "gameMode": "Ranked", "format": "Standard", "result": "Win", "wasConceded": False,
        "region": "EU", "playerBattleTag": "Player#1", "opponentBattleTag": "Opp#2",
        "rank": {"LeagueId": 5, "Rank": 0, "StarLevel": 40, "Stars": 1, "LegendRank": 0},
        "rankAfter": {"StarLevelAfter": 41, "StarsAfter": 2, "LegendRankAfter": 0},
        "seasonWins": 10, "seasonGames": 20, "winStreak": 1,
    }
    body.update(overrides)
    for key in drop:
        body.pop(key, None)
    return body


@pytest.fixture(scope="session")
def _client():
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def api(_client):
    a = Api(_client)
    a.db(lambda c: c.execute(
        "TRUNCATE rank_tracker_matches, rank_api_tokens, api_app_tokens RESTART IDENTITY CASCADE"))
    ratelimit.reset()
    settings.rate_limit_per_minute = 1000
    return a


@pytest.fixture()
def user(api):
    return api.add_user_token()


@pytest.fixture()
def app_tok(api):
    return api.add_app_token()
