import asyncio
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from .patterns import is_non_html_resource

_CONFIRMED_DEAD_STATUSES = {404, 410}

# Statuses where a HEAD's answer is worth a single GET double-check before trusting it.
# Live-verified (v3.1 unverified-bucket investigation): rfc-editor.org and
# support.google.com both answer HEAD with 404 but GET with a real 200 — HEAD support is
# just inconsistent on these origins, not evidence of a dead link. 405 is the original,
# unambiguous case (method genuinely not allowed).
_HEAD_DOUBLE_CHECK_STATUSES = _CONFIRMED_DEAD_STATUSES | {405}

_DNS_FAILURE_MARKERS = (
    "nodename nor servname",
    "name or service not known",
    "getaddrinfo failed",
    "temporary failure in name resolution",
)


@dataclass(frozen=True)
class ExternalCheckResult:
    classification: str
    reason: str | None = None
    status_code: int | None = None
    # False for a target plain HTTP already settled well enough that an Olostep escalation
    # can only make things worse (non-HTML resources — see patterns.is_non_html_resource).
    # Checked by cli.py before adding a result to the v3 escalation set.
    resolvable: bool = True


def _looks_like_dns_failure(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _DNS_FAILURE_MARKERS)


async def check_external(
    url: str,
    client,
    max_redirect_hops: int = 10,
    timeout: float = 10.0,
    confirm_dead: bool = True,
    recheck_delay: float = 2.0,
    sleep_fn=None,
) -> ExternalCheckResult:
    result = await _check_external_once(url, client, max_redirect_hops, timeout)

    # Live pilot finding (2026-07-23): a first-pass 404 on a reputable external domain
    # sometimes doesn't reproduce on a second try (transient anti-bot behavior on the
    # third-party site, not our bug) — ~40% of first-pass "dead" externals flipped to OK
    # on recheck. Only genuinely-dead-looking results are worth the extra request; an
    # already-ok or already-ambiguous (blocked/timeout) result needs no confirmation.
    if confirm_dead and result.classification == "external-dead" and result.status_code in _CONFIRMED_DEAD_STATUSES:
        if sleep_fn is None:
            sleep_fn = asyncio.sleep
        await sleep_fn(recheck_delay)
        result = await _check_external_once(url, client, max_redirect_hops, timeout)

    return result


async def _check_external_once(
    url: str,
    client,
    max_redirect_hops: int,
    timeout: float,
) -> ExternalCheckResult:
    non_html = is_non_html_resource(url)
    current_url = url
    method = "HEAD"
    downgraded_from_head = False
    hops = 0

    try:
        while True:
            response = await client.request(method, current_url, timeout=timeout)

            if (
                method == "HEAD"
                and response.status_code in _HEAD_DOUBLE_CHECK_STATUSES
                and not downgraded_from_head
            ):
                method = "GET"
                downgraded_from_head = True
                continue

            if getattr(response, "is_redirect", False):
                hops += 1
                if hops > max_redirect_hops:
                    return ExternalCheckResult(
                        classification="external-dead", reason="redirect-loop", resolvable=not non_html
                    )
                location = response.headers.get("location")
                current_url = urljoin(current_url, location)
                method = "HEAD"
                downgraded_from_head = False
                continue

            break
    except httpx.TimeoutException:
        return ExternalCheckResult(classification="external-timeout", reason="timeout", resolvable=not non_html)
    except httpx.ConnectError as exc:
        reason = "dns-failure" if _looks_like_dns_failure(exc) else "connection-error"
        return ExternalCheckResult(classification="external-dead", reason=reason, resolvable=not non_html)

    if response.status_code in _CONFIRMED_DEAD_STATUSES:
        return ExternalCheckResult(
            classification="external-dead",
            reason=str(response.status_code),
            status_code=response.status_code,
            resolvable=not non_html,
        )

    if response.status_code >= 400:
        # 403/429/999(LinkedIn)/5xx etc.: the site answered, it's just refusing our bot
        # or hiccuping — that's not evidence the link is broken. Report separately so
        # this doesn't drown the real dead-link signal in bot-block noise.
        return ExternalCheckResult(
            classification="external-blocked",
            reason=str(response.status_code),
            status_code=response.status_code,
            resolvable=not non_html,
        )

    content_type = response.headers.get("content-type", "")
    if non_html or (content_type and "text/html" not in content_type):
        return ExternalCheckResult(classification="skipped-non-html", status_code=response.status_code)

    return ExternalCheckResult(classification="ok", status_code=response.status_code)


async def check_many_external(
    urls: list[str],
    client,
    concurrency: int = 10,
    **kwargs,
) -> dict[str, ExternalCheckResult]:
    semaphore = asyncio.Semaphore(concurrency)

    async def bounded(u: str):
        async with semaphore:
            return u, await check_external(u, client, **kwargs)

    results = await asyncio.gather(*(bounded(u) for u in urls))
    return dict(results)
