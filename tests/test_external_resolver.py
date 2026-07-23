from olostep_link_checker.external_resolver import RESOLVABLE_CLASSIFICATIONS, resolve_external
from olostep_link_checker.olostep_client import OlostepAPIError

REAL_RFC_HTML = (
    "<html><head><title>RFC 9110: HTTP Semantics</title></head><body>"
    "<h1>RFC 9110</h1><p>" + ("This is real, substantial spec content. " * 40) + "</p>"
    "</body></html>"
)

# A live pilot finding (PRODUCTION_PLAN.md §10.6): third-party 404 templates vary in
# length and don't always say "404" in the body — but the <title>/<h1> reliably do.
THIRD_PARTY_404_HTML = (
    "<html><head><title>Page Not Found | ExampleCo</title></head>"
    "<body><h1>404</h1><p>Sorry, we could not find that page.</p></body></html>"
)

# A real dead page can also be verbose (a full site chrome around a "not found" block) —
# the fingerprint must win over length, never the other way around.
VERBOSE_404_HTML = (
    "<html><head><title>Oops! This page could not be found</title></head><body>"
    "<nav>Home About Contact</nav><h1>404 Error</h1>"
    + "<p>" + ("Site footer boilerplate and navigation text. " * 30) + "</p>"
    "</body></html>"
)

THIN_AMBIGUOUS_HTML = "<html><head><title>App</title></head><body><div id='root'></div></body></html>"


async def test_blocked_link_with_real_content_resolves_to_ok():
    async def scrape_fn(url):
        return 200, REAL_RFC_HTML

    result = await resolve_external("https://rfc-editor.org/rfc/rfc9110", scrape_fn)
    assert result.classification == "ok"
    assert result.confidence == "browser-verified"


async def test_dead_link_with_404_fingerprint_stays_dead():
    async def scrape_fn(url):
        return 200, THIRD_PARTY_404_HTML

    result = await resolve_external("https://example.com/gone", scrape_fn)
    assert result.classification == "external-dead"
    assert result.confidence == "browser-verified"


async def test_fingerprint_wins_over_length_even_on_a_verbose_404_page():
    async def scrape_fn(url):
        return 200, VERBOSE_404_HTML

    result = await resolve_external("https://example.com/verbose-gone", scrape_fn)
    assert result.classification == "external-dead"


async def test_thin_content_with_no_fingerprint_stays_unverified_not_guessed():
    async def scrape_fn(url):
        return 200, THIN_AMBIGUOUS_HTML

    result = await resolve_external("https://example.com/js-shell", scrape_fn)
    assert result.classification == "unverified"
    assert result.confidence == "unverified"


async def test_olostep_itself_failing_is_external_unreachable_not_dead_or_ok():
    async def failing_scrape_fn(url):
        raise RuntimeError("olostep API error: 504")

    result = await resolve_external("https://example.com/whatever", failing_scrape_fn)
    assert result.classification == "external-unreachable"
    assert result.confidence == "unverified"


async def test_olostep_504_timeout_is_external_unreachable():
    async def failing_scrape_fn(url):
        raise OlostepAPIError("Olostep API error: retries exhausted", status_code=504, code="scrape_poll_timeout")

    result = await resolve_external("https://www.rfc-editor.org/rfc/rfc6585", failing_scrape_fn)
    assert result.classification == "external-unreachable"
    assert result.confidence == "unverified"


async def test_olostep_approval_required_is_external_provider_unsupported():
    # Live-verified (v3.1): LinkedIn and Reddit both return this exact error on every
    # scrape attempt on this account — a durable policy block, not a technical failure —
    # so it must be labeled distinctly from a generic "Olostep couldn't reach it".
    async def policy_blocked_scrape_fn(url):
        raise OlostepAPIError(
            "This website is not currently supported.", status_code=403, code="approval_required"
        )

    result = await resolve_external("https://www.linkedin.com/in/jasonscui", policy_blocked_scrape_fn)
    assert result.classification == "external-provider-unsupported"
    assert result.confidence == "unverified"


async def test_empty_html_with_no_fingerprint_stays_unverified():
    async def scrape_fn(url):
        return 200, ""

    result = await resolve_external("https://example.com/empty", scrape_fn)
    assert result.classification == "unverified"


def test_resolvable_classifications_cover_blocked_timeout_and_dead():
    assert RESOLVABLE_CLASSIFICATIONS == {"external-blocked", "external-timeout", "external-dead"}
