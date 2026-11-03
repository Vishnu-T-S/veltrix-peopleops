"""OCR for PDF pages that have no text layer (scanned documents).

Uses the Tesseract command-line program, installed in the Docker image. If it is not
installed, a scanned page yields no text and a warning is recorded; ingestion carries on.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger("veltrix.ocr")


class OcrUnavailable(Exception):
    pass


class OcrEngine:
    def __init__(self, command: str = "tesseract", lang: str = "eng", dpi: int = 200,
                 timeout: int = 120):
        self.command = command
        self.lang = lang
        self.dpi = dpi
        self.timeout = timeout

    def available(self) -> bool:
        return shutil.which(self.command) is not None

    def page_text(self, page) -> str:
        """OCR one PyMuPDF page. Returns plain text, lines joined by newlines."""
        if not self.available():
            raise OcrUnavailable(f"'{self.command}' is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "page.png"
            page.get_pixmap(dpi=self.dpi).save(str(image))
            result = subprocess.run(
                [self.command, str(image), "stdout", "-l", self.lang],
                capture_output=True, text=True, timeout=self.timeout,
            )
        if result.returncode != 0:
            logger.error("tesseract failed (exit %s)", result.returncode)
            return ""
        return result.stdout
