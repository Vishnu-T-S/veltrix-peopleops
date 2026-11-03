"""Pick the reader for a file by its extension."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.ingestion.models import DocMeta, ParsedDocument
from app.ingestion.ocr import OcrEngine


class UnsupportedFormat(Exception):
    pass


def read_document(path: str, meta: DocMeta, ocr: Optional[OcrEngine] = None) -> ParsedDocument:
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        from app.ingestion.readers.pdf_reader import read_pdf
        return read_pdf(path, meta, ocr)
    if suffix == ".docx":
        from app.ingestion.readers.docx_reader import read_docx
        return read_docx(path, meta)
    if suffix in (".html", ".htm"):
        from app.ingestion.readers.html_reader import read_html
        return read_html(path, meta)
    if suffix in (".md", ".markdown"):
        from app.ingestion.readers.md_reader import read_markdown
        return read_markdown(path, meta)
    raise UnsupportedFormat(f"no reader for '{suffix}' files ({Path(path).name})")
