# Admin CLI: read-API app tokens

Admin how-to for managing the tokens that let predefined apps call the **read** endpoints of jeeves-api.
Code: `decktrackerAPI/admin_tokens.py`. Table: `api_app_tokens`.

## Two kinds of token (do not mix them up)

| | HSJeeves user token | App token |
|---|---|---|
| Table | `rank_api_tokens` | `api_app_tokens` |
| Issued by | Discord `/hdttoken` | this CLI |
| Used for | uploading matches (`POST /API`) | reading data (read endpoints) |
| On a read route | **403** (valid, but not allowed to read) | 200 |
| On `POST /API` | 200 | 401 |

Both are sent as `Authorization: Bearer <token>`. Only the SHA-256 hash is stored, never the token itself.

## Run it

The CLI needs the same `POSTGRES_*` environment as the API. In production Postgres has no host port, so run it
**inside the running `rank-api` container**, which already has the environment and the code (in `jeeves-deploy/`):

```bash
docker compose exec rank-api python -m decktrackerAPI.admin_tokens <command>
```

Locally (dev), with `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` set, from the
repo root:

```bash
python -m decktrackerAPI.admin_tokens <command>
```

The `api_app_tokens` table is created automatically when the API (or the CLI) first connects, so a fresh deploy
needs no manual migration.

## Commands

### Create a token

```bash
docker compose exec rank-api python -m decktrackerAPI.admin_tokens create <name> --scopes rank:read
```

- `<name>` is a unique label for the app (e.g. `web-app`, `discord-bot`). A duplicate name is refused.
- `--scopes` is a comma-separated list, free text (e.g. `rank:read`). It may be empty. A route protected with
  `require_scope("rank:read")` needs that exact scope on the token.
- The plaintext token is printed **once**. Copy it into the consuming app's secret store right away. It cannot be
  shown again; if lost, revoke it and create a new one.

### List tokens

```bash
docker compose exec rank-api python -m decktrackerAPI.admin_tokens list
```

Shows name, enabled/DISABLED, scopes, created time and **last used** (updated on every authenticated request;
`-` means never used). Hashes are not shown.

### Revoke a token

```bash
docker compose exec rank-api python -m decktrackerAPI.admin_tokens revoke <name>
```

Takes effect immediately: the next request with that token gets **401**. The row is kept (disabled) so `list` still
shows when it was last used.

### Re-enable a token

```bash
docker compose exec rank-api python -m decktrackerAPI.admin_tokens enable <name>
```

### Rotate a token (no downtime)

1. `create <name>-new --scopes ...` and give the new token to the app.
2. Once the app uses it, check `list`: the old token's `last_used` should stop moving.
3. `revoke <name>`.

## Expected HTTP results

| Request | Status |
|---|---|
| No `Authorization` header / not `Bearer` | 401 |
| Unknown or revoked app token | 401 |
| HSJeeves user token on a read route | 403 |
| Valid app token, route needs a scope it lacks | 403 |
| Valid app token (with scope) | 200 |

Quick check from a shell:

```bash
curl -i -H "Authorization: Bearer <token>" https://<api-host>/<read-route>
```

## Troubleshooting

- **`A token named 'x' already exists`**: pick another name, or `revoke` the old one and create a differently named one.
- **`No token named 'x'`**: names are case-sensitive; check `list`.
- **Connection error**: the CLI could not reach Postgres. In production use `docker compose exec rank-api ...`
  (a bare `python` on the host has no route to the database).
- **App gets 403 instead of 200**: either it is sending an HSJeeves user token, or the token lacks the scope the
  route requires. `list` shows the scopes.
