import olostep_link_checker.cli as cli_module
from olostep_link_checker import __version__
from olostep_link_checker.cli import main, parse_args


def test_version_flag_prints_version_and_exits(capsys):
    try:
        parse_args(["--version"])
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("--version should exit")
    captured = capsys.readouterr()
    assert __version__ in captured.out


def test_init_writes_config_and_refuses_to_overwrite_without_force(tmp_path, capsys):
    output_path = tmp_path / "config.yaml"

    exit_code = main(["init", "--output", str(output_path), "--site-url", "https://example.org"])
    assert exit_code == 0
    assert output_path.exists()
    content = output_path.read_text()
    assert 'site_url: "https://example.org"' in content
    assert "https://example.org/this-page-definitely-does-not-exist-404-test" in content

    exit_code_again = main(["init", "--output", str(output_path), "--site-url", "https://other.example"])
    assert exit_code_again == 1
    captured = capsys.readouterr()
    assert "already exists" in captured.err
    assert 'site_url: "https://example.org"' in output_path.read_text()


def test_init_force_overwrites_existing_config(tmp_path):
    output_path = tmp_path / "config.yaml"
    output_path.write_text("stale content")

    exit_code = main(["init", "--output", str(output_path), "--site-url", "https://new.example", "--force"])
    assert exit_code == 0
    assert 'site_url: "https://new.example"' in output_path.read_text()


def test_parse_args_defaults():
    args = parse_args([])
    assert args.config == "config.yaml"
    assert args.retention_days == 90
    assert args.csv is None


def test_parse_args_overrides():
    args = parse_args(["--config", "custom.yaml", "--retention-days", "30", "--csv", "out.csv"])
    assert args.config == "custom.yaml"
    assert args.retention_days == 30
    assert args.csv == "out.csv"


def _valid_config(tmp_path, monkeypatch):
    monkeypatch.setenv("OLOSTEP_API_KEY", "test-key")
    config_path = tmp_path / "config.yaml"
    config_path.write_text('site_url: "https://x.com"\ncanary_url: "https://x.com/404-test"\n')
    return config_path


def test_main_writes_csv_and_prints_pipe_table_when_csv_flag_given(tmp_path, monkeypatch, capsys):
    config_path = _valid_config(tmp_path, monkeypatch)
    csv_path = tmp_path / "broken.csv"

    canned_run = {
        "run_id": "2026-07-23T00:00:00Z",
        "results": [
            {
                "url": "https://x.com/broken",
                "classification": "hard-404",
                "status_code": 404,
                "source_pages": ["https://x.com/"],
                "anchor_text": ["Learn more"],
                "not_in_sitemap": False,
            }
        ],
    }

    async def fake_async_main(config, retention_days):
        from olostep_link_checker.differ import diff
        from olostep_link_checker.report import build_report

        diff_result = diff(None, canned_run)
        report = build_report(diff_result, canned_run, canary_passed=True)
        return {"report": report, "run": canned_run, "exit_code": 0}

    monkeypatch.setattr(cli_module, "_async_main", fake_async_main)

    exit_code = main(["--config", str(config_path), "--csv", str(csv_path)])

    assert exit_code == 0
    assert csv_path.exists()
    csv_content = csv_path.read_text()
    assert "https://x.com/broken" in csv_content

    captured = capsys.readouterr()
    assert "url | from | status" in captured.out
    assert "https://x.com/broken" in captured.out


def test_main_skips_csv_when_flag_not_given(tmp_path, monkeypatch):
    config_path = _valid_config(tmp_path, monkeypatch)

    async def fake_async_main(config, retention_days):
        return {"report": {"trusted": True, "run_failed": False, "canary": {"passed": True, "reason": None}, "new_baseline": [], "newly_broken": [], "still_broken": [], "fixed": [], "no_longer_scanned": [], "unverified": []}, "run": {"run_id": "x", "results": []}, "exit_code": 0}

    monkeypatch.setattr(cli_module, "_async_main", fake_async_main)

    exit_code = main(["--config", str(config_path)])
    assert exit_code == 0
    assert not (tmp_path / "broken.csv").exists()


def test_main_returns_config_error_exit_code_when_config_file_missing(tmp_path, capsys):
    missing_path = tmp_path / "does-not-exist.yaml"
    exit_code = main(["--config", str(missing_path)])
    assert exit_code == 4
    captured = capsys.readouterr()
    assert "Configuration error" in captured.err


def test_main_returns_config_error_exit_code_when_api_key_missing(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("OLOSTEP_API_KEY", raising=False)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        'site_url: "https://x.com"\ncanary_url: "https://x.com/404-test"\n'
    )
    exit_code = main(["--config", str(config_path)])
    assert exit_code == 4
    captured = capsys.readouterr()
    assert "OLOSTEP_API_KEY" in captured.err
