from unspeaks.rate_limiter import RateLimiter


def test_first_request_does_not_wait(limiter, clock):
    assert limiter.acquire() == 0
    assert clock.sleeps == []


def test_requests_are_at_least_three_seconds_apart(limiter, clock):
    limiter.acquire()
    limiter.acquire()
    limiter.acquire()
    assert clock.sleeps == [3.0, 3.0]
    assert clock.now == 6.0


def test_never_more_than_max_requests_per_window(clock):
    limiter = RateLimiter(3, 10.0, 0.0, clock=clock, sleep=clock.sleep)
    for _ in range(3):
        limiter.acquire()
    assert clock.now == 0.0
    limiter.acquire()  # the 4th must wait until the first one leaves the window
    assert clock.now == 10.0


def test_the_real_limit_allows_at_most_100_requests_in_5_minutes(limiter, clock):
    times = []
    for _ in range(250):
        limiter.acquire()
        times.append(clock.now)
    for i, start in enumerate(times):
        in_window = [t for t in times[i:] if t < start + 300.0]
        assert len(in_window) <= 100


def test_block_for_pauses_all_requests(limiter, clock):
    limiter.acquire()
    limiter.block_for(30.0)  # e.g. the server sent "Retry-After: 30"
    limiter.acquire()
    assert clock.now == 30.0
