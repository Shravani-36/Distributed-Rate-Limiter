from dataclasses import dataclass


@dataclass
class Decision:
    """The answer to 'may this request go through?'"""

    allowed: bool
    limit: int
    remaining: int
    retry_after: int  # seconds the client should wait before retrying


class RateLimiter:
    """Interface shared by every algorithm."""

    def allow(self, client_id: str) -> Decision:  # pragma: no cover - interface
        raise NotImplementedError
