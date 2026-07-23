from pathlib import Path

from olostep_link_checker.budget import Budget
from olostep_link_checker.cli import run_pipeline
from olostep_link_checker.http_fetcher import PageFetch

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


HOME_HTML = """
<html><head><title>Home</title></head>
<body>
<a href="/fine">Fine</a>
<a href="/broken">Broken</a>
<a href="/soft-broken">Soft Broken</a>
<a href="/unlisted-404">Unlisted 404</a>
<a href="https://external.com/dead">External Dead</a>
</body></html>
"""

# The reachable set Maps returns. Note /broken and /soft-broken ARE reachable per Maps
# (Maps can't tell a soft-404 from a real page), and /unlisted-404 is NOT in the set.
MAPS_URLS = [
    "https://x.com/",
    "https://x.com/fine",
    "https://x.com/broken",
    "https://x.com/soft-broken",
]

PAGES = {
    "https://x.com/": PageFetch("https://x.com/", 200, HOME_HTML),
    "https://x.com/fine": PageFetch(
        "https://x.com/fine",
        200,
        "<html><head><title>Fine</title></head><body><h1>A perfectly fine page</h1>"
        "<p>" + ("This page has plenty of server-rendered content and reads as a normal healthy page. " * 4) + "</p></body></html>",
    ),
    # Honest origin: a real 404 status, no scrape needed.
    "https://x.com/broken": PageFetch("https://x.com/broken", 404, "<html><body>gone</body></html>"),
    # Genuine soft-404: returns 200 but body matches the fingerprint (the rare case).
    "https://x.com/soft-broken": PageFetch("https://x.com/soft-broken", 200, load("soft_404_nextjs.html")),
    # Referenced by home, NOT in Maps set -> gets a fallback GET -> honest 404.
    "https://x.com/unlisted-404": PageFetch("https://x.com/unlisted-404", 404, "<html><body>nope</body></html>"),
}


async def http_get_fn(url):
    if url in PAGES:
        return PAGES[url]
    raise AssertionError(f"unexpected http GET: {url}")


async def canary_get_fn(url):
    # canary URL returns a real 404 whose body carries the fingerprint (verified live)
    return PageFetch(url, 404, load("soft_404_nextjs.html"))


class FakeExternalResult:
    def __init__(self, classification, status_code=None, resolvable=True):
        self.classification = classification
        self.status_code = status_code
        self.resolvable = resolvable


async def external_check_fn(url):
    if url == "https://external.com/dead":
        return FakeExternalResult("external-dead", 404)
    return FakeExternalResult("ok", 200)


async def scrape_fn(url):
    if url == "https://external.com/dead":
        # v3 escalates the external-dead bucket too (PRODUCTION_PLAN.md §10.2/§10.6) —
        # this fixture's dead link stays genuinely dead under Olostep re-verification.
        return 200, "<html><head><title>404 Not Found</title></head><body><h1>404</h1></body></html>"
    raise AssertionError(f"no JS-shell page in this fixture; scrape must not be called for {url}")


async def noop_sleep(seconds):
    pass


def base_kwargs(runs_dir, run_id="2026-07-23T00:00:00Z", budget=None, **overrides):
    kwargs = dict(
        create_map_fn=lambda: MAPS_URLS,
        http_get_fn=http_get_fn,
        canary_get_fn=canary_get_fn,
        canary_url="https://x.com/this-page-definitely-does-not-exist-404-test",
        exclude_patterns=[],
        external_check_fn=external_check_fn,
        scrape_fn=scrape_fn,
        budget=budget or Budget(unlimited=True),
        runs_dir=runs_dir,
        run_id=run_id,
        concurrency=5,
        sleep_fn=noop_sleep,
    )
    kwargs.update(overrides)
    return kwargs


async def test_happy_path_classifies_from_honest_http_status_no_scrape_credits(tmp_path):
    outcome = await run_pipeline(**base_kwargs(tmp_path))

    assert outcome["exit_code"] == 0
    by_url = {r["url"]: r for r in outcome["run"]["results"]}
    assert by_url["https://x.com/fine"]["classification"] == "ok"
    assert by_url["https://x.com/broken"]["classification"] == "hard-404"
    assert by_url["https://x.com/soft-broken"]["classification"] == "soft-404"
    assert by_url["https://x.com/unlisted-404"]["classification"] == "hard-404"
    assert by_url["https://x.com/unlisted-404"]["not_in_sitemap"] is True
    assert by_url["https://external.com/dead"]["classification"] == "external-dead"
    assert by_url["https://external.com/dead"]["confidence"] == "browser-verified"
    assert by_url["https://external.com/dead"]["source_pages"] == ["https://x.com/"]
    # Internal status/harvest still spends ZERO Olostep credits (v2.0's core result).
    # v3 spends credits only on the one ambiguous external target, to confirm it.
    assert outcome["run"]["credits_consumed"] == 1


