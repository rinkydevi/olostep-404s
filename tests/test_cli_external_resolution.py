from datetime import datetime, timezone

from olostep_link_checker.budget import Budget
from olostep_link_checker.cli import run_pipeline
from olostep_link_checker.http_fetcher import PageFetch
from olostep_link_checker.olostep_client import OlostepAPIError
from olostep_link_checker.verdict_cache import VerdictCache

HOME_HTML = (
    '<html><body><a href="https://ext.olostep-test.dev/target">Target</a>'
    "<p>plenty of healthy server-rendered words on this home page for the shell heuristic.</p>"
    "</body></html>"
)

REAL_CONTENT_HTML = (
    "<html><head><title>Real Page</title></head><body>"
    "<h1>Real Page</h1><p>" + ("Substantial real content rendered by the browser. " * 20) + "</p>"
    "</body></html>"
)

DEAD_FINGERPRINT_HTML = (
    "<html><head><title>Page Not Found</title></head><body><h1>404</h1></body></html>"
)


class FakeExternalResult:
    def __init__(self, classification, status_code=None, resolvable=True):
        self.classification = classification
        self.status_code = status_code
        self.resolvable = resolvable


async def http_get_fn(url):
    return PageFetch(url, 200, HOME_HTML)


_CANARY_HTML = (
    '<html><head><title>404: This page could not be found.</title></head>'
    '<body><h1 class="next-error-h1">404</h1></body></html>'
)


async def canary_get_fn(url):
    return PageFetch(url, 404, _CANARY_HTML)


async def noop_sleep(seconds):
    pass


def base_kwargs(runs_dir, run_id="2026-07-23T00:00:00Z", budget=None, **overrides):
    kwargs = dict(
        create_map_fn=lambda: ["https://x.com/"],
        http_get_fn=http_get_fn,
        canary_get_fn=canary_get_fn,
        canary_url="https://x.com/this-page-definitely-does-not-exist-404-test",
        exclude_patterns=[],
        external_check_fn=lambda url: _unused(),
        scrape_fn=lambda url: _unused(),
        budget=budget or Budget(unlimited=True),
        runs_dir=runs_dir,
        run_id=run_id,
        concurrency=5,
        sleep_fn=noop_sleep,
    )
    kwargs.update(overrides)
    return kwargs


async def _unused(*a, **k):
    raise AssertionError("must be overridden per test")


async def test_blocked_external_is_escalated_and_reclassified_ok_with_confidence(tmp_path):
    async def external_check_fn(url):
        return FakeExternalResult("external-blocked", 403)

    scrape_calls = []

    async def scrape_fn(url):
        scrape_calls.append(url)
        return 200, REAL_CONTENT_HTML

    outcome = await run_pipeline(
        **base_kwargs(tmp_path, external_check_fn=external_check_fn, scrape_fn=scrape_fn)
    )

    assert scrape_calls == ["https://ext.olostep-test.dev/target"]
    by_url = {r["url"]: r for r in outcome["run"]["results"]}
    entry = by_url["https://ext.olostep-test.dev/target"]
    assert entry["classification"] == "ok"
    assert entry["confidence"] == "browser-verified"
    assert outcome["run"]["credits_consumed"] == 1


async def test_dead_external_escalated_and_stays_dead_when_fingerprint_matches(tmp_path):
    async def external_check_fn(url):
        return FakeExternalResult("external-dead", 404)

    async def scrape_fn(url):
        return 200, DEAD_FINGERPRINT_HTML

    outcome = await run_pipeline(
        **base_kwargs(tmp_path, external_check_fn=external_check_fn, scrape_fn=scrape_fn)
    )

    by_url = {r["url"]: r for r in outcome["run"]["results"]}
    entry = by_url["https://ext.olostep-test.dev/target"]
    assert entry["classification"] == "external-dead"
    assert entry["confidence"] == "browser-verified"


async def test_dead_external_reclassified_ok_when_olostep_finds_real_content(tmp_path):
    # The §10.6 finding: plain HTTP can be soft-404'd by anti-bot defenses on a
    # reputable domain even though the page is genuinely alive.
    async def external_check_fn(url):
        return FakeExternalResult("external-dead", 404)

    async def scrape_fn(url):
        return 200, REAL_CONTENT_HTML

    outcome = await run_pipeline(
        **base_kwargs(tmp_path, external_check_fn=external_check_fn, scrape_fn=scrape_fn)
    )

    by_url = {r["url"]: r for r in outcome["run"]["results"]}
    assert by_url["https://ext.olostep-test.dev/target"]["classification"] == "ok"


