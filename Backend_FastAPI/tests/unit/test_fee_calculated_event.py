"""Unit guard: FeeCalculationService.calculate_fee emits FEE_CALCULATED (PR #8).

The event is broadcast-only (no DB rule) — its job is to trigger
FE cache invalidation on admission detail + finance dashboards.
Two things we lock here:

1. The post_commit callback actually dispatches FEE_CALCULATED — not
   an empty stub. Without this, the FE would never know a fee was
   calculated on another session.
2. The payload carries ``lead_stage_changed`` as a bool, derived from
   the pipeline_stage_id captured around the ``sync_lead_tuition_
   calculated`` call. FE reads this flag to decide whether to
   invalidate lead/pipeline caches in addition to finance caches.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.events import SystemEvents
from app.models.finance import FeeTypeEnum


def _make_profile_fee_eligible(profile) -> None:
    """Cho mock hồ sơ đủ thuộc tính THẬT mà ``calculate_fee`` đọc.

    ``MagicMock`` trả một mock truthy cho mọi thuộc tính chưa gán, nên gate nào
    cũng hiểu sai: ``major_change_requested`` thành "đang đổi ngành",
    ``priority_object_codes`` thành một mảng không lặp được. Gán tường minh.
    """
    profile.status = "submitted"
    profile.uses_choice_engine = False
    profile.major_change_requested = False
    profile.priority_object_codes = []
    profile.priority_object_evidence = {}


def _patch_profile_lock(profile):
    """``calculate_fee`` lấy hồ sơ qua ``AdmissionRepository.get_by_id_for_update``
    (khoá hàng), KHÔNG qua ``svc._get_profile``. Mock nhầm chỗ là lý do hai test
    này từng vỡ với ``'coroutine' object has no attribute '__dict__'``."""
    return patch(
        "app.repositories.admission_repository.AdmissionRepository"
        ".get_by_id_for_update",
        new=AsyncMock(return_value=profile),
    )


@pytest.mark.asyncio
async def test_calculate_fee_post_commit_emits_fee_calculated_with_lead_stage_changed():
    """After router commit, the returned callback must fire FEE_CALCULATED
    with ``lead_stage_changed=True`` when sync_lead_tuition_calculated
    advanced the lead pipeline stage.
    """
    from app.services.fee_calculation_service import FeeCalculationService

    # --- Fake profile + lead with pipeline_stage_id that "moves" during sync.
    lead = MagicMock()
    lead.id = 7
    lead.pipeline_stage_id = 10  # "old" stage before sync
    lead.unit_id = 1
    lead.assigned_officer_id = 42

    profile = MagicMock()
    profile.id = 99
    profile.__dict__["lead"] = lead  # rooms_for_admission / getattr path
    _make_profile_fee_eligible(profile)

    # --- Wire a service instance with mocked collaborators.
    # db.refresh is the step that populates fee.id in reality; fake it by
    # assigning id + status on the Fee instance the service constructs.
    async def _refresh(obj):
        obj.id = 55
        obj.status = "invoiced"

    svc = FeeCalculationService(db=AsyncMock())
    svc.db.refresh = _refresh  # type: ignore[method-assign]
    svc.fee_repo = MagicMock()
    svc.fee_repo.check_duplicate = AsyncMock(return_value=None)
    # ``calculate_fee`` KHÔNG dùng ``_get_profile`` (nó khoá hàng qua
    # ``AdmissionRepository.get_by_id_for_update``) — mock nhầm chỗ khiến hai
    # test này hỏng âm thầm: profile thật là mock của AsyncMock db, và
    # ``profile.__dict__`` vỡ ngay ở bước kiểm IDOR.
    svc._get_profile = AsyncMock(return_value=profile)
    svc._lookup_semester_tuition_amount = AsyncMock(return_value=Decimal("5000000"))
    # Định giá đi thẳng ``fee_pricing`` (hàm thuần); chỉ cần chặn tầng I/O nạp
    # chính sách là fee ra không giảm — không mock engine tính.
    svc._load_discount_policies = AsyncMock(return_value=[])
    svc._get_installment_plan = AsyncMock(return_value=None)

    # --- Patch the lead-pipeline sync to simulate a stage transition
    # (stage 10 → stage 20) while leaving the profile/lead in place.
    async def _fake_sync(db, profile, fee_amount, changed_by_user_id, reason):
        lead.pipeline_stage_id = 20

    with _patch_profile_lock(profile), patch(
        "app.services.fee_calculation_service.assert_major_change_cycle_closed",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.services.lead_admission_sync.sync_lead_tuition_calculated",
        new=_fake_sync,
    ), patch(
        "app.services.notification_dispatcher.rooms_for_admission",
        return_value=["role_admin", "unit_1", "user_room_42"],
    ), patch(
        "app.services.notification_dispatcher.safe_dispatch",
        new_callable=AsyncMock,
    ) as mock_dispatch:
        _, post_commit = await svc.calculate_fee(
            admission_profile_id=99,
            fee_type=FeeTypeEnum.tuition,
            base_amount=Decimal("0"),
            academic_year="2026",
            user_id=42,
            unit_id=1,
            semester_no=1,
        )

        # Sanity: service returned a callable, not a no-op pass.
        assert callable(post_commit)
        await post_commit()

        # Exactly one FEE_CALCULATED dispatch with the computed lead_stage_changed.
        assert mock_dispatch.await_count == 1, mock_dispatch.await_args_list
        kwargs = mock_dispatch.await_args.kwargs
        assert kwargs["event"] == SystemEvents.FEE_CALCULATED
        assert kwargs["rooms"] == ["role_admin", "unit_1", "user_room_42"]
        payload = kwargs["payload"]
        assert payload["admission_profile_id"] == 99
        assert payload["lead_id"] == 7
        assert payload["fee_id"] == 55
        assert payload["fee_status"] == "invoiced"
        assert payload["lead_stage_changed"] is True
        assert payload["actor_id"] == 42


@pytest.mark.asyncio
async def test_calculate_fee_reports_lead_stage_unchanged_when_sync_noop():
    """Non-tuition fees skip the pipeline sync entirely; lead_stage_changed
    must be False regardless so the FE doesn't invalidate lead caches
    spuriously.
    """
    from app.services.fee_calculation_service import FeeCalculationService

    lead = MagicMock()
    lead.id = 7
    lead.pipeline_stage_id = 10
    lead.unit_id = 1
    lead.assigned_officer_id = 42

    profile = MagicMock()
    profile.id = 99
    profile.__dict__["lead"] = lead
    _make_profile_fee_eligible(profile)

    fee = MagicMock()
    fee.id = 55
    fee.status = "invoiced"

    svc = FeeCalculationService(db=AsyncMock())
    svc.fee_repo = MagicMock()
    svc.fee_repo.check_duplicate = AsyncMock(return_value=None)
    svc.fee_repo.create = AsyncMock(return_value=fee)
    svc._get_profile = AsyncMock(return_value=profile)
    # Định giá đi thẳng ``fee_pricing`` (hàm thuần); chỉ cần chặn tầng I/O nạp
    # chính sách là fee ra không giảm — không mock engine tính.
    svc._load_discount_policies = AsyncMock(return_value=[])
    svc._get_installment_plan = AsyncMock(return_value=None)

    with _patch_profile_lock(profile), patch(
        "app.services.fee_calculation_service.assert_major_change_cycle_closed",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.services.notification_dispatcher.rooms_for_admission",
        return_value=["role_admin", "unit_1", "user_room_42"],
    ), patch(
        "app.services.notification_dispatcher.safe_dispatch",
        new_callable=AsyncMock,
    ) as mock_dispatch:
        _, post_commit = await svc.calculate_fee(
            admission_profile_id=99,
            fee_type=FeeTypeEnum.application,
            base_amount=Decimal("500000"),
            academic_year="2026",
            user_id=42,
            unit_id=1,
        )
        await post_commit()

        kwargs = mock_dispatch.await_args.kwargs
        assert kwargs["payload"]["lead_stage_changed"] is False
