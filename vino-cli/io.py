"""I/O helpers for the VINO external-validation CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def resolve_path(path: str | Path) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = ROOT / target
    return target


def ensure_dir(path: str | Path) -> Path:
    target = resolve_path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def read_json(path: str | Path, default: Any = None) -> Any:
    target = resolve_path(path)
    if not target.exists():
        return default
    return json.loads(target.read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any) -> Path:
    target = resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    target = resolve_path(path)
    if not target.exists():
        return []
    rows = []
    with target.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> Path:
    target = resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    return target


def write_text(path: str | Path, text: str) -> Path:
    target = resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target
