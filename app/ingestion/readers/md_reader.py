"""Markdown reader: # headings, pipe tables, bullet lists and paragraphs."""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

from app.ingestion.models import Block, DocMeta, ParsedDocument
from app.ingestion.readers.common import clean_rows, collapse, is_metadata_table

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_COMMENT = re.compile(r"<!--.*?-->", re.S)   # invisible when rendered, so never indexed


def _split_row(line: str) -> List[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def read_markdown(path: str, meta: DocMeta) -> ParsedDocument:
    text = _COMMENT.sub("", Path(path).read_text(encoding="utf-8", errors="replace"))
    parsed = ParsedDocument(meta=meta, blocks=[])
    paragraph: List[str] = []
    table: List[List[str]] = []

    def flush_paragraph():
        if paragraph:
            parsed.blocks.append(Block(kind="text", text=collapse(" ".join(paragraph))))
            paragraph.clear()

    def flush_table():
        if table:
            if not is_metadata_table(table):
                rows = clean_rows(table)
                if rows:
                    parsed.blocks.append(Block(kind="table", rows=rows))
            table.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            flush_paragraph()
            if not _SEPARATOR.match(stripped):
                table.append(_split_row(stripped))
            continue
        flush_table()
        heading = _HEADING.match(stripped)
        item = _LIST_ITEM.match(line)
        if heading:
            flush_paragraph()
            parsed.blocks.append(
                Block(kind="heading", text=collapse(heading.group(2)), level=len(heading.group(1)))
            )
        elif item:
            flush_paragraph()
            parsed.blocks.append(Block(kind="text", text="- " + collapse(item.group(1))))
        elif not stripped:
            flush_paragraph()
        else:
            paragraph.append(stripped)
    flush_paragraph()
    flush_table()
    return parsed
