import asyncio

import httpx
import pytest
import respx

from olostep_link_checker.external_checker import check_external, check_many_external

URL = "https://example.com/some-page"


@pytest.mark.respx(base_url=None)
async def test_head_200_is_ok():
    with respx.mock:
        respx.head(URL).mock(return_value=httpx.Response(200, headers={"content-type": "text/html"}))
        async with httpx.AsyncClient() as client:
            result = await check_external(URL, client)
        assert result.classification == "ok"


async def test_head_404_confirmed_by_get_is_external_dead():
    # HEAD and GET agree: genuinely dead.
    with respx.mock:
        respx.head(URL).mock(return_value=httpx.Response(404))
        respx.get(URL).mock(return_value=httpx.Response(404))
        async with httpx.AsyncClient() as client:
            result = await check_external(URL, client, confirm_dead=False)
        assert result.classification == "external-dead"
        assert result.status_code == 404


async def test_head_404_overridden_by_get_200_is_ok():
    # Live finding (v3.1 unverified-bucket investigation): rfc-editor.org and
    # support.google.com both answer HEAD with a false 404 but GET with a real 200 —
    # a single same-request GET double-check must win over the HEAD answer.
    with respx.mock:
        respx.head(URL).mock(return_value=httpx.Response(404))
        respx.get(URL).mock(return_value=httpx.Response(200, headers={"content-type": "text/html"}))
        async with httpx.AsyncClient() as client:
            result = await check_external(URL, client, confirm_dead=False)
        assert result.classification == "ok"


async def test_confirmed_dead_404_is_double_checked_before_finalizing():
    # First full check (HEAD 404, GET double-check agrees 404) and a delayed recheck
    # (same again) both say dead -> genuinely dead.
    sleeps = []

    async def sleep_fn(seconds):
        sleeps.append(seconds)

    with respx.mock:
        respx.head(URL).mock(return_value=httpx.Response(404))
        respx.get(URL).mock(return_value=httpx.Response(404))
        async with httpx.AsyncClient() as client:
            result = await check_external(URL, client, sleep_fn=sleep_fn)
        assert result.classification == "external-dead"
        assert len(sleeps) == 1  # exactly one recheck delay, not more


async def test_flaky_404_that_recovers_on_recheck_is_reported_ok_not_dead():
    async def sleep_fn(seconds):
        pass

    with respx.mock:
        # First full check: HEAD 404, GET double-check agrees -> genuinely dead for now.
        # Delayed recheck: HEAD alone now says 200 -> flaky, resolved to ok.
        respx.head(URL).side_effect = [httpx.Response(404), httpx.Response(200, headers={"content-type": "text/html"})]
        respx.get(URL).mock(return_value=httpx.Response(404))
        async with httpx.AsyncClient() as client:
            result = await check_external(URL, client, sleep_fn=sleep_fn)
        assert result.classification == "ok"


async def test_flaky_404_that_becomes_blocked_on_recheck_is_reported_blocked():
    async def sleep_fn(seconds):
        pass

    with respx.mock:
        respx.head(URL).side_effect = [httpx.Response(404), httpx.Response(403)]
        respx.get(URL).mock(return_value=httpx.Response(404))
        async with httpx.AsyncClient() as client:
            result = await check_external(URL, client, sleep_fn=sleep_fn)
        assert result.classification == "external-blocked"


async def test_already_ok_result_is_never_rechecked():
    calls = {"count": 0}

    def responder(request):
        calls["count"] += 1
        return httpx.Response(200, headers={"content-type": "text/html"})

    async def sleep_fn(seconds):
        raise AssertionError("should never sleep/recheck an already-ok result")

    with respx.mock:
        respx.head(URL).mock(side_effect=responder)
        async with httpx.AsyncClient() as client:
            result = await check_external(URL, client, sleep_fn=sleep_fn)
        assert result.classification == "ok"
        assert calls["count"] == 1


async def test_blocked_result_is_never_rechecked_only_confirmed_dead_is():
    calls = {"count": 0}

    def responder(request):
        calls["count"] += 1
        return httpx.Response(403)

    async def sleep_fn(seconds):
        raise AssertionError("blocked results are already ambiguous, no recheck needed")

    with respx.mock:
        respx.head(URL).mock(side_effect=responder)
        async with httpx.AsyncClient() as client:
            result = await check_external(URL, client, sleep_fn=sleep_fn)
        assert result.classification == "external-blocked"
        assert calls["count"] == 1


