# Tests

The suite (`tests/`) runs the real FastAPI app against a **real PostgreSQL** database, because the
SQL (`DISTINCT ON`, sorting, paging) and the token logic are what needs checking. No mocks.

Covered: payload v1/v2 acceptance and the insert (NULL vs stored season stats, idempotent re-POST, required
region, malformed bodies), upload auth, read auth (no token 401, HSJeeves user token 403, app token 200, scopes,
revoked tokens, `last_used`), rate limiting, the leaderboard (latest row per player, all four sorts, pagination,
filters, tie-breaks), player stats and the admin CLI functions.

## Run locally

```bash
# 1. a throwaway Postgres (the database name must contain "test": the tests TRUNCATE the tables)
docker run -d --rm --name jeeves-test-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=jeeves_test -p 5432:5432 postgres:16

# 2. dependencies (same pinned versions as production, plus pytest)
pip install -r requirements-dev.txt

# 3. run
python -m pytest
```

The defaults are `localhost:5432`, user/password `postgres`, database `jeeves_test`. Override with the usual
`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` variables (e.g. to use another
port). `conftest.py` refuses to run if `POSTGRES_DB` does not contain `test`, so it cannot wipe a real database by
accident.

Stop the database afterwards: `docker stop jeeves-test-pg`.

## CI

`.github/workflows/tests.yml` runs `python -m pytest` on every pull request and on pushes to `main`, against a
`postgres:16` service container.
