import pytest

from olostep_link_checker.retry import RetryExhausted, retry_async, retry_sync


def test_retry_sync_returns_result_on_first_success_no_sleep():
    sleeps = []

    def fn():
        return "ok"

    result = retry_sync(fn, max_attempts=3, sleep_fn=sleeps.append)
    assert result == "ok"
    assert sleeps == []


def test_retry_sync_succeeds_after_transient_failures():
    calls = {"count": 0}
    sleeps = []

    def fn():
        calls["count"] += 1
        if calls["count"] < 3:
            raise ConnectionError("transient")
        return "ok"

    result = retry_sync(fn, max_attempts=5, sleep_fn=sleeps.append)
    assert result == "ok"
    assert calls["count"] == 3
    assert len(sleeps) == 2  # slept before attempt 2 and attempt 3


def test_retry_sync_raises_after_exhausting_attempts():
    def fn():
        raise ConnectionError("always fails")

    with pytest.raises(RetryExhausted):
        retry_sync(fn, max_attempts=3, sleep_fn=lambda s: None)


def test_retry_sync_does_not_retry_when_should_retry_returns_false():
    calls = {"count": 0}

    def fn():
        calls["count"] += 1
        raise ValueError("not retryable")

    with pytest.raises(ValueError):
        retry_sync(fn, max_attempts=5, should_retry=lambda e: False, sleep_fn=lambda s: None)

    assert calls["count"] == 1


async def test_retry_async_succeeds_after_transient_failures():
    calls = {"count": 0}
    sleeps = []

    async def sleep_fn(seconds):
        sleeps.append(seconds)

    async def fn():
        calls["count"] += 1
        if calls["count"] < 3:
            raise ConnectionError("transient")
        return "ok"

    result = await retry_async(fn, max_attempts=5, sleep_fn=sleep_fn)
    assert result == "ok"
    assert calls["count"] == 3
    assert len(sleeps) == 2


async def test_retry_async_raises_after_exhausting_attempts():
    async def fn():
        raise ConnectionError("always fails")

    async def sleep_fn(seconds):
        pass

    with pytest.raises(RetryExhausted):
        await retry_async(fn, max_attempts=3, sleep_fn=sleep_fn)
