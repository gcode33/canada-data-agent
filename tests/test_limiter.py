import threading
import time

from hypothesis import given, settings
from hypothesis import strategies as st

from canada_agent.wds.limiter import TokenBucket


class FakeClock:
    """Time that only moves when someone sleeps, so the test is exact and instant."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        assert seconds >= 0, "never sleep a negative time"
        self.now += seconds


def grant_times(rate: float, gaps: list[float]) -> list[float]:
    clock = FakeClock()
    bucket = TokenBucket(rate, clock=clock.monotonic, sleep=clock.sleep)
    times = []
    for gap in gaps:
        clock.sleep(gap)  # the caller is idle for a while between requests
        bucket.acquire()
        times.append(clock.now)
    return times


@settings(max_examples=300)
@given(st.lists(st.floats(min_value=0, max_value=0.5, allow_nan=False), min_size=1, max_size=80))
def test_never_more_than_rate_grants_in_any_one_second_window(gaps):
    times = grant_times(10, gaps)
    for start in times:
        in_window = [t for t in times if start <= t < start + 1.0]
        assert len(in_window) <= 10


@given(st.lists(st.floats(min_value=0, max_value=0.5, allow_nan=False), min_size=2, max_size=40))
def test_grants_are_spaced_at_least_one_interval_apart(gaps):
    times = grant_times(10, gaps)
    assert all(b - a >= 0.1 - 1e-9 for a, b in zip(times, times[1:], strict=False))


def test_an_idle_caller_is_not_delayed():
    times = grant_times(10, [5.0, 5.0, 5.0])
    assert times == [1005.0, 1010.0, 1015.0]


def test_back_to_back_calls_wait_one_interval_each():
    times = grant_times(10, [0, 0, 0])
    assert [round(t - 1000.0, 9) for t in times] == [0.0, 0.1, 0.2]


def test_concurrent_callers_cannot_share_a_token():
    bucket = TokenBucket(50)  # real clock: one grant per 20 ms
    threads = [threading.Thread(target=bucket.acquire) for _ in range(8)]
    start = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # The first grant is free; the other 7 must each wait a full interval.
    assert time.monotonic() - start >= 7 * 0.020 - 0.002
