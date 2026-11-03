"""PDF reader: text with headings, tables, and OCR for pages without a text layer.

Headings are found from typography (bold and larger than the body text), with a
fallback for bold numbered headings such as "7. Sick leave". Page headers and footers
(small text at the top or bottom edge) are dropped. Tables come from PyMuPDF's table
finder. Pages with almost no text are treated as scans and sent to OCR.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import List, Optional

import pymupdf

from app.ingestion.models import Block, DocMeta, ParsedDocument
from app.ingestion.ocr import OcrEngine, OcrUnavailable
from app.ingestion.readers.common import BULLET, clean_rows, collapse, is_metadata_table

logger = logging.getLogger("veltrix.ingestion")

MIN_TEXT_CHARS = 20          # fewer characters than this on a page: treat it as a scan
_NUMBERED_HEADING = re.compile(r"^\d+(\.\d+)*\.?\s+\S")
_PAGE_NUMBER = re.compile(r"^page\s+\d+(\s+of\s+\d+)?$", re.I)


@dataclass
class _Line:
    text: str
    size: float
    bold: bool
    y0: float
    y1: float
    block_index: int


@dataclass
class _Paragraph:
    text: str
    size: float
    bold: bool
    y0: float
    lines: int


def _is_bold(span) -> bool:
    return bool(span["flags"] & 16) or "bold" in span["font"].lower()


def _inside_any(rect: pymupdf.Rect, tables: List[pymupdf.Rect]) -> bool:
    area = rect.get_area() or 1.0
    return any((rect & t).get_area() > 0.5 * area for t in tables if rect.intersects(t))


def _page_lines(page, table_rects: List[pymupdf.Rect]) -> List[_Line]:
    lines: List[_Line] = []
    for block_index, block in enumerate(page.get_text("dict")["blocks"]):
        if block.get("type") != 0:
            continue
        if _inside_any(pymupdf.Rect(block["bbox"]), table_rects):
            continue
        for line in block["lines"]:
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            text = collapse("".join(s["text"] for s in line["spans"]))
            lines.append(_Line(
                text=text,
                size=max(s["size"] for s in spans),
                bold=all(_is_bold(s) for s in spans),
                y0=line["bbox"][1], y1=line["bbox"][3],
                block_index=block_index,
            ))
    return lines


def _group_paragraphs(lines: List[_Line]) -> List[_Paragraph]:
    """Join the lines of one PDF text block into paragraphs; each bullet starts a new one."""
    paragraphs: List[_Paragraph] = []
    current: List[_Line] = []

    def flush():
        if not current:
            return
        first_text = current[0].text
        bullet = bool(BULLET.match(first_text))
        text = collapse(" ".join(l.text for l in current))
        if bullet:
            text = "- " + BULLET.sub("", text, count=1)
        paragraphs.append(_Paragraph(
            text=text,
            size=max(l.size for l in current),
            bold=all(l.bold for l in current),
            y0=current[0].y0,
            lines=len(current),
        ))
        current.clear()

    previous_block = None
    for line in lines:
        new_block = line.block_index != previous_block
        if current and (new_block or BULLET.match(line.text)):
            flush()
        current.append(line)
        previous_block = line.block_index
    flush()
    return paragraphs


def _find_tables(page):
    try:
        return list(page.find_tables().tables)
    except Exception:  # table finding is best effort; text is still extracted
        return []


def read_pdf(path: str, meta: DocMeta, ocr: Optional[OcrEngine] = None) -> ParsedDocument:
    ocr = ocr or OcrEngine()
    document = pymupdf.open(path)
    parsed = ParsedDocument(meta=meta, blocks=[])

    # Pass 1: gather lines and tables for each page, and learn the body font size.
    pages = []
    size_votes: Counter = Counter()
    for number, page in enumerate(document, start=1):
        if len(page.get_text().strip()) < MIN_TEXT_CHARS:
            pages.append((number, page, None, None, None))
            continue
        tables = _find_tables(page)
        rects = [pymupdf.Rect(t.bbox) for t in tables]
        lines = _page_lines(page, rects)
        for line in lines:
            size_votes[round(line.size, 1)] += len(line.text)
        pages.append((number, page, tables, rects, lines))
    body_size = size_votes.most_common(1)[0][0] if size_votes else 10.0
    title_size = max(size_votes) if size_votes else body_size

    # Pass 2: build blocks in reading order.
    for number, page, tables, rects, lines in pages:
        if lines is None:  # scanned page
            parsed.ocr_pages.append(number)
            try:
                text = ocr.page_text(page)
            except OcrUnavailable as exc:
                parsed.warnings.append(f"p. {number} is a scan but OCR is unavailable: {exc}")
                logger.error("%s: page %s is a scan and OCR is unavailable", meta.doc_id, number)
                continue
            # OCR has no layout information, so a page becomes one block of text.
            text = collapse(" ".join(text.splitlines()))
            if text:
                parsed.blocks.append(Block(kind="text", text=text, page=number))
            else:
                parsed.warnings.append(f"p. {number}: OCR found no text")
            continue

        height = page.rect.height
        kept = [
            l for l in lines
            if not (l.size <= body_size - 1.0 and (l.y1 < 0.09 * height or l.y0 > 0.91 * height))
            and not _PAGE_NUMBER.match(l.text)
        ]
        items = []
        for paragraph in _group_paragraphs(kept):
            items.append((paragraph.y0, "paragraph", paragraph))
        for table, rect in zip(tables, rects):
            raw = table.extract()
            if is_metadata_table(raw):
                continue
            rows = clean_rows(raw)
            if rows:
                items.append((rect.y0, "table", rows))
        items.sort(key=lambda item: item[0])

        for _, kind, payload in items:
            if kind == "table":
                parsed.blocks.append(Block(kind="table", rows=payload, page=number))
                continue
            p: _Paragraph = payload
            single_heading_like = p.bold and p.lines <= 2 and len(p.text) < 120
            is_heading = single_heading_like and (
                p.size >= body_size + 1.0 or _NUMBERED_HEADING.match(p.text)
            )
            if is_heading:
                level = 1 if p.size >= title_size - 0.1 and p.size > body_size + 3 else 2
                parsed.blocks.append(Block(kind="heading", text=p.text, page=number, level=level))
            else:
                parsed.blocks.append(Block(kind="text", text=p.text, page=number))
    return parsed
