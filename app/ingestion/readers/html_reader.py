"""HTML reader: visible headings, paragraphs, list items and tables.

Only text a person would see is kept. Scripts, styles, navigation, footers, comments
and elements hidden with CSS or the `hidden` attribute are dropped, so content that is
invisible to readers cannot reach the index.
"""
from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup

from app.ingestion.models import Block, DocMeta, ParsedDocument
from app.ingestion.readers.common import clean_rows, collapse, is_metadata_table

_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?![.\d])", re.I)
_DROP_TAGS = ["script", "style", "nav", "footer", "header", "noscript", "template", "head"]
_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


def _is_hidden(element) -> bool:
    attrs = element.attrs or {}
    return (
        "hidden" in attrs
        or str(attrs.get("aria-hidden", "")).lower() == "true"
        or bool(_HIDDEN_STYLE.search(str(attrs.get("style", ""))))
    )


def _has_ancestor(element, names) -> bool:
    return any(parent.name in names for parent in element.parents)


def read_html(path: str, meta: DocMeta) -> ParsedDocument:
    soup = BeautifulSoup(Path(path).read_text(encoding="utf-8", errors="replace"), "html.parser")
    for tag in soup(_DROP_TAGS):
        tag.decompose()
    for element in [e for e in soup.find_all(True) if _is_hidden(e)]:
        element.decompose()

    parsed = ParsedDocument(meta=meta, blocks=[])
    root = soup.body or soup
    for element in root.find_all(list(_HEADINGS) + ["p", "li", "table", "pre", "blockquote"]):
        name = element.name
        if name != "table" and _has_ancestor(element, {"table"}):
            continue
        if name in ("p", "li") and _has_ancestor(element, {"li"}):
            continue
        if name == "table":
            if _has_ancestor(element, {"table"}):
                continue
            raw = [
                [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
                for row in element.find_all("tr")
            ]
            if is_metadata_table(raw):
                continue
            rows = clean_rows(raw)
            if rows:
                parsed.blocks.append(Block(kind="table", rows=rows))
            continue
        text = collapse(element.get_text(" ", strip=True))
        if not text:
            continue
        if name in _HEADINGS:
            parsed.blocks.append(Block(kind="heading", text=text, level=_HEADINGS[name]))
        else:
            parsed.blocks.append(Block(kind="text", text=("- " + text) if name == "li" else text))
    return parsed
