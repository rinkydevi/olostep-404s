from dataclasses import dataclass
from pathlib import Path

import yaml


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    site_url: str
    canary_url: str
    exclude_patterns: list[str]
    budget_ceiling: int | None
    concurrency: int
    runs_dir: str
    api_key: str
    verdict_cache_path: str
    verdict_staleness_days: int


def load_config(config_path, env: dict[str, str]) -> Config:
    config_path = Path(config_path)
    try:
        text = config_path.read_text()
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {config_path}") from exc

    data = yaml.safe_load(text) or {}

    api_key = env.get("OLOSTEP_API_KEY")
    if not api_key:
        raise ConfigError("OLOSTEP_API_KEY environment variable is required and was not set")

    if "site_url" not in data:
        raise ConfigError("config is missing required field: site_url")
    if "canary_url" not in data:
        raise ConfigError("config is missing required field: canary_url")

    return Config(
        site_url=data["site_url"],
        canary_url=data["canary_url"],
        exclude_patterns=data.get("exclude_patterns", []),
        budget_ceiling=data.get("budget_ceiling"),
        concurrency=data.get("concurrency", 10),
        runs_dir=data.get("runs_dir", "data/runs"),
        api_key=api_key,
        verdict_cache_path=data.get("verdict_cache_path", "data/external_verdicts.json"),
        verdict_staleness_days=data.get("verdict_staleness_days", 14),
    )
