"""Build successor-selection tasks from continuation-candidate pair records."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ingestion.build_vino_continuation_candidates import build_all, write_outputs
from ingestion.common import stable_hash
from vino_cli.io import ensure_dir, read_jsonl, resolve_path, write_json, write_jsonl


PAIR_CANDIDATE_FILE = "continuation_candidates/vino_continuation_candidates.jsonl"


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def build_pair_candidates(input_dir: str, out_dir: str) -> dict[str, Any]:
    input_path = resolve_path(input_dir)
    pair_dir = input_path / "continuation_candidates"
    pair_file = pair_dir / "vino_continuation_candidates.jsonl"
    manifest_file = pair_dir / "continuation_candidate_manifest.json"
    candidates = build_all(input_path, max_software_baselines=500, max_git_baselines=200)
    return write_outputs(candidates, pair_dir, pair_file, manifest_file)


def score_candidate(pair: dict[str, Any]) -> dict[str, Any]:
    metrics = pair.get("candidate_metrics", {})
    carrier = clamp01(metrics.get("carrier_similarity_score", 0.0))
    relation = clamp01(metrics.get("relational_continuity_score", 0.0))
    transform = clamp01(metrics.get("transformation_recoverability_score", 0.0))
    lineage = clamp01(metrics.get("lineage_recoverability_score", 0.0))
    sigma = clamp01(metrics.get("Sigma_score", 0.0))
    j_score = clamp01(metrics.get("J_score", 0.0))
    convergence = clamp01(metrics.get("Sigma_J_convergence", sigma * j_score))
    entropy = clamp01(metrics.get("entropy_proxy", 1.0 - convergence))
    integrity = clamp01(metrics.get("continuation_integrity_score", 0.0))
    label_conf = clamp01(pair.get("ground_truth", {}).get("label_confidence", 0.0))
    candidate_type = pair.get("candidate_type", "")
    return {
        "material_identity_score": carrier if "file_hash" in str(pair.get("carrier_features", {})) else 0.35 * carrier,
        "visual_similarity_score": carrier,
        "raw_continuity_score": clamp01(0.50 * carrier + 0.30 * relation + 0.20 * lineage),
        "ancestry_score": lineage,
        "documented_lineage_score": clamp01(0.70 * lineage + 0.30 * transform),
        "feature_similarity_score": carrier,
        "stability_score": clamp01(1.0 - entropy),
        "recoverability_score": lineage,
        "faithful_transfer_score": clamp01(0.45 * transform + 0.35 * lineage + 0.20 * relation),
        "why_chain_reconstruction": transform,
        "accountable_lineage_score": clamp01(0.60 * lineage + 0.40 * transform),
        "distortion_reduction_score": clamp01(0.55 * (1.0 - entropy) + 0.45 * convergence),
        "successor_viability_score": clamp01(0.50 * integrity + 0.25 * sigma + 0.25 * j_score),
        "Sigma_score": sigma,
        "J_score": j_score,
        "Sigma_J_convergence": convergence,
        "continuation_integrity_score": integrity,
        "entropy_floor": entropy,
        "label_confidence": label_conf,
        "is_high_confidence_ground_truth": label_conf >= 0.95,
        "candidate_type": candidate_type,
    }


def pair_to_successor(pair: dict[str, Any]) -> dict[str, Any]:
    scores = score_candidate(pair)
    return {
        "candidate_id": pair.get("candidate_successor_id"),
        "pair_candidate_id": pair.get("candidate_id"),
        "event_type": pair.get("successor_event_type"),
        "candidate_type": pair.get("candidate_type"),
        "carrier_features": pair.get("carrier_features", {}).get("successor_summary", {}),
        "scores": scores,
        "ground_truth": pair.get("ground_truth", {}),
        "evidence": pair.get("evidence", {}),
        "metadata": {
            "heuristic_prototype_scoring": True,
            "source_pair_candidate_id": pair.get("candidate_id"),
        },
    }


def build_tasks_from_pairs(pair_records: list[dict[str, Any]], domains_enabled: list[str] | None = None) -> list[dict[str, Any]]:
    domain_set = set(domains_enabled or [])
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for pair in pair_records:
        if domain_set and pair.get("domain") not in domain_set:
            continue
        source_id = str(pair.get("source_entity_id"))
        groups[(str(pair.get("domain")), source_id)].append(pair)

    tasks = []
    for (domain, source_entity_id), pairs in sorted(groups.items()):
        successors = [pair_to_successor(pair) for pair in pairs]
        high_conf = [succ for succ in successors if succ["scores"]["is_high_confidence_ground_truth"]]
        ground_truth_successor_id = high_conf[0]["candidate_id"] if len(high_conf) == 1 else None
        source_pair = pairs[0]
        task_id = stable_hash({"domain": domain, "source_entity_id": source_entity_id})[:24]
        tasks.append(
            {
                "task_id": task_id,
                "domain": domain,
                "source_entity": {
                    "entity_id": source_entity_id,
                    "event_type": source_pair.get("source_event_type"),
                    "carrier_features": source_pair.get("carrier_features", {}).get("source_summary", {}),
                    "source_id": source_pair.get("source_id"),
                    "source_uri": source_pair.get("source_uri"),
                    "timestamp": source_pair.get("timestamp"),
                },
                "candidate_successors": successors,
                "ground_truth_successor_id": ground_truth_successor_id,
                "metadata": {
                    "heuristic_prototype_scoring": True,
                    "candidate_count": len(successors),
                    "ground_truth_available": ground_truth_successor_id is not None,
                    "limitations": [
                        "Candidate scores are deterministic heuristic features.",
                        "Only high-confidence source lineage labels are treated as ground truth.",
                    ],
                },
            }
        )
    return tasks


def build_candidate_tasks(input_dir: str, out_dir: str, domains_enabled: list[str] | None = None) -> dict[str, Any]:
    input_path = resolve_path(input_dir)
    pair_path = input_path / PAIR_CANDIDATE_FILE
    if not pair_path.exists():
        build_pair_candidates(input_dir, str(input_path / "continuation_candidates"))
    pair_records = read_jsonl(pair_path)
    tasks = build_tasks_from_pairs(pair_records, domains_enabled)
    output_dir = ensure_dir(out_dir)
    tasks_path = output_dir / "continuation_tasks.jsonl"
    manifest_path = output_dir / "candidate_task_manifest.json"
    write_jsonl(tasks_path, tasks)
    manifest = {
        "task_file": str(tasks_path),
        "task_count": len(tasks),
        "tasks_by_domain": count_by_domain(tasks),
        "source_pair_file": str(pair_path),
        "heuristic_prototype_scoring": True,
        "limitations": [
            "This converts normalized records into successor-selection tasks.",
            "It does not run VINO and does not validate continuation.",
        ],
    }
    write_json(manifest_path, manifest)
    return manifest


def count_by_domain(tasks: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in tasks:
        domain = task.get("domain", "unknown")
        counts[domain] = counts.get(domain, 0) + 1
    return counts
