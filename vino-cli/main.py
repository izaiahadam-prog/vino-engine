"""Command-line entry point for VINO external validation."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from ingestion.run_all_ingestion import create_samples, load_or_create_config, run_jobs
from vino_cli.candidates import build_candidate_tasks
from vino_cli.config import load_validation_config, write_example_configs
from vino_cli.evaluator import evaluate_file
from vino_cli.io import ROOT, read_json, write_json
from vino_cli.reporting import build_report


def cmd_ingest(args: argparse.Namespace) -> dict[str, Any]:
    create_samples()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    config = load_or_create_config(config_path)
    results = run_jobs(config)
    payload = {
        "command": "ingest",
        "config": str(config_path),
        "outputs": results,
        "limitations": [
            "These scripts ingest and normalize data.",
            "They do not prove VINO or validate continuation.",
        ],
    }
    write_json("data/external/ingestion_manifest.json", payload)
    return payload


def cmd_validate_ingestion(args: argparse.Namespace) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_ingestion_outputs.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return {"command": "validate-ingestion", "ok": False, "stderr": completed.stderr}
    return read_json("results/ingestion_validation_report.json", default={"ok": False})


def cmd_build_candidates(args: argparse.Namespace) -> dict[str, Any]:
    config = load_validation_config(args.validation_config)
    domains = config.get("domains_enabled", [])
    return build_candidate_tasks(args.input, args.out, domains)


def cmd_evaluate(args: argparse.Namespace) -> dict[str, Any]:
    candidate_path = Path(args.candidates)
    if candidate_path.is_dir() or not candidate_path.suffix:
        candidate_path = candidate_path / "continuation_tasks.jsonl"
    return evaluate_file(str(candidate_path), args.out, args.validation_config)


def cmd_report(args: argparse.Namespace) -> dict[str, Any]:
    return build_report(args.results)


def cmd_run_all(args: argparse.Namespace) -> dict[str, Any]:
    ingest = cmd_ingest(args)
    validation = cmd_validate_ingestion(args)
    config = load_validation_config(args.validation_config)
    candidate_out = config.get("output_paths", {}).get("candidate_dir", "data/candidates")
    results_out = config.get("output_paths", {}).get("results_dir", "results/external_validation")
    candidates = build_candidate_tasks("data/external", candidate_out, config.get("domains_enabled", []))
    evaluation = evaluate_file(str(Path(candidate_out) / "continuation_tasks.jsonl"), results_out, args.validation_config)
    report = build_report(results_out)
    return {
        "command": "run-all",
        "ingestion": ingest,
        "ingestion_validation": validation,
        "candidate_build": candidates,
        "evaluation_metrics": evaluation.get("metrics", {}),
        "report_summary": report.get("summary", {}),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Run configured ingestion jobs.")
    ingest.add_argument("--config", default="ingestion_config.json")
    ingest.set_defaults(func=cmd_ingest)

    validate = sub.add_parser("validate-ingestion", help="Validate normalized ingestion outputs.")
    validate.set_defaults(func=cmd_validate_ingestion)

    build = sub.add_parser("build-candidates", help="Build successor-selection candidate tasks.")
    build.add_argument("--input", default="data/external")
    build.add_argument("--out", default="data/candidates")
    build.add_argument("--validation-config", default=None)
    build.set_defaults(func=cmd_build_candidates)

    evaluate = sub.add_parser("evaluate", help="Evaluate VINO and baseline models.")
    evaluate.add_argument("--candidates", default="data/candidates")
    evaluate.add_argument("--out", default="results/external_validation")
    evaluate.add_argument("--validation-config", default=None)
    evaluate.set_defaults(func=cmd_evaluate)

    report = sub.add_parser("report", help="Build TXT and JSON reports.")
    report.add_argument("--results", default="results/external_validation")
    report.set_defaults(func=cmd_report)

    run_all = sub.add_parser("run-all", help="Run ingestion, validation, candidate build, evaluation, and reporting.")
    run_all.add_argument("--config", default="ingestion_config.json")
    run_all.add_argument("--validation-config", default=None)
    run_all.set_defaults(func=cmd_run_all)

    examples = sub.add_parser("write-example-configs", help="Write example ingestion and validation configs.")
    examples.set_defaults(func=lambda _args: (write_example_configs() or {"command": "write-example-configs", "ok": True}))
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    payload = args.func(args)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
