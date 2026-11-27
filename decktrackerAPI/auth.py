"""
Bearer-token authentication for the plugin upload endpoint.

Tokens are stored hashed (SHA-256) in rank_api_tokens — the plaintext token
is never persisted, only handed to the user once at issuance time (by a
future bot command; see docs/RankTrackerAPI-design.md).
"""
import hashlib
from dataclasses import dataclass, field

from fastapi import Depends, Header, HTTPException

from decktrackerAPI.db import get_db


@dataclass
class TokenRecord:
    id: int
    discord_id: str


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return token


async def get_current_token(authorization: str | None = Header(default=None)) -> TokenRecord:
    token = _bearer_token(authorization)
    token_hash = hash_token(token)

    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT id, discord_id FROM rank_api_tokens WHERE token_hash = $1 AND revoked_at IS NULL",
            token_hash,
        )
        if row is None:
            raise HTTPException(status_code=401, detail="Invalid or revoked token")

        await conn.execute(
            "UPDATE rank_api_tokens SET last_used_at = now() WHERE id = $1", row["id"]
        )

    return TokenRecord(id=row["id"], discord_id=row["discord_id"])


@dataclass
class AppTokenRecord:
    id: int
    name: str
    scopes: list[str] = field(default_factory=list)


async def require_app_token(authorization: str | None = Header(default=None)) -> AppTokenRecord:
    """Auth for the read API. Only enabled tokens in api_app_tokens are accepted.

    Missing/unknown/disabled token -> 401. A valid HSJeeves *user* upload token
    (rank_api_tokens) is recognised and answered with 403: authenticated, but not
    allowed to read.
    """
    token_hash = hash_token(_bearer_token(authorization))

    async with get_db() as conn:
        row = await conn.fetchrow(
            "UPDATE api_app_tokens SET last_used_at = now() "
            "WHERE token_hash = $1 AND enabled RETURNING id, name, scopes",
            token_hash,
        )
        if row is not None:
            return AppTokenRecord(id=row["id"], name=row["name"], scopes=list(row["scopes"]))

        is_user_token = await conn.fetchval(
            "SELECT 1 FROM rank_api_tokens WHERE token_hash = $1 AND revoked_at IS NULL", token_hash
        )
    if is_user_token:
        raise HTTPException(status_code=403, detail="This token is not allowed to read")
    raise HTTPException(status_code=401, detail="Invalid or revoked token")


def require_scope(scope: str):
    """Dependency factory: the app token must carry `scope` (403 otherwise)."""

    async def _check(token: AppTokenRecord = Depends(require_app_token)) -> AppTokenRecord:
        if scope not in token.scopes:
            raise HTTPException(status_code=403, detail=f"Token lacks scope '{scope}'")
        return token

    return _check
