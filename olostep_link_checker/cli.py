import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import __version__
from .budget import Budget
from .canary import run_canary
from .classifier import classify
from .config import ConfigError, load_config
from .differ import diff
from .discovery import discover_urls
from .escalation import needs_js_render
from .external_checker import check_external
from .external_resolver import RESOLVABLE_CLASSIFICATIONS, ResolvedVerdict, resolve_external
from .flat_report import flat_broken_list, render_pipe_table, write_csv
from .http_fetcher import PageFetch, fetch_page
from .links import extract_links
from .olostep_client import OlostepAPIError, OlostepClient
from .patterns import is_placeholder_domain, matches_exclude
from .report import build_report, render_human_readable
from .store import get_previous_run, prune_older_than, save_run
from .urlnorm import resolve
from .verdict_cache import VerdictCache

# Classifications plain HTTP settles on its own — never sent through the v3 external
# resolver, and never re-escalated once resolved.
_CONFIRMED_CONFIDENCE_DEFAULT = "confirmed"


def _classify_fetch(pf: PageFetch, trust_fingerprint: bool = True) -> str:
    if pf.error == "redirect-loop":
        return "redirect-loop"
    if pf.error:
        return "fetch-error"
    return classify(pf.status_code, pf.html, trust_fingerprint=trust_fingerprint)


# Classifications plain HTTP could not settle on its own — either pending v3 escalation
# or (for external-check-error) a transport failure with no known status at all. Both
# are honestly "we don't know yet," never "confirmed."
_UNVERIFIED_BY_DEFAULT = RESOLVABLE_CLASSIFICATIONS | {"external-check-error", "external-unreachable"}

# Terminal Olostep-side failures during escalation (it couldn't reach the page at all, or
# refuses the domain by durable account policy) don't overwrite the classification a real
# fingerprint resolution would — they're not a resolution, just a failure to get one. The
# pre-escalation status_code is still the last real signal we have, so it's kept (not
# blanked) for these two states only. See Stage 6 below.
_OLOSTEP_FAILURE_CLASSIFICATIONS = {"external-unreachable", "external-provider-unsupported"}


def _default_confidence(classification: str, resolvable: bool = True) -> str:
    # A classification in _UNVERIFIED_BY_DEFAULT is only "pending escalation" if it's
    # actually going to BE escalated. A non-resolvable result (v3.1: non-HTML resources —
    # see RESOLVABLE_CLASSIFICATIONS filtering in Stage 6) never reaches Stage 6 at all, so
    # plain HTTP's answer is final — trusting it fully is the whole point of skipping
    # escalation, so it must read "confirmed", not perpetually "unverified".
    if not resolvable:
        return _CONFIRMED_CONFIDENCE_DEFAULT
    return "unverified" if classification in _UNVERIFIED_BY_DEFAULT else _CONFIRMED_CONFIDENCE_DEFAULT


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _fetch_all(urls, http_get_fn, concurrency: int) -> dict[str, PageFetch]:
    semaphore = asyncio.Semaphore(concurrency)

    async def bounded(url: str):
        async with semaphore:
            try:
                return url, await http_get_fn(url)
            except Exception as exc:  # a single page failing must not abort the run
                return url, PageFetch(url=url, status_code=None, error=f"fetch-error: {exc}")

    results = await asyncio.gather(*(bounded(u) for u in urls))
    return dict(results)


