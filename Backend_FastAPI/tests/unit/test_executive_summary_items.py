"""Unit: executive_summary structured blocker/warning items (Phase 3).

Pins the ``{code, message, step, section, severity}`` shape + step/section
mapping + UNCHANGED blocker/warning semantics for
``_build_executive_summary_items``. Pure function — no DB, no fixtures.
"""
from app.services.admission_service import (
    _build_executive_summary_items,
    _coerce_year,
    _strict_int,
    _thcs_grade9_completion_year,
)


def _summary(**overrides):
    """Gọi builder với baseline SẠCH (0 blocker/warning) + override.

    Dùng cho nhóm test cảnh báo THCS — chỉ bật field cần kiểm tra, phần còn
    lại sạch để warning THCS là item duy nhất xuất hiện.
    """
    base = dict(
        personal_error_count=0,
        missing_doc_count=0,
        unverified_doc_count=0,
        gpa_error=False,
        has_family=True,
        has_academic=True,
        docs_format_confirmed=True,
    )
    base.update(overrides)
    return _build_executive_summary_items(**base)


def _all_triggered():
    return _build_executive_summary_items(
        personal_error_count=2,
        missing_doc_count=3,
        unverified_doc_count=1,
        gpa_error=True,
        has_family=False,
        has_academic=False,
        docs_format_confirmed=False,
    )


def test_critical_blockers_shape_and_mapping():
    blockers, _ = _all_triggered()
    by_code = {b["code"]: b for b in blockers}
    assert by_code["personal_info_missing"]["step"] == 1
    assert by_code["personal_info_missing"]["section"] == "personal_info"
    assert by_code["personal_info_missing"]["severity"] == "blocker"
    assert by_code["personal_info_missing"]["message"] == "Thiếu 2 thông tin cá nhân bắt buộc"
    assert by_code["documents_missing"]["step"] == 6
    assert by_code["documents_missing"]["section"] == "documents"
    assert by_code["documents_missing"]["message"] == "Thiếu 3 tài liệu bắt buộc"
    assert by_code["documents_unverified"]["step"] == 6
    assert by_code["documents_unverified"]["message"] == "1 tài liệu chờ xác minh từ quản lý"
    assert by_code["score_below_threshold"]["step"] == 5
    assert by_code["score_below_threshold"]["section"] == "scores"


def test_warnings_shape_and_mapping():
    _, warnings = _all_triggered()
    by_code = {w["code"]: w for w in warnings}
    assert by_code["family_missing"]["step"] == 2
    assert by_code["family_missing"]["section"] == "family"
    assert by_code["academic_missing"]["step"] == 3
    assert by_code["academic_missing"]["section"] == "academic"
    assert by_code["documents_format_unconfirmed"]["step"] == 6
    assert by_code["documents_format_unconfirmed"]["section"] == "documents"


def test_severity_split_unchanged():
    blockers, warnings = _all_triggered()
    assert all(b["severity"] == "blocker" for b in blockers)
    assert all(w["severity"] == "warning" for w in warnings)
    # family/academic/docs-format stay WARNINGS — NOT promoted to blockers.
    blocker_codes = {b["code"] for b in blockers}
    assert "family_missing" not in blocker_codes
    assert "academic_missing" not in blocker_codes
    assert "documents_format_unconfirmed" not in blocker_codes


def test_no_items_when_clean():
    blockers, warnings = _build_executive_summary_items(
        personal_error_count=0,
        missing_doc_count=0,
        unverified_doc_count=0,
        gpa_error=False,
        has_family=True,
        has_academic=True,
        docs_format_confirmed=True,
    )
    assert blockers == []
    assert warnings == []


def test_every_item_has_required_keys():
    blockers, warnings = _all_triggered()
    for item in [*blockers, *warnings]:
        assert set(item.keys()) == {"code", "message", "step", "section", "severity"}
        assert isinstance(item["step"], int)


def test_no_tuition_step_7_item():
    # Tuition is display-only — the builder must NEVER emit a step-7 item.
    blockers, warnings = _all_triggered()
    assert all(item["step"] != 7 for item in [*blockers, *warnings])


# ---------------------------------------------------------------------------
# THCS diploma review (soft warning) — Thông tư 10/2026 (bỏ bằng TN THCS)
# ---------------------------------------------------------------------------


def test_thcs_review_warning_fires_when_grade9_at_threshold():
    _, warnings = _summary(
        cultural="graduated_thcs",
        academic_history=[{"grade_to": 9, "year_to": 2026}],
        thcs_review_from_year=2026,
    )
    by_code = {w["code"]: w for w in warnings}
    assert "thcs_diploma_review" in by_code
    w = by_code["thcs_diploma_review"]
    assert w["step"] == 4
    assert w["section"] == "priority"
    assert w["severity"] == "warning"
    assert "2026" in w["message"]


def test_thcs_review_warning_silent_when_grade9_before_threshold():
    # Lớp 9 xong 2025 (NH 2024-2025) → còn có bằng TN THCS → không cảnh báo.
    _, warnings = _summary(
        cultural="graduated_thcs",
        academic_history=[{"grade_to": 9, "year_to": 2025}],
        thcs_review_from_year=2026,
    )
    assert all(w["code"] != "thcs_diploma_review" for w in warnings)


