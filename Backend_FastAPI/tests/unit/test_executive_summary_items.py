"""Unit: executive_summary structured blocker/warning items (Phase 3).

Pins the ``{code, message, step, section, severity}`` shape + step/section
mapping + UNCHANGED blocker/warning semantics for
``_build_executive_summary_items``. Pure function — no DB, no fixtures.
"""
from app.services.admission_service import _build_executive_summary_items


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
