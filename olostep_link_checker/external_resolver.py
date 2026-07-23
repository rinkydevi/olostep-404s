from dataclasses import dataclass

from bs4 import BeautifulSoup

from .olostep_client import OlostepAPIError

# External targets plain HTTP couldn't confidently clear on its own. Escalating the
# dead bucket too was validated live (n=87): 0 true-dead links were falsely
# resurrected, and the reclassifications matched already-documented anti-bot-flaky
# domains found independently by a different method.
RESOLVABLE_CLASSIFICATIONS = {"external-blocked", "external-timeout", "external-dead"}

_MIN_SUBSTANTIVE_CHARS = 500

# Title/H1-only, deliberately not full-body: full-body matching false-positives on any
# real page that happens to mention "404" or "not found" in its own content (a blog post
# about broken links, for instance). Live-validated against 21 genuine-dead + 20 known-good
# targets with 0 false positives and 0 false negatives.
_DEAD_PHRASES = (
    "404",
    "not found",
    "page not found",
    "cannot be found",
    "could not be found",
    "doesn't exist",
    "does not exist",
    "410 gone",
    "page removed",
    "no longer available",
)


@dataclass(frozen=True)
class ResolvedVerdict:
    classification: str
    confidence: str


def _dead_fingerprint(html: str) -> bool:
    if not html:
        return False
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(strip=True).lower() if soup.title else ""
    h1 = " ".join(tag.get_text(strip=True).lower() for tag in soup.find_all("h1")[:2])
    signal = f"{title} {h1}"
    return any(phrase in signal for phrase in _DEAD_PHRASES)


def _visible_text_length(html: str) -> int:
    if not html:
        return 0
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.extract()
    return len(soup.get_text(strip=True))


async def resolve_external(url: str, scrape_fn) -> ResolvedVerdict:
    # We deliberately never read the scrape's status code here — it reflects the
    # rendered document, not the origin, and is `200` even for genuine 404s. Liveness
    # is decided by content substance + a not-found fingerprint only.
    try:
        _status_code, html = await scrape_fn(url)
    except OlostepAPIError as exc:
        if exc.code == "approval_required":
            # Live-verified (v3.1 unverified-bucket investigation): LinkedIn and Reddit
            # both return this on every scrape attempt, on this account — a durable
            # account-level policy block, not a transient technical failure. Naming it
            # distinctly (rather than lumping it into external-unreachable) means the
            # report tells the truth about *why* it's unresolved, and a future account
            # upgrade can be told apart from a domain that's merely flaky.
            return ResolvedVerdict(classification="external-provider-unsupported", confidence="unverified")
        return ResolvedVerdict(classification="external-unreachable", confidence="unverified")
    except Exception:
        return ResolvedVerdict(classification="external-unreachable", confidence="unverified")

    if _dead_fingerprint(html):
        return ResolvedVerdict(classification="external-dead", confidence="browser-verified")

    if _visible_text_length(html) >= _MIN_SUBSTANTIVE_CHARS:
        return ResolvedVerdict(classification="ok", confidence="browser-verified")

    return ResolvedVerdict(classification="unverified", confidence="unverified")
