from datetime import date

import pytest

from app.data import repository
from app.ingestion.holidays import HolidayRow, extract_holidays, find_date, store_holidays
from app.ingestion.models import Block, DocMeta, ParsedDocument
from app.ingestion.readers import read_document
from tests.corpus_factory import build_corpus, write


@pytest.mark.parametrize("text, expected", [
    ("15 January 2026", date(2026, 1, 15)),
    ("1st May 2026", date(2026, 5, 1)),
    ("January 15, 2026", date(2026, 1, 15)),
    ("Sept 3 2026", date(2026, 9, 3)),
    ("2026-12-25", date(2026, 12, 25)),
    ("Date: 8 March 2026 (Sunday)", date(2026, 3, 8)),
])
def test_find_date_understands_common_spellings(text, expected):
    assert find_date(text) == expected


@pytest.mark.parametrize("text", ["", "no date here", "31 February 2026", "03/04/2026", "Monday"])
def test_find_date_returns_none_when_there_is_no_clear_date(text):
    assert find_date(text) is None


def meta(doc_id="CAL", regions=("IN",), effective="2026-01-01"):
    return DocMeta(doc_id, "f", "Calendar", "calendar", regions, effective, "all")


def table_doc(heading, rows):
    return ParsedDocument(meta=meta(), blocks=[
        Block(kind="heading", text=heading), Block(kind="table", rows=rows)])


def test_public_table_is_extracted_with_names_from_the_holiday_column():
    doc = table_doc("Public holidays 2026", [
        ["Date", "Day", "Holiday"],
        ["9 November 2026", "Monday", "Festival of Lights"],
        ["25 December 2026", "Friday", "Winter Day"]])
    assert extract_holidays(doc) == [
        HolidayRow(date(2026, 11, 9), "Festival of Lights", "public"),
        HolidayRow(date(2026, 12, 25), "Winter Day", "public")]


def test_weekend_holidays_are_kept_in_the_table():
    doc = table_doc("Holidays", [["Date", "Day", "Holiday"], ["1 November 2026", "Sunday", "State Day"]])
    assert extract_holidays(doc)[0].day == date(2026, 11, 1)


def test_restricted_kind_comes_from_the_heading():
    doc = table_doc("2. Restricted holidays 2026", [["Date", "Day", "Name"], ["24 November 2026", "Tuesday", "Guru Day"]])
    assert extract_holidays(doc)[0].kind == "restricted"


def test_restricted_kind_comes_from_the_column_header():
    doc = table_doc("Holidays", [["Date", "Day", "Optional holiday"], ["24 November 2026", "Tuesday", "Guru Day"]])
    assert extract_holidays(doc)[0].kind == "restricted"


def test_table_without_a_header_row_still_works():
    doc = table_doc("Holidays", [["1 January 2026", "New Year"], ["25 December 2026", "Winter Day"]])
    assert [h.name for h in extract_holidays(doc)] == ["New Year", "Winter Day"]


def test_tables_that_are_not_holiday_lists_are_ignored():
    doc = table_doc("Rates", [["Level", "Days"], ["Junior", "20"]])
    assert extract_holidays(doc) == []


def test_bulleted_holiday_lines_under_a_holiday_heading_are_read():
    doc = ParsedDocument(meta=meta(), blocks=[
        Block(kind="heading", text="Public holidays"),
        Block(kind="text", text="- 25 December 2026: Winter Day")])
    assert extract_holidays(doc) == [HolidayRow(date(2026, 12, 25), "Winter Day", "public")]


# ---- end to end through the readers and the database -------------------------------------

def test_pdf_and_html_calendars_are_extracted_and_stored(tmp_path, conn):
    built = build_corpus(tmp_path)
    corpus = built["corpus_dir"]
    for doc_id, file, region in (("CAL-IN", "calendar_in.pdf", "IN"), ("CAL-US", "calendar_us.html", "US")):
        m = DocMeta(doc_id, file, "Cal", "calendar", (region,), "2026-01-01", "all")
        store_holidays(conn, m, extract_holidays(read_document(str(corpus / file), m)))

    india = repository.holiday_dates(conn, "IN", date(2026, 10, 15), 2026)
    assert india == {date(2026, 11, 9), date(2026, 11, 1), date(2026, 12, 25)}   # restricted 24 Nov excluded
    us = repository.holiday_dates(conn, "US", date(2026, 10, 15), 2026)
    assert us == {date(2026, 11, 26), date(2026, 11, 27)}
    restricted = conn.execute("SELECT name FROM holidays WHERE doc_id='CAL-IN' AND kind='restricted'").fetchall()
    assert [r["name"] for r in restricted] == ["Guru Day"]


def test_storing_again_replaces_old_rows(conn):
    m = meta("CAL-X", ("DE",))
    store_holidays(conn, m, [HolidayRow(date(2026, 5, 1), "Labour Day", "public")])
    store_holidays(conn, m, [HolidayRow(date(2026, 5, 14), "Ascension", "public")])
    dates = [r["holiday_date"] for r in conn.execute("SELECT holiday_date FROM holidays WHERE doc_id='CAL-X'")]
    assert dates == ["2026-05-14"]


def test_a_calendar_for_several_regions_is_stored_for_each(conn):
    store_holidays(conn, meta("CAL-M", ("IN", "US")), [HolidayRow(date(2026, 7, 4), "Day", "public")])
    regions = {r["region"] for r in conn.execute("SELECT region FROM holidays WHERE doc_id='CAL-M'")}
    assert regions == {"IN", "US"}


def test_changed_calendar_changes_the_working_days(tmp_path, conn):
    # The reviewers test a modified corpus: new dates must flow through to apply_leave.
    from app.tools.leave_apply import check_apply_leave
    from tests.conftest import TODAY
    from app.tools.context import ToolContext

    path = tmp_path / "cal.md"
    m = DocMeta("CAL-NEW", "cal.md", "Cal", "calendar", ("IN",), "2026-09-01", "all")
    write(path, "# Calendar\n\n## Public holidays\n\n| Date | Day | Holiday |\n| --- | --- | --- |\n"
                "| 18 November 2026 | Wednesday | Moved Day |\n")
    store_holidays(conn, m, extract_holidays(read_document(str(path), m)))
    ctx = ToolContext(conn, repository.get_employee(conn, "E1"), TODAY)
    result = check_apply_leave(ctx, "annual", "2026-11-18", "2026-11-18")
    assert result.code == "zero_working_days"      # the new calendar (effective later) now applies
