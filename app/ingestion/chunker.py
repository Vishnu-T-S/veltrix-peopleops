"""Split a parsed document into retrievable chunks, one or more per section.

A chunk never crosses a heading, so its locator (the nearest section heading, or
"p. N" when there is none) is always accurate. Each chunk starts with its heading, so
it reads sensibly on its own. Tables become one self-describing line per row.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from app.ingestion.models import Block, Chunk, ParsedDocument
from app.ingestion.readers.common import table_row_lines
from app.tokens import count_tokens

MAX_CHUNK_TOKENS = 350
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

Piece = Tuple[str, int]   # (text, page)


def _split_oversize(text: str, limit: int) -> List[str]:
    """Break one over-long paragraph into sentence groups, then words if still too long."""
    parts, current = [], ""
    for sentence in _SENTENCE_END.split(text):
        candidate = f"{current} {sentence}".strip()
        if current and count_tokens(candidate) > limit:
            parts.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        parts.append(current)

    result: List[str] = []
    for part in parts:
        if count_tokens(part) <= limit:
            result.append(part)
            continue
        words, current = part.split(), ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and count_tokens(candidate) > limit:
                result.append(current)
                current = word
            else:
                current = candidate
        if current:
            result.append(current)
    return result


def _pieces(blocks: List[Block]) -> List[Piece]:
    pieces: List[Piece] = []
    for block in blocks:
        if block.kind == "table":
            pieces.extend((line, block.page) for line in table_row_lines(block.rows or []))
        elif block.text.strip():
            pieces.append((block.text.strip(), block.page))
    return pieces


def chunk_document(parsed: ParsedDocument, max_tokens: int = MAX_CHUNK_TOKENS) -> List[Chunk]:
    meta = parsed.meta

    # 1. Group blocks into sections, each starting at a heading.
    sections: List[Tuple[Optional[str], int, List[Block]]] = []
    heading: Optional[str] = None
    heading_page = 1
    body: List[Block] = []
    for block in parsed.blocks:
        if block.kind == "heading":
            if body:
                sections.append((heading, heading_page, body))
            heading, heading_page, body = block.text.strip().rstrip(":"), block.page, []
        else:
            if not body:
                heading_page = heading_page if heading is not None else block.page
            body.append(block)
    if body:
        sections.append((heading, heading_page, body))

    # 2. Pack each section's pieces into chunks under the token limit.
    chunks: List[Chunk] = []

    def emit(locator: str, heading_text: Optional[str], texts: List[str]):
        text = "\n".join(([heading_text] if heading_text else []) + texts)
        chunks.append(Chunk(
            chunk_id=f"{meta.doc_id}#{len(chunks) + 1}",
            meta=meta, locator=locator, text=text, tokens=count_tokens(text),
        ))

    for heading_text, section_page, blocks in sections:
        pieces: List[Piece] = []
        for text, page in _pieces(blocks):
            limit = max_tokens - count_tokens(heading_text or "") - 5
            if count_tokens(text) > limit:
                pieces.extend((part, page) for part in _split_oversize(text, limit))
            else:
                pieces.append((text, page))
        if not pieces:
            continue

        current: List[str] = []
        first_page = pieces[0][1]
        for text, page in pieces:
            trial = "\n".join(([heading_text] if heading_text else []) + current + [text])
            if current and count_tokens(trial) > max_tokens:
                emit(heading_text or f"p. {first_page}", heading_text, current)
                current, first_page = [], page
            current.append(text)
        emit(heading_text or f"p. {first_page}", heading_text, current)
    return chunks
