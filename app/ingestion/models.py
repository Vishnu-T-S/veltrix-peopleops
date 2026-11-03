"""Data shapes that flow through ingestion and retrieval."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class DocMeta:
    """One manifest entry. The manifest is the only source of these facts."""

    doc_id: str
    file: str
    title: str
    doc_type: str          # policy | addendum | memo | handbook | calendar | faq | wiki
    regions: Tuple[str, ...]   # ("GLOBAL",) or region codes such as ("IN", "US")
    effective_date: str    # YYYY-MM-DD
    access_level: str      # all | managers | hr


@dataclass
class Block:
    """A piece of a parsed document, in reading order."""

    kind: str                      # "heading" | "text" | "table"
    text: str = ""
    page: int = 1
    level: int = 0                 # headings only (1 = title)
    rows: Optional[List[List[str]]] = None   # tables only; rows[0] is the header row


@dataclass
class ParsedDocument:
    meta: DocMeta
    blocks: List[Block]
    ocr_pages: List[int] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class Chunk:
    """A retrievable passage. `locator` is the citation locator."""

    chunk_id: str
    meta: DocMeta
    locator: str           # nearest section heading, or "p. N" when there is none
    text: str
    tokens: int

    @property
    def doc_id(self) -> str:
        return self.meta.doc_id