async def test_confirm_dead_can_be_disabled_for_single_check_speed():
    # confirm_dead=False only skips the delayed outer recheck, not the same-request
    # HEAD->GET double-check (that one is cheap: no sleep, always correctness-improving).
    with respx.mock:
        respx.head(URL).mock(return_value=httpx.Response(404))
        respx.get(URL).mock(return_value=httpx.Response(404))
        async with httpx.AsyncClient() as client:
            result = await check_external(URL, client, confirm_dead=False)
        assert result.classification == "external-dead"


async def test_head_410_gone_is_external_dead():
    with respx.mock:
        respx.head(URL).mock(return_value=httpx.Response(410))
        respx.get(URL).mock(return_value=httpx.Response(410))
        async with httpx.AsyncClient() as client:
            result = await check_external(URL, client, confirm_dead=False)
        assert result.classification == "external-dead"


async def test_403_is_blocked_not_dead():
    # 403 to our bot means the site is up but won't talk to us — NOT a broken link.
    with respx.mock:
        respx.head(URL).mock(return_value=httpx.Response(403))
        respx.get(URL).mock(return_value=httpx.Response(403))
        async with httpx.AsyncClient() as client:
            result = await check_external(URL, client)
        assert result.classification == "external-blocked"
        assert result.status_code == 403


async def test_429_rate_limited_is_blocked_not_dead():
    with respx.mock:
        respx.head(URL).mock(return_value=httpx.Response(429))
        respx.get(URL).mock(return_value=httpx.Response(429))
        async with httpx.AsyncClient() as client:
            result = await check_external(URL, client)
        assert result.classification == "external-blocked"


async def test_linkedin_999_is_blocked_not_dead():
    with respx.mock:
        respx.head(URL).mock(return_value=httpx.Response(999))
        respx.get(URL).mock(return_value=httpx.Response(999))
        async with httpx.AsyncClient() as client:
            result = await check_external(URL, client)
        assert result.classification == "external-blocked"


async def test_500_server_error_is_blocked_not_confirmed_dead():
    with respx.mock:
        respx.head(URL).mock(return_value=httpx.Response(500))
        respx.get(URL).mock(return_value=httpx.Response(500))
        async with httpx.AsyncClient() as client:
            result = await check_external(URL, client)
        assert result.classification == "external-blocked"


async def test_head_405_falls_back_to_get():
    with respx.mock:
        respx.head(URL).mock(return_value=httpx.Response(405))
        respx.get(URL).mock(return_value=httpx.Response(200, headers={"content-type": "text/html"}))
        async with httpx.AsyncClient() as client:
            result = await check_external(URL, client)
        assert result.classification == "ok"


async def test_redirect_chain_two_hops_ending_ok():
    hop1 = "https://example.com/hop1"
    hop2 = "https://example.com/hop2"
    with respx.mock:
        respx.head(URL).mock(
            return_value=httpx.Response(301, headers={"location": hop1})
        )
        respx.head(hop1).mock(
            return_value=httpx.Response(302, headers={"location": hop2})
        )
        respx.head(hop2).mock(
            return_value=httpx.Response(200, headers={"content-type": "text/html"})
        )
        async with httpx.AsyncClient() as client:
            result = await check_external(URL, client, max_redirect_hops=10)
        assert result.classification == "ok"


async def test_redirect_chain_exceeding_cap_is_redirect_loop():
    with respx.mock:
        # every hop redirects to the next, forever
        for i in range(0, 15):
            src = f"https://example.com/hop{i}"
            dst = f"https://example.com/hop{i + 1}"
            respx.head(src).mock(return_value=httpx.Response(301, headers={"location": dst}))
        async with httpx.AsyncClient() as client:
            result = await check_external("https://example.com/hop0", client, max_redirect_hops=10)
        assert result.classification == "external-dead"
        assert result.reason == "redirect-loop"


async def test_connection_timeout_is_external_timeout():
    with respx.mock:
        respx.head(URL).mock(side_effect=httpx.TimeoutException("timed out"))
        async with httpx.AsyncClient() as client:
            result = await check_external(URL, client)
        assert result.classification == "external-timeout"


