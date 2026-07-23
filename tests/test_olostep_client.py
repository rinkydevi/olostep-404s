import httpx
import pytest
import respx

from olostep_link_checker.olostep_client import OlostepAPIError, OlostepClient

API_KEY = "test-key-123"
BASE_URL = "https://api.olostep.com/v1"


async def noop_sleep(seconds):
    pass


def make_client(http_client, max_attempts=3):
    return OlostepClient(
        api_key=API_KEY, http_client=http_client, max_attempts=max_attempts, sleep_fn=noop_sleep
    )


async def test_create_map_returns_urls_from_single_page_response():
    with respx.mock:
        respx.post(f"{BASE_URL}/maps").mock(
            return_value=httpx.Response(
                200,
                json={"id": "map_abc", "urls_count": 2, "urls": ["https://x.com/a", "https://x.com/b"]},
            )
        )
        async with httpx.AsyncClient() as http_client:
            client = make_client(http_client)
            urls = await client.create_map("https://x.com")
        assert urls == ["https://x.com/a", "https://x.com/b"]


async def test_create_map_follows_pagination_cursor_until_exhausted():
    with respx.mock:
        route = respx.post(f"{BASE_URL}/maps")
        route.side_effect = [
            httpx.Response(
                200,
                json={"id": "map_abc", "urls_count": 2, "urls": ["https://x.com/a", "https://x.com/b"], "cursor": "next-1"},
            ),
            httpx.Response(
                200,
                json={"id": "map_abc", "urls_count": 1, "urls": ["https://x.com/c"], "cursor": None},
            ),
        ]
        async with httpx.AsyncClient() as http_client:
            client = make_client(http_client)
            urls = await client.create_map("https://x.com")
        assert urls == ["https://x.com/a", "https://x.com/b", "https://x.com/c"]


async def test_create_map_sends_exclude_urls_when_provided():
    captured = {}

    def responder(request):
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"urls_count": 0, "urls": []})

    with respx.mock:
        respx.post(f"{BASE_URL}/maps").mock(side_effect=responder)
        async with httpx.AsyncClient() as http_client:
            client = make_client(http_client)
            await client.create_map("https://x.com", exclude_urls=["/dashboard/**", "/auth"])
        assert captured["body"]["exclude_urls"] == ["/dashboard/**", "/auth"]


async def test_scrape_returns_target_status_code_and_html():
    with respx.mock:
        respx.post(f"{BASE_URL}/scrapes").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "scrape_1",
                    "result": {
                        "html_content": "<html>hi</html>",
                        "page_metadata": {"status_code": 200, "title": "Hi"},
                    },
                    "credits_consumed": 1,
                },
            )
        )
        async with httpx.AsyncClient() as http_client:
            client = make_client(http_client)
            status_code, html = await client.scrape("https://x.com/a")
        assert status_code == 200
        assert html == "<html>hi</html>"


async def test_scrape_returns_target_hard_404_status_code_even_though_olostep_call_succeeded():
    with respx.mock:
        respx.post(f"{BASE_URL}/scrapes").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "scrape_2",
                    "result": {
                        "html_content": "<html>gone</html>",
                        "page_metadata": {"status_code": 404, "title": "Not Found"},
                    },
                    "credits_consumed": 1,
                },
            )
        )
        async with httpx.AsyncClient() as http_client:
            client = make_client(http_client)
            status_code, html = await client.scrape("https://x.com/removed")
        assert status_code == 404


async def test_scrape_retries_on_olostep_side_5xx_and_succeeds():
    with respx.mock:
        route = respx.post(f"{BASE_URL}/scrapes")
        route.side_effect = [
            httpx.Response(502, json={"error": {"type": "server_error", "code": "bad_gateway", "message": "try again"}}),
            httpx.Response(
                200,
                json={
                    "id": "scrape_3",
                    "result": {"html_content": "<html>ok</html>", "page_metadata": {"status_code": 200, "title": "Ok"}},
                    "credits_consumed": 1,
                },
            ),
        ]
        async with httpx.AsyncClient() as http_client:
            client = make_client(http_client, max_attempts=3)
            status_code, html = await client.scrape("https://x.com/flaky")
        assert status_code == 200


