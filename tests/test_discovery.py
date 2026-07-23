import pytest

from olostep_link_checker.discovery import discover_urls
from olostep_link_checker.retry import RetryExhausted

EXCLUDE_PATTERNS = ["/dashboard/**", "/auth", "/playground"]

MIXED_URLS = [
    "https://www.olostep.com/",
    "https://www.olostep.com/careers",
    "https://www.olostep.com/dashboard/monitors",
    "https://www.olostep.com/dashboard/playground",
    "https://www.olostep.com/auth",
    "https://www.olostep.com/playground",
    "https://docs.olostep.com/get-started/welcome",
    "https://status.olostep.com/",
]


def test_excluded_pattern_urls_are_removed_with_zero_false_negatives():
    urls = discover_urls(lambda: MIXED_URLS, EXCLUDE_PATTERNS)
    assert "https://www.olostep.com/dashboard/monitors" not in urls
    assert "https://www.olostep.com/dashboard/playground" not in urls
    assert "https://www.olostep.com/auth" not in urls
    assert "https://www.olostep.com/playground" not in urls


def test_in_scope_urls_are_kept():
    urls = discover_urls(lambda: MIXED_URLS, EXCLUDE_PATTERNS)
    assert urls == {
        "https://www.olostep.com/",
        "https://www.olostep.com/careers",
        "https://docs.olostep.com/get-started/welcome",
        "https://status.olostep.com/",
    }


def test_all_configured_subdomains_are_included():
    urls = discover_urls(lambda: MIXED_URLS, EXCLUDE_PATTERNS)
    hosts = {u.split("/")[2] for u in urls}
    assert hosts == {"www.olostep.com", "docs.olostep.com", "status.olostep.com"}


def test_create_map_transient_error_is_retried_not_swallowed():
    calls = {"count": 0}

    def flaky_create_map():
        calls["count"] += 1
        if calls["count"] < 3:
            raise ConnectionError("transient")
        return MIXED_URLS

    urls = discover_urls(
        flaky_create_map, EXCLUDE_PATTERNS, max_attempts=5, sleep_fn=lambda s: None
    )
    assert calls["count"] == 3
    assert "https://www.olostep.com/careers" in urls


def test_create_map_exhausting_retries_raises_not_silently_swallowed():
    def always_fails():
        raise ConnectionError("permanently down")

    with pytest.raises(RetryExhausted):
        discover_urls(always_fails, EXCLUDE_PATTERNS, max_attempts=3, sleep_fn=lambda s: None)
