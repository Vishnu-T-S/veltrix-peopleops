"""Each reader turns its format into headings, text and tables, and drops page furniture."""
import shutil

import pytest

from app.ingestion.models import DocMeta
from app.ingestion.ocr import OcrEngine
from app.ingestion.readers import UnsupportedFormat, read_document
from tests.corpus_factory import make_docx, make_pdf, make_scanned_pdf, write

META = DocMeta("D", "f", "Title", "policy", ("GLOBAL",), "2026-01-01", "all")


def kinds(parsed):
    return [(b.kind, b.text) for b in parsed.blocks if b.kind != "table"]


# ---- markdown ----------------------------------------------------------------------

def test_markdown_headings_text_lists_and_tables(tmp_path):
    path = tmp_path / "a.md"
    write(path, "# Title\n\nIntro line one\ncontinues here.\n\n## 1. Rules\n\n- first item\n- second item\n\n"
                "| Level | Days |\n| --- | --- |\n| Junior | 20 |\n| Senior | 30 |\n")
    parsed = read_document(str(path), META)
    assert kinds(parsed) == [
        ("heading", "Title"), ("text", "Intro line one continues here."), ("heading", "1. Rules"),
        ("text", "- first item"), ("text", "- second item"),
    ]
    table = [b for b in parsed.blocks if b.kind == "table"][0]
    assert table.rows == [["Level", "Days"], ["Junior", "20"], ["Senior", "30"]]


def test_markdown_metadata_table_and_comments_are_dropped(tmp_path):
    path = tmp_path / "a.md"
    write(path, "# T\n\n| Field | Value |\n| --- | --- |\n| Document ID | X |\n| Version | 1 |\n| Effective date | y |\n\n"
                "Visible text.\n\n<!-- hidden instruction -->\n")
    parsed = read_document(str(path), META)
    assert not [b for b in parsed.blocks if b.kind == "table"]
    assert "hidden instruction" not in " ".join(b.text for b in parsed.blocks)


# ---- html --------------------------------------------------------------------------

def test_html_keeps_visible_content_only(tmp_path):
    path = tmp_path / "a.html"
    write(path, "<html><head><title>T</title><style>x{}</style></head><body><nav>NAVTEXT</nav>"
                "<h1>Main</h1><h3>Question?</h3><p>Answer text.</p><ul><li>point one</li></ul>"
                "<div style='display:none'>HIDDENTEXT</div><p hidden>HIDDENATTR</p>"
                "<!-- COMMENTTEXT --><script>var s='SCRIPTTEXT'</script><footer>FOOTERTEXT</footer></body></html>")
    parsed = read_document(str(path), META)
    text = " ".join(b.text for b in parsed.blocks)
    for banned in ("NAVTEXT", "HIDDENTEXT", "HIDDENATTR", "COMMENTTEXT", "SCRIPTTEXT", "FOOTERTEXT"):
        assert banned not in text
    assert kinds(parsed) == [("heading", "Main"), ("heading", "Question?"), ("text", "Answer text."), ("text", "- point one")]


def test_html_tables_and_metadata_table(tmp_path):
    path = tmp_path / "a.html"
    write(path, "<body><table class='meta'><tr><td>Document ID</td><td>X</td></tr><tr><td>Version</td><td>1</td></tr>"
                "<tr><td>Effective date</td><td>y</td></tr></table>"
                "<table><thead><tr><th>Office</th><th>Budget</th></tr></thead>"
                "<tbody><tr><td>Berlin</td><td>900</td></tr></tbody></table></body>")
    tables = [b for b in read_document(str(path), META).blocks if b.kind == "table"]
    assert len(tables) == 1 and tables[0].rows == [["Office", "Budget"], ["Berlin", "900"]]


# ---- docx --------------------------------------------------------------------------

