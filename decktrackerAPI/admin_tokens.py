"""
Admin CLI for read-API app tokens (table api_app_tokens).

    python -m decktrackerAPI.admin_tokens create <name> [--scopes rank:read,...]
    python -m decktrackerAPI.admin_tokens list
    python -m decktrackerAPI.admin_tokens revoke <name>
    python -m decktrackerAPI.admin_tokens enable <name>

Uses the same POSTGRES_* environment as the API. `create` prints the plaintext
token once; only its SHA-256 hash is stored. `revoke` disables the token (the row
is kept for audit); `enable` turns it back on.
"""
import argparse
import asyncio
import secrets
import sys

import asyncpg

from decktrackerAPI.auth import hash_token
from decktrackerAPI.db import close_db_pool, get_db


async def create(name: str, scopes: list[str]) -> int:
    token = secrets.token_urlsafe(32)
    async with get_db() as conn:
        try:
            await conn.execute(
                "INSERT INTO api_app_tokens (name, token_hash, scopes) VALUES ($1, $2, $3)",
                name, hash_token(token), scopes,
            )
        except asyncpg.UniqueViolationError:
            print(f"A token named '{name}' already exists", file=sys.stderr)
            return 1
    print(f"Token for '{name}' (shown once, store it now):\n{token}")
    return 0


async def list_tokens() -> int:
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT name, scopes, enabled, created_at, last_used_at FROM api_app_tokens ORDER BY id"
        )
    for r in rows:
        print(f"{r['name']:<24} {'enabled ' if r['enabled'] else 'DISABLED'} "
              f"scopes={','.join(r['scopes']) or '-'} created={r['created_at']:%Y-%m-%d %H:%M} "
              f"last_used={r['last_used_at'] or '-'}")
    return 0


async def set_enabled(name: str, enabled: bool) -> int:
    async with get_db() as conn:
        res = await conn.execute("UPDATE api_app_tokens SET enabled = $2 WHERE name = $1", name, enabled)
    if res.endswith(" 0"):
        print(f"No token named '{name}'", file=sys.stderr)
        return 1
    print(f"Token '{name}' {'enabled' if enabled else 'revoked'}")
    return 0


async def _main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="admin_tokens", description="Manage read-API app tokens")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("name")
    c.add_argument("--scopes", default="")
    sub.add_parser("list")
    sub.add_parser("revoke").add_argument("name")
    sub.add_parser("enable").add_argument("name")
    a = p.parse_args(argv)
    try:
        if a.cmd == "create":
            return await create(a.name, [s.strip() for s in a.scopes.split(",") if s.strip()])
        if a.cmd == "list":
            return await list_tokens()
        return await set_enabled(a.name, a.cmd == "enable")
    finally:
        await close_db_pool()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
