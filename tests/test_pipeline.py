import json
import shutil
from datetime import date

import pytest

from app.data import repository
from app.ingestion.ocr import OcrEngine
from app.ingestion.pipeline import run_ingestion
from tests.corpus_factory import build_corpus

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")


def test_every_format_is_ingested_and_holidays_are_stored(tmp_path, conn):
    built = build_corpus(tmp_path)
    result = run_ingestion(str(built["manifest_path"]), str(built["corpus_dir"]), conn)
    assert not result.failures
    assert {d.doc_id for d in result.documents} == {e["doc_id"] for e in built["manifest"]}
    assert result.holiday_rows == 4 + 2     # India: 3 public + 1 restricted; US: 2
    assert repository.holiday_dates(conn, "US", date(2026, 10, 15), 2026) == {date(2026, 11, 26), date(2026, 11, 27)}


@needs_tesseract
def test_the_scanned_memo_is_read_with_ocr_and_findable(tmp_path):
    built = build_corpus(tmp_path)
    result = run_ingestion(str(built["manifest_path"]), str(built["corpus_dir"]))
    assert result.ocr_pages == {"MEMO-WFH": [1]}
    memo = " ".join(c.text for c in result.chunks if c.doc_id == "MEMO-WFH").lower()
    assert "4 days per week" in memo
    assert [c.locator for c in result.chunks if c.doc_id == "MEMO-WFH"] == ["p. 1"]


def test_a_missing_file_is_reported_and_the_rest_still_load(tmp_path):
    built = build_corpus(tmp_path)
    (built["corpus_dir"] / "policy_v1.md").unlink()
    result = run_ingestion(str(built["manifest_path"]), str(built["corpus_dir"]))
    assert "POL-V1" in result.failures and "file not found" in result.failures["POL-V1"]
    assert any(c.doc_id == "POL-V2" for c in result.chunks)


def test_a_corrupt_file_is_reported_and_the_rest_still_load(tmp_path):
    built = build_corpus(tmp_path)
    (built["corpus_dir"] / "addendum_de.pdf").write_bytes(b"this is not a pdf")
    result = run_ingestion(str(built["manifest_path"]), str(built["corpus_dir"]))
    assert "ADD-DE" in result.failures
    assert any(c.doc_id == "POL-V2" for c in result.chunks)


def test_scans_without_ocr_are_warned_about_not_fatal(tmp_path):
    built = build_corpus(tmp_path)
    result = run_ingestion(str(built["manifest_path"]), str(built["corpus_dir"]),
                           ocr=OcrEngine(command="no-such-ocr-program"))
    assert not result.failures
    assert any("MEMO-WFH" in w and "OCR is unavailable" in w for w in result.warnings)


def test_bad_manifest_entries_become_warnings(tmp_path):
    built = build_corpus(tmp_path)
    manifest = json.loads(built["manifest_path"].read_text())
    manifest.append({"doc_id": "BROKEN"})
    built["manifest_path"].write_text(json.dumps(manifest))
    result = run_ingestion(str(built["manifest_path"]), str(built["corpus_dir"]))
    assert any("BROKEN" in w for w in result.warnings) and not result.failures


def test_running_ingestion_twice_gives_the_same_holidays(tmp_path, conn):
    built = build_corpus(tmp_path)
    run_ingestion(str(built["manifest_path"]), str(built["corpus_dir"]), conn)
    first = conn.execute("SELECT COUNT(*) FROM holidays WHERE doc_id IN ('CAL-IN','CAL-US')").fetchone()[0]
    run_ingestion(str(built["manifest_path"]), str(built["corpus_dir"]), conn)
    assert conn.execute("SELECT COUNT(*) FROM holidays WHERE doc_id IN ('CAL-IN','CAL-US')").fetchone()[0] == first


def test_no_chunk_contains_page_furniture_or_metadata_tables(tmp_path):
    built = build_corpus(tmp_path)
    result = run_ingestion(str(built["manifest_path"]), str(built["corpus_dir"]))
    for chunk in result.chunks:
        assert "TEST-DOC" not in chunk.text and "Page 1" not in chunk.text
        assert "Document ID" not in chunk.text
