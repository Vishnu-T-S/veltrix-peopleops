from datetime import date

import pytest

from app.config import load_settings, parse_iso_date


def test_defaults_point_at_data_folder():
    s = load_settings({})
    assert s.corpus_dir == "./data/corpus"
    assert s.manifest_path == "./data/manifest.json"
    assert s.db_path == "./data/veltrix.db"
    assert s.llm_provider == "openai"


def test_app_today_is_read_from_environment():
    s = load_settings({"APP_TODAY": "2026-09-15"})
    assert s.app_today == date(2026, 9, 15)


def test_empty_app_today_falls_back_to_system_date():
    s = load_settings({"APP_TODAY": ""})
    assert s.app_today == date.today()


@pytest.mark.parametrize("bad", ["15/09/2026", "2026-9-5", "20260915", "tomorrow", ""])
def test_parse_iso_date_rejects_non_iso_strings(bad):
    with pytest.raises(ValueError):
        parse_iso_date(bad)


def test_parse_iso_date_rejects_impossible_dates():
    with pytest.raises(ValueError):
        parse_iso_date("2026-02-30")
