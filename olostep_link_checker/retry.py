from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


class RetryExhausted(Exception):
    pass


def _default_backoff(attempt: int) -> float:
    return 2 ** (attempt - 1)


def retry_sync(
    fn: Callable[[], T],
    max_attempts: int = 3,
    should_retry: Callable[[Exception], bool] = lambda e: True,
    backoff_seconds: Callable[[int], float] = _default_backoff,
    sleep_fn: Callable[[float], None] = lambda s: None,
) -> T:
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if not should_retry(exc):
                raise
            if attempt == max_attempts:
                raise RetryExhausted(f"gave up after {max_attempts} attempts") from exc
            sleep_fn(backoff_seconds(attempt))
    raise RetryExhausted("unreachable") from last_exc


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    max_attempts: int = 3,
    should_retry: Callable[[Exception], bool] = lambda e: True,
    backoff_seconds: Callable[[int], float] = _default_backoff,
    sleep_fn: Callable[[float], Awaitable[None]] = None,
) -> T:
    if sleep_fn is None:
        import asyncio

        sleep_fn = asyncio.sleep

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except Exception as exc:
            last_exc = exc
            if not should_retry(exc):
                raise
            if attempt == max_attempts:
                raise RetryExhausted(f"gave up after {max_attempts} attempts") from exc
            await sleep_fn(backoff_seconds(attempt))
    raise RetryExhausted("unreachable") from last_exc
