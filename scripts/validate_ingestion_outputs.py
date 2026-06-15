"""Validate normalized ingestion JSONL outputs."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.common import SCHEMA_FIELDS, read_jsonl, write_jsonl


ROOT = Path(__file__).resolve().parents[1]
EXTERNAL = ROOT / "data" / "external"
OUT_TXT = ROOT / "results" / "ingestion_validation_report.txt"
OUT_JSON = ROOT / "results" / "ingestion_validation_report.json"
EXPECTED = {
    "git_repos.jsonl": "git_repositories",
    "wikipedia_revisions.jsonl": "wikipedia_revisions",
    "paper_lineage.jsonl": "paper_lineage",
    "dataset_provenance.jsonl": "dataset_provenance",
    "software_symbols.jsonl": "software_symbols",
}


def validate_file(path: Path, expected_domain: str) -> dict[str, Any]:
    records = read_jsonl(path)
    missing_rows = []
    wrong_domain = 0
    event_counts: dict[str, int] = {}
    for idx, record in enumerate(records, start=1):
        missing = [field for field in SCHEMA_FIELDS if field not in record]
        if missing:
            missing_rows.append({"line": idx, "missing_fields": missing})
        if record.get("domain") != expected_domain:
            wrong_domain += 1
        event = record.get("event_type", "unknown")
        event_counts[event] = event_counts.get(event, 0) + 1
    return {
        "file": str(path),
        "exists": path.exists(),
        "expected_domain": expected_domain,
        "record_count": len(records),
        "missing_field_rows": missing_rows,
        "wrong_domain_count": wrong_domain,
        "event_counts": event_counts,
        "valid": path.exists() and not missing_rows and wrong_domain == 0,
    }


def render_txt(payload: dict[str, Any]) -> str:
    lines = [
        "Ingestion Output Validation Report",
        "",
        f"overall_valid: {payload['overall_valid']}",
        f"total_records: {payload['total_records']}",
        "",
        "Files",
    ]
    for result in payload["files"]:
        lines.append(
            f"{Path(result['file']).name}: exists={result['exists']}, valid={result['valid']}, records={result['record_count']}, domain={result['expected_domain']}"
        )
        if result["missing_field_rows"]:
            lines.append(f"  missing fields: {result['missing_field_rows'][:5]}")
        if result["wrong_domain_count"]:
            lines.append(f"  wrong domain count: {result['wrong_domain_count']}")
    lines.extend(
        [
            "",
            "Limitations",
            "These scripts ingest and normalize data.",
            "They do not prove VINO.",
            "They do not validate continuation yet.",
            "They create the external-data substrate for validation.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    results = [validate_file(EXTERNAL / filename, domain) for filename, domain in EXPECTED.items()]
    payload = {
        "files": results,
        "overall_valid": all(result["valid"] for result in results),
        "total_records": sum(result["record_count"] for result in results),
        "records_by_domain": {result["expected_domain"]: result["record_count"] for result in results},
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    OUT_TXT.write_text(render_txt(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
