import json

import pytest

from app.ingestion.manifest import ManifestError, load_manifest


def write_manifest(tmp_path, entries):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return str(path)


def entry(**overrides):
    base = {"doc_id": "D1", "file": "d1.md", "title": "T", "doc_type": "policy",
            "regions": ["GLOBAL"], "effective_date": "2026-01-01", "access_level": "all"}
    base.update(overrides)
    return base


def test_valid_entries_load(tmp_path):
    docs, problems = load_manifest(write_manifest(tmp_path, [entry(), entry(doc_id="D2")]))
    assert [d.doc_id for d in docs] == ["D1", "D2"] and problems == []


def test_regions_and_levels_are_normalised(tmp_path):
    docs, _ = load_manifest(write_manifest(tmp_path, [entry(regions=["in", " us "], access_level="HR", doc_type="FAQ")]))
    assert docs[0].regions == ("IN", "US") and docs[0].access_level == "hr" and docs[0].doc_type == "faq"


def test_a_single_region_string_is_accepted(tmp_path):
    docs, _ = load_manifest(write_manifest(tmp_path, [entry(regions="DE")]))
    assert docs[0].regions == ("DE",)


def test_bad_entries_are_reported_and_skipped(tmp_path):
    path = write_manifest(tmp_path, [
        entry(doc_id="OK"),
        entry(doc_id="NODATE", effective_date=""),
        entry(doc_id="BADDATE", effective_date="01/02/2026"),
        entry(doc_id="OK"),                       # duplicate
        "not an object",
    ])
    docs, problems = load_manifest(path)
    assert [d.doc_id for d in docs] == ["OK"]
    assert len(problems) == 4


def test_missing_or_invalid_manifest_raises(tmp_path):
    with pytest.raises(ManifestError):
        load_manifest(str(tmp_path / "nope.json"))
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(ManifestError):
        load_manifest(str(bad))
    obj = tmp_path / "obj.json"
    obj.write_text("{}")
    with pytest.raises(ManifestError):
        load_manifest(str(obj))
