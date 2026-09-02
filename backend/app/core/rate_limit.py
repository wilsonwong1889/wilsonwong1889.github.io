from collections import defaultdict, deque
from ipaddress import ip_address
from threading import Lock
from time import time

from fastapi import HTTPException, Request, status

from app.config import settings


_requests: dict[str, deque[float]] = defaultdict(deque)
_lock = Lock()

# Sweeping every key on every request would make each call O(number of clients).
# Once a minute is often enough to keep the map proportional to *active*
# clients rather than to every address that has ever connected.
_SWEEP_INTERVAL_SECONDS = 60.0
_last_sweep = 0.0

# A last-resort ceiling. If a flood ever outpaces the sweep, drop the whole map
# rather than let it grow without bound — the cost is one forgiving window for
# everyone, which is far better than exhausting a 512 MB instance.
_MAX_TRACKED_KEYS = 20_000


def _is_public(candidate: str) -> bool:
    try:
        parsed = ip_address(candidate)
    except ValueError:
        return False
    return not (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_reserved
        or parsed.is_unspecified
    )


def client_identifier(request: Request) -> str:
    """The address to bucket a caller under.

    Behind Render's proxy ``request.client.host`` is an internal 10.x address,
    so using it alone puts every visitor in one bucket — one attacker could then
    exhaust the auth limit and lock everybody out.

    ``X-Forwarded-For`` reads ``client, proxy1, proxy2``: the leftmost entry is
    whatever the *caller* sent and is therefore forgeable, while each proxy
    appends the peer it actually saw. Walking from the right and taking the
    first public address gives the last address a trusted hop observed, which a
    caller cannot spoof by setting the header themselves.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    for candidate in reversed([part.strip() for part in forwarded.split(",") if part.strip()]):
        if _is_public(candidate):
            return candidate

    # No usable forwarded address: local development, a direct connection, or an
    # all-private chain. The peer address is the best available answer.
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _sweep_locked(window_start: float) -> None:
    """Drop keys with no requests left in the window. Caller must hold the lock.

    Without this the map only ever grows: expired timestamps were trimmed inside
    each deque, but the keys themselves were never removed, so every address
    that ever called became a permanent entry.
    """
    stale = [key for key, entries in _requests.items() if not entries or entries[-1] < window_start]
    for key in stale:
        del _requests[key]


def rate_limit_dependency(namespace: str, max_requests: int):
    def dependency(request: Request) -> None:
        global _last_sweep

        key = f"{namespace}:{client_identifier(request)}"
        now = time()
        window_start = now - settings.RATE_LIMIT_WINDOW_SECONDS

        with _lock:
            if now - _last_sweep >= _SWEEP_INTERVAL_SECONDS:
                _sweep_locked(window_start)
                _last_sweep = now
            if len(_requests) >= _MAX_TRACKED_KEYS:
                _sweep_locked(window_start)
                if len(_requests) >= _MAX_TRACKED_KEYS:
                    _requests.clear()

            entries = _requests[key]
            while entries and entries[0] < window_start:
                entries.popleft()
            if len(entries) >= max_requests:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded",
                )
            entries.append(now)

    return dependency