async def test_olostep_unreachable_during_resolution_is_external_unreachable(tmp_path):
    async def external_check_fn(url):
        return FakeExternalResult("external-blocked", 403)

    async def failing_scrape_fn(url):
        raise RuntimeError("olostep API error: 504")

    outcome = await run_pipeline(
        **base_kwargs(tmp_path, external_check_fn=external_check_fn, scrape_fn=failing_scrape_fn)
    )

    by_url = {r["url"]: r for r in outcome["run"]["results"]}
    entry = by_url["https://ext.olostep-test.dev/target"]
    assert entry["classification"] == "external-unreachable"
    assert entry["confidence"] == "unverified"
    # v3.1: Olostep's own failure to reach the page is not the plain-HTTP verdict being
    # overwritten — the pre-escalation status_code is still the last real signal we have.
    assert entry["status_code"] == 403


async def test_olostep_policy_block_is_external_provider_unsupported(tmp_path):
    # Live-verified (v3.1): LinkedIn and Reddit both return this on every scrape attempt
    # on this account — a durable policy block, distinct from a generic unreachable.
    async def external_check_fn(url):
        return FakeExternalResult("external-blocked", 403)

    async def policy_blocked_scrape_fn(url):
        raise OlostepAPIError(
            "This website is not currently supported.", status_code=403, code="approval_required"
        )

    outcome = await run_pipeline(
        **base_kwargs(tmp_path, external_check_fn=external_check_fn, scrape_fn=policy_blocked_scrape_fn)
    )

    by_url = {r["url"]: r for r in outcome["run"]["results"]}
    entry = by_url["https://ext.olostep-test.dev/target"]
    assert entry["classification"] == "external-provider-unsupported"
    assert entry["confidence"] == "unverified"
    assert entry["status_code"] == 403


async def test_non_html_resource_is_never_escalated_even_when_dead_or_blocked(tmp_path):
    # v3.1: a dead/blocked PDF or JSON resource must keep its plain-HTTP verdict as-is —
    # escalating it to Olostep's HTML renderer only makes things worse (live-verified:
    # 504 timeout on a real PDF, null content on a real JSON file).
    pdf_home_html = (
        '<html><body><a href="https://ext.olostep-test.dev/paper.pdf">Paper</a>'
        "<p>plenty of healthy server-rendered words on this home page for the shell heuristic.</p>"
        "</body></html>"
    )

    async def http_get_fn2(url):
        return PageFetch(url, 200, pdf_home_html)

    async def external_check_fn(url):
        return FakeExternalResult("external-dead", 404, resolvable=False)

    async def scrape_fn(url):
        raise AssertionError("a non-HTML resource must never be escalated to Olostep")

    outcome = await run_pipeline(
        **base_kwargs(tmp_path, http_get_fn=http_get_fn2, external_check_fn=external_check_fn, scrape_fn=scrape_fn)
    )

    assert outcome["run"]["credits_consumed"] == 0
    by_url = {r["url"]: r for r in outcome["run"]["results"]}
    entry = by_url["https://ext.olostep-test.dev/paper.pdf"]
    assert entry["classification"] == "external-dead"
    assert entry["status_code"] == 404
    assert entry["confidence"] == "confirmed"


async def test_resolution_respects_budget_ceiling(tmp_path):
    home = "".join(f'<a href="https://ext{i}.olostep-test.dev/">e{i}</a>' for i in range(3))
    home = f"<html><body>{home}<p>plenty of healthy words on this page for the shell heuristic.</p></body></html>"

    async def http_get_fn2(url):
        return PageFetch(url, 200, home)

    async def external_check_fn(url):
        return FakeExternalResult("external-blocked", 403)

    scrape_calls = []

    async def scrape_fn(url):
        scrape_calls.append(url)
        return 200, REAL_CONTENT_HTML

    outcome = await run_pipeline(
        **base_kwargs(
            tmp_path,
            http_get_fn=http_get_fn2,
            external_check_fn=external_check_fn,
            scrape_fn=scrape_fn,
            budget=Budget(ceiling=1),
        )
    )

    assert len(scrape_calls) == 1
    assert outcome["exit_code"] == 1  # partial: budget stopped further resolution