async def test_scrape_raises_olostep_api_error_after_exhausting_5xx_retries():
    with respx.mock:
        respx.post(f"{BASE_URL}/scrapes").mock(
            return_value=httpx.Response(
                504, json={"error": {"type": "request_timeout", "code": "scrape_poll_timeout", "message": "timed out"}}
            )
        )
        async with httpx.AsyncClient() as http_client:
            client = make_client(http_client, max_attempts=2)
            with pytest.raises(OlostepAPIError):
                await client.scrape("https://x.com/always-times-out")


async def test_scrape_raises_immediately_on_permanent_4xx_error_without_retry():
    calls = {"count": 0}

    def responder(request):
        calls["count"] += 1
        return httpx.Response(
            400,
            json={"error": {"type": "invalid_request_error", "code": "dns_resolution_failed", "message": "bad domain"}},
        )

    with respx.mock:
        respx.post(f"{BASE_URL}/scrapes").mock(side_effect=responder)
        async with httpx.AsyncClient() as http_client:
            client = make_client(http_client, max_attempts=5)
            with pytest.raises(OlostepAPIError) as exc_info:
                await client.scrape("https://typo-domain.invalid/a")

    assert calls["count"] == 1
    assert exc_info.value.code == "dns_resolution_failed"


async def test_error_body_with_string_error_field_does_not_crash():
    # Maps returns 404 with error as a plain STRING (not a dict), e.g. the real
    # "Could not retrieve page URLs from the sitemap." — must surface as OlostepAPIError.
    with respx.mock:
        respx.post(f"{BASE_URL}/maps").mock(
            return_value=httpx.Response(
                404,
                json={"id": "map_x", "urls_count": 0, "error": "Could not retrieve page URLs from the sitemap."},
            )
        )
        async with httpx.AsyncClient() as http_client:
            client = make_client(http_client, max_attempts=1)
            with pytest.raises(OlostepAPIError) as exc_info:
                await client.create_map("https://x.com")
        assert "sitemap" in str(exc_info.value)


async def test_post_retries_on_network_timeout_then_succeeds():
    with respx.mock:
        route = respx.post(f"{BASE_URL}/maps")
        route.side_effect = [
            httpx.ReadTimeout("slow"),
            httpx.Response(200, json={"urls_count": 1, "urls": ["https://x.com/a"]}),
        ]
        async with httpx.AsyncClient() as http_client:
            client = make_client(http_client, max_attempts=3)
            urls = await client.create_map("https://x.com")
        assert urls == ["https://x.com/a"]


async def test_post_raises_olostep_error_after_exhausting_network_timeout_retries():
    with respx.mock:
        respx.post(f"{BASE_URL}/scrapes").mock(side_effect=httpx.ConnectTimeout("nope"))
        async with httpx.AsyncClient() as http_client:
            client = make_client(http_client, max_attempts=2)
            with pytest.raises(OlostepAPIError):
                await client.scrape("https://x.com/a")


async def test_post_uses_a_long_timeout_suitable_for_maps_and_scrapes():
    captured = {}

    def responder(request):
        captured["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, json={"urls_count": 0, "urls": []})

    with respx.mock:
        respx.post(f"{BASE_URL}/maps").mock(side_effect=responder)
        async with httpx.AsyncClient() as http_client:
            client = OlostepClient(api_key=API_KEY, http_client=http_client, timeout=120.0, sleep_fn=noop_sleep)
            await client.create_map("https://x.com")
    # Maps can take up to 120s per Olostep docs; the read timeout must be generous.
    assert captured["timeout"]["read"] >= 120.0


async def test_scrape_sends_bearer_auth_header_and_html_format():
    captured = {}

    def responder(request):
        import json

        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"result": {"html_content": "<html/>", "page_metadata": {"status_code": 200, "title": ""}}, "credits_consumed": 1},
        )

    with respx.mock:
        respx.post(f"{BASE_URL}/scrapes").mock(side_effect=responder)
        async with httpx.AsyncClient() as http_client:
            client = make_client(http_client)
            await client.scrape("https://x.com/a")

    assert captured["headers"]["authorization"] == f"Bearer {API_KEY}"
    assert "html" in captured["body"]["formats"]
