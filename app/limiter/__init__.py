from app.config import settings
from app.limiter.base import Decision, RateLimiter
from app.limiter.fixed_window import FixedWindowLimiter

__all__ = ["Decision", "RateLimiter", "FixedWindowLimiter", "build_limiter"]


def build_limiter(redis, algorithm: str | None = None) -> RateLimiter:
    """Pick the algorithm by name. Phase 5 registers "sliding" here."""
    name = (algorithm or settings.algorithm).lower()
    if name == "fixed":
        return FixedWindowLimiter(redis, settings.rate_limit, settings.window_seconds)
    raise ValueError(f"Unknown rate limit algorithm: {name!r}")
