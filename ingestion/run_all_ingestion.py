"""Run configured VINO external-data ingestion jobs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.common import ensure_dir, load_config, save_manifest
from ingestion.ingest_dataset_provenance import ingest as ingest_datasets
from ingestion.ingest_git_repos import ingest as ingest_git
from ingestion.ingest_paper_lineage import ingest as ingest_papers
from ingestion.ingest_software_symbols import ingest as ingest_symbols
from ingestion.ingest_wikipedia_revisions import ingest as ingest_wikipedia


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "ingestion_config.json"
EXTERNAL = ROOT / "data" / "external"


def create_samples() -> None:
    papers = ROOT / "data" / "raw" / "papers" / "sample_papers.json"
    if not papers.exists():
        ensure_dir(papers.parent)
        papers.write_text(
            json.dumps(
                {
                    "papers": [
                        {
                            "id": "vino_demo_001",
                            "title": "Recoverable Continuation Under Transformation",
                            "abstract": "A small sample paper record for VINO ingestion tests.",
                            "year": 2026,
                            "authors": ["VINO Demo"],
                            "references": ["theseus_demo_000"],
                            "keywords": ["continuation", "lineage", "uncertainty"],
                            "venue": "Synthetic Samples",
                        },
                        {
                            "id": "theseus_demo_000",
                            "title": "Ship of Theseus as Succession",
                            "abstract": "A local sample reference about successor authorization.",
                            "year": 2025,
                            "authors": ["VINO Demo"],
                            "references": [],
                            "keywords": ["identity", "succession"],
                            "venue": "Synthetic Samples",
                        },
                    ]
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    datasets_dir = ROOT / "data" / "raw" / "datasets"
    ensure_dir(datasets_dir)
    raw_csv = datasets_dir / "raw_v1.csv"
    clean_csv = datasets_dir / "cleaned_v2.csv"
    if not raw_csv.exists():
        raw_csv.write_text("id,label,value\n1,A,10\n2,B,20\n2,B,20\n", encoding="utf-8")
    if not clean_csv.exists():
        clean_csv.write_text("id,label,value\n1,a,10\n2,b,20\n", encoding="utf-8")
    manifest = datasets_dir / "manifest.json"
    if not manifest.exists():
        manifest.write_text(
            json.dumps(
                {
                    "datasets": [
                        {
                            "id": "raw_v1",
                            "path": "data/raw/datasets/raw_v1.csv",
                            "derived_from": [],
                            "transformations": ["source_extract"],
                        },
                        {
                            "id": "cleaned_v2",
                            "path": "data/raw/datasets/cleaned_v2.csv",
                            "derived_from": ["raw_v1"],
                            "transformations": ["dedupe", "normalize_columns"],
                        },
                    ]
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def default_config() -> dict[str, Any]:
    return {
        "git": [{"local_path": ".", "max_commits": 200}],
        "wikipedia": [{"page_title": "Ship of Theseus", "limit": 20}],
        "papers": [{"input_json": "data/raw/papers/sample_papers.json"}],
        "datasets": [{"input_dir": "data/raw/datasets", "manifest": "data/raw/datasets/manifest.json"}],
        "software_symbols": [{"repo_path": ".", "language": "python", "max_files": 500}],
    }


def load_or_create_config(path: Path) -> dict[str, Any]:
    if path.exists():
        return load_config(path)
    config = default_config()
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return config


def run_jobs(config: dict[str, Any]) -> list[dict[str, Any]]:
    ensure_dir(EXTERNAL)
    results = []
    for job in config.get("git", []):
        results.append(ingest_git(out=EXTERNAL / "git_repos.jsonl", **job))
    if "git" not in config:
        ingest_git(out=EXTERNAL / "git_repos.jsonl")
    for job in config.get("wikipedia", []):
        results.append(ingest_wikipedia(out=EXTERNAL / "wikipedia_revisions.jsonl", **job))
    if "wikipedia" not in config:
        ingest_wikipedia(out=EXTERNAL / "wikipedia_revisions.jsonl")
    for job in config.get("papers", []):
        results.append(ingest_papers(out=EXTERNAL / "paper_lineage.jsonl", **job))
    for job in config.get("datasets", []):
        results.append(ingest_datasets(out=EXTERNAL / "dataset_provenance.jsonl", **job))
    for job in config.get("software_symbols", []):
        results.append(ingest_symbols(out=EXTERNAL / "software_symbols.jsonl", **job))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args()
    create_samples()
    config = load_or_create_config(Path(args.config))
    results = run_jobs(config)
    manifest = {
        "config": str(Path(args.config).resolve()),
        "outputs": results,
        "notes": [
            "These scripts ingest and normalize data.",
            "They do not prove VINO or validate continuation yet.",
            "They create the external-data substrate for validation.",
        ],
    }
    save_manifest(EXTERNAL / "ingestion_manifest.json", manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
