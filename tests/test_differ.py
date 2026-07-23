from olostep_link_checker.differ import AMBIGUOUS_CLASSIFICATIONS, BROKEN_CLASSIFICATIONS, diff


def test_external_unreachable_is_ambiguous_not_broken():
    # v3: Olostep itself failing to resolve a link (its own 4xx/5xx) is a third honest
    # state — never claimed dead, never claimed alive. See PRODUCTION_PLAN.md §10.2.
    assert "external-unreachable" in AMBIGUOUS_CLASSIFICATIONS
    assert "external-unreachable" not in BROKEN_CLASSIFICATIONS


def make_run(run_id, results):
    return {"run_id": run_id, "results": results}


def test_confirmed_broken_classifications_are_treated_as_broken():
    for classification in ("hard-404", "soft-404", "external-dead", "redirect-loop"):
        assert classification in BROKEN_CLASSIFICATIONS


def test_ambiguous_signals_are_not_treated_as_confirmed_broken():
    # A bot-block (403/429/999) or a timeout means the site answered oddly or
    # slowly to OUR request — it is not evidence the link is actually dead.
    # Reporting these as "broken" is exactly the alert-fatigue failure the
    # production plan warns about, so the differ must not surface them as such.
    for classification in ("external-blocked", "external-timeout", "external-unreachable"):
        assert classification not in BROKEN_CLASSIFICATIONS

    current = make_run(
        "2026-07-23T00:00:00Z",
        [
            {"url": "https://x.com/blocked", "classification": "external-blocked", "first_seen": None},
            {"url": "https://x.com/slow", "classification": "external-timeout", "first_seen": None},
        ],
    )
    result = diff(None, current)
    all_urls = {e.url for e in result.new_baseline}
    assert "https://x.com/blocked" not in all_urls
    assert "https://x.com/slow" not in all_urls


def test_bootstrap_run_categorizes_broken_urls_as_new_baseline_not_newly_broken():
    current = make_run(
        "2026-07-23T00:00:00Z",
        [{"url": "https://x.com/a", "classification": "hard-404", "first_seen": None}],
    )
    result = diff(None, current)
    assert len(result.new_baseline) == 1
    assert result.new_baseline[0].url == "https://x.com/a"
    assert result.new_baseline[0].first_seen == "2026-07-23T00:00:00Z"
    assert result.newly_broken == []


def test_url_broken_in_both_runs_is_still_broken_with_first_seen_carried_forward():
    previous = make_run(
        "2026-07-20T00:00:00Z",
        [{"url": "https://x.com/a", "classification": "hard-404", "first_seen": "2026-07-18T00:00:00Z"}],
    )
    current = make_run(
        "2026-07-23T00:00:00Z",
        [{"url": "https://x.com/a", "classification": "hard-404", "first_seen": None}],
    )
    result = diff(previous, current)
    assert len(result.still_broken) == 1
    assert result.still_broken[0].first_seen == "2026-07-18T00:00:00Z"
    assert result.newly_broken == []


def test_url_broken_now_but_not_previously_is_newly_broken():
    previous = make_run("2026-07-20T00:00:00Z", [])
    current = make_run(
        "2026-07-23T00:00:00Z",
        [{"url": "https://x.com/new-break", "classification": "soft-404", "first_seen": None}],
    )
    result = diff(previous, current)
    assert len(result.newly_broken) == 1
    assert result.newly_broken[0].url == "https://x.com/new-break"
    assert result.newly_broken[0].first_seen == "2026-07-23T00:00:00Z"


def test_url_broken_previously_but_ok_now_is_fixed():
    previous = make_run(
        "2026-07-20T00:00:00Z",
        [{"url": "https://x.com/a", "classification": "hard-404", "first_seen": "2026-07-18T00:00:00Z"}],
    )
    current = make_run(
        "2026-07-23T00:00:00Z",
        [{"url": "https://x.com/a", "classification": "ok", "first_seen": None}],
    )
    result = diff(previous, current)
    assert len(result.fixed) == 1
    assert result.fixed[0].url == "https://x.com/a"


def test_url_broken_previously_but_absent_from_current_scan_is_no_longer_scanned():
    previous = make_run(
        "2026-07-20T00:00:00Z",
        [{"url": "https://x.com/removed-page", "classification": "hard-404", "first_seen": "2026-07-18T00:00:00Z"}],
    )
    current = make_run("2026-07-23T00:00:00Z", [])
    result = diff(previous, current)
    assert len(result.no_longer_scanned) == 1
    assert result.fixed == []


def test_ok_urls_never_appear_in_any_broken_category():
    previous = make_run("2026-07-20T00:00:00Z", [])
    current = make_run(
        "2026-07-23T00:00:00Z",
        [{"url": "https://x.com/fine", "classification": "ok", "first_seen": None}],
    )
    result = diff(previous, current)
    all_urls = {
        e.url
        for bucket in (result.new_baseline, result.newly_broken, result.still_broken, result.fixed, result.no_longer_scanned)
        for e in bucket
    }
    assert "https://x.com/fine" not in all_urls