async def run_pipeline(
    *,
    create_map_fn,
    http_get_fn,
    canary_get_fn,
    canary_url: str,
    exclude_patterns: list[str],
    external_check_fn,
    scrape_fn,
    budget: Budget,
    runs_dir,
    run_id: str,
    concurrency: int = 10,
    sleep_fn=None,
    verdict_cache: VerdictCache | None = None,
    verdict_staleness_days: int = 14,
    now_fn=None,
) -> dict:
    maps_set = discover_urls(create_map_fn, exclude_patterns)
    site_hosts = {urlsplit(u).netloc for u in maps_set}

    async def _canary_html(url: str) -> str:
        pf = await canary_get_fn(url)
        return pf.html

    # The canary independently gates ONLY the internal soft-404 fingerprint's
    # trustworthiness — it never blocks the rest of the run. Hard-404 (status-code
    # based) and every external result (external_checker.py / external_resolver.py use
    # a completely separate, generic fingerprint) don't depend on this canary at all,
    # so they run and are reported normally regardless of canary outcome. A failed
    # canary only means: don't trust a "soft-404" verdict this run (see classify()'s
    # trust_fingerprint param) — surfaced via report["canary"], never silently.
    canary_result = await run_canary(_canary_html, canary_url)
    trust_fingerprint = canary_result.passed

    # Stage 1: plain HTTP GET every reachable page (0 Olostep credits).
    page_fetches = await _fetch_all(sorted(maps_set), http_get_fn, concurrency)

    # Stage 2: escalate ONLY JS-shell pages to an Olostep scrape (budget-gated). A page
    # already classified as broken (hard/soft-404, redirect) has its answer — only an
    # otherwise-"ok" page that looks like an empty shell is worth a JS-render credit.
    budget_exhausted = False
    for url in sorted(page_fetches):
        pf = page_fetches[url]
        if _classify_fetch(pf, trust_fingerprint) != "ok":
            continue
        if not needs_js_render(pf.status_code, pf.html):
            continue
        if not budget.can_consume():
            budget_exhausted = True
            continue
        budget.consume()
        try:
            status_code, html = await scrape_fn(url)
            page_fetches[url] = PageFetch(url=url, status_code=status_code, html=html)
        except Exception:
            # an escalation scrape failing (timeout, API error) must not abort the run —
            # keep the page's plain-HTTP result and move on.
            pass

    # Stage 3: harvest the link graph from every fetched (and possibly escalated) page.
    anchors: dict[str, list[tuple[str, str]]] = {}
    internal_targets: set[str] = set()
    external_targets: set[str] = set()
    placeholder_targets: set[str] = set()

    for page_url, pf in page_fetches.items():
        if pf.error or not pf.html:
            continue
        for link in extract_links(pf.html):
            resolved = resolve(link.href, page_url)
            if resolved.normalized is None:
                continue
            target = resolved.normalized
            for text in link.anchor_texts:
                anchors.setdefault(target, []).append((page_url, text))
            if urlsplit(target).netloc in site_hosts:
                if not matches_exclude(target, exclude_patterns):
                    internal_targets.add(target)
            elif is_placeholder_domain(target):
                # Illustrative prose examples (example.com, yourdomain.com, ...) — never
                # real links, never worth a network call or a "broken" report entry.
                placeholder_targets.add(target)
            else:
                external_targets.add(target)

    # Stage 4: internal targets referenced but not in the Maps set -> free fallback GET.
    unlisted = sorted(t for t in internal_targets if t not in page_fetches)
    unlisted_fetches = await _fetch_all(unlisted, http_get_fn, concurrency)

    # Stage 5: classify everything.
    results = []
    for url in sorted(page_fetches):
        classification = _classify_fetch(page_fetches[url], trust_fingerprint)
        results.append(
            {
                "url": url,
                "classification": classification,
                "status_code": page_fetches[url].status_code,
                "source_pages": [p for p, _ in anchors.get(url, [])],
                "anchor_text": [t for _, t in anchors.get(url, [])],
                "not_in_sitemap": False,
                "first_seen": None,
                "confidence": _default_confidence(classification),
            }
        )
    for url in sorted(unlisted_fetches):
        classification = _classify_fetch(unlisted_fetches[url], trust_fingerprint)
        results.append(
            {
                "url": url,
                "classification": classification,
                "status_code": unlisted_fetches[url].status_code,
                "source_pages": [p for p, _ in anchors.get(url, [])],
                "anchor_text": [t for _, t in anchors.get(url, [])],
                "not_in_sitemap": True,
                "first_seen": None,
                "confidence": _default_confidence(classification),
            }
        )
    for target in sorted(placeholder_targets):
        results.append(
            {
                "url": target,
                "classification": "skipped-placeholder-domain",
                "status_code": None,
                "source_pages": [p for p, _ in anchors.get(target, [])],
                "anchor_text": [t for _, t in anchors.get(target, [])],
                "not_in_sitemap": True,
                "first_seen": None,
                "confidence": _CONFIRMED_CONFIDENCE_DEFAULT,
            }
        )

    ext_semaphore = asyncio.Semaphore(concurrency)

    async def _check_external_target(target: str):
        async with ext_semaphore:
            try:
                ext = await external_check_fn(target)
                return target, ext.classification, ext.status_code, ext.resolvable
            except Exception:
                # a single external target failing (bad transport, odd scheme that slipped
                # through) must not abort the run — record it and move on.
                return target, "external-check-error", None, True

    external_checked = await asyncio.gather(
        *(_check_external_target(t) for t in sorted(external_targets))
    )
    for target, classification, status_code, resolvable in external_checked:
        results.append(
            {
                "url": target,
                "classification": classification,
                "status_code": status_code,
                "source_pages": [p for p, _ in anchors.get(target, [])],
                "anchor_text": [t for _, t in anchors.get(target, [])],
                "not_in_sitemap": True,
                "first_seen": None,
                "confidence": _default_confidence(classification, resolvable),
                "resolvable": resolvable,
            }
        )

    # Stage 6 (v3): resolve every external result plain HTTP left ambiguous — blocked,
    # timed out, or even confirmed-dead, since a same-signature plain-HTTP recheck
    # cannot beat a signature-based anti-bot soft-block but Olostep's
    # differently-fingerprinted request can. Budget-gated like JS-shell escalation;
    # a cached, non-stale verdict from a prior run is reused for free.
    if verdict_cache is None:
        verdict_cache = VerdictCache({})
    now_fn = now_fn or _utcnow

    resolve_semaphore = asyncio.Semaphore(concurrency)
    budget_lock = asyncio.Lock()

    async def _resolve_one(r: dict):
        url = r["url"]
        cached = verdict_cache.get(url, now=now_fn(), staleness_days=verdict_staleness_days)
        if cached is not None:
            return r, cached.classification, cached.confidence, False

        async with budget_lock:
            if not budget.can_consume():
                return r, r["classification"], r["confidence"], True
            budget.consume()

        async with resolve_semaphore:
            try:
                verdict = await resolve_external(url, scrape_fn)
            except Exception:
                # an escalation failure must not abort the run, same as JS-shell escalation.
                # (resolve_external already catches scrape_fn failures internally; this is
                # a second layer against anything unexpected in the resolver itself.)
                verdict = ResolvedVerdict(classification="external-unreachable", confidence="unverified")
        return r, verdict.classification, verdict.confidence, False

    # v3.1: non-HTML resources (PDF/JSON/XML/CSV/ZIP — external_checker.is_non_html_resource)
    # are marked not-resolvable — Olostep's scrape is an HTML renderer and only makes
    # these worse (a 504 timeout on a real PDF 404, a null-content 200 on a real JSON
    # file — both live-verified). Plain HTTP's status is already the right answer for them.
    to_resolve = [
        r for r in results if r["classification"] in RESOLVABLE_CLASSIFICATIONS and r.get("resolvable", True)
    ]
    resolved = await asyncio.gather(*(_resolve_one(r) for r in to_resolve))
    for r, resolved_classification, resolved_confidence, exhausted in resolved:
        if exhausted:
            budget_exhausted = True
            continue
        r["classification"] = resolved_classification
        r["confidence"] = resolved_confidence
        if resolved_classification not in _OLOSTEP_FAILURE_CLASSIFICATIONS:
            # The pre-escalation status_code (from plain HTTP) no longer reflects why this
            # verdict was reached — the fingerprint/content-substance rule did, and we
            # deliberately never trust Olostep's own status code either. Keeping the
            # stale number would misleadingly imply e.g. "403 means dead" — a live run
            # surfaced this exact display bug on real data (gartner.com/pcmag.com,
            # both shown as "(403)").
            r["status_code"] = None
        verdict_cache.put(
            r["url"], classification=resolved_classification, confidence=resolved_confidence, resolved_at=now_fn()
        )

    run = {
        "run_id": run_id,
        "site_scope": sorted({f"{urlsplit(u).scheme}://{urlsplit(u).netloc}" for u in maps_set}),
        "excluded_patterns": list(exclude_patterns),
        "canary": {"passed": canary_result.passed, "reason": canary_result.reason, "fingerprint_version": "v1"},
        "urls_scanned": len(page_fetches) + len(unlisted_fetches),
        "credits_consumed": budget.credits_consumed,
        "duration_seconds": 0.0,
        "results": results,
    }

    previous_run = get_previous_run(runs_dir)
    diff_result = diff(previous_run, run)

    first_seen_by_url = {
        e.url: e.first_seen
        for bucket in (diff_result.new_baseline, diff_result.newly_broken, diff_result.still_broken)
        for e in bucket
    }
    for r in run["results"]:
        if r["url"] in first_seen_by_url:
            r["first_seen"] = first_seen_by_url[r["url"]]

    save_run(run, runs_dir)

    report = build_report(diff_result, run, canary_passed=canary_result.passed, canary_reason=canary_result.reason)
    # Canary failure (2) takes priority to surface over a mere budget partial (1) — it's
    # the rarer, more actionable signal (a stale fingerprint needs a code fix, not just a
    # bigger budget) — but either way the run completed and produced a full report.
    exit_code = 2 if not canary_result.passed else (1 if budget_exhausted else 0)
    return {"report": report, "run": run, "exit_code": exit_code}


