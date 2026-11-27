"""
Async PostgreSQL database layer for RankTrackerAPI.

Owns and migrates its own tables (rank_api_tokens, api_app_tokens, rank_tracker_matches) in the
same Postgres instance/database the bot uses, independently of bot/services/db.py.
"""
import asyncio
from contextlib import asynccontextmanager

import asyncpg

from decktrackerAPI.config import settings

_pool = None
_pool_lock = asyncio.Lock()


async def init_db_pool():
    global _pool
    async with _pool_lock:
        if _pool is None:
            _pool = await asyncpg.create_pool(
                host=settings.postgres_host,
                port=settings.postgres_port,
                user=settings.postgres_user,
                password=settings.postgres_password,
                database=settings.postgres_db,
                min_size=2,
                max_size=10,
            )
            async with _pool.acquire() as conn:
                await _migrate(conn)


async def close_db_pool():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def get_db():
    if _pool is None:
        await init_db_pool()
    async with _pool.acquire(timeout=10) as conn:
        yield conn


async def _migrate(conn: asyncpg.Connection) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS rank_api_tokens (
            id           SERIAL PRIMARY KEY,
            discord_id   TEXT NOT NULL,
            token_hash   TEXT NOT NULL UNIQUE,
            label        TEXT,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            revoked_at   TIMESTAMPTZ,
            last_used_at TIMESTAMPTZ
        );

        CREATE TABLE IF NOT EXISTS rank_tracker_matches (
            game_id            UUID PRIMARY KEY,
            token_id           INTEGER NOT NULL REFERENCES rank_api_tokens(id),
            schema_version     INTEGER NOT NULL,
            start_time         TIMESTAMPTZ NOT NULL,
            end_time           TIMESTAMPTZ NOT NULL,
            game_mode          TEXT NOT NULL,
            format             TEXT NOT NULL,
            result             TEXT NOT NULL,
            was_conceded       BOOLEAN NOT NULL,
            player_battletag   TEXT NOT NULL,
            opponent_battletag TEXT NOT NULL,
            league_id          INTEGER NOT NULL,
            rank               INTEGER NOT NULL,
            star_level         INTEGER NOT NULL,
            stars              INTEGER NOT NULL,
            legend_rank        INTEGER NOT NULL,
            star_level_after   INTEGER NOT NULL,
            stars_after        INTEGER NOT NULL,
            legend_rank_after  INTEGER NOT NULL,
            received_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS idx_rank_tracker_matches_battletag
            ON rank_tracker_matches (player_battletag, end_time DESC);
    """)

    # Additive: `region` wasn't in the original payload contract — the RankTracker
    # plugin only started sending it later. Pre-migration rows keep region = NULL;
    # region-filtered queries simply treat those as unattributed.
    await conn.execute("""
        ALTER TABLE rank_tracker_matches ADD COLUMN IF NOT EXISTS region TEXT;

        CREATE INDEX IF NOT EXISTS idx_rank_tracker_matches_battletag_ci
            ON rank_tracker_matches (LOWER(player_battletag), end_time DESC);
    """)

    # Read-API app tokens: a separate namespace from rank_api_tokens (the per-user HSJeeves
    # upload tokens), so a user token can never authorise a read. Hash only, never plaintext.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS api_app_tokens (
            id           SERIAL PRIMARY KEY,
            name         TEXT NOT NULL UNIQUE,
            token_hash   TEXT NOT NULL UNIQUE,
            scopes       TEXT[] NOT NULL DEFAULT '{}',
            enabled      BOOLEAN NOT NULL DEFAULT TRUE,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_used_at TIMESTAMPTZ
        );
    """)

    # Additive: season stats uploaded by HSJeeves (post-game season record). Nullable;
    # pre-migration rows stay NULL and are not backfilled. The index serves
    # "latest row per player" lookups, e.g.
    #   SELECT DISTINCT ON (LOWER(player_battletag), region, format) ...
    #   ORDER BY LOWER(player_battletag), region, format, end_time DESC
    await conn.execute("""
        ALTER TABLE rank_tracker_matches ADD COLUMN IF NOT EXISTS season_wins  INTEGER;
        ALTER TABLE rank_tracker_matches ADD COLUMN IF NOT EXISTS season_games INTEGER;
        ALTER TABLE rank_tracker_matches ADD COLUMN IF NOT EXISTS win_streak   INTEGER;

        CREATE INDEX IF NOT EXISTS idx_rank_tracker_matches_latest_per_player
            ON rank_tracker_matches (LOWER(player_battletag), region, format, end_time DESC);
    """)
