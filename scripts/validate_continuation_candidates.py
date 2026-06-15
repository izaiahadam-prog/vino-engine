"""Validate VINO continuation-candidate outputs."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.build_vino_continuation_candidates import CANDIDATE_FIELDS, validate_candidate
from ingestion.common import ensure_dir, read_jsonl, save_manifest


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATES = ROOT / "data" / "external" / "continuation_candidates" / "vino_continuation_candidates.jsonl"
OUT_TXT = ROOT / "results" / "continuation_candidate_validation_report.txt"
OUT_JSON = ROOT / "results" / "continuation_candidate_validation_report.json"


def validate(path: Path = DEFAULT_CANDIDATES) -> dict[str, Any]:
    records = read_jsonl(path)
    problems = []
    for idx, record in enumerate(records, start=1):
        row_problems = validate_candidate(record)
        if row_problems:
            problems.append({"row": idx, "candidate_id": record.get("candidate_id"), "problems": row_problems})
    by_domain = Counter(record.get("domain") for record in records)
    by_type = Counter(record.get("candidate_type") for record in records)
    explicit_or_high = sum(1 for row in records if row.get("ground_truth", {}).get("label_confidence", 0.0) >= 0.95)
    weak = sum(1 for row in records if row.get("ground_truth", {}).get("label_confidence", 0.0) < 0.95)
    metrics = {
        "candidate_file": str(path),
        "exists": path.exists(),
        "record_count": len(records),
        "records_by_domain": dict(by_domain),
        "records_by_candidate_type": dict(by_type),
        "high_confidence_label_count": explicit_or_high,
        "weak_label_count": weak,
        "missing_or_invalid_rows": problems[:200],
        "overall_valid": path.exists() and bool(records) and not problems,
        "schema_fields": CANDIDATE_FIELDS,
    }
    return metrics


def write_text_report(payload: dict[str, Any]) -> None:
    ensure_dir(OUT_TXT.parent)
    lines = [
        "VINO Continuation Candidate Validation Report",
        "",
        f"candidate_file: {payload['candidate_file']}",
        f"overall_valid: {payload['overall_valid']}",
        f"record_count: {payload['record_count']}",
        "",
        "records by domain",
    ]
    for domain, count in sorted(payload["records_by_domain"].items()):
        lines.append(f"{domain}: {count}")
    lines.extend(["", "records by candidate type"])
    for candidate_type, count in sorted(payload["records_by_candidate_type"].items()):
        lines.append(f"{candidate_type}: {count}")
    lines.extend(
        [
            "",
            f"high_confidence_label_count: {payload['high_confidence_label_count']}",
            f"weak_label_count: {payload['weak_label_count']}",
            f"invalid_row_count: {len(payload['missing_or_invalid_rows'])}",
            "",
            "Limitations:",
            "These records are candidate successor pairs and weak deterministic features.",
            "They do not validate VINO and they do not replace benchmark scoring.",
        ]
    )
    OUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    payload = validate()
    save_manifest(OUT_JSON, payload)
    write_text_report(payload)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
