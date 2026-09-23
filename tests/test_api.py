import fakeredis
import pytest
from fastapi.testclient import TestClient

from app import main
from app.limiter.fixed_window import FixedWindowLimiter


@pytest.fixture
def client(monkeypatch):
    """Swap the real Redis-backed limiter for an in-memory one."""
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(main, "limiter", FixedWindowLimiter(fake, limit=3, window=60))
    return TestClient(main.app)


def test_allowed_requests_carry_rate_limit_headers(client):
    res = client.get("/api/data", headers={"X-API-Key": "user1"})
    assert res.status_code == 200
    assert res.headers["X-RateLimit-Limit"] == "3"
    assert res.headers["X-RateLimit-Remaining"] == "2"


def test_fourth_request_is_rejected_with_429(client):
    headers = {"X-API-Key": "user1"}
    codes = [client.get("/api/data", headers=headers).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_429_tells_the_client_when_to_retry(client):
    headers = {"X-API-Key": "user1"}
    for _ in range(3):
        client.get("/api/data", headers=headers)
    res = client.get("/api/data", headers=headers)
    assert res.status_code == 429
    assert int(res.headers["Retry-After"]) >= 1


def test_different_api_keys_get_their_own_budget(client):
    for _ in range(3):
        client.get("/api/data", headers={"X-API-Key": "user1"})
    assert client.get("/api/data", headers={"X-API-Key": "user2"}).status_code == 200


def test_health_is_never_rate_limited(client):
    for _ in range(10):
        assert client.get("/health").status_code == 200
