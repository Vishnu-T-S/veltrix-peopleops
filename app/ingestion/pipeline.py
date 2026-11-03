"""Ingestion: manifest -> parse -> chunk -> holidays table.

Runs once at start-up. A document that fails to parse is reported and skipped; the
rest still load, so one bad file cannot stop the service.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from app.ingestion.chunker import chunk_document
from app.ingestion.holidays import extract_holidays, store_holidays
from app.ingestion.manifest import load_manifest
from app.ingestion.models import Chunk, DocMeta, ParsedDocument
from app.ingestion.ocr import OcrEngine
from app.ingestion.readers import read_document

logger = logging.getLogger("veltrix.ingestion")


@dataclass
class IngestionResult:
    documents: List[DocMeta] = field(default_factory=list)
    chunks: List[Chunk] = field(default_factory=list)
    holiday_rows: int = 0
    ocr_pages: Dict[str, List[int]] = field(default_factory=dict)
    failures: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


def run_ingestion(
    manifest_path: str,
    corpus_dir: str,
    conn: Optional[sqlite3.Connection] = None,
    ocr: Optional[OcrEngine] = None,
) -> IngestionResult:
    ocr = ocr or OcrEngine()
    result = IngestionResult()
    docs, problems = load_manifest(manifest_path)
    result.warnings.extend(f"manifest: {p}" for p in problems)

    for meta in docs:
        path = Path(corpus_dir) / meta.file
        if not path.is_file():
            result.failures[meta.doc_id] = f"file not found: {meta.file}"
            logger.error("%s: file not found (%s)", meta.doc_id, meta.file)
            continue
        try:
            parsed: ParsedDocument = read_document(str(path), meta, ocr)
            chunks = chunk_document(parsed)
            if not chunks:
                result.warnings.append(f"{meta.doc_id}: no text could be extracted")
            if parsed.ocr_pages:
                result.ocr_pages[meta.doc_id] = parsed.ocr_pages
            result.warnings.extend(f"{meta.doc_id}: {w}" for w in parsed.warnings)
            if conn is not None and meta.doc_type == "calendar":
                rows = extract_holidays(parsed)
                if not rows:
                    result.warnings.append(f"{meta.doc_id}: calendar contained no recognisable dates")
                result.holiday_rows += store_holidays(conn, meta, rows)
            result.documents.append(meta)
            result.chunks.extend(chunks)
        except Exception as exc:   # one broken document must not stop the others
            result.failures[meta.doc_id] = f"{type(exc).__name__}: {exc}"
            logger.exception("%s: ingestion failed", meta.doc_id)

    logger.info(
        "ingestion finished: %d documents, %d chunks, %d holiday rows, %d failures, %d warnings",
        len(result.documents), len(result.chunks), result.holiday_rows,
        len(result.failures), len(result.warnings),
    )
    return result