async def test_canary_failure_only_degrades_soft_404_trust_rest_of_run_is_unaffected(tmp_path):
    # A failed canary must NOT abort the run — hard-404 (status-code based) and every
    # external result (a completely separate fingerprint in external_resolver.py) don't
    # depend on the internal soft-404 fingerprint at all, so they're unaffected. Only
    # soft-404 detection itself is degraded: an unproven fingerprint is not trusted
    # either way, so a genuine soft-404 page reads as "ok" rather than risking a guess.
    page_calls = []

    async def tracking_http_get_fn(url):
        page_calls.append(url)
        return await http_get_fn(url)

    async def broken_canary_get_fn(url):
        return PageFetch(url, 404, "<html><head><title>Not Found</title></head><body><h1>Oops</h1></body></html>")

    outcome = await run_pipeline(
        **base_kwargs(tmp_path, http_get_fn=tracking_http_get_fn, canary_get_fn=broken_canary_get_fn)
    )

    assert outcome["exit_code"] == 2
    assert outcome["report"]["run_failed"] is False
    assert outcome["report"]["canary"]["passed"] is False
    assert page_calls != []  # the run proceeds; pages ARE fetched despite the canary failure

    by_url = {r["url"]: r for r in outcome["run"]["results"]}
    assert by_url["https://x.com/broken"]["classification"] == "hard-404"  # unaffected
    assert by_url["https://x.com/soft-broken"]["classification"] == "ok"  # fingerprint untrusted, not guessed
    assert by_url["https://external.com/dead"]["classification"] == "external-dead"  # unaffected


async def test_js_shell_page_is_escalated_to_scrape_and_costs_one_credit(tmp_path):
    shell = '<html><head><title>App</title></head><body><div id="__next"></div></body></html>'
    scraped_html = '<html><body><a href="/deep-link">Deep Link</a><p>Real content revealed after JS.</p></body></html>'

    pages = {
        "https://x.com/": PageFetch("https://x.com/", 200, shell),
    }

    async def shell_http_get_fn(url):
        if url in pages:
            return pages[url]
        if url == "https://x.com/deep-link":
            return PageFetch(url, 200, "<html><body><h1>A real deep page with plenty of words.</h1></body></html>")
        raise AssertionError(f"unexpected GET: {url}")

    scrape_calls = []

    async def counting_scrape_fn(url):
        scrape_calls.append(url)
        return 200, scraped_html

    outcome = await run_pipeline(
        **base_kwargs(
            tmp_path,
            create_map_fn=lambda: ["https://x.com/"],
            http_get_fn=shell_http_get_fn,
            scrape_fn=counting_scrape_fn,
        )
    )

    assert scrape_calls == ["https://x.com/"]
    assert outcome["run"]["credits_consumed"] == 1
    # the deep link only visible after JS render was harvested and checked
    by_url = {r["url"]: r for r in outcome["run"]["results"]}
    assert "https://x.com/deep-link" in by_url


async def test_js_shell_escalation_respects_budget_ceiling(tmp_path):
    shell = '<html><head><title>App</title></head><body><div id="__next"></div></body></html>'

    async def shell_http_get_fn(url):
        return PageFetch(url, 200, shell)

    scrape_calls = []

    async def counting_scrape_fn(url):
        scrape_calls.append(url)
        return 200, "<html><body><p>rendered content with enough words to be real now.</p></body></html>"

    outcome = await run_pipeline(
        **base_kwargs(
            tmp_path,
            create_map_fn=lambda: ["https://x.com/a", "https://x.com/b", "https://x.com/c"],
            http_get_fn=shell_http_get_fn,
            scrape_fn=counting_scrape_fn,
            budget=Budget(ceiling=1),
        )
    )

    assert len(scrape_calls) == 1  # only one escalation fit in the budget
    assert outcome["run"]["credits_consumed"] == 1
    assert outcome["exit_code"] == 1  # partial: budget stopped further escalation


