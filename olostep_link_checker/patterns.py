from urllib.parse import urlsplit

# RFC 2606 reserved example domains, plus the common convention "yourdomain.com" — used
# as illustrative prose text in docs/blog content (e.g. "see yourdomain.com/robots.txt"),
# never meant to be real, resolvable links.
_PLACEHOLDER_DOMAIN_BASES = ("example.com", "example.net", "example.org", "example.edu", "yourdomain.com")

# Live-verified (v3.1 unverified-bucket investigation): Olostep's scrape is an HTML
# renderer — pointed at a PDF or a raw JSON/XML file it either times out (504, seen on
# a kuleuven.be PDF) or returns 200 with every content field null (seen on olostep-storage
# S3 .json objects). Plain HTTP's status code is already the authoritative liveness signal
# for these — there is no soft-404-HTML page to be fooled by, so escalating them to Olostep
# only replaces a correct verdict with a worse one. Gate on the URL's own path extension
# (not the response content-type) because a dead PDF's 404 is often itself served as a
# small HTML error page, so content-type on the *error* response is useless here.
_NON_HTML_EXTENSIONS = (".pdf", ".json", ".xml", ".csv", ".zip")


def is_placeholder_domain(url: str) -> bool:
    host = urlsplit(url).netloc.lower()
    return any(host == base or host.endswith("." + base) for base in _PLACEHOLDER_DOMAIN_BASES)


def is_non_html_resource(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return path.endswith(_NON_HTML_EXTENSIONS)


def matches_exclude(url: str, exclude_patterns: list[str]) -> bool:
    path = urlsplit(url).path
    for pattern in exclude_patterns:
        if pattern.endswith("/**"):
            prefix = pattern[: -len("**")]
            if path.startswith(prefix):
                return True
        elif path == pattern:
            return True
    return False
