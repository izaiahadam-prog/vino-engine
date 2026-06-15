"""Shared ingestion utilities and normalized record schema."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_FIELDS = [
    "domain",
    "source_id",
    "source_uri",
    "timestamp",
    "entity_id",
    "candidate_successor_id",
    "event_type",
    "carrier_features",
    "relational_features",
    "transformation_features",
    "lineage_features",
    "ground_truth",
    "metadata",
]


def ensure_dir(path: str | Path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def write_jsonl(path: str | Path, records: list[dict[str, Any]]) -> Path:
    target = Path(path)
    ensure_dir(target.parent)
    with target.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
    return target


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    records = []
    with target.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_run(cmd: list[str], cwd: str | Path | None = None, timeout: int = 60) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "cmd": cmd,
        }
    except Exception as exc:  # pragma: no cover - defensive CLI helper
        return {"ok": False, "returncode": None, "stdout": "", "stderr": str(exc), "cmd": cmd}


def load_config(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {}
    with target.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_manifest(path: str | Path, manifest: dict[str, Any]) -> Path:
    target = Path(path)
    ensure_dir(target.parent)
    manifest = dict(manifest)
    manifest.setdefault("generated_at", now_iso())
    with target.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return target


def make_record(
    *,
    domain: str,
    source_id: str,
    source_uri: str | None = None,
    timestamp: str | None = None,
    entity_id: str,
    candidate_successor_id: str | None = None,
    event_type: str,
    carrier_features: dict[str, Any] | None = None,
    relational_features: dict[str, Any] | None = None,
    transformation_features: dict[str, Any] | None = None,
    lineage_features: dict[str, Any] | None = None,
    ground_truth: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = {
        "domain": domain,
        "source_id": source_id,
        "source_uri": source_uri,
        "timestamp": timestamp,
        "entity_id": entity_id,
        "candidate_successor_id": candidate_successor_id,
        "event_type": event_type,
        "carrier_features": carrier_features or {},
        "relational_features": relational_features or {},
        "transformation_features": transformation_features or {},
        "lineage_features": lineage_features or {},
        "ground_truth": ground_truth or {},
        "metadata": metadata or {},
    }
    missing = [field for field in SCHEMA_FIELDS if field not in record]
    if missing:
        raise ValueError(f"record missing schema fields: {missing}")
    return record
