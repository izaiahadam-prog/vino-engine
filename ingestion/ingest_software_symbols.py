"""Ingest Python function/class/method symbols for survival across rewrites."""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.common import make_record, stable_hash, write_jsonl


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data" / "external" / "software_symbols.jsonl"


def source_hash(text: str) -> str:
    return stable_hash(text)


def signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = [arg.arg for arg in node.args.args]
    if node.args.vararg:
        args.append("*" + node.args.vararg.arg)
    args.extend(arg.arg for arg in node.args.kwonlyargs)
    if node.args.kwarg:
        args.append("**" + node.args.kwarg.arg)
    return f"{node.name}({', '.join(args)})"


class SymbolVisitor(ast.NodeVisitor):
    def __init__(self, module_path: str, text: str) -> None:
        self.module_path = module_path
        self.text = text
        self.class_stack: list[str] = []
        self.records: list[dict[str, Any]] = []

    def call_refs(self, node: ast.AST) -> list[str]:
        refs = []
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                if isinstance(sub.func, ast.Name):
                    refs.append(sub.func.id)
                elif isinstance(sub.func, ast.Attribute):
                    refs.append(sub.func.attr)
        return sorted(set(refs))

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        entity = ".".join([*self.class_stack, node.name]) if self.class_stack else node.name
        self.records.append(
            {
                "event_type": "class",
                "entity_id": f"{self.module_path}:{entity}",
                "name": node.name,
                "qualified_name": entity,
                "signature": node.name,
                "docstring": ast.get_docstring(node),
                "line": node.lineno,
                "end_line": getattr(node, "end_lineno", None),
                "calls": self.call_refs(node),
                "source_hash": source_hash(ast.get_source_segment(self.text, node) or node.name),
            }
        )
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self._function(node)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qualified = ".".join([*self.class_stack, node.name]) if self.class_stack else node.name
        self.records.append(
            {
                "event_type": "method" if self.class_stack else "function",
                "entity_id": f"{self.module_path}:{qualified}",
                "name": node.name,
                "qualified_name": qualified,
                "signature": signature(node),
                "docstring": ast.get_docstring(node),
                "line": node.lineno,
                "end_line": getattr(node, "end_lineno", None),
                "calls": self.call_refs(node),
                "source_hash": source_hash(ast.get_source_segment(self.text, node) or node.name),
            }
        )
        self.generic_visit(node)


def parse_python(path: Path, root: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    module_path = str(path.relative_to(root)).replace("\\", "/")
    visitor = SymbolVisitor(module_path, text)
    visitor.visit(tree)
    return visitor.records


def ingest(repo_path: str = ".", language: str = "python", out: str | Path = DEFAULT_OUT, max_files: int = 500) -> dict[str, Any]:
    root = Path(repo_path).resolve()
    records = []
    warnings: list[str] = []
    if language.lower() != "python":
        warnings.append("only python support is implemented")
    files = list(root.rglob("*.py"))[:max_files]
    for path in files:
        if any(part in {".venv", ".venv-1", "__pycache__", "node_modules"} for part in path.parts):
            continue
        for symbol in parse_python(path, root):
            records.append(
                make_record(
                    domain="software_symbols",
                    source_id=str(root),
                    source_uri=str(path),
                    timestamp=None,
                    entity_id=symbol["entity_id"],
                    event_type=symbol["event_type"],
                    carrier_features={
                        "module_path": str(path.relative_to(root)).replace("\\", "/"),
                        "name": symbol["name"],
                        "qualified_name": symbol["qualified_name"],
                        "signature": symbol["signature"],
                        "docstring": symbol["docstring"],
                        "source_hash": symbol["source_hash"],
                        "line": symbol["line"],
                        "end_line": symbol["end_line"],
                    },
                    relational_features={"call_references": symbol["calls"]},
                    transformation_features={},
                    lineage_features={"module_path": str(path.relative_to(root)).replace("\\", "/"), "qualified_name": symbol["qualified_name"]},
                    ground_truth={},
                    metadata={"language": "python"},
                )
            )
    write_jsonl(out, records)
    return {"domain": "software_symbols", "out": str(out), "records": len(records), "warnings": warnings}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-path", default=".")
    parser.add_argument("--language", default="python")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--max-files", type=int, default=500)
    args = parser.parse_args()
    print(ingest(**vars(args)))


if __name__ == "__main__":
    main()