async def test_escalation_scrape_failure_does_not_crash_the_run(tmp_path):
    shell = '<html><head><title>App</title></head><body><div id="__next"></div></body></html>'

    async def shell_http_get_fn(url):
        return PageFetch(url, 200, shell)

    async def failing_scrape_fn(url):
        raise TimeoutError("olostep scrape timed out")

    outcome = await run_pipeline(
        **base_kwargs(
            tmp_path,
            create_map_fn=lambda: ["https://x.com/a"],
            http_get_fn=shell_http_get_fn,
            scrape_fn=failing_scrape_fn,
        )
    )

    # run completes with the plain-HTTP result preserved rather than crashing
    assert outcome["run"] is not None
    by_url = {r["url"]: r for r in outcome["run"]["results"]}
    assert "https://x.com/a" in by_url


async def test_external_checks_run_with_bounded_concurrency_not_serially(tmp_path):
    import asyncio

    links = "".join(f'<a href="https://ext{i}.com/">e{i}</a>' for i in range(20))
    home = f"<html><body>{links}<p>a healthy page with lots of outbound links and words.</p></body></html>"

    async def http_get_fn2(url):
        return PageFetch(url, 200, home)

    max_seen = 0
    current = 0
    lock = asyncio.Lock()

    async def concurrent_external_check_fn(url):
        nonlocal max_seen, current
        async with lock:
            current += 1
            max_seen = max(max_seen, current)
        await asyncio.sleep(0.02)
        async with lock:
            current -= 1
        return FakeExternalResult("ok", 200)

    await run_pipeline(
        **base_kwargs(
            tmp_path,
            create_map_fn=lambda: ["https://x.com/"],
            http_get_fn=http_get_fn2,
            external_check_fn=concurrent_external_check_fn,
            concurrency=6,
        )
    )
    assert 1 < max_seen <= 6  # ran concurrently, but stayed within the ceiling


async def test_external_check_failure_does_not_crash_the_run(tmp_path):
    home = '<html><body><a href="https://external.com/weird">Weird</a><p>plenty of real words here on this page to look healthy.</p></body></html>'

    async def http_get_fn2(url):
        if url == "https://x.com/":
            return PageFetch(url, 200, home)
        raise AssertionError(url)

    async def exploding_external_check_fn(url):
        raise RuntimeError("unexpected protocol or transport error")

    outcome = await run_pipeline(
        **base_kwargs(
            tmp_path,
            create_map_fn=lambda: ["https://x.com/"],
            http_get_fn=http_get_fn2,
            external_check_fn=exploding_external_check_fn,
        )
    )

    assert outcome["run"] is not None  # a bad external target must not abort the whole run
    by_url = {r["url"]: r for r in outcome["run"]["results"]}
    assert by_url["https://external.com/weird"]["classification"] == "external-check-error"


async def test_placeholder_domain_links_are_skipped_without_a_network_call(tmp_path):
    home = (
        '<html><body>'
        '<a href="https://example.com/robots.txt">Example</a>'
        '<a href="https://yourdomain.com/robots.txt">Your domain</a>'
        '<p>plenty of real healthy words on this page for the shell heuristic.</p>'
        '</body></html>'
    )

    async def http_get_fn2(url):
        return PageFetch(url, 200, home)

    async def exploding_external_check_fn(url):
        raise AssertionError(f"placeholder domains must never be network-checked: {url}")

    outcome = await run_pipeline(
        **base_kwargs(
            tmp_path,
            create_map_fn=lambda: ["https://x.com/"],
            http_get_fn=http_get_fn2,
            external_check_fn=exploding_external_check_fn,
        )
    )

    by_url = {r["url"]: r for r in outcome["run"]["results"]}
    assert by_url["https://example.com/robots.txt"]["classification"] == "skipped-placeholder-domain"
    assert by_url["https://yourdomain.com/robots.txt"]["classification"] == "skipped-placeholder-domain"


async def test_bootstrap_run_frames_everything_as_baseline(tmp_path):
    outcome = await run_pipeline(**base_kwargs(tmp_path))
    report = outcome["report"]
    assert len(report["new_baseline"]) > 0
    assert report["newly_broken"] == []


async def test_rerun_with_identical_fixtures_is_idempotent(tmp_path):
    first = await run_pipeline(**base_kwargs(tmp_path, run_id="2026-07-23T00:00:00Z"))
    second = await run_pipeline(**base_kwargs(tmp_path, run_id="2026-07-24T00:00:00Z"))

    def classifications(outcome):
        return {r["url"]: r["classification"] for r in outcome["run"]["results"]}

    assert classifications(first) == classifications(second)
