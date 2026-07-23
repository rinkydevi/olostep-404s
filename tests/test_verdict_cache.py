from datetime import datetime, timezone

from olostep_link_checker.verdict_cache import VerdictCache

NOW = datetime(2026, 7, 23, tzinfo=timezone.utc)


def test_empty_cache_has_no_entries(tmp_path):
    cache = VerdictCache.load(tmp_path / "verdicts.json")
    assert cache.get("https://example.com/x", now=NOW, staleness_days=14) is None


def test_round_trips_a_saved_verdict(tmp_path):
    path = tmp_path / "verdicts.json"
    cache = VerdictCache.load(path)
    cache.put("https://example.com/x", classification="ok", confidence="browser-verified", resolved_at=NOW)
    cache.save(path)

    reloaded = VerdictCache.load(path)
    entry = reloaded.get("https://example.com/x", now=NOW, staleness_days=14)
    assert entry is not None
    assert entry.classification == "ok"
    assert entry.confidence == "browser-verified"


def test_stale_entry_is_not_returned(tmp_path):
    cache = VerdictCache.load(tmp_path / "verdicts.json")
    old = datetime(2026, 7, 1, tzinfo=timezone.utc)
    cache.put("https://example.com/x", classification="ok", confidence="browser-verified", resolved_at=old)

    entry = cache.get("https://example.com/x", now=NOW, staleness_days=14)
    assert entry is None  # 22 days old, staleness window is 14


def test_fresh_entry_within_staleness_window_is_returned(tmp_path):
    cache = VerdictCache.load(tmp_path / "verdicts.json")
    recent = datetime(2026, 7, 20, tzinfo=timezone.utc)
    cache.put("https://example.com/x", classification="external-dead", confidence="browser-verified", resolved_at=recent)

    entry = cache.get("https://example.com/x", now=NOW, staleness_days=14)
    assert entry is not None
    assert entry.classification == "external-dead"


def test_missing_file_loads_as_empty_cache_not_an_error(tmp_path):
    cache = VerdictCache.load(tmp_path / "does-not-exist.json")
    assert cache.get("https://example.com/x", now=NOW, staleness_days=14) is None


def test_put_overwrites_existing_entry_for_same_url(tmp_path):
    cache = VerdictCache.load(tmp_path / "verdicts.json")
    cache.put("https://example.com/x", classification="external-dead", confidence="browser-verified", resolved_at=NOW)
    cache.put("https://example.com/x", classification="ok", confidence="browser-verified", resolved_at=NOW)

    entry = cache.get("https://example.com/x", now=NOW, staleness_days=14)
    assert entry.classification == "ok"
