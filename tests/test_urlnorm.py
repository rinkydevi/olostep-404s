from olostep_link_checker.urlnorm import resolve

BASE = "https://www.olostep.com/blog/some-post"


def test_relative_path_resolves_to_absolute():
    r = resolve("/careers", BASE)
    assert r.normalized == "https://www.olostep.com/careers"
    assert r.original == "https://www.olostep.com/careers"
    assert r.skip_reason is None


def test_protocol_relative_resolves_using_base_scheme():
    r = resolve("//cdn.example.com/asset.js", "https://www.olostep.com/")
    assert r.normalized == "https://cdn.example.com/asset.js"


def test_trailing_slash_stripped_on_non_root_path():
    r = resolve("https://x.com/careers/", BASE)
    assert r.normalized == "https://x.com/careers"


def test_bare_domain_root_keeps_trailing_slash():
    r = resolve("https://x.com/", BASE)
    assert r.normalized == "https://x.com/"


def test_query_string_stripped_for_comparison_but_kept_in_original():
    r = resolve("https://x.com/careers?utm_source=abc", BASE)
    assert r.normalized == "https://x.com/careers"
    assert r.original == "https://x.com/careers?utm_source=abc"


def test_fragment_stripped_for_comparison_but_kept_in_original():
    r = resolve("https://x.com/careers#team", BASE)
    assert r.normalized == "https://x.com/careers"
    assert r.original == "https://x.com/careers#team"


def test_query_and_fragment_both_present():
    r = resolve("https://x.com/careers?utm=1#team", BASE)
    assert r.normalized == "https://x.com/careers"
    assert r.original == "https://x.com/careers?utm=1#team"


def test_already_absolute_url_passes_through_unchanged():
    r = resolve("https://x.com/careers", BASE)
    assert r.normalized == "https://x.com/careers"
    assert r.original == "https://x.com/careers"


def test_mailto_link_is_skipped_not_a_page_link():
    r = resolve("mailto:info@olostep.com", BASE)
    assert r.normalized is None
    assert r.skip_reason == "non-page-link"


def test_tel_link_is_skipped():
    r = resolve("tel:+15551234567", BASE)
    assert r.normalized is None
    assert r.skip_reason == "non-page-link"


def test_javascript_link_is_skipped():
    r = resolve("javascript:void(0)", BASE)
    assert r.normalized is None
    assert r.skip_reason == "non-page-link"


def test_scheme_and_host_lowercased_path_case_preserved():
    r = resolve("HTTPS://WWW.Olostep.COM/Careers", BASE)
    assert r.normalized == "https://www.olostep.com/Careers"


def test_non_http_schemes_are_skipped_not_treated_as_targets():
    # IDE/app deep-links and other schemes must never become checkable targets.
    for href in ["cursor://anysphere.cursor-deeplink/x", "vscode://file/x", "ftp://x.com/f", "data:text/plain,hi", "slack://open"]:
        r = resolve(href, BASE)
        assert r.normalized is None, f"{href} should be skipped"
        assert r.skip_reason == "non-page-link"


def test_malformed_url_is_skipped_not_raised():
    r = resolve("http://[invalid", BASE)
    assert r.normalized is None
    assert r.skip_reason == "malformed"


def test_empty_href_is_skipped():
    r = resolve("", BASE)
    assert r.normalized is None
    assert r.skip_reason == "malformed"
