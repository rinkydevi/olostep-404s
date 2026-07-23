import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class CachedVerdict:
    classification: str
    confidence: str
    resolved_at: datetime


class VerdictCache:
    """Persists resolved external-link verdicts across runs so only new/changed links
    pay an Olostep escalation credit — a link resolved last run doesn't need
    re-resolving until its staleness window expires.
    """

    def __init__(self, entries: dict[str, CachedVerdict]):
        self._entries = entries

    @classmethod
    def load(cls, path) -> "VerdictCache":
        path = Path(path)
        if not path.exists():
            return cls({})
        raw = json.loads(path.read_text())
        entries = {
            url: CachedVerdict(
                classification=v["classification"],
                confidence=v["confidence"],
                resolved_at=datetime.fromisoformat(v["resolved_at"]),
            )
            for url, v in raw.items()
        }
        return cls(entries)

    def save(self, path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = {
            url: {
                "classification": v.classification,
                "confidence": v.confidence,
                "resolved_at": v.resolved_at.isoformat(),
            }
            for url, v in self._entries.items()
        }
        path.write_text(json.dumps(raw, indent=2))

    def get(self, url: str, now: datetime, staleness_days: int) -> CachedVerdict | None:
        entry = self._entries.get(url)
        if entry is None:
            return None
        age_days = (now - entry.resolved_at).total_seconds() / 86400
        if age_days > staleness_days:
            return None
        return entry

    def put(self, url: str, classification: str, confidence: str, resolved_at: datetime) -> None:
        self._entries[url] = CachedVerdict(
            classification=classification, confidence=confidence, resolved_at=resolved_at
        )