def test_thcs_review_warning_silent_for_completed_thcs():
    _, warnings = _summary(
        cultural="completed_thcs",
        academic_history=[{"grade_to": 9, "year_to": 2026}],
        thcs_review_from_year=2026,
    )
    assert all(w["code"] != "thcs_diploma_review" for w in warnings)


def test_thcs_review_warning_silent_when_no_grade9_record():
    # Thiếu record lớp 9 → không đủ cơ sở → KHÔNG cảnh báo (tránh false-positive).
    for hist in (None, [], [{"grade_to": 12, "year_to": 2026}]):
        _, warnings = _summary(
            cultural="graduated_thcs",
            academic_history=hist,
            thcs_review_from_year=2026,
        )
        assert all(w["code"] != "thcs_diploma_review" for w in warnings)


def test_thcs_review_warning_silent_when_year_not_configured():
    # review_from_year=None (mặc định) → no-op kể cả graduated_thcs + lớp 9 mới.
    _, warnings = _summary(
        cultural="graduated_thcs",
        academic_history=[{"grade_to": 9, "year_to": 2030}],
    )
    assert all(w["code"] != "thcs_diploma_review" for w in warnings)


def test_thcs_review_warning_takes_max_grade9_year():
    # Nhiều record lớp 9 (học lại/chuyển trường) → lấy max(year_to).
    _, warnings = _summary(
        cultural="graduated_thcs",
        academic_history=[
            {"grade_to": 9, "year_to": 2024},
            {"grade_to": 9, "year_to": 2026},
        ],
        thcs_review_from_year=2026,
    )
    assert any(w["code"] == "thcs_diploma_review" for w in warnings)


# -- parser nghiêm: chỉ int + chuỗi-int; loại bool/float --


def test_strict_int_accepts_int_and_int_string():
    assert _strict_int(9) == 9
    assert _strict_int("9") == 9
    assert _strict_int("  2026 ") == 2026
    assert _strict_int("-5") == -5


def test_strict_int_rejects_bool_float_and_garbage():
    assert _strict_int(True) is None  # bool KHÔNG được coi là 1
    assert _strict_int(False) is None
    assert _strict_int(9.0) is None  # float bị int() cắt cụt → loại
    assert _strict_int(9.7) is None
    assert _strict_int("9.0") is None
    assert _strict_int("nine") is None
    assert _strict_int(None) is None


def test_grade9_year_ignores_bool_float_grade():
    assert _thcs_grade9_completion_year(
        [{"grade_to": True, "year_to": 2026}]
    ) is None
    assert _thcs_grade9_completion_year(
        [{"grade_to": 9.0, "year_to": 2026}]
    ) is None
    assert (
        _thcs_grade9_completion_year([{"grade_to": "9", "year_to": "2026"}])
        == 2026
    )


def test_strict_int_rejects_unicode_digit_and_overlong():
    # '²' isdigit()=True nhưng int('²') ném ValueError → PHẢI trả None.
    assert _strict_int("²") is None
    assert _strict_int("٩") is None  # chữ số Ả Rập-Ấn (non-ASCII)
    # Chuỗi cực dài → tránh ValueError "integer string conversion limit".
    assert _strict_int("9" * 5000) is None
    assert _strict_int("9" * 10) is None  # >9 ký tự → loại


def test_grade9_year_rejects_out_of_range():
    # year_to ngoài [1900, 2100] → bỏ (applied JSONB bẩn không qua schema).
    assert _thcs_grade9_completion_year([{"grade_to": 9, "year_to": 9999}]) is None
    assert _thcs_grade9_completion_year([{"grade_to": 9, "year_to": "1899"}]) is None
    assert _thcs_grade9_completion_year([{"grade_to": 9, "year_to": 2026}]) == 2026


def test_grade9_year_accepts_level_thcs_without_grade_to():
    # F1: officer điền level='THCS' nhưng để grade_to NULL → vẫn nhận (recall).
    assert (
        _thcs_grade9_completion_year(
            [{"level": "THCS", "year_from": 2022, "year_to": 2026}]
        )
        == 2026
    )
    assert (
        _thcs_grade9_completion_year([{"level": "thcs", "year_to": 2026}]) == 2026
    )
    # THCS_THPT (cấp 2+3): year_to là năm TN THPT, KHÔNG phải lớp 9 → loại.
    assert (
        _thcs_grade9_completion_year([{"level": "THCS_THPT", "year_to": 2026}])
        is None
    )


def test_grade9_year_accepts_float_integer_year():
    # F2: year_to dạng float nguyên (2026.0) vẫn nhận; float lẻ thì loại.
    assert _thcs_grade9_completion_year([{"grade_to": 9, "year_to": 2026.0}]) == 2026
    assert _thcs_grade9_completion_year([{"grade_to": 9, "year_to": 2026.5}]) is None


def test_coerce_year_accepts_int_float_integer_string():
    assert _coerce_year(2026) == 2026
    assert _coerce_year(2026.0) == 2026
    assert _coerce_year("2026") == 2026
    assert _coerce_year(2026.5) is None
    assert _coerce_year(True) is None  # bool KHÔNG phải năm
    assert _coerce_year(float("nan")) is None
    assert _coerce_year(float("inf")) is None
