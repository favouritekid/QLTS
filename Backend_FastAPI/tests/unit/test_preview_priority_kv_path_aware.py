"""Unit tests for preview-priority-kv route path-aware behavior.

Reviewer 2026-05-21: Trước fix-up, ``preview_priority_kv()`` gọi
``resolve_kv_for_profile(preview_profile, db)`` KHÔNG truyền target_level/
admission_type → engine fall vào legacy matrix (target_level=None branch)
→ basis hiển thị FE sai cho một số combo (vd CĐ chính quy + completed_thpt
→ THUONG_TRU legacy thay vì LICH_SU_THPT Phase E.4).

Fix: route gọi ``derive_profile_target_context(profile, db)`` rồi pass
target context vào engine. Test pin wiring đúng bằng cách mock 2 hàm và
verify chúng được gọi với arguments đúng.

KHÔNG dùng AsyncClient ở đây — route function gọi nhiều DB-bound helpers
(bonus rate lookup) phức tạp; mock-direct test giữ slice nhỏ.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


pytestmark = pytest.mark.unit


# ===========================================================================
# Test wiring: preview route → derive_profile_target_context → resolve_kv
# ===========================================================================


@pytest.mark.asyncio
async def test_preview_passes_target_context_to_engine_resolve() -> None:
    """preview-priority-kv route phải pass target_level + admission_type
    (từ derive_profile_target_context) vào resolve_kv_for_profile call.
    """
    # Lazy import để patch applied trước khi import route
    from app.routers import admissions_v2
    from app.schemas.admission import PreviewPriorityKvRequest

    # Stub profile
    profile = SimpleNamespace(
        id=99,
        cultural_education_level="graduated_thpt",
        vocational_qualification="none",
        area_resolution_basis=None,
        permanent_commune_code=None,
        academic_history=[],
        priority_object_codes=[],
        admission_path=None,
        academic_year=2026,
    )

    captured = {}

    async def fake_derive_context(profile_arg, db_arg):
        captured["derive_called_with_profile_id"] = profile_arg.id
        return {
            "target_level": "cao_dang",
            "admission_type": "chinh_quy",
            "eligibility": {"passed": True, "reason": None},
            "path_bonus_rule": None,
            "source": "multi_nv_first_choice",
        }

    async def fake_resolve(profile_arg, db_arg, target_level=None, admission_type=None):
        captured["resolve_target_level"] = target_level
        captured["resolve_admission_type"] = admission_type
        return ("KV1", {
            "kv_resolved": "KV1",
            "rule_applied": "longest_duration",
            "pathway": "lich_su_thpt",
            "basis": "LICH_SU_THPT",
            "basis_reason": "cd_chinh_quy_post_thpt_uses_school_history",
            "breakdown": {},
        })

    # Mock db.execute cho bonus rate lookup (PriorityAreaConfig + PriorityObjectConfig)
    bonus_result = MagicMock()
    bonus_result.scalar_one_or_none = MagicMock(return_value=None)  # no rate row
    object_result = MagicMock()
    object_result.all = MagicMock(return_value=[])

    async def fake_execute(stmt, *args, **kwargs):
        stmt_str = str(stmt)
        if "priority_object_config" in stmt_str:
            return object_result
        return bonus_result

    db = MagicMock()
    db.execute = AsyncMock(side_effect=fake_execute)

    with patch.object(
        admissions_v2,
        "log",
        MagicMock(),
    ):
        # Replace priority_service exports in the namespace the route imports.
        import app.services.priority_service as priority_module

        with patch.object(
            priority_module, "derive_profile_target_context", side_effect=fake_derive_context,
        ), patch.object(
            priority_module, "resolve_kv_for_profile", side_effect=fake_resolve,
        ):
            response = await admissions_v2.preview_priority_kv(
                profile_id=99,
                payload=PreviewPriorityKvRequest(),
                db=db,
                profile=profile,
                current_user=SimpleNamespace(id=1, role="officer"),
            )

    # Wiring assertions:
    assert captured["derive_called_with_profile_id"] == 99
    # Phase E.4 fix Finding: target context phải reach engine
    assert captured["resolve_target_level"] == "cao_dang"
    assert captured["resolve_admission_type"] == "chinh_quy"
    # Response carries kv + basis từ engine
    assert response.kv_resolved == "KV1"


@pytest.mark.asyncio
async def test_preview_missing_target_context_still_calls_engine_with_none() -> None:
    """Khi derive_profile_target_context không derive được (vd path chain
    missing), engine vẫn được gọi với target_level=None — legacy matrix
    branch fallback. Engine KHÔNG crash."""
    from app.routers import admissions_v2
    from app.schemas.admission import PreviewPriorityKvRequest

    profile = SimpleNamespace(
        id=100,
        cultural_education_level="graduated_thcs",
        vocational_qualification="none",
        area_resolution_basis=None,
        permanent_commune_code="66_22255",
        academic_history=[],
        priority_object_codes=[],
        admission_path=None,
        academic_year=2026,
    )

    captured = {}

    async def fake_derive_context(profile_arg, db_arg):
        # Simulate path chain missing → all fields None
        return {
            "target_level": None,
            "admission_type": None,
            "eligibility": None,
            "path_bonus_rule": None,
            "source": "unknown",
        }

    async def fake_resolve(profile_arg, db_arg, target_level=None, admission_type=None):
        captured["resolve_target_level"] = target_level
        captured["resolve_admission_type"] = admission_type
        return ("KV2-NT", {
            "kv_resolved": "KV2-NT",
            "rule_applied": "commune_lookup",
            "pathway": "thuong_tru",
            "basis": "THUONG_TRU",
            "basis_reason": "legacy_thcs_pathway_uses_commune",
            "breakdown": {"commune_code_used": "66_22255"},
        })

    bonus_result = MagicMock()
    bonus_result.scalar_one_or_none = MagicMock(return_value=None)
    object_result = MagicMock()
    object_result.all = MagicMock(return_value=[])

    async def fake_execute(stmt, *args, **kwargs):
        stmt_str = str(stmt)
        if "priority_object_config" in stmt_str:
            return object_result
        return bonus_result

    db = MagicMock()
    db.execute = AsyncMock(side_effect=fake_execute)

    import app.services.priority_service as priority_module

    with patch.object(
        admissions_v2, "log", MagicMock(),
    ), patch.object(
        priority_module, "derive_profile_target_context", side_effect=fake_derive_context,
    ), patch.object(
        priority_module, "resolve_kv_for_profile", side_effect=fake_resolve,
    ):
        response = await admissions_v2.preview_priority_kv(
            profile_id=100,
            payload=PreviewPriorityKvRequest(),
            db=db,
            profile=profile,
            current_user=SimpleNamespace(id=1, role="officer"),
        )

    # Wiring assertions: engine nhận None (legacy matrix branch)
    assert captured["resolve_target_level"] is None
    assert captured["resolve_admission_type"] is None
    assert response.kv_resolved == "KV2-NT"
