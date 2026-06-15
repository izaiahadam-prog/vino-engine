"""Run a deterministic smoke test for the VINO external-validation pipeline."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str]) -> dict[str, object]:
    completed = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
    return {
        "cmd": cmd,
        "returncode": completed.returncode,
        "ok": completed.returncode == 0,
        "stdout_tail": completed.stdout[-1200:],
        "stderr_tail": completed.stderr[-1200:],
    }


def main() -> None:
    commands = [
        [sys.executable, "-m", "vino_cli.main", "ingest", "--config", "ingestion_config.example.json"],
        [sys.executable, "-m", "vino_cli.main", "validate-ingestion"],
        [
            sys.executable,
            "-m",
            "vino_cli.main",
            "build-candidates",
            "--input",
            "data/external",
            "--out",
            "data/candidates",
            "--validation-config",
            "vino_validation_config.example.json",
        ],
        [
            sys.executable,
            "-m",
            "vino_cli.main",
            "evaluate",
            "--candidates",
            "data/candidates",
            "--out",
            "results/external_validation",
            "--validation-config",
            "vino_validation_config.example.json",
        ],
        [sys.executable, "-m", "vino_cli.main", "report", "--results", "results/external_validation"],
    ]
    results = [run(cmd) for cmd in commands]
    required_outputs = [
        ROOT / "data" / "external" / "git_repos.jsonl",
        ROOT / "data" / "external" / "wikipedia_revisions.jsonl",
        ROOT / "data" / "external" / "paper_lineage.jsonl",
        ROOT / "data" / "external" / "dataset_provenance.jsonl",
        ROOT / "data" / "external" / "software_symbols.jsonl",
        ROOT / "data" / "candidates" / "continuation_tasks.jsonl",
        ROOT / "results" / "external_validation" / "external_validation_results.json",
        ROOT / "results" / "external_validation" / "external_validation_report.txt",
        ROOT / "results" / "external_validation" / "external_validation_report.json",
    ]
    payload = {
        "ok": all(result["ok"] for result in results) and all(path.exists() for path in required_outputs),
        "commands": results,
        "required_outputs": [{"path": str(path), "exists": path.exists()} for path in required_outputs],
        "limitations": [
            "This smoke test verifies pipeline execution, not VINO validity.",
            "Sample-data results are not proof of continuation-under-uncertainty behavior.",
        ],
    }
    out = ROOT / "results" / "external_validation" / "smoke_test_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    if not payload["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
