from dataclasses import dataclass
from typing import Awaitable, Callable

from .classifier import soft_404_signals


@dataclass(frozen=True)
class CanaryResult:
    passed: bool
    reason: str | None = None


async def run_canary(fetch_fn: Callable[[str], Awaitable[str]], canary_url: str) -> CanaryResult:
    try:
        html = await fetch_fn(canary_url)
    except Exception:
        return CanaryResult(passed=False, reason="canary unreachable")

    signals = soft_404_signals(html)
    if all(signals.values()):
        return CanaryResult(passed=True, reason=None)

    failed_signals = [name for name, matched in signals.items() if not matched]
    reason = "fingerprint signals failed: " + ", ".join(failed_signals)
    return CanaryResult(passed=False, reason=reason)
