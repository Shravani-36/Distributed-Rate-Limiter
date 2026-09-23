from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All settings can be overridden with environment variables.

    Example: REDIS_URL=redis://redis:6379/0 RATE_LIMIT=100
    """

    redis_url: str = "redis://localhost:6379/0"

    # rate_limit requests allowed per window_seconds, per client
    rate_limit: int = 10
    window_seconds: int = 60

    # "fixed" (simple, cheap) or "sliding" (accurate, no boundary burst)
    algorithm: str = "sliding"


settings = Settings()
