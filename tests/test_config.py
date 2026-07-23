import pytest

from olostep_link_checker.config import ConfigError, load_config

FULL_YAML = """
site_url: "https://www.olostep.com"
exclude_patterns:
  - "/dashboard/**"
  - "/auth"
  - "/playground"
budget_ceiling: 600
canary_url: "https://www.olostep.com/this-page-definitely-does-not-exist-404-test"
concurrency: 10
runs_dir: "data/runs"
verdict_cache_path: "data/external_verdicts.json"
verdict_staleness_days: 14
"""

MINIMAL_YAML = """
site_url: "https://www.olostep.com"
canary_url: "https://www.olostep.com/this-page-definitely-does-not-exist-404-test"
"""


def write_config(tmp_path, content):
    path = tmp_path / "config.yaml"
    path.write_text(content)
    return path


def test_loads_full_config_with_api_key_from_env(tmp_path):
    path = write_config(tmp_path, FULL_YAML)
    config = load_config(path, env={"OLOSTEP_API_KEY": "secret-123"})

    assert config.site_url == "https://www.olostep.com"
    assert config.exclude_patterns == ["/dashboard/**", "/auth", "/playground"]
    assert config.budget_ceiling == 600
    assert config.concurrency == 10
    assert config.runs_dir == "data/runs"
    assert config.api_key == "secret-123"
    assert config.verdict_cache_path == "data/external_verdicts.json"
    assert config.verdict_staleness_days == 14


def test_missing_api_key_env_var_raises_config_error(tmp_path):
    path = write_config(tmp_path, FULL_YAML)
    with pytest.raises(ConfigError, match="OLOSTEP_API_KEY"):
        load_config(path, env={})


def test_defaults_applied_when_optional_fields_omitted(tmp_path):
    path = write_config(tmp_path, MINIMAL_YAML)
    config = load_config(path, env={"OLOSTEP_API_KEY": "secret-123"})

    assert config.exclude_patterns == []
    assert config.budget_ceiling is None  # no cap by default — unlimited
    assert config.concurrency == 10
    assert config.runs_dir == "data/runs"
    assert config.verdict_cache_path == "data/external_verdicts.json"
    assert config.verdict_staleness_days == 14


def test_missing_required_site_url_raises_config_error_not_key_error(tmp_path):
    path = write_config(tmp_path, 'canary_url: "https://x.com/404-test"\n')
    with pytest.raises(ConfigError, match="site_url"):
        load_config(path, env={"OLOSTEP_API_KEY": "secret-123"})


def test_missing_config_file_raises_config_error_not_file_not_found_error(tmp_path):
    missing_path = tmp_path / "does-not-exist.yaml"
    with pytest.raises(ConfigError, match="does-not-exist.yaml"):
        load_config(missing_path, env={"OLOSTEP_API_KEY": "secret-123"})


def test_missing_required_canary_url_raises_config_error(tmp_path):
    path = write_config(tmp_path, 'site_url: "https://x.com"\n')
    with pytest.raises(ConfigError, match="canary_url"):
        load_config(path, env={"OLOSTEP_API_KEY": "secret-123"})
