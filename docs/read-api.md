# Read API (leaderboard and player stats)

Server-to-server endpoints for predefined apps. Machine-readable contract: `openapi.json` (regenerated from the
code, see the end of this page). Code: `decktrackerAPI/read_api.py`, `decktrackerAPI/ratelimit.py`.

## Auth

```
Authorization: Bearer <app token>
```

- The token must be an **app token** with the **`rank:read`** scope. Create one with the admin CLI, see
  [admin-cli.md](admin-cli.md): `create <name> --scopes rank:read`.
- Missing/unknown/revoked token: **401**. An HSJeeves user upload token, or an app token without `rank:read`: **403**.
- No CORS (server-to-server only).

## Rate limiting

Per app token, sliding 60 s window, default **60 requests/minute** (`RATE_LIMIT_PER_MINUTE` env var, `0` = off).
Successful responses carry `X-RateLimit-Limit` and `X-RateLimit-Remaining`; over the limit gives **429** with
`Retry-After` (seconds). The window lives in process memory: with several API replicas each enforces the limit
separately.

## What the numbers are

Season stats come from schemaVersion 2 uploads (`seasonWins`, `seasonGames`, `winStreak`, see
[payload-definition.md](payload-definition.md)). Every endpoint uses, per player and format, the **latest match that
has season stats**; older v1 matches have none and never appear in `latest`/leaderboards. `winRate` is
`seasonWins / seasonGames` (0..1, rounded to 4 decimals). A player is identified by case-insensitive BattleTag
plus region. `region` was added to the upload payload after schemaVersion 1, so old uploads have no region (`null`);
HSJeeves always sends one (`UNKNOWN` if its lookup had not finished, which is then a region of its own). Players
with a `null` region appear in an unfiltered leaderboard but cannot be matched by a `region` filter or the player
endpoint. Uploads without a region are rejected (400), so only pre-region rows can have `null`; they have no season stats.

Rows are not tied to a season id, so a player who has not played since the season reset still shows last season's
numbers until they play again.

## `GET /API/leaderboard`

| Query | Default | Notes |
|---|---|---|
| `format` | `Standard` | `Standard`, `Wild`, `Classic`, `Twist` |
| `region` | all | `EU`, `US`, `AP`, ... (case-insensitive) |
| `sort` | `wins` | `wins`, `games`, `streak`, `winrate`, always descending. Ties: more games, then name |
| `limit` | 50 | 1 to 100 |
| `offset` | 0 | |

```json
{ "format": "Standard", "region": null, "sort": "wins", "total": 5, "limit": 50, "offset": 0,
  "items": [ { "battleTag": "B#2", "region": "EU", "format": "Standard", "seasonWins": 30, "seasonGames": 40,
               "winStreak": 5, "winRate": 0.75, "starLevel": 41, "stars": 2, "legendRank": 0,
               "lastMatchAt": "2026-11-27T10:02:00+00:00" } ] }
```

`total` is the number of ranked players matching the filters (use it for paging). `starLevel`, `stars` and
`legendRank` are the values after the player's latest match.

## `GET /API/player/{region}/{battletag}/stats`

BattleTags contain `#`: send it URL-encoded, e.g. `/API/player/EU/Player%231234/stats`.

| Query | Default | Notes |
|---|---|---|
| `format` | all | limits both `latest` and `history` to one format |
| `limit` | 20 | history page size, 1 to 100 |
| `offset` | 0 | history offset |

Returns `latest` (one entry per format, same shape as a leaderboard item) and `history`: the player's matches,
newest first, with `total`, `limit`, `offset` and `items` (`gameId`, `endTime`, `format`, `result`, `wasConceded`,
`opponentBattleTag`, `seasonWins`, `seasonGames`, `winStreak`, `starLevelAfter`, `starsAfter`, `legendRankAfter`).
History includes older v1 matches, whose season fields are `null`. **404** if the player has no matches in that
region (and format, if given).

## Errors

| Status | When |
|---|---|
| 400 | Invalid query parameter (bad `sort`/`format`, `limit` out of range). Body: `{"status":"error","detail":[...]}` |
| 401 / 403 | See Auth |
| 404 | Unknown player (player endpoint) |
| 429 | Rate limit exceeded |

## Regenerating `openapi.json`

From the repo root, with the pinned versions from `requirements.txt` installed (`POSTGRES_USER` only needs to be
set to import the app, no database is contacted):

```bash
POSTGRES_USER=x python -c "import json; from decktrackerAPI.main import app; open('openapi.json','w',newline='\n').write(json.dumps(app.openapi(), indent=2) + '\n')"
```
