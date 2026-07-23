from dataclasses import dataclass, field

BROKEN_CLASSIFICATIONS = {
    "hard-404",
    "soft-404",
    "external-dead",
    "redirect-loop",
}

# Ambiguous signals — the site answered oddly (bot-block, rate-limit) or too slowly
# to say anything for certain. Deliberately excluded from BROKEN_CLASSIFICATIONS:
# reporting these as confirmed-broken is exactly the alert-fatigue failure the
# production plan warns about. Callers (report.py) can surface these separately.
AMBIGUOUS_CLASSIFICATIONS = {
    "external-blocked",
    "external-timeout",
    # v3: Olostep itself couldn't resolve the link (its own 4xx/5xx) even after
    # escalation — a third honest state, never claimed dead or alive. See
    # PRODUCTION_PLAN.md §10.2.
    "external-unreachable",
    # v3.1: Olostep refuses this domain by durable account policy (LinkedIn, Reddit —
    # "approval_required"), not a transient technical failure. Distinct from
    # external-unreachable so the report names the real reason. See external_resolver.py.
    "external-provider-unsupported",
}


@dataclass(frozen=True)
class DiffEntry:
    url: str
    classification: str
    first_seen: str


@dataclass(frozen=True)
class DiffResult:
    new_baseline: list[DiffEntry] = field(default_factory=list)
    newly_broken: list[DiffEntry] = field(default_factory=list)
    still_broken: list[DiffEntry] = field(default_factory=list)
    fixed: list[DiffEntry] = field(default_factory=list)
    no_longer_scanned: list[DiffEntry] = field(default_factory=list)


def _broken_by_url(run: dict) -> dict[str, dict]:
    return {
        r["url"]: r for r in run["results"] if r["classification"] in BROKEN_CLASSIFICATIONS
    }


def diff(previous_run: dict | None, current_run: dict) -> DiffResult:
    current_by_url = {r["url"]: r for r in current_run["results"]}
    current_broken = _broken_by_url(current_run)

    if previous_run is None:
        new_baseline = [
            DiffEntry(url=u, classification=r["classification"], first_seen=current_run["run_id"])
            for u, r in current_broken.items()
        ]
        return DiffResult(new_baseline=new_baseline)

    previous_broken = _broken_by_url(previous_run)

    newly_broken = []
    still_broken = []
    for u, r in current_broken.items():
        if u in previous_broken:
            still_broken.append(
                DiffEntry(url=u, classification=r["classification"], first_seen=previous_broken[u]["first_seen"])
            )
        else:
            newly_broken.append(
                DiffEntry(url=u, classification=r["classification"], first_seen=current_run["run_id"])
            )

    fixed = []
    no_longer_scanned = []
    for u, r in previous_broken.items():
        if u in current_broken:
            continue
        if u in current_by_url:
            fixed.append(
                DiffEntry(url=u, classification=current_by_url[u]["classification"], first_seen=r["first_seen"])
            )
        else:
            no_longer_scanned.append(
                DiffEntry(url=u, classification=r["classification"], first_seen=r["first_seen"])
            )

    return DiffResult(
        newly_broken=newly_broken,
        still_broken=still_broken,
        fixed=fixed,
        no_longer_scanned=no_longer_scanned,
    )