_INIT_CONFIG_TEMPLATE = """\
# Copy of the olostep-link-checker config template, scaffolded by `olostep-link-checker init`.
# The API key is never read from this file — set it via the OLOSTEP_API_KEY env var.

site_url: "{site_url}"

# Glob patterns for app routes / non-SEO surface to skip (same syntax as Olostep Maps'
# exclude_urls), e.g.:
# exclude_patterns:
#   - "/dashboard/**"
#   - "/auth"

exclude_patterns: []

# A URL on your site that is guaranteed not to exist. Checked every run to confirm the
# soft-404 fingerprint (olostep_link_checker/classifier.py) still matches your site's
# actual 404 page before trusting any soft-404 classification.
canary_url: "{site_url}/this-page-definitely-does-not-exist-404-test"

# Optional hard cap on Olostep scrape credits per run. Leave commented out for no cap:
# every JS-shell page and every ambiguous external link gets resolved every run.
# budget_ceiling: 250

# Max concurrent scrape calls in flight at once.
concurrency: 10

# Where run history (JSON, one file per run) is written and read back from for diffing.
runs_dir: "data/runs"

# Where resolved external-link verdicts are cached across runs, keyed by URL.
verdict_cache_path: "data/external_verdicts.json"
verdict_staleness_days: 14
"""


