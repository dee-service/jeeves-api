"""
Read endpoints for predefined apps (server-to-server, app-token protected).

    GET /API/leaderboard?format=&region=&sort=&limit=&offset=
    GET /API/player/{region}/{battletag}/stats

Auth: Bearer app token (api_app_tokens) carrying the `rank:read` scope; HSJeeves user
upload tokens get 403. Rate limited per token (see ratelimit.py). Season stats exist
only on schemaVersion 2 uploads, so rows without them are ignored here.
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from decktrackerAPI.db import get_db
from decktrackerAPI.ratelimit import read_access

router = APIRouter(prefix="/API", tags=["read"], dependencies=[Depends(read_access("rank:read"))])

FormatName = Literal["Standard", "Wild", "Classic", "Twist"]
SortKey = Literal["wins", "games", "streak", "winrate"]

# Whitelisted ORDER BY expressions (never interpolate user input). Ties fall back to
# more games, then name, so paging is deterministic.
_SORT_SQL = {
    "wins": "season_wins DESC",
    "games": "season_games DESC",
    "streak": "win_streak DESC",
    "winrate": "(season_wins::float8 / NULLIF(season_games, 0)) DESC NULLS LAST",
}


class _Out(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class PlayerStats(_Out):
    battletag: str = Field(alias="battleTag")
    region: Optional[str]
    format: str
    season_wins: int = Field(alias="seasonWins")
    season_games: int = Field(alias="seasonGames")
    win_streak: Optional[int] = Field(alias="winStreak")
    win_rate: Optional[float] = Field(alias="winRate", description="seasonWins / seasonGames, 0..1")
    star_level: int = Field(alias="starLevel")
    stars: int
    legend_rank: int = Field(alias="legendRank")
    last_match_at: str = Field(alias="lastMatchAt")


class LeaderboardResponse(_Out):
    format: str
    region: Optional[str]
    sort: str
    total: int
    limit: int
    offset: int
    items: list[PlayerStats]


class MatchEntry(_Out):
    game_id: str = Field(alias="gameId")
    end_time: str = Field(alias="endTime")
    format: str
    result: str
    was_conceded: bool = Field(alias="wasConceded")
    opponent_battletag: str = Field(alias="opponentBattleTag")
    season_wins: Optional[int] = Field(alias="seasonWins")
    season_games: Optional[int] = Field(alias="seasonGames")
    win_streak: Optional[int] = Field(alias="winStreak")
    star_level_after: int = Field(alias="starLevelAfter")
    stars_after: int = Field(alias="starsAfter")
    legend_rank_after: int = Field(alias="legendRankAfter")


class HistoryPage(_Out):
    total: int
    limit: int
    offset: int
    items: list[MatchEntry]


class PlayerStatsResponse(_Out):
    battletag: str = Field(alias="battleTag")
    region: str
    latest: list[PlayerStats]
    history: HistoryPage


def _stats(r) -> PlayerStats:
    games = r["season_games"]
    return PlayerStats(
        battleTag=r["player_battletag"], region=r["region"], format=r["format"],
        seasonWins=r["season_wins"], seasonGames=games, winStreak=r["win_streak"],
        winRate=round(r["season_wins"] / games, 4) if games else None,
        starLevel=r["star_level_after"], stars=r["stars_after"], legendRank=r["legend_rank_after"],
        lastMatchAt=r["end_time"].isoformat(),
    )


_LATEST_COLS = (
    "player_battletag, region, format, season_wins, season_games, win_streak, "
    "star_level_after, stars_after, legend_rank_after, end_time"
)


@router.get("/leaderboard", response_model=LeaderboardResponse)
async def leaderboard(
    format: FormatName = "Standard",
    region: Optional[str] = Query(default=None, description="EU, US, AP, ... (case-insensitive); omit for all"),
    sort: SortKey = "wins",
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    region = region.strip().upper() if region else None
    # Latest stats row per player (DISTINCT ON uses idx_rank_tracker_matches_latest_per_player).
    latest = f"""
        SELECT DISTINCT ON (LOWER(player_battletag), region, format) {_LATEST_COLS}
        FROM rank_tracker_matches
        WHERE format = $1 AND ($2::text IS NULL OR region = $2) AND season_games IS NOT NULL
        ORDER BY LOWER(player_battletag), region, format, end_time DESC
    """
    async with get_db() as conn:
        total = await conn.fetchval(f"SELECT count(*) FROM ({latest}) t", format, region)
        rows = await conn.fetch(
            f"SELECT * FROM ({latest}) t ORDER BY {_SORT_SQL[sort]}, season_games DESC, "
            f"LOWER(player_battletag), region LIMIT $3 OFFSET $4",
            format, region, limit, offset,
        )
    return LeaderboardResponse(
        format=format, region=region, sort=sort, total=total, limit=limit, offset=offset,
        items=[_stats(r) for r in rows],
    )


@router.get("/player/{region}/{battletag}/stats", response_model=PlayerStatsResponse)
async def player_stats(
    region: str,
    battletag: str,
    format: Optional[FormatName] = Query(default=None, description="Limit history (and latest) to one format"),
    limit: int = Query(default=20, ge=1, le=100, description="History page size"),
    offset: int = Query(default=0, ge=0, description="History offset"),
):
    """Battletags contain '#': send it URL-encoded as %23 (e.g. Player%231234)."""
    region = region.strip().upper()
    who = "LOWER(player_battletag) = LOWER($1) AND region = $2 AND ($3::text IS NULL OR format = $3)"
    args = (battletag, region, format)
    async with get_db() as conn:
        latest = await conn.fetch(
            f"SELECT DISTINCT ON (format) {_LATEST_COLS} FROM rank_tracker_matches "
            f"WHERE {who} AND season_games IS NOT NULL ORDER BY format, end_time DESC",
            *args,
        )
        total = await conn.fetchval(f"SELECT count(*) FROM rank_tracker_matches WHERE {who}", *args)
        if total == 0:
            raise HTTPException(status_code=404, detail="No matches found for this player")
        hist = await conn.fetch(
            f"SELECT game_id, end_time, format, result, was_conceded, opponent_battletag, season_wins, "
            f"season_games, win_streak, star_level_after, stars_after, legend_rank_after, player_battletag "
            f"FROM rank_tracker_matches WHERE {who} ORDER BY end_time DESC, game_id LIMIT $4 OFFSET $5",
            *args, limit, offset,
        )
    name = (latest[0] if latest else hist[0] if hist else None)
    return PlayerStatsResponse(
        battleTag=name["player_battletag"] if name else battletag,
        region=region,
        latest=[_stats(r) for r in latest],
        history=HistoryPage(
            total=total, limit=limit, offset=offset,
            items=[
                MatchEntry(
                    gameId=str(r["game_id"]), endTime=r["end_time"].isoformat(), format=r["format"],
                    result=r["result"], wasConceded=r["was_conceded"], opponentBattleTag=r["opponent_battletag"],
                    seasonWins=r["season_wins"], seasonGames=r["season_games"], winStreak=r["win_streak"],
                    starLevelAfter=r["star_level_after"], starsAfter=r["stars_after"],
                    legendRankAfter=r["legend_rank_after"],
                )
                for r in hist
            ],
        ),
    )
