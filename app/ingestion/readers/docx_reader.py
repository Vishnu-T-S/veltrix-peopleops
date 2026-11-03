"""DOCX reader: paragraphs with heading styles, tables, and approximate page numbers."""
from __future__ import annotations

import re
from typing import List

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.ingestion.models import Block, DocMeta, ParsedDocument
from app.ingestion.readers.common import clean_rows, collapse, is_metadata_table

_HEADING_STYLE = re.compile(r"^heading\s*(\d+)$", re.I)


def _style_name(paragraph: Paragraph) -> str:
    try:
        return paragraph.style.name or ""
    except Exception:  # some generated files reference styles that do not exist
        return ""


def _page_breaks(element) -> int:
    """Count page breaks inside a paragraph (rendered or explicit)."""
    count = 0
    for node in element.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "lastRenderedPageBreak":
            count += 1
        elif tag == "br" and node.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}type") == "page":
            count += 1
    return count


def _table_rows(table: Table) -> List[List[str]]:
    rows = []
    for row in table.rows:
        cells, previous = [], None
        for cell in row.cells:
            if previous is not None and cell._tc is previous:   # merged cell repeats itself
                continue
            previous = cell._tc
            cells.append(cell.text)
        rows.append(cells)
    return rows


def read_docx(path: str, meta: DocMeta) -> ParsedDocument:
    document = docx.Document(path)
    parsed = ParsedDocument(meta=meta, blocks=[])
    page = 1
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(child, document)
            text = collapse(paragraph.text)
            style = _style_name(paragraph)
            if text:
                if style.lower() == "title":
                    parsed.blocks.append(Block(kind="heading", text=text, page=page, level=1))
                elif _HEADING_STYLE.match(style):
                    level = int(_HEADING_STYLE.match(style).group(1)) + 1
                    parsed.blocks.append(Block(kind="heading", text=text, page=page, level=level))
                else:
                    is_list = style.lower().startswith("list") or child.find(
                        ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr"
                    ) is not None
                    parsed.blocks.append(
                        Block(kind="text", text=("- " + text) if is_list else text, page=page)
                    )
            page += _page_breaks(child)
        elif tag == "tbl":
            raw = _table_rows(Table(child, document))
            if is_metadata_table(raw):
                continue
            rows = clean_rows(raw)
            if rows:
                parsed.blocks.append(Block(kind="table", rows=rows, page=page))
    return parsed
