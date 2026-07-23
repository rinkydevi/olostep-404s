import csv
from pathlib import Path

from .differ import BROKEN_CLASSIFICATIONS


def flat_broken_list(run: dict) -> list[dict]:
    rows = []
    for r in run["results"]:
        if r["classification"] not in BROKEN_CLASSIFICATIONS:
            continue
        source_pages = r.get("source_pages") or []
        status = r["classification"]
        if r.get("status_code"):
            status = f"{status} ({r['status_code']})"
        rows.append(
            {
                "url": r["url"],
                "from": source_pages[0] if source_pages else "",
                "status": status,
            }
        )
    return sorted(rows, key=lambda row: row["url"])


def render_pipe_table(rows: list[dict]) -> str:
    if not rows:
        return "url | from | status\n(no confirmed broken links)"
    lines = ["url | from | status"]
    for row in rows:
        lines.append(f"{row['url']} | {row['from']} | {row['status']}")
    return "\n".join(lines)


def write_csv(rows: list[dict], path) -> None:
    path = Path(path)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["url", "from", "status"])
        for row in rows:
            writer.writerow([row["url"], row["from"], row["status"]])
