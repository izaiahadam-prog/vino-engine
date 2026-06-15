"""Reporting for VINO external validation."""

from __future__ import annotations

from typing import Any

from vino_cli.config import DEFAULT_VALIDATION_CONFIG
from vino_cli.io import ensure_dir, read_json, write_json, write_text


def build_report(results_dir: str) -> dict[str, Any]:
    output_dir = ensure_dir(results_dir)
    results = read_json(output_dir / "external_validation_results.json", default={}) or {}
    metrics = results.get("metrics", {})
    task_results = results.get("task_results", [])
    failure_cases = []
    win_cases = []
    for row in task_results:
        gt = row.get("ground_truth_successor_id")
        vino = row.get("vino_result", {})
        if gt is None:
            continue
        if vino.get("selected_candidate_id") == gt:
            win_cases.append({"task_id": row.get("task_id"), "domain": row.get("domain"), "selected": gt})
        else:
            failure_cases.append(
                {
                    "task_id": row.get("task_id"),
                    "domain": row.get("domain"),
                    "ground_truth": gt,
                    "vino_selected": vino.get("selected_candidate_id"),
                    "refusal_reason": vino.get("refusal_reason"),
                }
            )
    report = {
        "summary": {
            "domains_evaluated": metrics.get("domains_evaluated", []),
            "task_count": metrics.get("task_count", 0),
            "continuation_model_accuracy": metrics.get("continuation_model_accuracy"),
            "best_baseline_accuracy": metrics.get("best_baseline_accuracy"),
            "continuation_advantage": metrics.get("continuation_advantage"),
            "domain_transfer_score": metrics.get("domain_transfer_score"),
        },
        "metrics": metrics,
        "cases_where_vino_wins": win_cases[:100],
        "cases_where_vino_fails": failure_cases[:100],
        "refusal_or_failure_cases": [
            {
                "task_id": row.get("task_id"),
                "domain": row.get("domain"),
                "reason": row.get("vino_result", {}).get("refusal_reason"),
            }
            for row in task_results
            if row.get("vino_result", {}).get("refusal_reason")
        ][:100],
        "limitations": DEFAULT_VALIDATION_CONFIG["limitations"],
        "next_recommended_validation": "Run ingestion on larger real external datasets with known continuation labels, then compare against these same baselines without retuning.",
    }
    write_json(output_dir / "external_validation_report.json", report)
    write_text(output_dir / "external_validation_report.txt", render_text(report))
    return report


def render_text(report: dict[str, Any]) -> str:
    summary = report["summary"]
    metrics = report.get("metrics", {})
    lines = [
        "VINO External Validation Report",
        "",
        "Purpose",
        "Test whether continuation-under-uncertainty predicts successor selection better than ordinary baselines across external/public-data tasks.",
        "",
        "Domains evaluated",
        ", ".join(summary.get("domains_evaluated", [])) or "none",
        "",
        "Task counts",
        f"total_tasks: {summary.get('task_count', 0)}",
        "",
        "VINO vs baselines",
        f"continuation_model_accuracy: {summary.get('continuation_model_accuracy')}",
        f"best_baseline_accuracy: {summary.get('best_baseline_accuracy')}",
        f"continuation_advantage: {summary.get('continuation_advantage')}",
        f"domain_transfer_score: {summary.get('domain_transfer_score')}",
        "",
        "Model comparison table",
    ]
    global_models = metrics.get("global_model_metrics", {})
    for model, row in sorted(global_models.items()):
        lines.append(
            f"{model}: tasks={row['task_count']}, gt={row['ground_truth_available_count']}, "
            f"accuracy={row['accuracy_if_ground_truth']}, auth={row['authorization_rate']:.3f}, "
            f"refusal={row['refusal_rate']:.3f}, vino_agreement={row.get('selection_agreement_with_vino', 0.0):.3f}, "
            f"confidence={row['average_confidence']:.3f}"
        )
    lines.extend(["", "Cases where VINO wins"])
    if report["cases_where_vino_wins"]:
        for case in report["cases_where_vino_wins"][:20]:
            lines.append(f"{case['domain']} task={case['task_id']} selected={case['selected']}")
    else:
        lines.append("No ground-truth win cases found in this run.")
    lines.extend(["", "Cases where VINO fails"])
    if report["cases_where_vino_fails"]:
        for case in report["cases_where_vino_fails"][:20]:
            lines.append(
                f"{case['domain']} task={case['task_id']} gt={case['ground_truth']} selected={case['vino_selected']} reason={case['refusal_reason']}"
            )
    else:
        lines.append("No ground-truth failure cases found in this run.")
    lines.extend(["", "Refusal/failure cases"])
    if report["refusal_or_failure_cases"]:
        for case in report["refusal_or_failure_cases"][:20]:
            lines.append(f"{case['domain']} task={case['task_id']} reason={case['reason']}")
    else:
        lines.append("No VINO refusal cases found in this run.")
    lines.extend(["", "Limitations"])
    lines.extend(report["limitations"])
    lines.extend(["", "Next recommended validation", report["next_recommended_validation"], ""])
    return "\n".join(lines)
