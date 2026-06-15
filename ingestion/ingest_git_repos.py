"""Ingest Git repository commit and file-lineage events."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.common import ensure_dir, make_record, safe_run, stable_hash, write_jsonl


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data" / "external" / "git_repos.jsonl"
RAW_GIT = ROOT / "data" / "raw" / "git"


def repo_name(uri: str) -> str:
    name = uri.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name or stable_hash(uri)[:12]


def prepare_repo(repo_url: str | None, local_path: str | None) -> tuple[Path | None, str | None, list[str]]:
    warnings: list[str] = []
    if local_path:
        path = Path(local_path).resolve()
        return (path if path.exists() else None), str(path), warnings
    if repo_url:
        ensure_dir(RAW_GIT)
        target = RAW_GIT / repo_name(repo_url)
        if not target.exists():
            result = safe_run(["git", "clone", "--depth", "200", repo_url, str(target)], timeout=180)
            if not result["ok"]:
                warnings.append(f"clone failed: {result['stderr']}")
                return None, repo_url, warnings
        return target, repo_url, warnings
    warnings.append("no repo-url or local-path supplied")
    return None, None, warnings


def git_lines(repo: Path, args: list[str], timeout: int = 60) -> list[str]:
    result = safe_run(["git", *args], cwd=repo, timeout=timeout)
    if not result["ok"]:
        return []
    return [line for line in result["stdout"].splitlines() if line.strip()]


def commit_list(repo: Path, max_commits: int, since: str | None, until: str | None) -> list[str]:
    args = ["log", f"--max-count={max_commits}", "--format=%H"]
    if since:
        args.append(f"--since={since}")
    if until:
        args.append(f"--until={until}")
    return git_lines(repo, args)


def commit_metadata(repo: Path, commit: str) -> dict[str, Any]:
    fmt = "%H%x1f%P%x1f%aI%x1f%an%x1f%s"
    rows = git_lines(repo, ["show", "-s", f"--format={fmt}", commit])
    if not rows:
        return {"commit": commit, "parents": [], "timestamp": None, "author": None, "message": ""}
    parts = rows[0].split("\x1f")
    return {
        "commit": parts[0],
        "parents": parts[1].split() if len(parts) > 1 and parts[1] else [],
        "timestamp": parts[2] if len(parts) > 2 else None,
        "author": parts[3] if len(parts) > 3 else None,
        "message": parts[4] if len(parts) > 4 else "",
    }


def changed_files(repo: Path, commit: str) -> list[dict[str, Any]]:
    rows = git_lines(repo, ["diff-tree", "--root", "--no-commit-id", "--name-status", "-r", "-M", commit])
    changes = []
    for row in rows:
        parts = row.split("\t")
        status = parts[0]
        if status.startswith("R") and len(parts) >= 3:
            changes.append({"status": "R", "score": status[1:], "old_path": parts[1], "path": parts[2]})
        elif len(parts) >= 2:
            changes.append({"status": status[0], "path": parts[1]})
    return changes


def blob_hash(repo: Path, commit: str, path: str) -> str | None:
    result = safe_run(["git", "rev-parse", f"{commit}:{path}"], cwd=repo)
    return result["stdout"].strip() if result["ok"] else None


def ingest(
    repo_url: str | None = None,
    local_path: str | None = None,
    out: str | Path = DEFAULT_OUT,
    max_commits: int = 200,
    since: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    repo, source_uri, warnings = prepare_repo(repo_url, local_path)
    records = []
    if repo is not None:
        commits = commit_list(repo, max_commits, since, until)
        for commit in commits:
            meta = commit_metadata(repo, commit)
            records.append(
                make_record(
                    domain="git_repositories",
                    source_id=repo.name,
                    source_uri=source_uri,
                    timestamp=meta["timestamp"],
                    entity_id=commit,
                    event_type="commit",
                    carrier_features={"commit": commit, "message": meta["message"], "author": meta["author"]},
                    relational_features={"parents": meta["parents"]},
                    transformation_features={"changed_file_count": len(changed_files(repo, commit))},
                    lineage_features={"commit": commit, "parents": meta["parents"]},
                    metadata={"repo_path": str(repo)},
                )
            )
            for change in changed_files(repo, commit):
                status = change["status"]
                path = change.get("path")
                old_path = change.get("old_path")
                event_type = {
                    "A": "file_added",
                    "M": "file_modified",
                    "D": "file_deleted",
                    "R": "file_renamed",
                }.get(status, "file_modified")
                entity_id = f"{commit}:{path or old_path}"
                records.append(
                    make_record(
                        domain="git_repositories",
                        source_id=repo.name,
                        source_uri=source_uri,
                        timestamp=meta["timestamp"],
                        entity_id=entity_id,
                        candidate_successor_id=f"{commit}:{path}" if old_path and path else None,
                        event_type=event_type,
                        carrier_features={
                            "path": path,
                            "old_path": old_path,
                            "blob_hash": blob_hash(repo, commit, path) if path and status != "D" else None,
                        },
                        relational_features={"commit": commit, "parents": meta["parents"]},
                        transformation_features=change,
                        lineage_features={"commit": commit, "parent_commits": meta["parents"], "old_path": old_path},
                        ground_truth={"continuation_label": "rename" if event_type == "file_renamed" else None},
                        metadata={"repo_path": str(repo)},
                    )
                )
    write_jsonl(out, records)
    return {"domain": "git", "out": str(out), "records": len(records), "warnings": warnings}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-url")
    parser.add_argument("--local-path")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--max-commits", type=int, default=200)
    parser.add_argument("--since")
    parser.add_argument("--until")
    args = parser.parse_args()
    print(ingest(**vars(args)))


if __name__ == "__main__":
    main()
