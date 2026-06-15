"""Build VINO continuation-candidate records from normalized ingestion JSONL.

This module does not run the VINO engine and does not validate continuation.
It converts external ingestion records into reproducible candidate successor
pairs with weak, explicit heuristic features for downstream benchmarks.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.common import ensure_dir, normalize_text, read_jsonl, save_manifest, stable_hash, write_jsonl


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = ROOT / "data" / "external"
DEFAULT_OUT_DIR = ROOT / "data" / "external" / "continuation_candidates"
DEFAULT_COMBINED_OUT = DEFAULT_OUT_DIR / "vino_continuation_candidates.jsonl"
DEFAULT_MANIFEST = DEFAULT_OUT_DIR / "continuation_candidate_manifest.json"

CANDIDATE_FIELDS = [
    "candidate_id",
    "domain",
    "source_id",
    "source_uri",
    "timestamp",
    "source_entity_id",
    "candidate_successor_id",
    "source_event_type",
    "successor_event_type",
    "candidate_type",
    "carrier_features",
    "relational_features",
    "transformation_features",
    "lineage_features",
    "candidate_metrics",
    "ground_truth",
    "evidence",
    "metadata",
]


def clamp01(value: float) -> float:
    if math.isnan(value):
        return 0.0
    return max(0.0, min(1.0, value))


def tokens(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        text = " ".join(str(item) for item in value)
    elif isinstance(value, dict):
        text = " ".join(str(v) for v in value.values())
    else:
        text = str(value)
    text = normalize_text(text).lower()
    return {part for part in text.replace("_", " ").replace("-", " ").replace("/", " ").split() if part}


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def list_overlap(left: Any, right: Any) -> float:
    return jaccard(tokens(left), tokens(right))


def carrier_similarity(source: dict[str, Any], successor: dict[str, Any]) -> float:
    left = source.get("carrier_features", {})
    right = successor.get("carrier_features", {})
    pieces = [
        list_overlap(left.get("title") or left.get("name") or left.get("path"), right.get("title") or right.get("name") or right.get("path")),
        list_overlap(left.get("schema"), right.get("schema")),
        list_overlap(left.get("text_snippet") or left.get("abstract") or left.get("docstring"), right.get("text_snippet") or right.get("abstract") or right.get("docstring")),
        1.0 if left.get("qualified_name") and left.get("qualified_name") == right.get("qualified_name") else 0.0,
        1.0 if left.get("file_hash") and left.get("file_hash") == right.get("file_hash") else 0.0,
        1.0 if left.get("blob_hash") and left.get("blob_hash") == right.get("blob_hash") else 0.0,
    ]
    useful = [score for score in pieces if score > 0.0]
    return clamp01(sum(useful) / len(useful)) if useful else 0.0


def relational_continuity(source: dict[str, Any], successor: dict[str, Any]) -> float:
    left = source.get("relational_features", {})
    right = successor.get("relational_features", {})
    scores = [
        list_overlap(left.get("links"), right.get("links")),
        list_overlap(left.get("categories"), right.get("categories")),
        list_overlap(left.get("references"), right.get("references")),
        list_overlap(left.get("citations"), right.get("citations")),
        list_overlap(left.get("derived_from"), right.get("derived_from")),
        list_overlap(left.get("call_references"), right.get("call_references")),
    ]
    useful = [score for score in scores if score > 0.0]
    return clamp01(sum(useful) / len(useful)) if useful else 0.0


def lineage_recoverability(source: dict[str, Any], successor: dict[str, Any], relation_type: str) -> float:
    s_id = source.get("entity_id")
    c_id = successor.get("entity_id")
    s_lineage = source.get("lineage_features", {})
    c_lineage = successor.get("lineage_features", {})
    c_rel = successor.get("relational_features", {})
    if relation_type in {"explicit_successor", "derived_from", "revision_parent", "citation_successor", "rename"}:
        return 1.0
    if s_id and s_id in c_lineage.get("derived_from", []):
        return 1.0
    if s_id and s_id in c_rel.get("derived_from", []):
        return 1.0
    if s_lineage.get("qualified_name") and s_lineage.get("qualified_name") == c_lineage.get("qualified_name"):
        return 0.72
    if s_lineage.get("module_path") and s_lineage.get("module_path") == c_lineage.get("module_path"):
        return 0.44
    return 0.20 if relation_type == "weak_snapshot_similarity" else 0.0


def transformation_recoverability(source: dict[str, Any], successor: dict[str, Any], relation_type: str) -> float:
    features = successor.get("transformation_features", {})
    if relation_type == "revision_parent":
        return 0.80 if features.get("comment") else 0.65
    if relation_type == "derived_from":
        return 0.90 if features.get("transformations") else 0.70
    if relation_type == "citation_successor":
        return 0.58
    if relation_type == "rename":
        return 0.95
    if relation_type == "explicit_successor":
        return 0.72
    return 0.25


def make_candidate(
    source: dict[str, Any],
    successor: dict[str, Any],
    *,
    relation_type: str,
    weak_label: str | None,
    label_confidence: float,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    carrier = carrier_similarity(source, successor)
    relational = relational_continuity(source, successor)
    lineage = lineage_recoverability(source, successor, relation_type)
    transform = transformation_recoverability(source, successor, relation_type)
    sigma = clamp01(0.35 * lineage + 0.25 * relational + 0.25 * carrier + 0.15 * transform)
    j_score = clamp01(0.40 * transform + 0.35 * lineage + 0.15 * relational + 0.10 * carrier)
    convergence = clamp01(sigma * j_score)
    entropy_proxy = clamp01(1.0 - (0.45 * lineage + 0.25 * transform + 0.20 * relational + 0.10 * carrier))
    integrity = clamp01(0.45 * convergence + 0.25 * lineage + 0.20 * transform + 0.10 * relational)
    candidate_id = stable_hash(
        {
            "domain": source.get("domain"),
            "source_entity_id": source.get("entity_id"),
            "candidate_successor_id": successor.get("entity_id"),
            "relation_type": relation_type,
        }
    )[:24]
    return {
        "candidate_id": candidate_id,
        "domain": source.get("domain"),
        "source_id": source.get("source_id"),
        "source_uri": source.get("source_uri") or successor.get("source_uri"),
        "timestamp": successor.get("timestamp") or source.get("timestamp"),
        "source_entity_id": source.get("entity_id"),
        "candidate_successor_id": successor.get("entity_id"),
        "source_event_type": source.get("event_type"),
        "successor_event_type": successor.get("event_type"),
        "candidate_type": relation_type,
        "carrier_features": {
            "source_summary": summarize_carrier(source),
            "successor_summary": summarize_carrier(successor),
            "carrier_similarity": carrier,
        },
        "relational_features": {
            "relational_continuity": relational,
            "source_relation_keys": sorted(source.get("relational_features", {}).keys()),
            "successor_relation_keys": sorted(successor.get("relational_features", {}).keys()),
        },
        "transformation_features": {
            "transformation_recoverability": transform,
            "source_transform": source.get("transformation_features", {}),
            "successor_transform": successor.get("transformation_features", {}),
        },
        "lineage_features": {
            "lineage_recoverability": lineage,
            "source_lineage": source.get("lineage_features", {}),
            "successor_lineage": successor.get("lineage_features", {}),
        },
        "candidate_metrics": {
            "carrier_similarity_score": carrier,
            "relational_continuity_score": relational,
            "transformation_recoverability_score": transform,
            "lineage_recoverability_score": lineage,
            "Sigma_score": sigma,
            "J_score": j_score,
            "Sigma_J_convergence": convergence,
            "entropy_proxy": entropy_proxy,
            "continuation_integrity_score": integrity,
        },
        "ground_truth": {
            "label": weak_label,
            "label_confidence": label_confidence,
            "label_source": "source_ground_truth" if label_confidence >= 0.95 else "weak_heuristic",
            "source_ground_truth": source.get("ground_truth", {}),
            "successor_ground_truth": successor.get("ground_truth", {}),
        },
        "evidence": evidence or {},
        "metadata": {
            "converter": "build_vino_continuation_candidates.py",
            "note": "Candidate metrics are deterministic weak features for external validation setup; they are not VINO scoring results.",
        },
    }


def summarize_carrier(record: dict[str, Any]) -> dict[str, Any]:
    carrier = record.get("carrier_features", {})
    keys = [
        "title",
        "name",
        "qualified_name",
        "module_path",
        "path",
        "schema",
        "file_hash",
        "blob_hash",
        "signature",
    ]
    summary = {key: carrier[key] for key in keys if key in carrier}
    for text_key in ["text_snippet", "abstract", "docstring"]:
        if carrier.get(text_key):
            summary[text_key] = normalize_text(str(carrier[text_key]))[:240]
    return summary


def load_external_records(input_dir: Path) -> dict[str, list[dict[str, Any]]]:
    files = {
        "git_repositories": input_dir / "git_repos.jsonl",
        "wikipedia_revisions": input_dir / "wikipedia_revisions.jsonl",
        "paper_lineage": input_dir / "paper_lineage.jsonl",
        "dataset_provenance": input_dir / "dataset_provenance.jsonl",
        "software_symbols": input_dir / "software_symbols.jsonl",
    }
    return {domain: read_jsonl(path) for domain, path in files.items()}


def by_entity(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(record.get("entity_id")): record for record in records}


def build_wikipedia_candidates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index = by_entity(records)
    out = []
    for record in records:
        parent_id = record.get("lineage_features", {}).get("parent_id")
        if parent_id is not None and str(parent_id) in index:
            source = index[str(parent_id)]
            out.append(
                make_candidate(
                    source,
                    record,
                    relation_type="revision_parent",
                    weak_label="revision_chain_continuation",
                    label_confidence=0.98,
                    evidence={"parent_revision_id": parent_id, "revision_id": record.get("entity_id")},
                )
            )
    return out


def build_dataset_candidates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index = by_entity([record for record in records if record.get("event_type") == "dataset"])
    out = []
    for record in records:
        if record.get("event_type") == "dataset":
            for parent_id in record.get("lineage_features", {}).get("derived_from", []) or []:
                if str(parent_id) in index:
                    out.append(
                        make_candidate(
                            index[str(parent_id)],
                            record,
                            relation_type="derived_from",
                            weak_label="derived_dataset_continuation",
                            label_confidence=0.98,
                            evidence={"derived_from": parent_id, "dataset_id": record.get("entity_id")},
                        )
                    )
        elif record.get("event_type") == "derived_from":
            parent = record.get("lineage_features", {}).get("parent")
            child = record.get("lineage_features", {}).get("child")
            if str(parent) in index and str(child) in index:
                out.append(
                    make_candidate(
                        index[str(parent)],
                        index[str(child)],
                        relation_type="derived_from",
                        weak_label="derived_dataset_continuation",
                        label_confidence=0.98,
                        evidence={"edge_record_id": record.get("entity_id")},
                    )
                )
    return dedupe_candidates(out)


def build_paper_candidates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    papers = by_entity([record for record in records if record.get("event_type") == "paper"])
    out = []
    for paper in papers.values():
        for ref in paper.get("lineage_features", {}).get("references", []) or []:
            if str(ref) in papers:
                out.append(
                    make_candidate(
                        papers[str(ref)],
                        paper,
                        relation_type="citation_successor",
                        weak_label="idea_lineage_candidate",
                        label_confidence=0.55,
                        evidence={"referenced_paper": ref, "citing_paper": paper.get("entity_id")},
                    )
                )
    return out


def build_git_candidates(records: list[dict[str, Any]], max_self_baselines: int = 200) -> list[dict[str, Any]]:
    index = by_entity(records)
    out = []
    path_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("event_type", "").startswith("file_"):
            path = record.get("carrier_features", {}).get("path")
            if path:
                path_records[str(path)].append(record)
            old_path = record.get("carrier_features", {}).get("old_path")
            if old_path:
                source_id = f"{record.get('lineage_features', {}).get('commit')}:{old_path}"
                source = index.get(source_id)
                if source:
                    out.append(
                        make_candidate(
                            source,
                            record,
                            relation_type="rename",
                            weak_label="renamed_file_continuation",
                            label_confidence=0.95,
                            evidence={"old_path": old_path, "new_path": path},
                        )
                    )
    for same_path, items in path_records.items():
        ordered = sorted(items, key=lambda row: row.get("timestamp") or "")
        for source, successor in zip(ordered, ordered[1:]):
            out.append(
                make_candidate(
                    source,
                    successor,
                    relation_type="explicit_successor",
                    weak_label="same_path_file_survival",
                    label_confidence=0.70,
                    evidence={"path": same_path},
                )
            )
    if not out:
        file_records = [record for record in records if record.get("event_type", "").startswith("file_")]
        for record in file_records[:max_self_baselines]:
            out.append(
                make_candidate(
                    record,
                    record,
                    relation_type="weak_snapshot_similarity",
                    weak_label="single_snapshot_git_file_baseline",
                    label_confidence=0.25,
                    evidence={
                        "reason": "Only one Git snapshot/change point was available; this is a baseline self-candidate, not temporal continuation ground truth."
                    },
                )
            )
    return dedupe_candidates(out)


def build_software_symbol_candidates(records: list[dict[str, Any]], max_self_baselines: int = 500) -> list[dict[str, Any]]:
    out = []
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        lineage = record.get("lineage_features", {})
        key = (str(lineage.get("module_path", "")), str(lineage.get("qualified_name", "")))
        if key[0] and key[1]:
            grouped[key].append(record)
    for rows in grouped.values():
        if len(rows) > 1:
            ordered = sorted(rows, key=lambda row: (row.get("timestamp") or "", row.get("entity_id") or ""))
            for source, successor in zip(ordered, ordered[1:]):
                out.append(
                    make_candidate(
                        source,
                        successor,
                        relation_type="explicit_successor",
                        weak_label="symbol_survival_candidate",
                        label_confidence=0.70,
                        evidence={"qualified_name": source.get("lineage_features", {}).get("qualified_name")},
                    )
                )
    if not out:
        for record in records[:max_self_baselines]:
            out.append(
                make_candidate(
                    record,
                    record,
                    relation_type="weak_snapshot_similarity",
                    weak_label="single_snapshot_symbol_baseline",
                    label_confidence=0.25,
                    evidence={
                        "reason": "Only one symbol snapshot was available; this is a baseline self-candidate, not temporal continuation ground truth."
                    },
                )
            )
    return dedupe_candidates(out)


def dedupe_candidates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for record in records:
        key = record["candidate_id"]
        if key not in seen:
            seen.add(key)
            out.append(record)
    return out


def build_all(input_dir: Path, max_software_baselines: int, max_git_baselines: int) -> dict[str, list[dict[str, Any]]]:
    records = load_external_records(input_dir)
    return {
        "git_repositories": build_git_candidates(records["git_repositories"], max_git_baselines),
        "wikipedia_revisions": build_wikipedia_candidates(records["wikipedia_revisions"]),
        "paper_lineage": build_paper_candidates(records["paper_lineage"]),
        "dataset_provenance": build_dataset_candidates(records["dataset_provenance"]),
        "software_symbols": build_software_symbol_candidates(records["software_symbols"], max_software_baselines),
    }


def validate_candidate(record: dict[str, Any]) -> list[str]:
    missing = [field for field in CANDIDATE_FIELDS if field not in record]
    problems = [f"missing:{field}" for field in missing]
    metrics = record.get("candidate_metrics", {})
    for key in [
        "carrier_similarity_score",
        "relational_continuity_score",
        "transformation_recoverability_score",
        "lineage_recoverability_score",
        "Sigma_score",
        "J_score",
        "Sigma_J_convergence",
        "entropy_proxy",
        "continuation_integrity_score",
    ]:
        value = metrics.get(key)
        if not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
            problems.append(f"invalid_metric:{key}")
    return problems


def write_outputs(candidates_by_domain: dict[str, list[dict[str, Any]]], out_dir: Path, combined_out: Path, manifest_out: Path) -> dict[str, Any]:
    ensure_dir(out_dir)
    all_candidates: list[dict[str, Any]] = []
    domain_outputs = []
    for domain, candidates in candidates_by_domain.items():
        path = out_dir / f"{domain}_candidates.jsonl"
        write_jsonl(path, candidates)
        all_candidates.extend(candidates)
        domain_outputs.append({"domain": domain, "path": str(path), "records": len(candidates)})
    all_candidates.sort(key=lambda row: (row.get("domain") or "", row.get("candidate_id") or ""))
    write_jsonl(combined_out, all_candidates)
    problems = []
    for idx, candidate in enumerate(all_candidates, start=1):
        row_problems = validate_candidate(candidate)
        if row_problems:
            problems.append({"row": idx, "candidate_id": candidate.get("candidate_id"), "problems": row_problems})
    counts = Counter(candidate.get("domain") for candidate in all_candidates)
    manifest = {
        "purpose": "Convert normalized ingestion records into VINO continuation candidates for external validation benchmarks.",
        "combined_output": str(combined_out),
        "domain_outputs": domain_outputs,
        "total_candidates": len(all_candidates),
        "candidates_by_domain": dict(counts),
        "schema_fields": CANDIDATE_FIELDS,
        "valid": not problems,
        "validation_problems": problems[:100],
        "limitations": [
            "Candidate metrics are deterministic weak features for benchmark setup, not VINO runtime scoring.",
            "Ground truth is explicit only where the source data provides lineage links; otherwise labels are weak heuristics.",
            "Single-snapshot software symbols become baseline self-candidates until multi-revision symbol history is ingested.",
        ],
    }
    save_manifest(manifest_out, manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build VINO continuation candidates from normalized ingestion JSONL.")
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--combined-out", default=str(DEFAULT_COMBINED_OUT))
    parser.add_argument("--manifest-out", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--max-software-baselines", type=int, default=500)
    parser.add_argument("--max-git-baselines", type=int, default=200)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    candidates = build_all(Path(args.input_dir), args.max_software_baselines, args.max_git_baselines)
    manifest = write_outputs(candidates, Path(args.out_dir), Path(args.combined_out), Path(args.manifest_out))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
