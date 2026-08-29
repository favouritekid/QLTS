"""Unit tests for #184 Wave 4 #15b hotfix — race-safe idempotency check
in ``create_profile()`` must scope to the target ``academic_year``.

Background
----------

Wave 3-E ``phase1_15a`` (PR #223 squash ``15f52c8e``) replaced the
single-profile-per-lead UNIQUE with composite ``(lead_id, academic_year)``
UNIQUE. Wave 4 PR #15b (squash ``966d5f5f``) flipped the model to
plural and updated the eligibility check, but **left the secondary
race-safe DB check inside the redis lock using the deprecated
``get_profile_by_lead_id`` method** that returns the latest year
regardless. That secondary check would incorrectly block a lead that
already has a profile for, say, 2025 from creating one for 2026.

Hotfix
------

The check now uses ``get_profile_by_lead_year(lead_id, academic_year)``
with ``academic_year`` resolved from the explicit parameter or the
``current_intake_year`` system config (mirroring the eligibility check
fallback at the same call site).

Tests target the source surface (text grep + behavior expectations)
because the full ``create_profile`` flow has a long dependency chain
(redis lock + offering + path lookup + ...) that would dwarf the
narrow hotfix surface in setup/mock complexity.
"""
from __future__ import annotations

import inspect
import re

import pytest


# ---------------------------------------------------------------------------
# 1. Race-safe check uses year-aware repository method
# ---------------------------------------------------------------------------


def test_race_safe_check_calls_get_profile_by_lead_year_not_lead_id() -> None:
    """The secondary race-safe DB query must hit the composite-UNIQUE-
    keyed lookup so multi-year creates are not falsely rejected."""
    from app.services import admission_service

    src = inspect.getsource(admission_service.create_profile)

    # Find the redis-lock block — race-safe check lives inside it.
    lock_idx = src.index("acquire_redis_lock")
    eligibility_idx = src.index("check_lead_level_admission_eligibility(")
    race_block = src[lock_idx:eligibility_idx]

    # Inside the lock block, the new method must be called with both
    # lead_id and the resolved year.
    assert "get_profile_by_lead_year(" in race_block, (
        "race-safe check must call get_profile_by_lead_year (composite-"
        "UNIQUE-keyed) — not the deprecated get_profile_by_lead_id"
    )
    # And the deprecated method must NOT be reachable from the lock
    # block. (The repository class still exposes get_profile_by_lead_id
    # as a deprecated wrapper for legacy callers; create_profile must
    # not be one of them.)
    assert "get_profile_by_lead_id(" not in race_block, (
        "create_profile race-safe check still references the deprecated "
        "get_profile_by_lead_id — Wave 4 #15b hotfix incomplete"
    )


def test_race_safe_check_khong_con_fallback_academic_year_la_bat_buoc() -> None:
    """F30 (plan v4, 25-05-2026) GỠ HẲN fallback ``current_intake_year``.

    Ca cũ (`..._falls_back_to_current_intake_year_when_year_none`) khẳng định
    đúng thứ đã bị xoá CỐ Ý: ``SystemConfigService(db).get_value(
    "current_intake_year", 2026)``. Giữ nó là đang đòi khôi phục một hành vi
    mà bản hardening chủ động bỏ.

    Hợp đồng MỚI, và cũng là bất biến đáng canh hơn: ``academic_year`` là tham
    số BẮT BUỘC, nên hai cổng (race-safe check và eligibility check) không thể
    tự suy ra hai năm khác nhau. Một fallback ngầm quay lại chính là đường để
    chúng lệch năm mà không ai thấy.
    """
    import inspect as _inspect

    from app.services import admission_service

    tham_so = _inspect.signature(admission_service.create_profile).parameters
    assert "academic_year" in tham_so, "create_profile phải nhận academic_year"
    assert tham_so["academic_year"].default is _inspect.Parameter.empty, (
        "academic_year phải là tham số BẮT BUỘC (không default) — có default là "
        "mở lại đường suy ngầm ra năm, thứ F30 đã đóng"
    )

    src = _inspect.getsource(admission_service.create_profile)
    lock_idx = src.index("acquire_redis_lock")
    eligibility_idx = src.index("check_lead_level_admission_eligibility(")
    race_block = src[lock_idx:eligibility_idx]

    # So trên MÃ, không trên nguyên văn: cụm "current_intake_year" vẫn còn
    # trong CHÚ THÍCH giải thích việc gỡ. Khẳng định trên nguyên văn sẽ đỏ oan.
    ma = "\n".join(
        l for l in race_block.splitlines() if not l.strip().startswith("#")
    )
    assert "SystemConfigService" not in ma, (
        "race-safe check không được suy năm qua SystemConfigService nữa"
    )
    assert "current_intake_year" not in ma, (
        "race-safe check không được đọc config current_intake_year nữa"
    )
    assert "academic_year" in ma, "race-safe check phải scope theo academic_year"


# ---------------------------------------------------------------------------
# 2. Error message scoped to the year (operator UX)
# ---------------------------------------------------------------------------


def test_race_safe_conflict_message_scoped_to_year(monkeypatch) -> None:
    """The ``ConflictError`` raised when a duplicate is detected must
    name the academic year — operators reading the prod log shouldn't
    have to guess whether it's a multi-year edge case or a same-year
    duplicate. Mirrors the year-aware message the Wave 4 #15b
    eligibility check now emits."""
    from app.services import admission_service

    src = inspect.getsource(admission_service.create_profile)
    lock_idx = src.index("acquire_redis_lock")
    eligibility_idx = src.index("check_lead_level_admission_eligibility(")
    race_block = src[lock_idx:eligibility_idx]

    # Both ``academic year`` and a year placeholder must appear in the
    # raise statement after ``get_profile_by_lead_year``.
    raise_idx = race_block.index("ConflictError(")
    raise_block = race_block[raise_idx : raise_idx + 400]
    assert "academic year" in raise_block.lower()

    # Khoá BẤT BIẾN "năm được nội suy", KHÔNG khoá TÊN BIẾN. Bản cũ tìm
    # ``{race_check_year}``/``{year}``; F30 đổi tên sang ``academic_year`` nên
    # ca đỏ trong khi thông điệp vẫn nêu đúng năm. Bắt mọi placeholder f-string
    # có tên kết thúc bằng "year" — đổi tên biến lần nữa vẫn xanh, còn bỏ hẳn
    # nội suy (quay về chuỗi tĩnh) thì đỏ.
    placeholder = re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", raise_block)
    assert any(t.endswith("year") for t in placeholder), (
        "ConflictError message must f-string the resolved year so prod "
        f"logs disambiguate same-year vs cross-year duplicate cases; "
        f"placeholder thấy được: {placeholder}"
    )


# ---------------------------------------------------------------------------
# 3. Repository contract — both methods present (deprecated + new)
# ---------------------------------------------------------------------------


def test_repository_exposes_both_methods_during_migration_window() -> None:
    """The deprecated ``get_profile_by_lead_id`` stays callable for any
    pre-Wave-4 caller still in flight; the new
    ``get_profile_by_lead_year`` is the create-profile race-safe path."""
    from app.repositories.admission_repository import AdmissionRepository

    assert callable(getattr(AdmissionRepository, "get_profile_by_lead_id", None))
    assert callable(getattr(AdmissionRepository, "get_profile_by_lead_year", None))
