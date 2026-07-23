import json
from datetime import datetime, timezone
from pathlib import Path


def _safe_filename(run_id: str) -> str:
    return run_id.replace(":", "-") + ".json"


def save_run(run: dict, runs_dir: Path) -> Path:
    runs_dir = Path(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / _safe_filename(run["run_id"])
    path.write_text(json.dumps(run, indent=2))
    return path


def load_run(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def _run_files(runs_dir: Path) -> list[Path]:
    runs_dir = Path(runs_dir)
    if not runs_dir.exists():
        return []
    return sorted(runs_dir.glob("*.json"))


def get_previous_run(runs_dir: Path) -> dict | None:
    files = _run_files(runs_dir)
    if not files:
        return None
    return load_run(files[-1])


def prune_older_than(runs_dir: Path, days: int, now: datetime | None = None) -> list[Path]:
    now = now or datetime.now(timezone.utc)
    deleted = []
    for path in _run_files(runs_dir):
        run = load_run(path)
        run_time = datetime.fromisoformat(run["run_id"].replace("Z", "+00:00"))
        age_days = (now - run_time).total_seconds() / 86400
        if age_days > days:
            path.unlink()
            deleted.append(path)
    return deleted
