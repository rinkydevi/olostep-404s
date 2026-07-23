from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

_SKIPPED_SCHEMES = {"mailto", "tel", "javascript"}


@dataclass(frozen=True)
class NormalizedUrl:
    original: str
    normalized: str | None
    skip_reason: str | None = None


def resolve(href: str, base_url: str) -> NormalizedUrl:
    if not href or not href.strip():
        return NormalizedUrl(original=href, normalized=None, skip_reason="malformed")

    try:
        scheme = urlsplit(href).scheme
    except ValueError:
        return NormalizedUrl(original=href, normalized=None, skip_reason="malformed")

    if scheme in _SKIPPED_SCHEMES:
        return NormalizedUrl(original=href, normalized=None, skip_reason="non-page-link")

    try:
        absolute = urljoin(base_url, href)
        parts = urlsplit(absolute)
    except ValueError:
        return NormalizedUrl(original=href, normalized=None, skip_reason="malformed")

    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return NormalizedUrl(original=href, normalized=None, skip_reason="non-page-link")

    netloc = parts.netloc.lower()
    original = urlunsplit((scheme, netloc, parts.path, parts.query, parts.fragment))

    path = parts.path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    normalized = urlunsplit((scheme, netloc, path, "", ""))

    return NormalizedUrl(original=original, normalized=normalized, skip_reason=None)
