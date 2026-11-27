"""
Per-app-token rate limiting for the read API.

Sliding window kept in process memory, keyed by app token id. The API runs as a
single uvicorn process, so this is exact; with several workers/replicas each would
enforce the limit on its own (effective limit = N x), which is acceptable for
server-to-server read traffic. Configure with RATE_LIMIT_PER_MINUTE (default 60;
0 disables).
"""
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Response

from decktrackerAPI.auth import AppTokenRecord, require_scope
from decktrackerAPI.config import settings

WINDOW_SECONDS = 60.0

_hits: dict[int, deque] = defaultdict(deque)


def reset() -> None:
    _hits.clear()


def read_access(scope: str = "rank:read"):
    """Dependency: valid app token with `scope`, within its rate limit."""

    async def _dep(response: Response, token: AppTokenRecord = Depends(require_scope(scope))) -> AppTokenRecord:
        limit = settings.rate_limit_per_minute
        if limit <= 0:
            return token
        now = time.monotonic()
        hits = _hits[token.id]
        while hits and now - hits[0] >= WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= limit:
            retry_after = max(1, int(WINDOW_SECONDS - (now - hits[0])) + 1)
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )
        hits.append(now)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(limit - len(hits))
        return token

    return _dep
