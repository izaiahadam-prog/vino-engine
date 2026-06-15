"""Baseline successor selectors for external validation tasks."""

from __future__ import annotations

import random
from typing import Any, Callable


def _select_max(task: dict[str, Any], score_name: str, model: str, explanation: str) -> dict[str, Any]:
    candidates = task.get("candidate_successors", [])
    if not candidates:
        return {"model": model, "selected_candidate_id": None, "score": 0.0, "explanation": "No candidates available."}
    ranked = sorted(candidates, key=lambda row: row.get("scores", {}).get(score_name, 0.0), reverse=True)
    best = ranked[0]
    return {
        "model": model,
        "selected_candidate_id": best.get("candidate_id"),
        "score": float(best.get("scores", {}).get(score_name, 0.0)),
        "explanation": explanation,
    }


def material_identity_baseline(task: dict[str, Any]) -> dict[str, Any]:
    return _select_max(task, "material_identity_score", "material_identity_baseline", "Selects highest material/file-hash continuity.")


def feature_similarity_baseline(task: dict[str, Any]) -> dict[str, Any]:
    return _select_max(task, "feature_similarity_score", "feature_similarity_baseline", "Selects highest surface feature similarity.")


def raw_continuity_baseline(task: dict[str, Any]) -> dict[str, Any]:
    return _select_max(task, "raw_continuity_score", "raw_continuity_baseline", "Selects highest raw continuity.")


def ancestry_or_lineage_baseline(task: dict[str, Any]) -> dict[str, Any]:
    return _select_max(task, "documented_lineage_score", "ancestry_or_lineage_baseline", "Selects strongest documented ancestry/lineage.")


def stability_baseline(task: dict[str, Any]) -> dict[str, Any]:
    return _select_max(task, "stability_score", "stability_baseline", "Selects highest stability/lowest entropy proxy.")


def timestamp_or_latest_baseline(task: dict[str, Any]) -> dict[str, Any]:
    candidates = task.get("candidate_successors", [])
    if not candidates:
        return {"model": "timestamp_or_latest_baseline", "selected_candidate_id": None, "score": 0.0, "explanation": "No candidates available."}
    selected = candidates[-1]
    return {
        "model": "timestamp_or_latest_baseline",
        "selected_candidate_id": selected.get("candidate_id"),
        "score": 1.0,
        "explanation": "Selects the latest/last-listed candidate deterministically.",
    }


def random_baseline(task: dict[str, Any], seed: int = 7) -> dict[str, Any]:
    candidates = task.get("candidate_successors", [])
    if not candidates:
        return {"model": "random_baseline", "selected_candidate_id": None, "score": 0.0, "explanation": "No candidates available."}
    rng = random.Random(f"{seed}:{task.get('task_id')}")
    selected = rng.choice(candidates)
    return {
        "model": "random_baseline",
        "selected_candidate_id": selected.get("candidate_id"),
        "score": 1.0 / len(candidates),
        "explanation": "Fixed-seed random selection.",
    }


BASELINES: list[Callable[[dict[str, Any]], dict[str, Any]]] = [
    material_identity_baseline,
    feature_similarity_baseline,
    raw_continuity_baseline,
    ancestry_or_lineage_baseline,
    stability_baseline,
    timestamp_or_latest_baseline,
]


def run_baselines(task: dict[str, Any], seed: int = 7) -> list[dict[str, Any]]:
    results = [selector(task) for selector in BASELINES]
    results.append(random_baseline(task, seed=seed))
    return results
