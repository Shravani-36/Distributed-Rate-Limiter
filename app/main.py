import socket

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

from app.config import settings
from app.limiter import build_limiter
from app.redis_client import redis_client

app = FastAPI(title="Distributed Rate Limiter")

limiter = build_limiter(redis_client)
INSTANCE = settings.instance_name or socket.gethostname()

# Paths that must answer even when the client is being rate limited.
EXEMPT_PATHS = {"/health", "/metrics", "/docs", "/openapi.json"}


def client_id(request: Request) -> str:
    """Per-API-key limits, falling back to the caller's IP."""
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"key:{api_key}"
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path in EXEMPT_PATHS:
        return await call_next(request)

    decision = limiter.allow(client_id(request))

    headers = {
        "X-RateLimit-Limit": str(decision.limit),
        "X-RateLimit-Remaining": str(decision.remaining),
        "X-RateLimit-Algorithm": settings.algorithm,
        # Which instance answered - visible on 429s too, where there is no body
        # from the app to carry it.
        "X-Instance": INSTANCE,
    }

    if decision.degraded:
        # Redis is down, so this answer came from the fallback policy rather
        # than a real count. Say so instead of pretending the limit was checked.
        headers["X-RateLimit-Degraded"] = "true"

    if not decision.allowed:
        return JSONResponse(
            {"detail": "Too Many Requests", "retry_after": decision.retry_after},
            status_code=429,
            headers={**headers, "Retry-After": str(decision.retry_after)},
        )

    response = await call_next(request)
    response.headers.update(headers)
    return response


@app.get("/health")
def health():
    try:
        redis_client.ping()
        redis_ok = True
    except RedisError:
        redis_ok = False

    # Deliberately still 200 when Redis is down and we fail open: the instance
    # can serve traffic, so a load balancer or Kubernetes readiness probe
    # should keep sending it requests. Failing closed is different - the
    # instance can only produce 429s, so it reports itself as not ready.
    status_code = 200 if (redis_ok or settings.fail_open) else 503

    return JSONResponse(
        {
            "status": "ok" if redis_ok else "degraded",
            "instance": INSTANCE,
            "redis": redis_ok,
            "policy": "fail_open" if settings.fail_open else "fail_closed",
            "redis_errors": limiter.redis_errors,
        },
        status_code=status_code,
    )


@app.get("/api/data")
def get_data():
    # `instance` shows which API server answered - handy once phase 7 runs
    # three of them behind a load balancer.
    return {"message": "Here is your data", "instance": INSTANCE}
