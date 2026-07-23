import json
from datetime import datetime, timezone

from olostep_link_checker.store import get_previous_run, load_run, prune_older_than, save_run

SAMPLE_RUN = {
    "run_id": "2026-07-23T20:15:00Z",
    "site_scope": ["https://www.olostep.com"],
    "excluded_patterns": ["/dashboard/**"],
    "canary": {"passed": True, "fingerprint_version": "v1"},
    "urls_scanned": 3,
    "credits_consumed": 3,
    "duration_seconds": 12.5,
    "results": [],
}


def test_saving_a_run_produces_a_json_file_in_runs_dir(tmp_path):
    path = save_run(SAMPLE_RUN, tmp_path)
    assert path.exists()
    assert path.suffix == ".json"
    assert path.parent == tmp_path


def test_written_run_round_trips_identically(tmp_path):
    path = save_run(SAMPLE_RUN, tmp_path)
    loaded = load_run(path)
    assert loaded == SAMPLE_RUN


def test_get_previous_run_returns_none_when_no_prior_run_exists(tmp_path):
    assert get_previous_run(tmp_path) is None


def test_get_previous_run_returns_none_when_runs_dir_does_not_exist(tmp_path):
    missing_dir = tmp_path / "does-not-exist"
    assert get_previous_run(missing_dir) is None


def test_get_previous_run_returns_the_most_recent_by_run_id(tmp_path):
    older = {**SAMPLE_RUN, "run_id": "2026-07-20T00:00:00Z"}
    middle = {**SAMPLE_RUN, "run_id": "2026-07-22T00:00:00Z"}
    newest = {**SAMPLE_RUN, "run_id": "2026-07-23T00:00:00Z"}
    for run in (middle, older, newest):  # write out of order on purpose
        save_run(run, tmp_path)

    previous = get_previous_run(tmp_path)
    assert previous["run_id"] == "2026-07-23T00:00:00Z"


def test_prune_older_than_deletes_old_runs_and_keeps_recent_ones(tmp_path):
    old_run = {**SAMPLE_RUN, "run_id": "2026-01-01T00:00:00Z"}
    recent_run = {**SAMPLE_RUN, "run_id": "2026-07-20T00:00:00Z"}
    save_run(old_run, tmp_path)
    save_run(recent_run, tmp_path)

    now = datetime(2026, 7, 23, tzinfo=timezone.utc)
    deleted = prune_older_than(tmp_path, days=30, now=now)

    remaining_ids = {json.loads(p.read_text())["run_id"] for p in tmp_path.glob("*.json")}
    assert remaining_ids == {"2026-07-20T00:00:00Z"}
    assert len(deleted) == 1