async def test_cached_verdict_is_reused_without_spending_a_credit(tmp_path):
    async def external_check_fn(url):
        return FakeExternalResult("external-blocked", 403)

    scrape_calls = []

    async def scrape_fn(url):
        scrape_calls.append(url)
        return 200, REAL_CONTENT_HTML

    cache = VerdictCache.load(tmp_path / "verdicts.json")
    cache.put(
        "https://ext.olostep-test.dev/target",
        classification="ok",
        confidence="browser-verified",
        resolved_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
    )

    outcome = await run_pipeline(
        **base_kwargs(
            tmp_path,
            external_check_fn=external_check_fn,
            scrape_fn=scrape_fn,
            verdict_cache=cache,
            verdict_staleness_days=14,
            now_fn=lambda: datetime(2026, 7, 23, tzinfo=timezone.utc),
        )
    )

    assert scrape_calls == []  # cache hit, no escalation needed
    assert outcome["run"]["credits_consumed"] == 0
    by_url = {r["url"]: r for r in outcome["run"]["results"]}
    assert by_url["https://ext.olostep-test.dev/target"]["classification"] == "ok"
    assert by_url["https://ext.olostep-test.dev/target"]["confidence"] == "browser-verified"


async def test_stale_cached_verdict_is_ignored_and_re_resolved(tmp_path):
    async def external_check_fn(url):
        return FakeExternalResult("external-blocked", 403)

    scrape_calls = []

    async def scrape_fn(url):
        scrape_calls.append(url)
        return 200, REAL_CONTENT_HTML

    cache = VerdictCache.load(tmp_path / "verdicts.json")
    cache.put(
        "https://ext.olostep-test.dev/target",
        classification="external-dead",
        confidence="browser-verified",
        resolved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    outcome = await run_pipeline(
        **base_kwargs(
            tmp_path,
            external_check_fn=external_check_fn,
            scrape_fn=scrape_fn,
            verdict_cache=cache,
            verdict_staleness_days=14,
            now_fn=lambda: datetime(2026, 7, 23, tzinfo=timezone.utc),
        )
    )

    assert scrape_calls == ["https://ext.olostep-test.dev/target"]
    by_url = {r["url"]: r for r in outcome["run"]["results"]}
    assert by_url["https://ext.olostep-test.dev/target"]["classification"] == "ok"


async def test_resolution_failure_does_not_crash_the_run(tmp_path):
    async def external_check_fn(url):
        return FakeExternalResult("external-blocked", 403)

    async def exploding_scrape_fn(url):
        raise RuntimeError("boom")

    outcome = await run_pipeline(
        **base_kwargs(tmp_path, external_check_fn=external_check_fn, scrape_fn=exploding_scrape_fn)
    )

    assert outcome["run"] is not None
    by_url = {r["url"]: r for r in outcome["run"]["results"]}
    assert by_url["https://ext.olostep-test.dev/target"]["classification"] == "external-unreachable"


async def test_already_ok_external_is_never_escalated(tmp_path):
    async def external_check_fn(url):
        return FakeExternalResult("ok", 200)

    async def scrape_fn(url):
        raise AssertionError("an already-ok external must never be escalated")

    outcome = await run_pipeline(
        **base_kwargs(tmp_path, external_check_fn=external_check_fn, scrape_fn=scrape_fn)
    )

    assert outcome["run"]["credits_consumed"] == 0
    by_url = {r["url"]: r for r in outcome["run"]["results"]}
    assert by_url["https://ext.olostep-test.dev/target"]["classification"] == "ok"
    assert by_url["https://ext.olostep-test.dev/target"]["confidence"] == "confirmed"


async def test_resolved_verdict_clears_the_stale_pre_escalation_status_code(tmp_path):
    # Live-run finding (2026-07-23): a link plain HTTP saw as 403 got escalated and
    # fingerprint-confirmed dead by Olostep — but the report kept showing "(403)" next
    # to "external-dead", implying 403 itself proved deadness. That contradicts this
    # project's own rule (403 != dead) and is just stale display state from before
    # escalation ran. The status shown for a resolved verdict must not imply
    # a status code we no longer trust decided the classification.
    async def external_check_fn(url):
        return FakeExternalResult("external-blocked", 403)

    async def scrape_fn(url):
        return 200, DEAD_FINGERPRINT_HTML

    outcome = await run_pipeline(
        **base_kwargs(tmp_path, external_check_fn=external_check_fn, scrape_fn=scrape_fn)
    )

    by_url = {r["url"]: r for r in outcome["run"]["results"]}
    entry = by_url["https://ext.olostep-test.dev/target"]
    assert entry["classification"] == "external-dead"
    assert entry["status_code"] is None


async def test_confirmed_internal_classifications_have_confirmed_confidence(tmp_path):
    async def external_check_fn(url):
        return FakeExternalResult("ok", 200)

    async def scrape_fn(url):
        raise AssertionError("no JS-shell page in this fixture")

    outcome = await run_pipeline(
        **base_kwargs(tmp_path, external_check_fn=external_check_fn, scrape_fn=scrape_fn)
    )

    by_url = {r["url"]: r for r in outcome["run"]["results"]}
    assert by_url["https://x.com/"]["confidence"] == "confirmed"
