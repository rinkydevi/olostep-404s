from bs4 import BeautifulSoup

# A page is treated as a JS-shell (its real content/links are injected client-side, so a
# plain HTTP GET can't see them) when it returns 200 but the server HTML carries almost no
# visible text and no links. Only such pages are worth spending an Olostep scrape credit on.
_MIN_VISIBLE_TEXT_CHARS = 200


def needs_js_render(status_code: int | None, html: str) -> bool:
    if status_code != 200:
        return False

    if not html or not html.strip():
        return True

    soup = BeautifulSoup(html, "lxml")

    if soup.find("a", href=True) is not None:
        return False

    for tag in soup(["script", "style", "noscript"]):
        tag.extract()
    visible_text = soup.get_text(strip=True)

    return len(visible_text) < _MIN_VISIBLE_TEXT_CHARS
