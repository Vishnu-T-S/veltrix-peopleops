"""Extract holiday dates from calendar documents into the holidays table.

Nothing about specific holidays is written by hand: dates and names are read from the
tables in documents the manifest marks as `calendar`. A table (or the heading above
it) that talks about "restricted" or "optional" holidays produces rows of kind
'restricted': days when the office stays open, which never count as holidays when
working days are calculated.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple

from app.data.db import transaction
from app.ingestion.models import DocMeta, ParsedDocument

_MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"),
            ("may",), ("june", "jun"), ("july", "jul"), ("august", "aug"),
            ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for name in names
}
_MONTH_NAMES = "|".join(sorted(_MONTHS, key=len, reverse=True))
_DAY_MONTH_YEAR = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_NAMES})\.?,?\s+(\d{{4}})\b", re.I)
_MONTH_DAY_YEAR = re.compile(rf"\b({_MONTH_NAMES})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
_NAME_HEADER = re.compile(r"holiday|name|occasion|festival|event|description", re.I)
_RESTRICTED = re.compile(r"restricted|optional|floating|elective", re.I)
_LINE_DATE_FIRST = re.compile(r"^-?\s*(?P<date>.+?\d{4})\s*[:\-–—]\s*(?P<name>.+)$")


@dataclass(frozen=True)
class HolidayRow:
    day: date
    name: str
    kind: str   # "public" | "restricted"


def find_date(text: str) -> Optional[date]:
    """First calendar date written in `text`, or None. Day-first and month-first
    spellings and ISO dates are understood; ambiguous numeric formats (03/04/2026) are not."""
    for pattern, order in ((_DAY_MONTH_YEAR, "dmy"), (_MONTH_DAY_YEAR, "mdy"), (_ISO, "ymd")):
        match = pattern.search(text or "")
        if not match:
            continue
        a, b, c = match.groups()
        try:
            if order == "dmy":
                return date(int(c), _MONTHS[b.lower()], int(a))
            if order == "mdy":
                return date(int(c), _MONTHS[a.lower()], int(b))
            return date(int(a), int(b), int(c))
        except ValueError:
            continue
    return None


def _table_columns(rows: List[List[str]]) -> Optional[Tuple[int, int, bool]]:
    """Return (date_column, name_column, has_header_row) or None if this is not a holiday table."""
    if len(rows) < 1:
        return None
    first_is_header = find_date(" ".join(rows[0])) is None
    header = rows[0] if first_is_header else []
    data = rows[1:] if first_is_header else rows
    if not data:
        return None
    width = max(len(r) for r in data)

    date_col = None
    for col in range(width):
        hits = sum(1 for r in data if col < len(r) and find_date(r[col]))
        if hits * 2 > len(data):
            date_col = col
            break
    if date_col is None:
        return None

    name_col = None
    for col, label in enumerate(header):
        if col != date_col and _NAME_HEADER.search(label or ""):
            name_col = col
            break
    if name_col is None:
        for col in reversed(range(width)):
            values = [r[col].strip().lower() for r in data if col < len(r)]
            is_weekday_col = values and all(v in _WEEKDAYS for v in values if v)
            if col != date_col and not is_weekday_col:
                name_col = col
                break
    if name_col is None:
        return None
    return date_col, name_col, first_is_header


def extract_holidays(parsed: ParsedDocument) -> List[HolidayRow]:
    found: List[HolidayRow] = []
    heading = ""
    for block in parsed.blocks:
        if block.kind == "heading":
            heading = block.text
        elif block.kind == "table" and block.rows:
            columns = _table_columns(block.rows)
            if columns is None:
                continue
            date_col, name_col, has_header = columns
            header = block.rows[0] if has_header else []
            context = f"{heading} {' '.join(header)}"
            kind = "restricted" if _RESTRICTED.search(context) else "public"
            for row in (block.rows[1:] if has_header else block.rows):
                if max(date_col, name_col) >= len(row):
                    continue
                day = find_date(row[date_col])
                name = row[name_col].strip()
                if day and name:
                    found.append(HolidayRow(day, name, kind))
        elif block.kind == "text" and re.search(r"holiday", heading, re.I):
            match = _LINE_DATE_FIRST.match(block.text.strip())
            if match and find_date(match.group("date")):
                kind = "restricted" if _RESTRICTED.search(heading) else "public"
                found.append(HolidayRow(find_date(match.group("date")), match.group("name").strip(), kind))
    unique = {(h.day, h.kind): h for h in found}
    return sorted(unique.values(), key=lambda h: (h.day, h.kind))


def store_holidays(conn: sqlite3.Connection, meta: DocMeta, rows: List[HolidayRow]) -> int:
    """Replace this document's rows in the holidays table. Safe to run again at every start."""
    with transaction(conn):
        conn.execute("DELETE FROM holidays WHERE doc_id = ?", (meta.doc_id,))
        for region in meta.regions:
            for row in rows:
                conn.execute(
                    "INSERT OR IGNORE INTO holidays "
                    "(doc_id, region, holiday_date, name, kind, effective_date) VALUES (?,?,?,?,?,?)",
                    (meta.doc_id, region, row.day.isoformat(), row.name, row.kind, meta.effective_date),
                )
    return len(rows) * len(meta.regions)
