# RankTrackerPlugin upload payload

Reference for implementing the real backend. Describes exactly what
`src/plugin/RankTrackerPlugin.cs` sends, matching `main.py` (the mock) field
for field. `main.py` is intentionally a minimal stand-in — this doc is the
actual contract to build against.

## Request

```
POST /API
Authorization: Bearer <api-key>
Content-Type: application/json
```

- Path is exactly `/API` (case-sensitive on most routers) — that's what's
  hardcoded as the plugin's default `ApiUrl`.
- `<api-key>` is an opaque token the backend issues per user/account. The
  backend resolves the authenticated account from the token alone; nothing
  in the body identifies who's uploading (see `playerBattleTag` below for
  why that's still sent anyway).
- One request per finished ranked match. Currently only `GameMode.Ranked`
  matches are ever sent (see "Game modes" below).

## Body

```json
{
  "schemaVersion": 1,
  "gameId": "681ae3e7-056c-4ebe-b5e8-dbb6303d0586",
  "startTime": "2026-07-24T17:25:41.6418834+02:00",
  "endTime": "2026-07-24T17:33:03.474066+02:00",
  "gameMode": "Ranked",
  "format": "Standard",
  "result": "Win",
  "wasConceded": false,
  "region": "EU",
  "playerBattleTag": "Player#1234",
  "opponentBattleTag": "Opponent#5678",
  "rank": {
    "LeagueId": 5,
    "Rank": 0,
    "StarLevel": 36,
    "Stars": 1,
    "LegendRank": 0
  },
  "rankAfter": {
    "StarLevelAfter": 36,
    "StarsAfter": 2,
    "LegendRankAfter": 0
  }
}
```

(Example values are shaped after an actual captured upload — see
`received_games.log` — with the real BattleTags replaced by placeholders.)

## Fields

