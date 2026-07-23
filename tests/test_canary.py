from pathlib import Path

from olostep_link_checker.canary import run_canary

FIXTURES = Path(__file__).parent / "fixtures"
CANARY_URL = "https://www.olostep.com/this-page-definitely-does-not-exist-404-test"


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


async def test_canary_passes_when_fixture_matches_fingerprint():
    async def fetch_fn(url):
        return load("soft_404_nextjs.html")

    result = await run_canary(fetch_fn, CANARY_URL)
    assert result.passed is True
    assert result.reason is None


async def test_canary_fails_when_fingerprint_no_longer_matches():
    changed_404_page = "<html><head><title>Not Found</title></head><body><h1>Oops</h1></body></html>"

    async def fetch_fn(url):
        return changed_404_page

    result = await run_canary(fetch_fn, CANARY_URL)
    assert result.passed is False
    assert "title" in result.reason
    assert "error_class" in result.reason
    assert "h1" in result.reason


async def test_canary_fails_distinctly_when_unreachable():
    async def raise_network_error(url):
        raise ConnectionError("boom")

    result = await run_canary(raise_network_error, CANARY_URL)
    assert result.passed is False
    assert result.reason == "canary unreachable"
