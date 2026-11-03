"""Helpers shared by every reader."""
from __future__ import annotations

import re
from typing import List

# The first table of most documents just repeats manifest facts (Document ID, Version,
# Effective date...). The manifest is authoritative, so these tables are dropped.
META_KEYS = {"document id", "version", "effective date", "applies to", "owner", "classification"}

BULLET = re.compile(r"^\s*(?:[•●▪◦‣·\-\*–])\s+")


def collapse(text: str) -> str:
    """Collapse all whitespace runs to single spaces."""
    return re.sub(r"\s+", " ", text or "").strip()


def is_metadata_table(rows: List[List[str]]) -> bool:
    """True for a Document ID / Version / Effective date style header table."""
    keys = set()
    for row in rows:
        for cell in row[:1]:   # labels live in the first column...
            for part in (cell or "").splitlines():
                keys.add(part.strip().lower())
    return len(keys & META_KEYS) >= 3


def clean_rows(rows: List[List[str]]) -> List[List[str]]:
    """Normalise cell whitespace and drop rows that are entirely empty."""
    cleaned = [[collapse(c or "") for c in row] for row in rows]
    return [r for r in cleaned if any(r)]


def table_row_lines(rows: List[List[str]]) -> List[str]:
    """Turn a table into one self-describing line per data row.

    "Sick leave per year | 10 | 12" becomes
    "Topic: Sick leave per year; Version 1: 10; Version 2: 12", so each row keeps its
    column names when it is retrieved on its own.
    """
    if not rows:
        return []
    if len(rows) == 1:
        return [" | ".join(c for c in rows[0] if c)]
    header, body = rows[0], rows[1:]
    lines = []
    for row in body:
        parts = []
        for index, cell in enumerate(row):
            if not cell:
                continue
            label = header[index] if index < len(header) else ""
            parts.append(f"{label}: {cell}" if label else cell)
        if parts:
            lines.append("; ".join(parts))
    return lines