| Field | Type | Notes |
|---|---|---|
| `schemaVersion` | int | `1` (original) or `2` (adds the season-stats fields below). The backend accepts both. Bump whenever a field is added/renamed/removed so the backend can branch on payload shape across plugin versions. |
| `gameId` | string (GUID) | Generated client-side by HDT (`Guid.NewGuid()`) per match, globally unique. **Use this as the idempotency key** — enforce a unique constraint and treat a repeat POST of the same `gameId` as a no-op, not a new row. |
| `startTime` / `endTime` | string (ISO 8601, with offset) | Match start/end, local machine time including UTC offset — not normalized to UTC. |
| `gameMode` | string | Enum-as-string from `Hearthstone_Deck_Tracker.Enums.GameMode`. Currently only ever `"Ranked"` (see "Game modes" below), but treat as an open string — this may grow (Battlegrounds, Arena, etc.) without a `schemaVersion` bump if the backend just stores the string. |
| `format` | string | One of `All`, `Standard`, `Wild`, `Classic`, `Twist` (`Hearthstone_Deck_Tracker.Enums.Format`). For a real ranked match this is the format actually played, not `All`. |
| `result` | string | One of `None`, `Win`, `Loss`, `Draw` (`Hearthstone_Deck_Tracker.Enums.GameResult`). `None` shouldn't occur in practice — the plugin only sends completed matches. |
| `wasConceded` | bool | Whether the match ended by concede rather than a natural finish. |
| `region` | string, **required** | Uploads without a region (missing, `null` or blank) are rejected with `400`. One of `EU`, `US`, `AP` — the realm the match was played on. Remapped from HDT's `Region` enum (`Hearthstone_Deck_Tracker.Enums.Region`), which calls this realm `ASIA` internally; the plugin's `RegionLabel` helper translates that to `AP` for the payload. Can read `UNKNOWN` (region lookup hadn't completed yet — see below) or, in principle, `CHINA` (separate client, not expected in practice). |
| `playerBattleTag` | string | The uploading account's own BattleTag (`Name#Number`), detected by HDT from the game log. Included even though the API key already identifies the account — see "Why `playerBattleTag` is sent" below. |
| `opponentBattleTag` | string | Opponent's BattleTag, same format. |
| `rank.LeagueId` | int | `5` = the current Bronze→Diamond star-league system (see "Rank fields" below). Values `< 5` are the legacy pre-rework rank tiers. |
| `rank.Rank` | int | Only meaningful when `LeagueId < 5` (legacy system). `0` under the current system. |
| `rank.StarLevel` | int | `1`–`50` under the current system (`LeagueId == 5`); see the League/StarLevel table below. Rank **entering** the match. |
| `rank.Stars` | int | Star count within the current `StarLevel`, entering the match. |
| `rank.LegendRank` | int | `> 0` means the player was Legend rank entering the match (overrides `StarLevel`/`Rank` display entirely — lower number is better, `1` is rank #1). `0` otherwise. |
| `rankAfter.StarLevelAfter` | int | `StarLevel` after the match's rank change was applied. |
| `rankAfter.StarsAfter` | int | `Stars` after the match. |
| `rankAfter.LegendRankAfter` | int | `LegendRank` after the match. |
| `seasonWins` | int, optional | **schemaVersion 2.** Ranked wins this season in the played `format`, after the match. Top-level camelCase (not nested in `rankAfter`). Read from HSMagic `GetMedalInfo().<Format>.SeasonWins`. |
| `seasonGames` | int, optional | **schemaVersion 2.** Ranked games played this season in the played `format`, after the match. From `SeasonGames`. |
| `winStreak` | int, optional | **schemaVersion 2.** Current win streak in the played `format`, after the match. From HSMagic `Streak` (note the different name). |

The three season fields are optional. A schemaVersion 1 payload omits them and the backend stores NULL. A schemaVersion 2 payload sends all three; if one is omitted or `null` it is stored as NULL. The sender (HSJeeves) takes all three from the same HSMagic `GetMedalInfo()` record that signals the end of the game (`SeasonGames` of the played format rose by 1), so they are the post-game values. Do not read them from the per-player medal copy, which is stale at game end (see HS-Magic `docs/end-of-game-data.md`, section 7). Consistency expectation, usable as a sender-side sanity check: after a `Win`, `winStreak >= 1`; after a `Loss`, `winStreak == 0`; `seasonWins <= seasonGames`.

There is currently no `opponentRank`/`opponentLegendRank` in the payload,
even though HDT captures them (`GameStats.OpponentRank`,
`OpponentLegendRank`) — not included in this schema version.

### Rank fields: League/StarLevel table

Only relevant when `rank.LeagueId == 5`. `StarLevel` runs 1→50 across 5
leagues of 10 levels each, counting **down** within a league (1 = bottom,
10 = top):

| StarLevel range | League |
|---|---|
| 1–10 | Bronze (10 → 1) |
| 11–20 | Silver (10 → 1) |
| 21–30 | Gold (10 → 1) |
| 31–40 | Platinum (10 → 1) |
| 41–50 | Diamond (10 → 1) |

E.g. `StarLevel: 36` = Platinum 5. Above `StarLevel: 50` is Legend, signaled
by `rank.LegendRank`/`rankAfter.LegendRankAfter` being `> 0` instead — those
override the League/StarLevel display entirely when set. See
`../../design/rank-data-fetch-plugin.md` ("Fetching post-match rank")
and `HDT/.../Hearthstone/RankTranslator.cs` for the source this is derived
from.

### Why `playerBattleTag` is sent

The Bearer token already identifies *who's authorized to upload*, but
`playerBattleTag` is ground truth for *which BattleTag was actually detected
playing this match* — useful if one account plays under multiple BattleTags
(region-specific tags, renames), and doubles as an audit trail against
whatever the token maps to server-side.

### Region

`region` comes from `GameStats.Region`, which HDT stamps onto every match
from `Game.CurrentRegion` — detected once per Hearthstone session via
`HearthMirror.Reflection.Client.GetAccountId()` (a byte embedded in the
account ID), not something the plugin derives itself. `UNKNOWN` means the
match started before that lookup finished; treat it as "region not yet
known," not an error. See `../../design/rank-data-fetch-plugin.md`
("Authentication and payload delivery" → the `region` paragraph) for the full
detection chain and source references.

### Game modes

Only `GameMode.Ranked` is uploaded today (see `UploadedModes` in
`RankTrackerPlugin.cs`) — `gameMode` will currently always read `"Ranked"`.
Other modes populate different rank/rating fields entirely on the HDT side
(Battlegrounds rating, Arena rating, etc.), so supporting them later is a
schema addition, not just a filter change.

## Expected response

The mock (`main.py`) returns, on success:

```json
{ "status": "ok", "gameId": "681ae3e7-056c-4ebe-b5e8-dbb6303d0586" }
```

The plugin only checks `response.IsSuccessStatusCode` (any 2xx) — it doesn't
parse the response body at all. A real backend has latitude on the exact
response shape as long as the status code is correct:

| Status | Meaning |
|---|---|
| `2xx` | Accepted. Plugin logs success and discards the match — **there is no retry**, so this must mean "durably stored," not just "received." |
| `401` | Missing or invalid Bearer token. |
| `400` | Malformed JSON body. |
| anything else | Treated as failure — plugin logs a warning and drops the match (no retry in this version). |

## Idempotency

Because there is no retry queue on the plugin side (a dropped request is
gone for good), but there could be in a future version, and because network
retries in general can duplicate a request: **enforce uniqueness on
`gameId`** and make a repeat POST of the same `gameId` a safe no-op
(e.g. `200`/`409` without inserting a duplicate row), not an error.
