from olostep_link_checker.differ import DiffEntry, DiffResult
from olostep_link_checker.report import build_report, render_human_readable

CURRENT_RUN = {
    "run_id": "2026-07-23T00:00:00Z",
    "results": [
        {
            "url": "https://x.com/broken",
            "classification": "hard-404",
            "source_pages": ["https://x.com/"],
            "anchor_text": ["Learn more"],
        },
        {
            "url": "https://x.com/fine",
            "classification": "ok",
            "source_pages": ["https://x.com/"],
            "anchor_text": ["Home"],
        },
    ],
}


def test_json_report_includes_all_required_fields_per_broken_entry():
    diff_result = DiffResult(
        newly_broken=[DiffEntry(url="https://x.com/broken", classification="hard-404", first_seen="2026-07-23T00:00:00Z")]
    )
    report = build_report(diff_result, CURRENT_RUN, canary_passed=True)

    entry = report["newly_broken"][0]
    assert entry["url"] == "https://x.com/broken"
    assert entry["break_type"] == "hard-404"
    assert entry["source_pages"] == ["https://x.com/"]
    assert entry["anchor_text"] == ["Learn more"]
    assert entry["first_seen"] == "2026-07-23T00:00:00Z"


def test_human_readable_report_surfaces_newly_broken_before_still_broken():
    diff_result = DiffResult(
        newly_broken=[DiffEntry(url="https://x.com/new-break", classification="soft-404", first_seen="2026-07-23T00:00:00Z")],
        still_broken=[DiffEntry(url="https://x.com/old-break", classification="hard-404", first_seen="2026-07-18T00:00:00Z")],
    )
    report = build_report(diff_result, CURRENT_RUN, canary_passed=True)
    text = render_human_readable(report)

    assert text.index("new-break") < text.index("old-break")
    assert "NEWLY BROKEN" in text
    assert "STILL BROKEN" in text


def test_zero_broken_links_produces_all_clear_report():
    diff_result = DiffResult()
    report = build_report(diff_result, CURRENT_RUN, canary_passed=True)
    text = render_human_readable(report)
    assert "all clear" in text.lower()


def test_ambiguous_signals_are_surfaced_as_unverified_not_dropped_or_confirmed_broken():
    run_with_ambiguous = {
        "run_id": "2026-07-23T00:00:00Z",
        "results": [
            {
                "url": "https://external.com/blocked",
                "classification": "external-blocked",
                "source_pages": ["https://x.com/"],
                "anchor_text": ["Some Link"],
                "status_code": 403,
            },
            {
                "url": "https://external.com/slow",
                "classification": "external-timeout",
                "source_pages": ["https://x.com/"],
                "anchor_text": ["Another Link"],
            },
            {
                "url": "https://x.com/fine",
                "classification": "ok",
                "source_pages": [],
                "anchor_text": [],
            },
        ],
    }
    diff_result = DiffResult()  # nothing confirmed-broken this run
    report = build_report(diff_result, run_with_ambiguous, canary_passed=True)

    assert len(report["unverified"]) == 2
    urls = {e["url"] for e in report["unverified"]}
    assert urls == {"https://external.com/blocked", "https://external.com/slow"}

    text = render_human_readable(report)
    assert "all clear" in text.lower()  # zero CONFIRMED broken still reads as clean
    assert "UNVERIFIED" in text
    assert "external.com/blocked" in text


def test_confidence_field_distinguishes_confirmed_from_browser_verified():
    run = {
        "run_id": "2026-07-23T00:00:00Z",
        "results": [
            {
                "url": "https://x.com/broken",
                "classification": "hard-404",
                "source_pages": [],
                "anchor_text": [],
                "confidence": "confirmed",
            },
            {
                "url": "https://external.com/resurrected",
                "classification": "external-dead",
                "source_pages": [],
                "anchor_text": [],
                "confidence": "browser-verified",
            },
            {
                "url": "https://external.com/still-unsure",
                "classification": "external-blocked",
                "source_pages": [],
                "anchor_text": [],
                "confidence": "unverified",
            },
        ],
    }
    diff_result = DiffResult(
        newly_broken=[
            DiffEntry(url="https://x.com/broken", classification="hard-404", first_seen="2026-07-23T00:00:00Z"),
            DiffEntry(url="https://external.com/resurrected", classification="external-dead", first_seen="2026-07-23T00:00:00Z"),
        ]
    )
    report = build_report(diff_result, run, canary_passed=True)

    by_url = {e["url"]: e for e in report["newly_broken"]}
    assert by_url["https://x.com/broken"]["confidence"] == "confirmed"
    assert by_url["https://external.com/resurrected"]["confidence"] == "browser-verified"
    assert report["unverified"][0]["confidence"] == "unverified"


def test_human_readable_flags_broken_entries_that_never_got_escalated():
    run = {
        "run_id": "2026-07-23T00:00:00Z",
        "results": [
            {
                "url": "https://external.com/ran-out-of-budget",
                "classification": "external-dead",
                "source_pages": [],
                "anchor_text": [],
                "confidence": "unverified",
            },
        ],
    }
    diff_result = DiffResult(
        newly_broken=[
            DiffEntry(url="https://external.com/ran-out-of-budget", classification="external-dead", first_seen="2026-07-23T00:00:00Z")
        ]
    )
    text = render_human_readable(build_report(diff_result, run, canary_passed=True))
    assert "unverified — Olostep escalation did not run" in text


def test_no_run_at_all_reports_run_failed_and_omits_classification_results():
    # current_run=None means no run happened at all (e.g. site discovery itself failed)
    # — the sole case with nothing to report.
    report = build_report(None, None, canary_passed=False, canary_reason="site discovery failed: 500")
    assert report["run_failed"] is True
    assert "newly_broken" not in report

    text = render_human_readable(report)
    assert text.startswith("RUN FAILED")
    assert "site discovery failed: 500" in text


def test_canary_failure_does_not_abort_the_run_or_hide_other_results():
    # A failed canary only means the soft-404 fingerprint is unproven this run — the
    # rest of the run (hard-404s, external results) is unaffected and must still be
    # reported, not suppressed the way a fatal run_failed is.
    diff_result = DiffResult(
        newly_broken=[DiffEntry(url="https://x.com/broken", classification="hard-404", first_seen="2026-07-23T00:00:00Z")]
    )
    report = build_report(diff_result, CURRENT_RUN, canary_passed=False, canary_reason="fingerprint signals failed: title")

    assert report["run_failed"] is False
    assert report["canary"] == {"passed": False, "reason": "fingerprint signals failed: title"}
    assert report["newly_broken"][0]["url"] == "https://x.com/broken"

    text = render_human_readable(report)
    assert text.startswith("CANARY FAILED")
    assert "fingerprint signals failed: title" in text
    assert "NEWLY BROKEN" in text
    assert "x.com/broken" in text
