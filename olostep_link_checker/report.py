from .differ import AMBIGUOUS_CLASSIFICATIONS, DiffEntry, DiffResult

_CATEGORIES = ("new_baseline", "newly_broken", "still_broken", "fixed", "no_longer_scanned")


def _entry_dict(diff_entry: DiffEntry, results_by_url: dict) -> dict:
    result = results_by_url.get(diff_entry.url, {})
    return {
        "url": diff_entry.url,
        "break_type": diff_entry.classification,
        "source_pages": result.get("source_pages", []),
        "anchor_text": result.get("anchor_text", []),
        "first_seen": diff_entry.first_seen,
        # v3: was this "confirmed" by plain HTTP or "browser-verified" via an Olostep
        # escalation — never conflate the two.
        "confidence": result.get("confidence", "confirmed"),
    }


def build_report(
    diff_result: DiffResult | None,
    current_run: dict | None,
    canary_passed: bool,
    canary_reason: str | None = None,
) -> dict:
    # current_run is None only when no run happened at all (e.g. site discovery itself
    # failed) — that's the sole "nothing to report" case. A failed canary is a narrower,
    # independent signal (see below): it means the internal soft-404 fingerprint is
    # unproven this run, NOT that the whole run's data is garbage. Hard-404s (status-code
    # based) and every external result (a completely separate fingerprint, see
    # external_resolver.py) never depend on this canary and are reported normally either way.
    if current_run is None:
        return {
            "canary": {"passed": canary_passed, "reason": canary_reason},
            "trusted": False,
            "run_failed": True,
        }

    results_by_url = {r["url"]: r for r in current_run["results"]}

    report = {
        "canary": {"passed": canary_passed, "reason": canary_reason},
        "trusted": True,
        "run_failed": False,
    }
    for category in _CATEGORIES:
        entries = getattr(diff_result, category)
        report[category] = [_entry_dict(e, results_by_url) for e in entries]

    report["unverified"] = [
        {
            "url": r["url"],
            "break_type": r["classification"],
            "source_pages": r.get("source_pages", []),
            "anchor_text": r.get("anchor_text", []),
            "first_seen": None,
            "confidence": r.get("confidence", "unverified"),
        }
        for r in current_run["results"]
        if r["classification"] in AMBIGUOUS_CLASSIFICATIONS
    ]

    return report


def render_human_readable(report: dict) -> str:
    if report["run_failed"]:
        return (
            "RUN FAILED — no results to report.\n"
            f"Reason: {report['canary']['reason']}"
        )

    lines = []
    if not report["canary"]["passed"]:
        lines.append(
            "CANARY FAILED — the internal soft-404 fingerprint is unproven this run "
            f"({report['canary']['reason']}). Soft-404 pages may be silently reported "
            "as ok until this is fixed (see README.md). hard-404 and every external "
            "result below do NOT depend on this fingerprint and are still trustworthy."
        )
        lines.append("")

    total_broken = (
        len(report["newly_broken"]) + len(report["still_broken"]) + len(report["new_baseline"])
    )
    if total_broken == 0:
        lines.append("All clear — no confirmed broken links detected.")
        lines.extend(_unverified_lines(report))
        return "\n".join(lines)

    if report["newly_broken"]:
        lines.append(f"NEWLY BROKEN ({len(report['newly_broken'])}):")
        for e in report["newly_broken"]:
            lines.append(f"  - {e['url']} [{e['break_type']}]{_confidence_tag(e)}")
    if report["still_broken"]:
        lines.append(f"STILL BROKEN ({len(report['still_broken'])}):")
        for e in report["still_broken"]:
            lines.append(f"  - {e['url']} [{e['break_type']}]{_confidence_tag(e)}")
    if report["new_baseline"]:
        lines.append(f"BASELINE, first run ({len(report['new_baseline'])}):")
        for e in report["new_baseline"]:
            lines.append(f"  - {e['url']} [{e['break_type']}]{_confidence_tag(e)}")
    lines.append(f"Fixed since last run: {len(report['fixed'])}")
    lines.extend(_unverified_lines(report))
    return "\n".join(lines)


def _confidence_tag(entry: dict) -> str:
    # A "broken" entry can still carry confidence "unverified" if the v3 escalation
    # never ran (e.g. budget exhausted before reaching it) — surface that rather than
    # let it read identically to a fully browser-verified or plain-HTTP-confirmed break.
    if entry.get("confidence") == "unverified":
        return " (unverified — Olostep escalation did not run)"
    return ""


def _unverified_lines(report: dict) -> list[str]:
    unverified = report.get("unverified", [])
    if not unverified:
        return []
    lines = [f"UNVERIFIED, needs manual check ({len(unverified)}):"]
    for e in unverified:
        lines.append(f"  - {e['url']} [{e['break_type']}]")
    return lines
