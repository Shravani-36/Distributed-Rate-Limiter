import time

import fakeredis
import pytest

from app.limiter.fixed_window import FixedWindowLimiter
from app.limiter.sliding_window import SlidingWindowLimiter


@pytest.fixture
def redis():
    return fakeredis.FakeRedis(decode_responses=True)


def test_blocks_once_the_limit_is_reached(redis):
    limiter = SlidingWindowLimiter(redis, limit=3, window=60)
    allowed = [limiter.allow("u1").allowed for _ in range(5)]
    assert allowed == [True, True, True, False, False]


def test_remaining_counts_down(redis):
    limiter = SlidingWindowLimiter(redis, limit=3, window=60)
    assert [limiter.allow("u1").remaining for _ in range(4)] == [2, 1, 0, 0]


def test_clients_are_independent(redis):
    limiter = SlidingWindowLimiter(redis, limit=1, window=60)
    assert limiter.allow("u1").allowed
    assert limiter.allow("u2").allowed
    assert not limiter.allow("u1").allowed


def test_two_instances_share_one_budget(redis):
    api1 = SlidingWindowLimiter(redis, limit=2, window=60)
    api2 = SlidingWindowLimiter(redis, limit=2, window=60)
    assert api1.allow("u1").allowed
    assert api2.allow("u1").allowed
    assert not api1.allow("u1").allowed


def test_rejected_requests_are_not_logged(redis):
    """A blocked request must not extend the window - otherwise a client that
    keeps hammering could lock itself out forever."""
    limiter = SlidingWindowLimiter(redis, limit=2, window=60)
    for _ in range(10):
        limiter.allow("u1")
    assert redis.zcard("rl:sliding:u1") == 2


def test_requests_expire_out_of_the_window(redis):
    limiter = SlidingWindowLimiter(redis, limit=2, window=1)
    assert limiter.allow("u1").allowed
    assert limiter.allow("u1").allowed
    assert not limiter.allow("u1").allowed
    time.sleep(1.1)  # the window slides past the first two requests
    assert limiter.allow("u1").allowed


def test_retry_after_is_at_least_one_second(redis):
    limiter = SlidingWindowLimiter(redis, limit=1, window=60)
    limiter.allow("u1")
    decision = limiter.allow("u1")
    assert not decision.allowed
    assert 1 <= decision.retry_after <= 60


def test_sliding_window_stops_the_boundary_burst(redis):
    """The reason this algorithm exists.

    Limit 4 per second. Send 4 requests at the very end of one fixed bucket,
    then 4 more just after it rolls over. The fixed window lets all 8 through
    (8 requests in a few milliseconds); the sliding window does not.
    """
    window = 1
    limit = 4

    # line up just before a fixed-window bucket boundary
    while (time.time() % window) < 0.9:
        time.sleep(0.01)

    fixed = FixedWindowLimiter(redis, limit=limit, window=window)
    sliding = SlidingWindowLimiter(redis, limit=limit, window=window)

    fixed_allowed = sum(fixed.allow("burst").allowed for _ in range(limit))
    sliding_allowed = sum(sliding.allow("burst").allowed for _ in range(limit))

    time.sleep(0.15)  # cross the boundary into the next bucket

    fixed_allowed += sum(fixed.allow("burst").allowed for _ in range(limit))
    sliding_allowed += sum(sliding.allow("burst").allowed for _ in range(limit))

    assert fixed_allowed == 2 * limit  # 8 requests in ~150ms - too many
    assert sliding_allowed == limit  # the burst is capped at the real limit
