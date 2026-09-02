from collections import defaultdict, deque
from ipaddress import ip_address
from threading import Lock
from time import time
from uuid import uuid4

from fastapi import HTTPException, Request, status

from app.config import settings

try:
    import redis
except ImportError:  # pragma: no cover - optional local dependency
    redis = None


# ---------------------------------------------------------------------------
# Client identity
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Shared counters (Redis) — correct across instances and across restarts
# ---------------------------------------------------------------------------

_redis_pool = None
_redis_failed = False


def _redis_client():
    """A reused client, or None if Redis is unavailable.

    Cached rather than built per request: a new connection on every rate-limit
    check would cost more than the check itself.
    """
    global _redis_pool, _redis_failed
    if redis is None or _redis_failed:
        return None
    if _redis_pool is None:
        try:
            _redis_pool = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        except Exception:  # noqa: BLE001 - fall back rather than fail the request
            _redis_failed = True
            return None
    return _redis_pool


def _check_redis(key: str, max_requests: int, now: float, window: float) -> bool | None:
    """True if allowed, False if over the limit, None if Redis could not answer.

    A sorted set keyed by timestamp gives the same sliding window the in-memory
    path uses, rather than a fixed window that would let through a double burst
    at the boundary.
    """
    client = _redis_client()
    if client is None:
        return None

    member = f"{now:.6f}:{uuid4().hex[:8]}"  # unique: two hits can share a timestamp
    try:
        pipe = client.pipeline()
        pipe.zremrangebyscore(key, 0, now - window)
        pipe.zadd(key, {member: now})
        pipe.zcard(key)
        pipe.expire(key, int(window) + 1)
        results = pipe.execute()
        count = results[2]
    except Exception:  # noqa: BLE001 - Redis blips must not break sign-in
        return None

    if count > max_requests:
        # Drop the rejected attempt, so a blocked caller cannot keep pushing the
        # window forward and lock themselves out for longer than the window.
        try:
            client.zrem(key, member)
        except Exception:  # noqa: BLE001
            pass
        return False
    return True


# ---------------------------------------------------------------------------
# Fallback counters (in-process) — used only when Redis cannot answer
# ---------------------------------------------------------------------------

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


def _sweep_locked(window_start: float) -> None:
    """Drop keys with no requests left in the window. Caller must hold the lock.

    Without this the map only ever grows: expired timestamps were trimmed inside
    each deque, but the keys themselves were never removed, so every address
    that ever called became a permanent entry.
    """
    stale = [key for key, entries in _requests.items() if not entries or entries[-1] < window_start]
    for key in stale:
        del _requests[key]


def _check_memory(key: str, max_requests: int, now: float, window: float) -> bool:
    global _last_sweep
    window_start = now - window

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
            return False
        entries.append(now)
        return True


# ---------------------------------------------------------------------------

def rate_limit_dependency(namespace: str, max_requests: int):
    def dependency(request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        key = f"ratelimit:{namespace}:{client_identifier(request)}"
        now = time()
        window = float(settings.RATE_LIMIT_WINDOW_SECONDS)

        # Redis first: counters in a module-level dict are per-process, and
        # production runs more than one instance, so each kept its own tally and
        # the effective limit was a multiple of the configured one. They also
        # reset on every deploy.
        allowed = _check_redis(key, max_requests, now, window)
        if allowed is None:
            allowed = _check_memory(key, max_requests, now, window)

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many attempts. Wait a minute and try again.",
            )

    return dependency
