from datetime import date

from app.data import repository
from app.tools.working_days import count_working_days, working_dates

# October 2026: Thu 15, Fri 16, Sat 17, Sun 18, Mon 19
NO_HOLIDAYS: set = set()


def test_single_weekday_is_one_day():
    assert count_working_days(date(2026, 10, 15), date(2026, 10, 15), NO_HOLIDAYS) == 1


def test_a_full_week_is_five_days():
    assert count_working_days(date(2026, 10, 12), date(2026, 10, 18), NO_HOLIDAYS) == 5


def test_saturday_only_is_zero():
    assert count_working_days(date(2026, 10, 17), date(2026, 10, 17), NO_HOLIDAYS) == 0


def test_weekend_only_range_is_zero():
    assert count_working_days(date(2026, 10, 17), date(2026, 10, 18), NO_HOLIDAYS) == 0


def test_range_spanning_a_weekend_skips_it():
    # Fri 16 -> Mon 19: Friday and Monday only
    assert count_working_days(date(2026, 10, 16), date(2026, 10, 19), NO_HOLIDAYS) == 2


def test_holiday_on_a_weekday_is_removed():
    holidays = {date(2026, 11, 9)}  # Monday
    assert count_working_days(date(2026, 11, 9), date(2026, 11, 13), holidays) == 4


def test_holiday_on_a_weekend_is_not_subtracted_twice():
    holidays = {date(2026, 11, 1)}  # Sunday
    assert count_working_days(date(2026, 10, 30), date(2026, 11, 3), holidays) == 3  # Fri, Mon, Tue


def test_range_spanning_weekend_and_holiday():
    # Thu 5 -> Tue 10 Nov 2026 with a Monday holiday on the 9th: Thu, Fri, Tue
    holidays = {date(2026, 11, 9)}
    assert count_working_days(date(2026, 11, 5), date(2026, 11, 10), holidays) == 3


def test_holiday_at_start_and_end_of_range():
    holidays = {date(2026, 12, 24), date(2026, 12, 25)}  # Thu, Fri
    assert count_working_days(date(2026, 12, 24), date(2026, 12, 25), holidays) == 0


def test_end_before_start_is_zero():
    assert count_working_days(date(2026, 10, 20), date(2026, 10, 19), NO_HOLIDAYS) == 0


def test_long_range_over_a_month():
    # 1 to 31 Dec 2026 has 23 weekdays; minus Christmas Day (Friday) = 22
    holidays = {date(2026, 12, 25)}
    assert count_working_days(date(2026, 12, 1), date(2026, 12, 31), holidays) == 22


def test_working_dates_lists_the_actual_days():
    days = working_dates(date(2026, 10, 15), date(2026, 10, 19), NO_HOLIDAYS)
    assert days == [date(2026, 10, 15), date(2026, 10, 16), date(2026, 10, 19)]


# ---- holidays read from the database --------------------------------------

def test_holidays_come_from_the_requesters_region(conn):
    india = repository.holiday_dates(conn, "IN", date(2026, 10, 15), 2026)
    germany = repository.holiday_dates(conn, "DE", date(2026, 10, 15), 2026)
    assert date(2026, 11, 9) in india and date(2026, 11, 9) not in germany
    assert date(2026, 12, 24) in germany and date(2026, 12, 24) not in india


def test_restricted_holidays_do_not_count_as_holidays(conn):
    india = repository.holiday_dates(conn, "IN", date(2026, 10, 15), 2026)
    assert date(2026, 11, 24) not in india  # restricted: the office stays open


def test_calendar_for_the_right_year_is_used(conn):
    # An older (2025) calendar exists too; it must not leak into 2026 results
    india = repository.holiday_dates(conn, "IN", date(2026, 10, 15), 2026)
    assert all(d.year == 2026 for d in india)


def test_later_effective_calendar_wins_for_the_same_region_and_year(conn):
    conn.execute(
        "INSERT INTO holidays VALUES ('CAL-IN-2026-REV','IN','2026-11-10','Revised day','public','2026-09-01')"
    )
    india = repository.holiday_dates(conn, "IN", date(2026, 10, 15), 2026)
    assert india == {date(2026, 11, 10)}


def test_calendar_not_yet_effective_is_ignored(conn):
    conn.execute(
        "INSERT INTO holidays VALUES ('CAL-IN-2026-NEXT','IN','2026-11-10','Future day','public','2026-12-01')"
    )
    india = repository.holiday_dates(conn, "IN", date(2026, 10, 15), 2026)
    assert date(2026, 11, 10) not in india
    assert date(2026, 11, 9) in india


def test_region_without_a_calendar_has_no_holidays(conn):
    assert repository.holiday_dates(conn, "FR", date(2026, 10, 15), 2026) == set()
