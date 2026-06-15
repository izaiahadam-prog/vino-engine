"""Ingest paper / idea lineage from local JSON, BibTeX, or optional Semantic Scholar query."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.common import make_record, normalize_text, stable_hash, write_jsonl


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data" / "external" / "paper_lineage.jsonl"


def load_json_papers(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    with target.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, list) else payload.get("papers", [])


def parse_bibtex(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    text = target.read_text(encoding="utf-8", errors="ignore")
    entries = []
    for match in re.finditer(r"@\w+\s*\{\s*([^,]+),(.*?)\n\}", text, re.DOTALL):
        key = match.group(1).strip()
        body = match.group(2)
        fields = dict(re.findall(r"(\w+)\s*=\s*[\{\"]([^}\"]+)[}\"]", body))
        fields["id"] = key
        entries.append(fields)
    return entries


def semantic_scholar(query: str, limit: int) -> tuple[list[dict[str, Any]], list[str]]:
    url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(
        {"query": query, "limit": limit, "fields": "paperId,title,abstract,year,authors,venue,referenceCount,citationCount"}
    )
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "VINO-ingestion/0.1"})
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload.get("data", []), []
    except Exception as exc:
        return [], [f"Semantic Scholar query failed: {exc}"]


def paper_id(paper: dict[str, Any]) -> str:
    return str(paper.get("paperId") or paper.get("id") or paper.get("doi") or stable_hash(paper)[:16])


def ingest(
    input_bibtex: str | None = None,
    input_json: str | None = None,
    semantic_scholar_query: str | None = None,
    out: str | Path = DEFAULT_OUT,
    limit: int = 100,
) -> dict[str, Any]:
    warnings: list[str] = []
    papers: list[dict[str, Any]] = []
    if input_json:
        papers = load_json_papers(input_json)
    if not papers and input_bibtex:
        papers = parse_bibtex(input_bibtex)
    if not papers and semantic_scholar_query:
        papers, warnings = semantic_scholar(semantic_scholar_query, limit)
    records = []
    for paper in papers[:limit]:
        pid = paper_id(paper)
        authors = paper.get("authors", [])
        if authors and isinstance(authors[0], dict):
            authors = [author.get("name") for author in authors]
        references = paper.get("references") or paper.get("reference_ids") or []
        citations = paper.get("citations") or paper.get("citation_ids") or []
        keywords = paper.get("keywords") or []
        records.append(
            make_record(
                domain="paper_lineage",
                source_id=str(input_json or input_bibtex or semantic_scholar_query or "papers"),
                source_uri=paper.get("url") or paper.get("doi"),
                timestamp=str(paper.get("year")) if paper.get("year") else None,
                entity_id=pid,
                event_type="paper",
                carrier_features={"title": normalize_text(paper.get("title")), "abstract": normalize_text(paper.get("abstract"))},
                relational_features={"authors": authors, "references": references, "citations": citations},
                transformation_features={"keywords": keywords, "terminology": keywords},
                lineage_features={"paper_id": pid, "references": references},
                ground_truth=paper.get("ground_truth") or {},
                metadata={"venue": paper.get("venue"), "year": paper.get("year")},
            )
        )
        for ref in references:
            records.append(
                make_record(
                    domain="paper_lineage",
                    source_id=pid,
                    source_uri=None,
                    timestamp=str(paper.get("year")) if paper.get("year") else None,
                    entity_id=f"{pid}->ref:{ref}",
                    candidate_successor_id=str(ref),
                    event_type="reference",
                    relational_features={"source_paper": pid, "target_paper": ref},
                    lineage_features={"citing_paper": pid, "referenced_paper": ref},
                    metadata={},
                )
            )
    write_jsonl(out, records)
    return {"domain": "papers", "out": str(out), "records": len(records), "warnings": warnings}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-bibtex")
    parser.add_argument("--input-json")
    parser.add_argument("--semantic-scholar-query")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    print(ingest(**vars(args)))


if __name__ == "__main__":
    main()
