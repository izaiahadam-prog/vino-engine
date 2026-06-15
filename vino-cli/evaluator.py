"""Evaluate VINO continuation-integrity selector against baselines."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from vino_cli.baselines import run_baselines
from vino_cli.config import load_validation_config
from vino_cli.io import ensure_dir, read_jsonl, write_json, write_jsonl


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def score_vino_candidate(candidate: dict[str, Any], config: dict[str, Any]) -> float:
    scores = candidate.get("scores", {})
    weights = config.get("scoring_weights", {})
    total_weight = sum(float(value) for value in weights.values()) or 1.0
    weighted = sum(float(weights.get(key, 0.0)) * float(scores.get(key, 0.0)) for key in weights)
    return clamp01(weighted / total_weight)


def continuation_integrity_model(task: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    candidates = task.get("candidate_successors", [])
    if not candidates:
        return {
            "model": "continuation_integrity_model",
            "selected_candidate_id": None,
            "score": 0.0,
            "authorized": False,
            "refusal_reason": "no_candidates",
            "explanation": "No successor candidates were available.",
        }
    entropy_floor_default = float(config.get("entropy_floor", 0.35))
    authorization_threshold = float(config.get("authorization_threshold", 0.50))
    convergence_threshold = float(config.get("convergence_threshold", 0.20))
    ranked = []
    for candidate in candidates:
        score = score_vino_candidate(candidate, config)
        entropy_floor = min(entropy_floor_default, float(candidate.get("scores", {}).get("entropy_floor", entropy_floor_default)))
        convergence = float(candidate.get("scores", {}).get("Sigma_J_convergence", 0.0))
        ranked.append({**candidate, "vino_score": score, "entropy_floor_for_authorization": entropy_floor, "convergence": convergence})
    ranked.sort(key=lambda row: row["vino_score"], reverse=True)
    best = ranked[0]
    margin = best["vino_score"] - ranked[1]["vino_score"] if len(ranked) > 1 else best["vino_score"]
    authorized = (
        best["vino_score"] > best["entropy_floor_for_authorization"]
        and best["vino_score"] >= authorization_threshold
        and best["convergence"] >= convergence_threshold
    )
    return {
        "model": "continuation_integrity_model",
        "selected_candidate_id": best.get("candidate_id") if authorized else None,
        "best_candidate_id": best.get("candidate_id"),
        "score": best["vino_score"],
        "confidence": best["vino_score"],
        "margin": margin,
        "authorized": authorized,
        "refusal_reason": None if authorized else "continuation_integrity_below_authorization_rule",
        "explanation": (
            "Authorized successor by recoverability, faithful transfer, why-chain, accountable lineage, distortion reduction, successor viability, and Sigma/J convergence."
            if authorized
            else "No successor authorized because continuation integrity or Sigma/J convergence did not clear the entropy floor and authorization rule."
        ),
    }


def evaluate_tasks(tasks: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    rows = []
    seed = int(config.get("random_seed", 7))
    for task in tasks:
        vino = continuation_integrity_model(task, config)
        baselines = run_baselines(task, seed=seed)
        ground_truth = task.get("ground_truth_successor_id")
        model_results = [vino] + baselines
        for result in model_results:
            selected = result.get("selected_candidate_id")
            result["correct_if_ground_truth"] = selected == ground_truth if ground_truth is not None else None
            result["ground_truth_successor_id"] = ground_truth
            result["task_id"] = task.get("task_id")
            result["domain"] = task.get("domain")
            result["selection_agreement_with_vino"] = selected == vino.get("selected_candidate_id")
        rows.append(
            {
                "task_id": task.get("task_id"),
                "domain": task.get("domain"),
                "ground_truth_successor_id": ground_truth,
                "candidate_count": len(task.get("candidate_successors", [])),
                "vino_result": vino,
                "baseline_results": baselines,
            }
        )
    return {"task_results": rows, "metrics": compute_metrics(rows)}


def compute_metrics(task_results: list[dict[str, Any]]) -> dict[str, Any]:
    flat = []
    for row in task_results:
        flat.append(row["vino_result"])
        flat.extend(row["baseline_results"])

    by_domain_model: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in flat:
        by_domain_model[(result["domain"], result["model"])].append(result)
        by_model[result["model"]].append(result)

    domain_model_metrics = {}
    for (domain, model), rows in sorted(by_domain_model.items()):
        domain_model_metrics.setdefault(domain, {})[model] = summarize_model(rows)

    global_model_metrics = {model: summarize_model(rows) for model, rows in sorted(by_model.items())}
    vino_acc = global_model_metrics.get("continuation_integrity_model", {}).get("accuracy_if_ground_truth")
    baseline_accs = [
        metric.get("accuracy_if_ground_truth")
        for model, metric in global_model_metrics.items()
        if model != "continuation_integrity_model" and metric.get("accuracy_if_ground_truth") is not None
    ]
    best_baseline_accuracy = max(baseline_accs) if baseline_accs else None
    domains_where_vino_wins = []
    domains_where_baseline_wins = []
    for domain, models in domain_model_metrics.items():
        vino = models.get("continuation_integrity_model", {}).get("accuracy_if_ground_truth")
        baselines = [
            metric.get("accuracy_if_ground_truth")
            for model, metric in models.items()
            if model != "continuation_integrity_model" and metric.get("accuracy_if_ground_truth") is not None
        ]
        if vino is None or not baselines:
            continue
        if vino > max(baselines):
            domains_where_vino_wins.append(domain)
        elif vino < max(baselines):
            domains_where_baseline_wins.append(domain)
    return {
        "task_count": len(task_results),
        "domains_evaluated": sorted({row["domain"] for row in task_results}),
        "domain_model_metrics": domain_model_metrics,
        "global_model_metrics": global_model_metrics,
        "continuation_model_accuracy": vino_acc,
        "best_baseline_accuracy": best_baseline_accuracy,
        "continuation_advantage": None if vino_acc is None or best_baseline_accuracy is None else vino_acc - best_baseline_accuracy,
        "domains_where_vino_wins": domains_where_vino_wins,
        "domains_where_baseline_wins": domains_where_baseline_wins,
        "domain_transfer_score": len(domains_where_vino_wins) / max(1, len({row["domain"] for row in task_results})),
    }


def summarize_model(rows: list[dict[str, Any]]) -> dict[str, Any]:
    gt_rows = [row for row in rows if row.get("correct_if_ground_truth") is not None]
    authorized = [row for row in rows if row.get("authorized", row.get("selected_candidate_id") is not None)]
    scores = [float(row.get("score", 0.0)) for row in rows]
    margins = [float(row.get("margin", 0.0)) for row in rows if row.get("margin") is not None]
    false_auth = [
        row
        for row in gt_rows
        if row.get("selected_candidate_id") is not None and row.get("selected_candidate_id") != row.get("ground_truth_successor_id")
    ]
    return {
        "task_count": len(rows),
        "ground_truth_available_count": len(gt_rows),
        "accuracy_if_ground_truth": sum(1 for row in gt_rows if row["correct_if_ground_truth"]) / len(gt_rows) if gt_rows else None,
        "selection_agreement_with_vino": sum(1 for row in rows if row.get("selection_agreement_with_vino")) / len(rows) if rows else 0.0,
        "authorization_rate": len(authorized) / len(rows) if rows else 0.0,
        "refusal_rate": 1.0 - (len(authorized) / len(rows)) if rows else 0.0,
        "false_authorization_rate_if_known": len(false_auth) / len(gt_rows) if gt_rows else None,
        "average_confidence": sum(scores) / len(scores) if scores else 0.0,
        "average_margin": sum(margins) / len(margins) if margins else 0.0,
    }


def evaluate_file(candidates_path: str, out_dir: str, config_path: str | None = None) -> dict[str, Any]:
    config = load_validation_config(config_path)
    tasks = read_jsonl(candidates_path)
    payload = evaluate_tasks(tasks, config)
    output_dir = ensure_dir(out_dir)
    write_json(output_dir / "external_validation_results.json", payload)
    write_jsonl(output_dir / "external_validation_task_results.jsonl", payload["task_results"])
    return payload
