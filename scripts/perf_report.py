from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "log_file",
        nargs="?",
        default="workspace/logs/performance.jsonl",
        help="Path to performance.jsonl",
    )
    parser.add_argument("--run-id", default="latest", help="Specific BOOK2MP3_PERF_RUN_ID or 'latest'")
    parser.add_argument("--top", type=int, default=25, help="How many rows to print")
    return parser.parse_args()


def load_records(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def resolve_run_id(records: list[dict[str, object]], requested: str) -> str:
    if requested != "latest":
        return requested
    for record in reversed(records):
        run_id = str(record.get("run_id", "") or "")
        if run_id:
            return run_id
    return ""


def main() -> int:
    args = parse_args()
    log_path = Path(args.log_file)
    if not log_path.exists():
        raise SystemExit(f"Missing performance log: {log_path}")
    records = load_records(log_path)
    run_id = resolve_run_id(records, args.run_id)
    filtered = [record for record in records if not run_id or str(record.get("run_id", "") or "") == run_id]
    spans = [
        record
        for record in filtered
        if record.get("type") == "event"
        and isinstance(record.get("fields"), dict)
        and record["fields"].get("phase") == "end"
    ]
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for record in spans:
        fields = record["fields"]
        duration = float(fields.get("duration_ms", 0.0) or 0.0)
        grouped[(str(record.get("category", "")), str(record.get("name", "")))].append(duration)
    rows = []
    for (category, name), durations in grouped.items():
        rows.append(
            {
                "category": category,
                "name": name,
                "count": len(durations),
                "total_ms": round(sum(durations), 3),
                "avg_ms": round(sum(durations) / len(durations), 3),
                "max_ms": round(max(durations), 3),
            }
        )
    rows.sort(key=lambda item: item["total_ms"], reverse=True)
    print(json.dumps({"run_id": run_id, "rows": rows[: args.top]}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