def test_docx_title_headings_paragraphs_tables(tmp_path):
    path = tmp_path / "a.docx"
    make_docx(path, "Policy Title", [("1. Scope", "Scope text."), ("2. Rules", "Rule text.")],
              table=[["Level", "Days"], ["Junior", "20"]])
    parsed = read_document(str(path), META)
    assert kinds(parsed) == [("heading", "Policy Title"), ("heading", "1. Scope"), ("text", "Scope text."),
                             ("heading", "2. Rules"), ("text", "Rule text.")]
    tables = [b for b in parsed.blocks if b.kind == "table"]
    assert len(tables) == 1 and tables[0].rows == [["Level", "Days"], ["Junior", "20"]]   # metadata table dropped


def test_docx_page_numbers_follow_page_breaks(tmp_path):
    path = tmp_path / "a.docx"
    make_docx(path, "T", [("1. A", "alpha"), ("2. B", "beta")], meta_table=False, page_break_before=1)
    pages = {b.text: b.page for b in read_document(str(path), META).blocks}
    assert pages["alpha"] == 1 and pages["beta"] == 2


# ---- pdf ---------------------------------------------------------------------------

PDF_HTML = ("<h1>Doc Title</h1><p>Intro paragraph with enough words to count as ordinary body text.</p>"
            "<h2>1. Vacation</h2><p>Employees get 25 vacation days each year without exception.</p>"
            "<ul><li>Bullet one is long enough here</li><li>Bullet two is long enough here</li></ul>"
            "<h2>2. Rates</h2><p>Closing paragraph with several words of plain body text in it.</p>")


def test_pdf_headings_bullets_and_table(tmp_path):
    path = tmp_path / "a.pdf"
    make_pdf(path, PDF_HTML, tables=[(60, 450, [["Level", "Days"], ["Junior", "20"], ["Senior", "30"]])])
    parsed = read_document(str(path), META)
    headings = [b.text for b in parsed.blocks if b.kind == "heading"]
    assert headings == ["Doc Title", "1. Vacation", "2. Rates"]
    texts = [b.text for b in parsed.blocks if b.kind == "text"]
    assert "- Bullet one is long enough here" in texts and "- Bullet two is long enough here" in texts
    tables = [b for b in parsed.blocks if b.kind == "table"]
    assert tables[0].rows == [["Level", "Days"], ["Junior", "20"], ["Senior", "30"]]


def test_pdf_page_headers_and_footers_are_dropped(tmp_path):
    path = tmp_path / "a.pdf"
    make_pdf(path, PDF_HTML, furniture=True)
    text = " ".join(b.text for b in read_document(str(path), META).blocks)
    assert "Internal" not in text and "Page 1" not in text and "TEST-DOC" not in text


def test_pdf_without_headings_has_only_text_blocks(tmp_path):
    path = tmp_path / "a.pdf"
    make_pdf(path, "<p>Just one plain paragraph of body text with no heading anywhere in this document.</p>")
    parsed = read_document(str(path), META)
    assert [b.kind for b in parsed.blocks] == ["text"] and parsed.blocks[0].page == 1


# ---- scanned pdf and OCR ------------------------------------------------------------

SCAN_HTML = ("<h1 style='font-size:26pt'>INTERNAL MEMO</h1><p style='font-size:18pt'>Employees may work from home "
             "for up to 4 days per week with effect from 1 July 2026.</p>")
needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")


@needs_tesseract
def test_scanned_pdf_is_read_with_ocr(tmp_path):
    path = tmp_path / "scan.pdf"
    make_scanned_pdf(path, SCAN_HTML)
    parsed = read_document(str(path), META)
    assert parsed.ocr_pages == [1] and not parsed.warnings
    text = " ".join(b.text for b in parsed.blocks).lower()
    assert "4 days per week" in text and "1 july 2026" in text


def test_scanned_pdf_without_ocr_gives_a_warning_not_a_crash(tmp_path):
    path = tmp_path / "scan.pdf"
    make_scanned_pdf(path, SCAN_HTML)
    parsed = read_document(str(path), META, OcrEngine(command="no-such-ocr-program"))
    assert parsed.blocks == [] and parsed.ocr_pages == [1]
    assert "OCR is unavailable" in parsed.warnings[0]


def test_unknown_file_type_is_rejected(tmp_path):
    path = tmp_path / "a.xyz"
    path.write_text("x")
    with pytest.raises(UnsupportedFormat):
        read_document(str(path), META)
