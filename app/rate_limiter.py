import os
import sys
import time
from collections import defaultdict
from typing import Dict, List, Optional
from fastapi import HTTPException, Request, status

from app.config import settings


class InMemoryRateLimiter:
    """
    In-memory sliding-window rate limiter for sensitive/expensive endpoints.
    Tracks requests per IP or authenticated principal subject.
    """

    def __init__(self, requests_limit: int = 30, window_seconds: int = 60):
        self.requests_limit = requests_limit
        self.window_seconds = window_seconds
        self.history: Dict[str, List[float]] = defaultdict(list)

    def _get_client_identifier(self, request: Request) -> str:
        # If client provided an authorization header, use the token hash prefix
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ").strip()
            return f"token:{hash(token)}"
        # Otherwise fall back to client IP address
        if request.client and request.client.host:
            return f"ip:{request.client.host}"
        return "ip:anonymous"

    def check(self, request: Request, force: bool = False) -> None:
        if not force and os.getenv("RATE_LIMIT_ENABLED", "").lower() not in {"1", "true"} and ("pytest" in sys.modules or settings.ENVIRONMENT == "development"):
            return

        now = time.time()
        client_id = self._get_client_identifier(request)
        cutoff = now - self.window_seconds

        # Prune older entries
        recent = [ts for ts in self.history[client_id] if ts > cutoff]
        self.history[client_id] = recent

        if len(recent) >= self.requests_limit:
            retry_after = int(self.window_seconds - (now - recent[0])) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: maximum {self.requests_limit} requests per {self.window_seconds}s. Please retry in {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )

        self.history[client_id].append(now)

    def reset(self) -> None:
        self.history.clear()


# Default rate limiter instances for sensitive/expensive operations
verifier_rate_limiter = InMemoryRateLimiter(requests_limit=20, window_seconds=60)
csv_upload_rate_limiter = InMemoryRateLimiter(requests_limit=10, window_seconds=60)
crypto_issue_rate_limiter = InMemoryRateLimiter(requests_limit=15, window_seconds=60)
reevaluate_rate_limiter = InMemoryRateLimiter(requests_limit=5, window_seconds=60)


def rate_limit_verifier(request: Request) -> None:
    verifier_rate_limiter.check(request)


def rate_limit_csv_upload(request: Request) -> None:
    csv_upload_rate_limiter.check(request)


def rate_limit_credential_issuance(request: Request) -> None:
    crypto_issue_rate_limiter.check(request)


def rate_limit_reevaluation(request: Request) -> None:
    reevaluate_rate_limiter.check(request)
