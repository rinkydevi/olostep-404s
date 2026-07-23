from typing import Callable

from .patterns import matches_exclude
from .retry import retry_sync


def discover_urls(
    create_map_fn: Callable[[], list[str]],
    exclude_patterns: list[str],
    max_attempts: int = 3,
    sleep_fn: Callable[[float], None] = lambda s: None,
) -> set[str]:
    urls = retry_sync(create_map_fn, max_attempts=max_attempts, sleep_fn=sleep_fn)
    return {u for u in urls if not matches_exclude(u, exclude_patterns)}
