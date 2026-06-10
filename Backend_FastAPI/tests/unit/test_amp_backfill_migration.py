"""Unit test cho logic backfill migration ampfix01 (gỡ double-escape "amp").

Khóa nửa "sửa dữ liệu lịch sử" của fix amp: ``_unescape_stable`` (gỡ N lớp
``&amp;``), ``_ENTITY_RE`` (predicate nhận diện entity), ``_coerce_json``
(asyncpg trả str vs list), ``_clean_list``. Migration không chạy qua alembic
trong test DB (create_all), nên test này là tầng bảo vệ runtime cho logic gỡ
corruption.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "ampfix01_20260609_backfill_school_name_unescape.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ampfix01_mig", str(MIGRATION_PATH))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mig = _load()


def test_unescape_stable_collapses_many_amp_layers():
    corrupted = "THPT Ea H&amp;amp;amp;amp;amp;amp;amp;amp;#x27;leo (Từ 04/6/2021)"
    assert mig._unescape_stable(corrupted) == "THPT Ea H'leo (Từ 04/6/2021)"


def test_unescape_stable_single_layer():
    assert mig._unescape_stable("THPT Ea H&#x27;leo") == "THPT Ea H'leo"
    assert mig._unescape_stable("THCS &amp; THPT") == "THCS & THPT"


def test_unescape_stable_idempotent_on_clean():
    cleans = ["THPT Ea H'leo (Từ 04/6/2021)", "THCS & THPT Nguyễn Du", "Bình thường"]
    for clean in cleans:
        assert mig._unescape_stable(clean) == clean


def test_unescape_stable_non_string_passthrough():
    assert mig._unescape_stable(None) is None
    assert mig._unescape_stable(123) == 123


def test_entity_regex_matches_real_entities_not_bare_ampersand():
    pat = re.compile(mig._ENTITY_RE)
    for hit in ["a&amp;b", "x&#x27;y", "p&#39;q", "u&lt;v", "m&gt;n", "s&quot;t"]:
        assert pat.search(hit), f"phải match entity: {hit}"
    # Bare '&' (tên trường thật "THCS & THPT") KHÔNG được match → không backfill nhầm.
    for clean in ["THCS & THPT", "THCS&THPT", "A & B & C", "Plain name"]:
        assert not pat.search(clean), f"KHÔNG được match clean: {clean}"


def test_coerce_json_handles_str_and_parsed():
    # asyncpg có thể trả JSONB đã parse (list) hoặc str — cả hai phải ra list.
    assert mig._coerce_json('[{"school_name": "X"}]') == [{"school_name": "X"}]
    assert mig._coerce_json([{"school_name": "X"}]) == [{"school_name": "X"}]


def test_clean_list_unescapes_target_fields_and_reports_change():
    academic = [{"school_name": "THPT Ea H&amp;#x27;leo", "gpa": None}]
    changed = mig._clean_list(academic, ("school_name",))
    assert changed is True
    assert academic[0]["school_name"] == "THPT Ea H'leo"
    # field không nằm trong danh sách → không đụng; clean → không báo changed.
    clean = [{"school_name": "THPT Sạch", "full_name": "Nguyễn &amp; Văn"}]
    assert mig._clean_list(clean, ("school_name",)) is False
    assert clean[0]["full_name"] == "Nguyễn &amp; Văn"


@pytest.mark.parametrize("bad", [None, "not-a-list", 42])
def test_clean_list_tolerates_non_list_entries(bad):
    # _clean_list duyệt entry; entry không phải dict bị bỏ qua, không crash.
    assert mig._clean_list([bad], ("school_name",)) is False
