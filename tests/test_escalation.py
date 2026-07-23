from olostep_link_checker.escalation import needs_js_render


def test_healthy_page_with_links_does_not_need_escalation():
    html = "<html><body>" + "".join(f'<a href="/p{i}">Link {i}</a>' for i in range(10)) + "<p>Lots of real content here that a server rendered.</p></body></html>"
    assert needs_js_render(200, html) is False


def test_near_empty_js_shell_with_no_links_needs_escalation():
    shell = '<html><head><title>App</title></head><body><div id="__next"></div><script src="/app.js"></script></body></html>'
    assert needs_js_render(200, shell) is True


def test_non_200_page_never_escalates():
    # a 404/redirect is already a definitive answer; no point spending a scrape credit
    shell = '<html><body><div id="__next"></div></body></html>'
    assert needs_js_render(404, shell) is False
    assert needs_js_render(500, shell) is False


def test_empty_html_at_200_needs_escalation():
    assert needs_js_render(200, "") is True


def test_page_with_text_but_no_links_does_not_escalate():
    # a real content page (e.g. a legal page) can legitimately have few/no links
    html = "<html><body><h1>Terms of Service</h1>" + "<p>" + ("word " * 300) + "</p></body></html>"
    assert needs_js_render(200, html) is False


def test_none_status_never_escalates():
    assert needs_js_render(None, "<html></html>") is False
