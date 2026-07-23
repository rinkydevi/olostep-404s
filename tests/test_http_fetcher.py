import asyncio

import httpx
import respx

from olostep_link_checker.http_fetcher import fetch_page, fetch_pages

URL = "https://x.com/a"


async def noop_sleep(seconds):
    pass


async def test_get_200_returns_status_and_html():
    with respx.mock:
        respx.get(URL).mock(return_value=httpx.Response(200, html="<html>hi</html>"))
        async with httpx.AsyncClient() as client:
            result = await fetch_page(URL, client, sleep_fn=noop_sleep)
        assert result.status_code == 200
        assert result.html == "<html>hi</html>"
        assert result.error is None


async def test_get_404_is_returned_as_status_not_error():
    with respx.mock:
        respx.get(URL).mock(return_value=httpx.Response(404, html="<html>gone</html>"))
        async with httpx.AsyncClient() as client:
            result = await fetch_page(URL, client, sleep_fn=noop_sleep)
        assert result.status_code == 404
        assert result.error is None  # a 404 is a valid answer, not a fetch failure


async def test_redirect_chain_follows_to_final_200():
    with respx.mock:
        respx.get(URL).mock(return_value=httpx.Response(301, headers={"location": "https://x.com/final"}))
        respx.get("https://x.com/final").mock(return_value=httpx.Response(200, html="<html>final</html>"))
        async with httpx.AsyncClient() as client:
            result = await fetch_page(URL, client, sleep_fn=noop_sleep)
        assert result.status_code == 200
        assert result.html == "<html>final</html>"


async def test_redirect_loop_is_reported_as_error_not_infinite():
    with respx.mock:
        respx.get("https://x.com/loop0").mock(return_value=httpx.Response(301, headers={"location": "https://x.com/loop1"}))
        respx.get("https://x.com/loop1").mock(return_value=httpx.Response(301, headers={"location": "https://x.com/loop0"}))
        async with httpx.AsyncClient(max_redirects=5) as client:
            result = await fetch_page("https://x.com/loop0", client, sleep_fn=noop_sleep)
        assert result.status_code is None
        assert result.error == "redirect-loop"


async def test_5xx_is_retried_then_succeeds():
    with respx.mock:
        route = respx.get(URL)
        route.side_effect = [
            httpx.Response(503, html=""),
            httpx.Response(200, html="<html>ok</html>"),
        ]
        async with httpx.AsyncClient() as client:
            result = await fetch_page(URL, client, max_attempts=3, sleep_fn=noop_sleep)
        assert result.status_code == 200


async def test_persistent_5xx_becomes_fetch_error_not_a_status():
    with respx.mock:
        respx.get(URL).mock(return_value=httpx.Response(500, html=""))
        async with httpx.AsyncClient() as client:
            result = await fetch_page(URL, client, max_attempts=2, sleep_fn=noop_sleep)
        assert result.status_code is None
        assert result.error is not None


async def test_timeout_is_retried_then_becomes_error():
    with respx.mock:
        respx.get(URL).mock(side_effect=httpx.TimeoutException("slow"))
        async with httpx.AsyncClient() as client:
            result = await fetch_page(URL, client, max_attempts=2, sleep_fn=noop_sleep)
        assert result.status_code is None
        assert result.error is not None


async def test_fetch_pages_concurrency_never_exceeds_ceiling():
    max_seen = 0
    current = 0
    lock = asyncio.Lock()

    class FakeResponse:
        status_code = 200
        text = "<html/>"

    class FakeClient:
        async def get(self, url, **kwargs):
            nonlocal max_seen, current
            async with lock:
                current += 1
                max_seen = max(max_seen, current)
            await asyncio.sleep(0.01)
            async with lock:
                current -= 1
            return FakeResponse()

    urls = [f"https://x.com/p{i}" for i in range(20)]
    results = await fetch_pages(urls, FakeClient(), concurrency=4, sleep_fn=noop_sleep)
    assert max_seen <= 4
    assert len(results) == 20


async def test_fetch_pages_one_failure_does_not_stop_the_batch():
    class FakeResponse:
        def __init__(self, status):
            self.status_code = status
            self.text = "<html/>"

    class FakeClient:
        async def get(self, url, **kwargs):
            if url == "https://x.com/bad":
                raise ValueError("unexpected")
            return FakeResponse(200)

    urls = ["https://x.com/bad", "https://x.com/a", "https://x.com/b"]
    results = await fetch_pages(urls, FakeClient(), concurrency=5, sleep_fn=noop_sleep)
    assert results["https://x.com/bad"].error is not None
    assert results["https://x.com/a"].status_code == 200
    assert results["https://x.com/b"].status_code == 200
