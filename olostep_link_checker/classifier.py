from bs4 import BeautifulSoup

_SOFT_404_TITLE_SUBSTRING = "this page could not be found"
_SOFT_404_ERROR_CLASS = "next-error-h1"
_SOFT_404_H1_TEXT = "404"


def soft_404_signals(html: str) -> dict[str, bool]:
    if not html or not html.strip():
        return {"title": False, "error_class": False, "h1": False}

    soup = BeautifulSoup(html, "lxml")

    title = soup.title.string if soup.title and soup.title.string else ""
    title_matches = _SOFT_404_TITLE_SUBSTRING in title.strip().lower()

    error_class_matches = soup.find(class_=_SOFT_404_ERROR_CLASS) is not None

    h1 = soup.find("h1")
    h1_matches = h1 is not None and h1.get_text(strip=True) == _SOFT_404_H1_TEXT

    return {"title": title_matches, "error_class": error_class_matches, "h1": h1_matches}


def _matches_soft_404_fingerprint(html: str) -> bool:
    return all(soft_404_signals(html).values())


def classify(status_code: int, html: str, trust_fingerprint: bool = True) -> str:
    if 400 <= status_code < 600:
        return "hard-404"

    if 300 <= status_code < 400:
        return "redirect"

    # trust_fingerprint=False (canary failed this run) means the soft-404 fingerprint
    # is unproven — a 200 page is reported "ok" rather than risking a false soft-404
    # verdict either way. Status-code-based classification (hard-404/redirect above)
    # never depends on the fingerprint, so it's unaffected by canary status.
    if trust_fingerprint and _matches_soft_404_fingerprint(html):
        return "soft-404"

    return "ok"
