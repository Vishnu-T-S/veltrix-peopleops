"""Load manifest.json into DocMeta objects.

Bad entries are reported and skipped rather than crashing start-up, so one broken
row cannot take the whole service down. Unknown access levels are kept as written and
are later denied by default (see retrieval.eligibility).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Tuple

from app.ingestion.models import DocMeta

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REQUIRED = ("doc_id", "file", "title", "doc_type", "regions", "effective_date", "access_level")


class ManifestError(Exception):
    pass


def load_manifest(path: str) -> Tuple[List[DocMeta], List[str]]:
    """Return (documents, problems)."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"manifest not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"manifest is not valid JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise ManifestError("manifest must be a JSON array")

    docs: List[DocMeta] = []
    problems: List[str] = []
    seen = set()
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            problems.append(f"entry {index}: not an object")
            continue
        missing = [k for k in _REQUIRED if entry.get(k) in (None, "", [])]
        if missing:
            problems.append(f"entry {index} ({entry.get('doc_id')}): missing {missing}")
            continue
        if not _ISO.match(str(entry["effective_date"])):
            problems.append(f"{entry['doc_id']}: effective_date must be YYYY-MM-DD")
            continue
        if entry["doc_id"] in seen:
            problems.append(f"{entry['doc_id']}: duplicate doc_id")
            continue
        seen.add(entry["doc_id"])
        regions = entry["regions"] if isinstance(entry["regions"], list) else [entry["regions"]]
        docs.append(
            DocMeta(
                doc_id=str(entry["doc_id"]),
                file=str(entry["file"]),
                title=str(entry["title"]),
                doc_type=str(entry["doc_type"]).strip().lower(),
                regions=tuple(str(r).strip().upper() for r in regions),
                effective_date=str(entry["effective_date"]),
                access_level=str(entry["access_level"]).strip().lower(),
            )
        )
    return docs, problems
