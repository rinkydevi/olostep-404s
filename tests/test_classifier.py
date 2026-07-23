from pathlib import Path

from olostep_link_checker.classifier import classify

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_status_404_is_hard_404_regardless_of_html():
    assert classify(404, "<html><body>whatever</body></html>") == "hard-404"


def test_status_500_is_hard_404():
    assert classify(500, "<html><body>server error</body></html>") == "hard-404"


def test_status_200_healthy_page_is_ok():
    assert classify(200, load("healthy_page.html")) == "ok"


def test_status_200_soft_404_fixture_is_soft_404():
    assert classify(200, load("soft_404_nextjs.html")) == "soft-404"


def test_decoy_page_mentioning_404_in_body_copy_is_ok():
    assert classify(200, load("decoy_404_in_body.html")) == "ok"


def test_redirect_status_is_not_hard_404():
    assert classify(301, "<html><body>moved</body></html>") == "redirect"
    assert classify(302, "<html><body>moved</body></html>") == "redirect"


def test_fingerprint_requires_all_signals_not_just_h1_text():
    html = """
    <html><head><title>My blog post</title></head>
    <body><h1>404</h1><p>A post about the history of the HTTP 404 status code.</p></body>
    </html>
    """
    assert classify(200, html) == "ok"


def test_fingerprint_requires_all_signals_not_just_title():
    html = """
    <html><head><title>404: This page could not be found.</title></head>
    <body><h1>Welcome</h1><p>Unrelated content, no error class present.</p></body>
    </html>
    """
    assert classify(200, html) == "ok"


def test_empty_html_with_200_is_ok():
    assert classify(200, "") == "ok"
    assert classify(200, "   ") == "ok"