async def test_dns_failure_is_external_dead_with_dns_reason():
    with respx.mock:
        respx.head(URL).mock(
            side_effect=httpx.ConnectError("[Errno 8] nodename nor servname provided, or not known")
        )
        async with httpx.AsyncClient() as client:
            result = await check_external(URL, client)
        assert result.classification == "external-dead"
        assert result.reason == "dns-failure"


async def test_generic_connect_error_is_external_dead_not_dns():
    with respx.mock:
        respx.head(URL).mock(side_effect=httpx.ConnectError("Connection refused"))
        async with httpx.AsyncClient() as client:
            result = await check_external(URL, client)
        assert result.classification == "external-dead"
        assert result.reason == "connection-error"


async def test_non_html_content_type_is_skipped_not_ok_or_broken():
    with respx.mock:
        respx.head(URL).mock(return_value=httpx.Response(200, headers={"content-type": "application/pdf"}))
        async with httpx.AsyncClient() as client:
            result = await check_external(URL, client)
        assert result.classification == "skipped-non-html"


async def test_blocked_or_dead_html_link_defaults_to_resolvable():
    with respx.mock:
        respx.head(URL).mock(return_value=httpx.Response(403))
        respx.get(URL).mock(return_value=httpx.Response(403))
        async with httpx.AsyncClient() as client:
            result = await check_external(URL, client)
        assert result.resolvable is True


async def test_dead_pdf_by_url_extension_is_not_resolvable():
    # Live finding (v3.1 unverified-bucket investigation): a dead PDF's 404 is often
    # itself served as a small HTML error page, so content-type on the error response
    # can't be trusted to detect this — the URL's own extension is the reliable signal.
    # Escalating a non-HTML resource to Olostep's HTML renderer only makes things worse
    # (504 timeout on a kuleuven.be PDF, live-verified), so it must never be escalated.
    pdf_url = "https://homes.esat.kuleuven.be/paper.pdf"
    with respx.mock:
        respx.head(pdf_url).mock(return_value=httpx.Response(404, headers={"content-type": "text/html"}))
        respx.get(pdf_url).mock(return_value=httpx.Response(404, headers={"content-type": "text/html"}))
        async with httpx.AsyncClient() as client:
            result = await check_external(pdf_url, client)
        assert result.classification == "external-dead"
        assert result.resolvable is False


async def test_blocked_json_by_url_extension_is_not_resolvable():
    # Live finding: an S3-hosted .json object returns 403 with content-type application/xml
    # (the S3 error body, not the JSON itself) — and even when Olostep does get through, it
    # returns every content field null for a non-HTML resource. Never worth a credit.
    json_url = "https://olostep-storage.s3.us-east-1.amazonaws.com/data.json"
    with respx.mock:
        respx.head(json_url).mock(return_value=httpx.Response(403, headers={"content-type": "application/xml"}))
        respx.get(json_url).mock(return_value=httpx.Response(403, headers={"content-type": "application/xml"}))
        async with httpx.AsyncClient() as client:
            result = await check_external(json_url, client)
        assert result.classification == "external-blocked"
        assert result.resolvable is False


async def test_live_json_by_url_extension_is_skipped_non_html_even_with_html_content_type():
    # The URL-extension gate must win even if the origin's content-type header lies
    # (some servers serve JSON with a text/html content-type on success too).
    json_url = "https://olostep-storage.s3.us-east-1.amazonaws.com/data.json"
    with respx.mock:
        respx.head(json_url).mock(return_value=httpx.Response(200, headers={"content-type": "text/html"}))
        async with httpx.AsyncClient() as client:
            result = await check_external(json_url, client)
        assert result.classification == "skipped-non-html"


async def test_concurrency_never_exceeds_configured_ceiling():
    max_concurrent_seen = 0
    current_concurrent = 0
    lock = asyncio.Lock()

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/html"}
        is_redirect = False

    class FakeClient:
        async def request(self, method, url, **kwargs):
            nonlocal max_concurrent_seen, current_concurrent
            async with lock:
                current_concurrent += 1
                max_concurrent_seen = max(max_concurrent_seen, current_concurrent)
            await asyncio.sleep(0.01)
            async with lock:
                current_concurrent -= 1
            return FakeResponse()

    urls = [f"https://example.com/page{i}" for i in range(20)]
    await check_many_external(urls, FakeClient(), concurrency=3)
    assert max_concurrent_seen <= 3
