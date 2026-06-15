"""Ingest local dataset provenance and transformation metadata."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.common import make_record, stable_hash, write_jsonl


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data" / "external" / "dataset_provenance.jsonl"
SUPPORTED_SUFFIXES = {".csv", ".json", ".jsonl", ".parquet"}


def file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def csv_info(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            headers = next(reader, [])
            row_count = sum(1 for _ in reader)
        return {"columns": headers, "row_count": row_count}
    except Exception as exc:
        return {"columns": [], "row_count": None, "error": str(exc)}


def json_info(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        rows = payload if isinstance(payload, list) else payload.get("data", [])
        columns = sorted({key for row in rows for key in row.keys()}) if rows and isinstance(rows[0], dict) else []
        return {"columns": columns, "row_count": len(rows) if isinstance(rows, list) else None}
    except Exception as exc:
        return {"columns": [], "row_count": None, "error": str(exc)}


def jsonl_info(path: Path) -> dict[str, Any]:
    columns = set()
    count = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                count += 1
                row = json.loads(line)
                if isinstance(row, dict):
                    columns.update(row.keys())
        return {"columns": sorted(columns), "row_count": count}
    except Exception as exc:
        return {"columns": sorted(columns), "row_count": count, "error": str(exc)}


def parquet_info(path: Path) -> dict[str, Any]:
    try:
        import pyarrow.parquet as pq  # type: ignore

        meta = pq.ParquetFile(path)
        return {"columns": meta.schema.names, "row_count": meta.metadata.num_rows}
    except Exception as exc:
        return {"columns": [], "row_count": None, "error": f"parquet unavailable: {exc}"}


def inspect_file(path: Path) -> dict[str, Any]:
    if path.suffix == ".csv":
        info = csv_info(path)
    elif path.suffix == ".json":
        info = json_info(path)
    elif path.suffix == ".jsonl":
        info = jsonl_info(path)
    elif path.suffix == ".parquet":
        info = parquet_info(path)
    else:
        info = {"columns": [], "row_count": None}
    info.update({"file_hash": file_sha256(path), "file_size": path.stat().st_size})
    return info


def load_manifest(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {"datasets": []}
    target = Path(path)
    if not target.exists():
        return {"datasets": []}
    with target.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def discover(input_dir: Path) -> list[dict[str, Any]]:
    if not input_dir.exists():
        return []
    rows = []
    for path in input_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            rows.append({"id": path.stem, "path": str(path), "derived_from": [], "transformations": []})
    return rows


def ingest(input_dir: str | None = None, manifest: str | None = None, out: str | Path = DEFAULT_OUT) -> dict[str, Any]:
    input_path = Path(input_dir) if input_dir else ROOT / "data" / "raw" / "datasets"
    manifest_payload = load_manifest(manifest)
    datasets = manifest_payload.get("datasets") or discover(input_path)
    records = []
    for item in datasets:
        path = Path(item["path"])
        if not path.is_absolute():
            path = (ROOT / path).resolve()
        if not path.exists():
            continue
        info = inspect_file(path)
        dataset_id = item.get("id") or path.stem
        records.append(
            make_record(
                domain="dataset_provenance",
                source_id=dataset_id,
                source_uri=str(path),
                timestamp=None,
                entity_id=dataset_id,
                event_type="dataset",
                carrier_features={"path": str(path), "file_hash": info["file_hash"], "schema": info.get("columns")},
                relational_features={"derived_from": item.get("derived_from", [])},
                transformation_features={"transformations": item.get("transformations", []), "row_count": info.get("row_count")},
                lineage_features={"dataset_id": dataset_id, "derived_from": item.get("derived_from", [])},
                ground_truth={"derived_from": item.get("derived_from", [])},
                metadata={k: v for k, v in info.items() if k not in {"file_hash", "columns"}},
            )
        )
        for parent in item.get("derived_from", []):
            records.append(
                make_record(
                    domain="dataset_provenance",
                    source_id=dataset_id,
                    source_uri=str(path),
                    entity_id=f"{parent}->{dataset_id}",
                    candidate_successor_id=dataset_id,
                    event_type="derived_from",
                    relational_features={"parent": parent, "child": dataset_id},
                    transformation_features={"transformations": item.get("transformations", [])},
                    lineage_features={"parent": parent, "child": dataset_id},
                    ground_truth={"continuation_label": "derived_dataset"},
                    metadata={},
                )
            )
    write_jsonl(out, records)
    return {"domain": "datasets", "out": str(out), "records": len(records), "warnings": []}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir")
    parser.add_argument("--manifest")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    print(ingest(**vars(args)))


if __name__ == "__main__":
    main()