def run_init(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="olostep-link-checker init", description="Scaffold a config.yaml for your site"
    )
    parser.add_argument("--site-url", default="https://example.com", help="Your site's URL")
    parser.add_argument("--output", default="config.yaml", help="Path to write the config file")
    parser.add_argument("--force", action="store_true", help="Overwrite the output file if it already exists")
    args = parser.parse_args(argv)

    output_path = Path(args.output)
    if output_path.exists() and not args.force:
        print(f"{output_path} already exists. Use --force to overwrite.", file=sys.stderr)
        return 1

    output_path.write_text(_INIT_CONFIG_TEMPLATE.format(site_url=args.site_url.rstrip("/")))
    print(f"Wrote {output_path}.")
    print(f"Next: edit it, then run `export OLOSTEP_API_KEY=<your-key>` and `olostep-link-checker --config {output_path}`.")
    return 0


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Olostep Link Checker")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", default="config.yaml", help="Path to the config YAML file")
    parser.add_argument(
        "--retention-days",
        type=int,
        default=90,
        help="Delete run history older than N days after each run",
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="Write confirmed-broken links to this CSV file (url,from,status)",
    )
    return parser.parse_args(argv)


async def _async_main(config, retention_days: int) -> dict:
    async with httpx.AsyncClient(follow_redirects=True, max_redirects=10, timeout=15.0) as http_client:
        client = OlostepClient(api_key=config.api_key, http_client=http_client)

        try:
            # NOTE: we deliberately do NOT pass exclude_urls to Maps. Verified live
            # (2026-07-23) that any exclude_urls value makes the Maps call fail with
            # 404 "Could not retrieve page URLs from the sitemap." on this site/account.
            # The exclude patterns are enforced client-side in discover_urls instead
            # (see run_pipeline), which is tested and reliable.
            maps_urls = await client.create_map(config.site_url)
        except OlostepAPIError as exc:
            report = build_report(
                None, None, canary_passed=False, canary_reason=f"site discovery failed: {exc}"
            )
            return {"report": report, "run": None, "exit_code": 5}

        async def http_get_fn(url: str) -> PageFetch:
            return await fetch_page(url, http_client)

        async def external_check_fn(url: str):
            return await check_external(url, http_client)

        async def scrape_fn(url: str):
            return await client.scrape(url)

        # budget_ceiling is None by default (see config.py) — no cap, every JS-shell
        # escalation and every ambiguous external link gets resolved. Set budget_ceiling
        # in config.yaml only if you want a hard cost cap for a specific run.
        budget = Budget(ceiling=config.budget_ceiling, unlimited=config.budget_ceiling is None)
        run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        runs_dir = Path(config.runs_dir)
        verdict_cache_path = Path(config.verdict_cache_path)
        verdict_cache = VerdictCache.load(verdict_cache_path)

        outcome = await run_pipeline(
            create_map_fn=lambda: maps_urls,
            http_get_fn=http_get_fn,
            canary_get_fn=http_get_fn,
            canary_url=config.canary_url,
            exclude_patterns=config.exclude_patterns,
            external_check_fn=external_check_fn,
            scrape_fn=scrape_fn,
            budget=budget,
            runs_dir=runs_dir,
            run_id=run_id,
            concurrency=config.concurrency,
            verdict_cache=verdict_cache,
            verdict_staleness_days=config.verdict_staleness_days,
        )

        # Persisted regardless of outcome — a partial/budget-stopped run still resolved
        # some externals, and those verdicts are worth keeping for next time.
        verdict_cache.save(verdict_cache_path)

        prune_older_than(runs_dir, days=retention_days)
        return outcome


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "init":
        return run_init(argv[1:])

    args = parse_args(argv)

    try:
        config = load_config(args.config, env=os.environ)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 4

    outcome = asyncio.run(_async_main(config, args.retention_days))

    print(render_human_readable(outcome["report"]))

    if outcome["run"] is not None:
        rows = flat_broken_list(outcome["run"])
        print()
        print(render_pipe_table(rows))
        if args.csv:
            write_csv(rows, args.csv)
            print(f"\nWrote {len(rows)} confirmed-broken link(s) to {args.csv}")

    return outcome["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
