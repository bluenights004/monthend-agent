"""Shared HTTP behaviour for Xero and Microsoft Graph: retries, throttling, token files."""

from __future__ import annotations

import json
import logging
import os
import random
import stat
import time
from collections import deque
from pathlib import Path
from typing import Callable

log = logging.getLogger("monthend.http")


class IntegrationError(RuntimeError):
    """A connector failed in a way an operator must look at."""


class ReauthorisationRequired(IntegrationError):
    """The stored refresh token is no longer valid; a human must reconnect the app."""


def retry_after_seconds(headers, default: float) -> float:
    value = headers.get("Retry-After") or headers.get("retry-after")
    try:
        return max(float(value), 0.5) if value else default
    except ValueError:
        return default


def send_with_retries(send: Callable[[], "object"], *, max_attempts: int = 6,
                      sleep: Callable[[float], None] = time.sleep, on_unauthorised: Callable[[], None] | None = None):
    """Call `send()` (returns an httpx.Response) with retry on 429, 5xx and one 401 refresh.

    429 honours Retry-After. 5xx and network errors use capped exponential backoff with
    jitter. Other 4xx responses are returned to the caller unchanged.
    """
    import httpx

    refreshed = False
    for attempt in range(1, max_attempts + 1):
        try:
            response = send()
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            if attempt == max_attempts:
                raise IntegrationError(f"network error after {attempt} attempts: {exc}") from exc
            sleep(min(2 ** attempt, 60) + random.random())
            continue
        if response.status_code == 401 and on_unauthorised and not refreshed:
            on_unauthorised()
            refreshed = True
            continue
        if response.status_code == 429:
            wait = retry_after_seconds(response.headers, default=60)
            problem = response.headers.get("X-Rate-Limit-Problem", "")
            log.warning("rate limited (%s); sleeping %.1fs", problem or "429", wait)
            if attempt == max_attempts:
                raise IntegrationError(f"still rate limited after {attempt} attempts ({problem or '429'})")
            sleep(wait)
            continue
        if response.status_code >= 500:
            if attempt == max_attempts:
                raise IntegrationError(f"server error {response.status_code} after {attempt} attempts")
            sleep(retry_after_seconds(response.headers, default=min(2 ** attempt, 60) + random.random()))
            continue
        return response
    raise IntegrationError("unreachable")


class MinuteWindowLimiter:
    """Client-side limiter so we stay under a per-minute quota instead of hitting 429s."""

    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.per_minute = per_minute
        self.calls: deque[float] = deque()
        self.clock, self.sleep = clock, sleep

    def acquire(self) -> None:
        now = self.clock()
        while self.calls and now - self.calls[0] >= 60:
            self.calls.popleft()
        if len(self.calls) >= self.per_minute:
            wait = 60 - (now - self.calls[0]) + 0.05
            self.sleep(wait)
            return self.acquire()
        self.calls.append(now)


class FileTokenStore:
    """Token persistence for a single-machine deployment.

    The file is created with 0600 permissions. A hosted deployment should replace this
    with a secret manager (Azure Key Vault, AWS Secrets Manager); only load/save change.
    """

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text())

    def save(self, token: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as handle:
            json.dump(token, handle)
        os.replace(tmp, self.path)


def require_env(*names: str) -> dict[str, str]:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise IntegrationError(f"missing environment variables: {', '.join(missing)} (see .env.example)")
    return {n: os.environ[n] for n in names}
