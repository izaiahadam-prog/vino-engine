"""Configuration defaults for the VINO external-validation CLI."""

from __future__ import annotations

from typing import Any

from vino_cli.io import read_json, write_json


DEFAULT_VALIDATION_CONFIG = {
    "domains_enabled": [
        "git_repositories",
        "wikipedia_revisions",
        "paper_lineage",
        "dataset_provenance",
        "software_symbols",
    ],
    "input_paths": {
        "external_records": "data/external",
        "pair_candidates": "data/external/continuation_candidates/vino_continuation_candidates.jsonl",
        "tasks": "data/candidates/continuation_tasks.jsonl",
    },
    "output_paths": {
        "candidate_dir": "data/candidates",
        "results_dir": "results/external_validation",
    },
    "max_records": 1000,
    "random_seed": 7,
    "entropy_floor": 0.35,
    "authorization_threshold": 0.50,
    "convergence_threshold": 0.20,
    "scoring_weights": {
        "recoverability_score": 0.18,
        "faithful_transfer_score": 0.18,
        "why_chain_reconstruction": 0.14,
        "accountable_lineage_score": 0.14,
        "distortion_reduction_score": 0.12,
        "successor_viability_score": 0.12,
        "Sigma_J_convergence": 0.12,
    },
    "limitations": [
        "This pipeline is an external-validation scaffold.",
        "The current VINO scoring is heuristic.",
        "Results from sample data are not proof.",
        "Serious validation requires real external datasets and baseline comparison.",
    ],
}


def load_validation_config(path: str | None = None) -> dict[str, Any]:
    if not path:
        return dict(DEFAULT_VALIDATION_CONFIG)
    loaded = read_json(path, default={}) or {}
    config = dict(DEFAULT_VALIDATION_CONFIG)
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            merged = dict(config[key])
            merged.update(value)
            config[key] = merged
        else:
            config[key] = value
    return config


def write_example_configs() -> None:
    ingestion_example = {
        "git": [{"local_path": ".", "max_commits": 200}],
        "wikipedia": [{"page_title": "Ship of Theseus", "limit": 20}],
        "papers": [{"input_json": "data/raw/papers/sample_papers.json"}],
        "datasets": [{"input_dir": "data/raw/datasets", "manifest": "data/raw/datasets/manifest.json"}],
        "software_symbols": [{"repo_path": ".", "language": "python", "max_files": 500}],
    }
    write_json("ingestion_config.example.json", ingestion_example)
    write_json("vino_validation_config.example.json", DEFAULT_VALIDATION_CONFIG)
