import asyncio
from dataclasses import dataclass

import httpx

from .retry import RetryExhausted, retry_async

_HEADERS = {"User-Agent": "olostep-link-checker/1.0 (+https://www.olostep.com)"}


class _TransientHTTP(Exception):
    pass


@dataclass(frozen=True)
class PageFetch:
    url: str
    status_code: int | None
    html: str = ""
    error: str | None = None


def _is_transient(exc: Exception) -> bool:
    return isinstance(exc, (_TransientHTTP, httpx.TimeoutException, httpx.ConnectError))


async def fetch_page(
    url: str,
    client,
    max_attempts: int = 3,
    timeout: float = 15.0,
    sleep_fn=None,
) -> PageFetch:
    if sleep_fn is None:
        sleep_fn = asyncio.sleep

    async def attempt():
        response = await client.get(
            url,
            follow_redirects=True,
            timeout=timeout,
            headers=_HEADERS,
        )
        if response.status_code == 429 or 500 <= response.status_code < 600:
            raise _TransientHTTP(f"transient status {response.status_code}")
        return PageFetch(url=url, status_code=response.status_code, html=response.text)

    try:
        return await retry_async(
            attempt, max_attempts=max_attempts, should_retry=_is_transient, sleep_fn=sleep_fn
        )
    except RetryExhausted:
        return PageFetch(url=url, status_code=None, error="fetch-failed-after-retries")
    except httpx.TooManyRedirects:
        return PageFetch(url=url, status_code=None, error="redirect-loop")
    except Exception as exc:
        return PageFetch(url=url, status_code=None, error=f"fetch-error: {exc}")


async def fetch_pages(
    urls: list[str],
    client,
    concurrency: int = 10,
    max_attempts: int = 3,
    timeout: float = 15.0,
    sleep_fn=None,
) -> dict[str, PageFetch]:
    semaphore = asyncio.Semaphore(concurrency)

    async def bounded(url: str):
        async with semaphore:
            return url, await fetch_page(
                url,
                client,
                max_attempts=max_attempts,
                timeout=timeout,
                sleep_fn=sleep_fn,
            )

    results = await asyncio.gather(*(bounded(u) for u in urls))
    return dict(results)
