"""Ingest Wikipedia revisions through the MediaWiki API or a local JSON export."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.common import make_record, normalize_text, stable_hash, write_jsonl


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data" / "external" / "wikipedia_revisions.jsonl"


def api_revisions(page_title: str | None, page_id: str | None, limit: int) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    params = {
        "action": "query",
        "format": "json",
        "prop": "revisions|links|categories",
        "rvprop": "ids|timestamp|user|comment|content",
        "rvslots": "main",
        "rvlimit": str(limit),
        "pllimit": "max",
        "cllimit": "max",
    }
    if page_id:
        params["pageids"] = str(page_id)
    elif page_title:
        params["titles"] = page_title
    else:
        return [], ["no page title or page id supplied"]
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "VINO-ingestion/0.1"})
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        pages = payload.get("query", {}).get("pages", {})
        records = []
        for page in pages.values():
            links = [link.get("title") for link in page.get("links", [])]
            categories = [cat.get("title") for cat in page.get("categories", [])]
            for rev in page.get("revisions", []):
                content = rev.get("slots", {}).get("main", {}).get("*", rev.get("*", ""))
                records.append(
                    {
                        "page_id": str(page.get("pageid")),
                        "title": page.get("title"),
                        "revision": rev,
                        "content": content,
                        "links": links,
                        "categories": categories,
                        "source_uri": url,
                    }
                )
        return records, warnings
    except Exception as exc:
        return [], [f"MediaWiki API failed: {exc}"]


def local_revisions(input_json: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    path = Path(input_json)
    if not path.exists():
        return [], [f"input json not found: {path}"]
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        return payload, []
    return payload.get("revisions", []), []


def ingest(
    page_title: str | None = None,
    page_id: str | None = None,
    input_json: str | None = None,
    out: str | Path = DEFAULT_OUT,
    limit: int = 50,
) -> dict[str, Any]:
    warnings: list[str] = []
    raw, local_warnings = local_revisions(input_json) if input_json else ([], [])
    warnings.extend(local_warnings)
    if not raw:
        raw, api_warnings = api_revisions(page_title, page_id, limit)
        warnings.extend(api_warnings)
    records = []
    previous_id = None
    previous_links: set[str] = set()
    for item in raw[:limit]:
        rev = item.get("revision", item)
        revision_id = str(rev.get("revid") or rev.get("id") or item.get("revision_id") or stable_hash(item)[:12])
        parent_id = rev.get("parentid") or item.get("parent_id") or previous_id
        title = item.get("title") or item.get("page_title") or page_title
        text = item.get("content") or item.get("text") or rev.get("text") or ""
        links = set(item.get("links") or [])
        event_type = "revision"
        if previous_links and links != previous_links:
            event_type = "link_change"
        records.append(
            make_record(
                domain="wikipedia_revisions",
                source_id=str(item.get("page_id") or page_id or title or "wikipedia"),
                source_uri=item.get("source_uri"),
                timestamp=rev.get("timestamp") or item.get("timestamp"),
                entity_id=revision_id,
                candidate_successor_id=None,
                event_type=event_type,
                carrier_features={"title": title, "text_snippet": normalize_text(text)[:1200]},
                relational_features={"links": sorted(links), "categories": item.get("categories", [])},
                transformation_features={"comment": rev.get("comment") or item.get("comment")},
                lineage_features={"revision_id": revision_id, "parent_id": parent_id},
                ground_truth={"continuation_label": "revision_chain" if parent_id else None},
                metadata={"user": rev.get("user") or item.get("user")},
            )
        )
        previous_id = revision_id
        previous_links = links
    write_jsonl(out, records)
    return {"domain": "wikipedia", "out": str(out), "records": len(records), "warnings": warnings}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page-title")
    parser.add_argument("--page-id")
    parser.add_argument("--input-json")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    print(ingest(**vars(args)))


if __name__ == "__main__":
    main()
