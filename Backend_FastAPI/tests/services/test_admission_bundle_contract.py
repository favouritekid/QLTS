"""Service-level contract tests for Arch-3 notification bundle refactor.

Replaces the 3 router-layer tests deleted from
``tests/unit/test_zalo_phase1_review_findings.py`` when paired dispatch
moved from router into service. Targets:

1. ``approve_profile`` / ``reject_profile`` / ``request_revision`` /
   ``resubmit_profile`` propagate the locked ``pre_status`` (i.e. the
   status snapshotted inside the service under ``with_for_update``) into
   both bundle payloads and the commission callback — not a hardcoded
   or post-mutation value.
2. ``finalize_profile`` uses ``pre_status="confirmed"`` (via
   ``_perform_enrollment_core``) end-to-end.
3. ``bulk_approve`` / ``bulk_reject`` preserve per-profile ``old_status``
   in the per-profile bundles — proving the service no longer has the
   hardcoded ``"submitted"`` bug that the deleted router test guarded.
4. P1 regression: a ``_bulk_create_notifications`` failure inside
   ``dispatch_bundle`` rolls back ONLY the notification savepoint; the
   outer admission mutation survives ``db.commit()``.

All tests use real DB (following the ``test_admission_withdraw.py``
pattern) + patching ``dispatch_bundle`` and
``safe_check_commission_on_status_change`` at the
``app.services.admission_service`` module-level bind site so we capture
the exact args the service passes at the contract boundary.
"""
from __future__ import annotations

import random
import uuid
from typing import List
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import models
from app.database import AsyncSessionLocal
from app.services.notification_bundle import BundleDispatchResult


pytestmark = pytest.mark.asyncio


# ==============================================================================
# HELPERS
# ==============================================================================


async def _create_lead(unit_id: int, officer_id: int) -> int:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            unique = uuid.uuid4().hex[:12]
            lead = models.Lead(
                full_name=f"Bundle Contract Lead {unique}",
                phone=f"090{random.randint(1000000, 9999999)}",
                email=f"bundle_{unique}@test.com",
                source="website",
                unit_id=unit_id,
                assigned_officer_id=officer_id,
                consultation_status_id="sts06",
            )
            session.add(lead)
            await session.flush()
            return lead.id


async def _create_profile(
    lead_id: int,
    status: str = "submitted",
    **extra,
) -> models.AdmissionProfile:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            citizen = f"20{random.randint(1000000000, 9999999999)}"
            profile = models.AdmissionProfile(
                lead_id=lead_id,
                status=status,
                citizen_id=citizen,
                academic_year=2026,
                version=1,
                applied_rules={"min_gpa": 0, "mandatory_docs": []},
                **extra,
            )
            session.add(profile)
            await session.flush()
            pid = profile.id

        result = await session.execute(
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == pid)
            .options(selectinload(models.AdmissionProfile.lead))
        )
        return result.scalar_one()


def _build_actor(user_info: dict, role: str = "admin") -> models.User:
    """Build a User ORM instance (not persisted by us — already in DB via
    ``admin_user_in_db`` / ``manager_user_in_db`` fixtures). We attach the
    same id so IDOR + actor_id serialization round-trip correctly."""
    return models.User(
        id=user_info["id"],
        username=user_info["username"],
        email=f"{user_info['username']}@test.com",
        password_hash="x",
        role=role,
        status="active",
        full_name=user_info.get("full_name") or user_info["username"],
    )


def _ok_bundle(label: str) -> BundleDispatchResult:
    """Stand-in ``BundleDispatchResult`` for patched ``dispatch_bundle``.
    Callback is non-None so composition through
    ``compose_post_commit_callbacks`` retains a runnable chain."""
    return BundleDispatchResult(
        bundle_label=label,
        intent_events=("application_status_changed", "lead_status_changed"),
        notification_ids=[],
        persist_status="ok",
        callback=AsyncMock(),
    )


# ==============================================================================
# SINGLE-PROFILE CONTRACT TESTS
# ==============================================================================


class TestSingleProfileBundleContract:
    """Per-flow: verify service passes correct pre_status to bundle+commission."""

    async def test_approve_preserves_locked_pre_status(
        self,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """approve_profile: pre_status captured under with_for_update flows
        into both bundle intents + commission tuple. Profile mutated to
        'approved' before bundle is built, but the intents must still
        carry the LOCKED pre-mutation status."""
        from app.services import admission_service

        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await _create_lead(unit_id, admin_user_in_db["id"])
        profile = await _create_profile(lead_id, status="resubmitted")
        actor = _build_actor(admin_user_in_db)

        with patch.object(
            admission_service, "dispatch_bundle",
            new=AsyncMock(return_value=_ok_bundle("admission_approve")),
        ) as m_bundle, patch.object(
            admission_service, "safe_check_commission_on_status_change",
            new=AsyncMock(),
        ) as m_commission:
            async with AsyncSessionLocal() as session:
                result, callback = await admission_service.approve_profile(
                    db=session,
                    profile_id=profile.id,
                    approver=actor,
                    data={"version": 1},
                )
                await session.commit()
                if callback:
                    await callback()

        # Bundle was called exactly once with the resubmitted pre_status
        assert m_bundle.await_count == 1
        kwargs = m_bundle.await_args.kwargs
        assert kwargs["bundle_label"] == "admission_approve"
        intents = kwargs["intents"]
        assert len(intents) == 2
        assert intents[0].event.value == "application_status_changed"
        assert intents[0].payload["old_status"] == "resubmitted"
        assert intents[0].payload["new_status"] == "approved"
        assert intents[1].event.value == "lead_status_changed"
        assert intents[1].payload["old_status"] == "resubmitted"
        assert intents[1].payload["new_status"] == "sts09"

        # Commission closure invoked with the same pre_status tuple
        m_commission.assert_awaited_once()
        c_args = m_commission.await_args.args
        assert c_args[1] == lead_id
        assert c_args[2] == "resubmitted"  # old_status argument
        assert c_args[3] == "sts09"

    async def test_reject_preserves_locked_pre_status(
        self,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """reject_profile from a resubmitted state: old_status must be
        'resubmitted' in payload + commission args, not 'submitted'."""
        from app.services import admission_service

        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await _create_lead(unit_id, admin_user_in_db["id"])
        profile = await _create_profile(lead_id, status="resubmitted")
        actor = _build_actor(admin_user_in_db)

        with patch.object(
            admission_service, "dispatch_bundle",
            new=AsyncMock(return_value=_ok_bundle("admission_reject")),
        ) as m_bundle, patch.object(
            admission_service, "safe_check_commission_on_status_change",
            new=AsyncMock(),
        ) as m_commission:
            async with AsyncSessionLocal() as session:
                result, callback = await admission_service.reject_profile(
                    db=session,
                    profile_id=profile.id,
                    rejector=actor,
                    data={"reason": "Hồ sơ không đạt yêu cầu sau resubmit", "version": 1},
                )
                await session.commit()
                if callback:
                    await callback()

        kwargs = m_bundle.await_args.kwargs
        assert kwargs["bundle_label"] == "admission_reject"
        intents = kwargs["intents"]
        assert intents[0].payload["old_status"] == "resubmitted"
        assert intents[0].payload["new_status"] == "rejected"
        assert intents[1].payload["new_status"] == "sts16"
        m_commission.assert_awaited_once()
        assert m_commission.await_args.args[2] == "resubmitted"
        assert m_commission.await_args.args[3] == "sts16"

    async def test_request_revision_preserves_pre_status(
        self,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """request_revision from submitted: pre_status='submitted'."""
        from app.services import admission_service

        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await _create_lead(unit_id, admin_user_in_db["id"])
        profile = await _create_profile(lead_id, status="submitted")
        actor = _build_actor(admin_user_in_db)

        with patch.object(
            admission_service, "dispatch_bundle",
            new=AsyncMock(return_value=_ok_bundle("admission_request_revision")),
        ) as m_bundle, patch.object(
            admission_service, "safe_check_commission_on_status_change",
            new=AsyncMock(),
        ) as m_commission:
            async with AsyncSessionLocal() as session:
                _, callback = await admission_service.request_revision(
                    db=session,
                    profile_id=profile.id,
                    reviewer=actor,
                    data={"reason": "Cần bổ sung học bạ lớp 12", "version": 1},
                )
                await session.commit()
                if callback:
                    await callback()

        kwargs = m_bundle.await_args.kwargs
        assert kwargs["bundle_label"] == "admission_request_revision"
        intents = kwargs["intents"]
        assert intents[0].payload["old_status"] == "submitted"
        assert intents[0].payload["new_status"] == "revision_requested"
        assert intents[1].payload["new_status"] == "sts17"
        assert m_commission.await_args.args[2] == "submitted"
        assert m_commission.await_args.args[3] == "sts17"

    async def test_resubmit_uses_revision_requested_pre_status(
        self,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """resubmit_profile from revision_requested: the deleted router
        test covered this exact path (officer resubmit after manager asked
        for revision). pre_status must be 'revision_requested', not the
        hardcoded 'rejected' the old router fallback used."""
        from app.services import admission_service

        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await _create_lead(unit_id, admin_user_in_db["id"])
        profile = await _create_profile(
            lead_id, status="revision_requested",
        )
        # Use admin role so IDOR short-circuits. The admin_user_in_db
        # fixture doesn't populate unit_id, so role="officer" would fail
        # the unit-scope gate in _check_idor_access. The role gate is
        # enforced by the router, not the service.
        actor = _build_actor(admin_user_in_db, role="admin")

        with patch.object(
            admission_service, "dispatch_bundle",
            new=AsyncMock(return_value=_ok_bundle("admission_resubmit")),
        ) as m_bundle, patch.object(
            admission_service, "safe_check_commission_on_status_change",
            new=AsyncMock(),
        ) as m_commission:
            async with AsyncSessionLocal() as session:
                _, callback = await admission_service.resubmit_profile(
                    db=session,
                    profile_id=profile.id,
                    officer=actor,
                    data={"notes": "Đã bổ sung học bạ.", "version": 1},
                )
                await session.commit()
                if callback:
                    await callback()

        kwargs = m_bundle.await_args.kwargs
        assert kwargs["bundle_label"] == "admission_resubmit"
        intents = kwargs["intents"]
        assert intents[0].payload["old_status"] == "revision_requested"
        assert intents[0].payload["new_status"] == "resubmitted"
        assert intents[1].payload["old_status"] == "revision_requested"
        assert intents[1].payload["new_status"] == "sts07"
        assert m_commission.await_args.args[2] == "revision_requested"
        assert m_commission.await_args.args[3] == "sts07"

    async def test_finalize_uses_confirmed_pre_status(
        self,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """finalize_profile from confirmed: pre_status='confirmed' flows
        into both bundle intents and the commission callback.

        finalize delegates to ``_perform_enrollment_core`` for the
        lock/mutate/student-creation body. We stub that seam so this test
        stays focused on the bundle/commission contract instead of
        re-exercising the full enrollment path (which has its own
        dedicated tests)."""
        from app.services import admission_service

        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await _create_lead(unit_id, admin_user_in_db["id"])
        profile = await _create_profile(lead_id, status="confirmed")
        actor = _build_actor(admin_user_in_db)

        # Stub out the enrollment body: return a synthetic locked_profile
        # (with lead_id intact so the bundle branch engages), plus the
        # pre_status "confirmed" that the router used to capture.
        fake_result = {
            "student_id": 12345,
            "student_code": "SV20260001",
            "enrollment_date": None,
        }

        async def _fake_core(db, profile_id, user):
            # Build a lightweight stand-in; only lead_id is read downstream.
            stub = models.AdmissionProfile(
                id=profile_id,
                lead_id=lead_id,
                status="enrolled",
                citizen_id=profile.citizen_id,
                academic_year=profile.academic_year,
                version=profile.version + 1,
                applied_rules=profile.applied_rules,
            )
            return stub, fake_result, False, "confirmed"

        with patch.object(
            admission_service, "_perform_enrollment_core",
            new=AsyncMock(side_effect=_fake_core),
        ), patch.object(
            admission_service, "dispatch_bundle",
            new=AsyncMock(return_value=_ok_bundle("admission_finalize")),
        ) as m_bundle, patch.object(
            admission_service, "safe_check_commission_on_status_change",
            new=AsyncMock(),
        ) as m_commission:
            async with AsyncSessionLocal() as session:
                # Re-fetch profile from the new session so SQLAlchemy has
                # a live identity-mapped instance to pass in.
                live = (await session.execute(
                    select(models.AdmissionProfile)
                    .where(models.AdmissionProfile.id == profile.id)
                )).scalar_one()
                _, callback = await admission_service.finalize_profile(
                    db=session,
                    profile=live,
                    admin=actor,
                    data={"version": 1},
                )
                await session.commit()
                if callback:
                    await callback()

        kwargs = m_bundle.await_args.kwargs
        assert kwargs["bundle_label"] == "admission_finalize"
        intents = kwargs["intents"]
        assert intents[0].payload["old_status"] == "confirmed"
        assert intents[0].payload["new_status"] == "enrolled"
        assert intents[1].payload["old_status"] == "confirmed"
        assert intents[1].payload["new_status"] == "sts11"
        m_commission.assert_awaited_once()
        assert m_commission.await_args.args[2] == "confirmed"
        assert m_commission.await_args.args[3] == "sts11"


# ==============================================================================
# BULK-FLOW CONTRACT TESTS
# ==============================================================================


class TestBulkBundleContract:
    """Bulk approve/reject: per-profile bundles must carry the locked
    per-profile ``old_status`` into payload + commission — not a shared
    hardcoded value. This is the contract the deleted
    ``test_bulk_approve_uses_pre_status_from_service`` guarded."""

    async def test_bulk_approve_preserves_per_profile_old_status(
        self,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        from app.services import admission_service

        unit_id = seed_lead_dependencies["unit_id"]
        actor = _build_actor(admin_user_in_db)

        # Two profiles at DIFFERENT states — if the service hardcoded
        # "submitted" (the old bug), both bundles would share that value.
        lead_a = await _create_lead(unit_id, admin_user_in_db["id"])
        profile_a = await _create_profile(lead_a, status="submitted")
        lead_b = await _create_lead(unit_id, admin_user_in_db["id"])
        profile_b = await _create_profile(lead_b, status="resubmitted")

        captured: List[dict] = []

        async def _capture_bundle(db, *, bundle_label, intents):
            # Snapshot the intent payload immediately so later dispatches
            # don't mutate what we've captured (NotificationIntent is
            # frozen, so a shallow copy is fine).
            captured.append({
                "label": bundle_label,
                "app_old": intents[0].payload["old_status"],
                "lead_old": intents[1].payload["old_status"],
            })
            return _ok_bundle(bundle_label)

        with patch.object(
            admission_service, "dispatch_bundle", new=AsyncMock(side_effect=_capture_bundle),
        ), patch.object(
            admission_service, "safe_check_commission_on_status_change",
            new=AsyncMock(),
        ) as m_commission:
            async with AsyncSessionLocal() as session:
                result, callback = await admission_service.bulk_approve(
                    db=session,
                    items=[
                        {"profile_id": profile_a.id, "version": 1},
                        {"profile_id": profile_b.id, "version": 1},
                    ],
                    approver=actor,
                    notes="bulk-approve",
                )
                await session.commit()
                if callback:
                    await callback()

        assert result["success_count"] == 2
        assert len(captured) == 2

        by_label = {c["app_old"]: c for c in captured}
        assert "submitted" in by_label and by_label["submitted"]["lead_old"] == "submitted"
        assert "resubmitted" in by_label and by_label["resubmitted"]["lead_old"] == "resubmitted"

        # Commission: one per profile, each with its own pre_status
        assert m_commission.await_count == 2
        old_statuses = {call.args[2] for call in m_commission.await_args_list}
        assert old_statuses == {"submitted", "resubmitted"}
        for call in m_commission.await_args_list:
            assert call.args[3] == "sts09"

    async def test_bulk_reject_preserves_per_profile_old_status(
        self,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        from app.services import admission_service

        unit_id = seed_lead_dependencies["unit_id"]
        actor = _build_actor(admin_user_in_db)

        lead_a = await _create_lead(unit_id, admin_user_in_db["id"])
        profile_a = await _create_profile(lead_a, status="submitted")
        lead_b = await _create_lead(unit_id, admin_user_in_db["id"])
        profile_b = await _create_profile(lead_b, status="resubmitted")

        captured: List[dict] = []

        async def _capture_bundle(db, *, bundle_label, intents):
            captured.append({
                "label": bundle_label,
                "app_old": intents[0].payload["old_status"],
                "lead_old": intents[1].payload["old_status"],
            })
            return _ok_bundle(bundle_label)

        with patch.object(
            admission_service, "dispatch_bundle", new=AsyncMock(side_effect=_capture_bundle),
        ), patch.object(
            admission_service, "safe_check_commission_on_status_change",
            new=AsyncMock(),
        ) as m_commission:
            async with AsyncSessionLocal() as session:
                result, callback = await admission_service.bulk_reject(
                    db=session,
                    items=[
                        {"profile_id": profile_a.id, "version": 1},
                        {"profile_id": profile_b.id, "version": 1},
                    ],
                    rejector=actor,
                    reason="Bulk rejection for bundle-contract test",
                )
                await session.commit()
                if callback:
                    await callback()

        assert result["success_count"] == 2
        old_statuses = {c["app_old"] for c in captured}
        assert old_statuses == {"submitted", "resubmitted"}
        for c in captured:
            assert c["app_old"] == c["lead_old"]

        assert m_commission.await_count == 2
        for call in m_commission.await_args_list:
            assert call.args[3] == "sts16"


# ==============================================================================
# P1 REGRESSION: BUNDLE FAILURE MUST NOT ROLL BACK BUSINESS MUTATION
# ==============================================================================


class TestBundleFailureBusinessSurvives:
    """The Arch-3 bundle wraps dispatch in ``db.begin_nested()`` and runs
    ``dispatch()`` with ``strict=True`` so an inner persistence failure
    only rolls back the SAVEPOINT. Without this, dispatch's
    ``_bulk_create_notifications`` hits ``db.rollback()`` on error and
    wipes the outer admission mutation as collateral damage."""

    async def test_bulk_insert_failure_rolls_back_savepoint_only(
        self,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Patch ``_bulk_create_notifications`` to raise. The service
        should still succeed, the outer commit should persist the
        approved status, and the bundle result should carry
        ``persist_status="rolled_back"``."""
        from app.services import admission_service, notification_dispatcher

        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await _create_lead(unit_id, admin_user_in_db["id"])
        profile = await _create_profile(lead_id, status="submitted")
        actor = _build_actor(admin_user_in_db)

        raise_bulk = AsyncMock(side_effect=RuntimeError("simulated insert failure"))

        # Also patch commission so the test doesn't depend on its real
        # wiring; we only care about business-mutation survival here.
        with patch.object(
            notification_dispatcher, "_bulk_create_notifications", new=raise_bulk,
        ), patch.object(
            admission_service, "safe_check_commission_on_status_change",
            new=AsyncMock(),
        ):
            async with AsyncSessionLocal() as session:
                result, callback = await admission_service.approve_profile(
                    db=session,
                    profile_id=profile.id,
                    approver=actor,
                    data={"version": 1},
                )
                # If the savepoint leaked, this commit would fail or the
                # profile row would be reverted. Must succeed cleanly.
                await session.commit()
                if callback:
                    await callback()

        # Outer mutation survived: profile persisted as approved.
        async with AsyncSessionLocal() as verify_session:
            reloaded = (await verify_session.execute(
                select(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == profile.id)
            )).scalar_one()
            assert reloaded.status == "approved"
            assert reloaded.version == 2

    async def test_delivery_row_failure_rolls_back_savepoint_only(
        self,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """P1 follow-up: ``_create_deliveries_for_action`` failure must
        also propagate under strict=True. Without this, dispatch would
        persist Notification rows inside the savepoint but silently drop
        their paired NotificationDelivery rows, leaving the bundle in a
        "ok" state with half-persisted data.

        Same survival expectation as the Notification-insert failure
        test: the outer admission mutation must commit cleanly."""
        from app.services import admission_service, notification_dispatcher

        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await _create_lead(unit_id, admin_user_in_db["id"])
        profile = await _create_profile(lead_id, status="submitted")
        actor = _build_actor(admin_user_in_db)

        raise_delivery = AsyncMock(
            side_effect=RuntimeError("simulated delivery insert failure")
        )

        with patch.object(
            notification_dispatcher, "_create_deliveries_for_action",
            new=raise_delivery,
        ), patch.object(
            admission_service, "safe_check_commission_on_status_change",
            new=AsyncMock(),
        ):
            async with AsyncSessionLocal() as session:
                _, callback = await admission_service.approve_profile(
                    db=session,
                    profile_id=profile.id,
                    approver=actor,
                    data={"version": 1},
                )
                await session.commit()
                if callback:
                    await callback()

        async with AsyncSessionLocal() as verify_session:
            reloaded = (await verify_session.execute(
                select(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == profile.id)
            )).scalar_one()
            assert reloaded.status == "approved"
            assert reloaded.version == 2

    async def test_bulk_create_notifications_strict_reraises(self):
        """Unit-level guard: the strict flag on
        ``_bulk_create_notifications`` must propagate exceptions instead
        of calling ``db.rollback()``."""
        from app.services import notification_dispatcher

        db = AsyncMock()
        db.rollback = AsyncMock()

        fake_repo = AsyncMock()
        fake_repo.bulk_create = AsyncMock(side_effect=RuntimeError("boom"))

        with patch.object(
            notification_dispatcher, "NotificationRepository",
            return_value=fake_repo,
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await notification_dispatcher._bulk_create_notifications(
                    db=db,
                    user_ids=[1, 2],
                    title="t", message="m", notification_type="info",
                    link=None, data={},
                    strict=True,
                )

        # Critical: strict path must NOT call db.rollback() — that's the
        # exact behavior that was collateral-damaging the outer txn.
        db.rollback.assert_not_awaited()

    async def test_bulk_create_notifications_non_strict_khong_duoc_rollback(self):
        """Non-strict cũng KHÔNG được `db.rollback()` — hợp đồng đổi 2026-09-02.

        Bản trước của ca này khoá hành vi cũ: non-strict *nuốt* lỗi, trả `[]`,
        và `db.rollback.assert_awaited()`. Chính lời gọi rollback ấy là khuyết
        tật — `Session.rollback()` cuộn về GỐC chứ không về savepoint, nên nó
        xoá luôn dữ liệu nghiệp vụ CHƯA commit của người gọi. Đã đo bằng SQL
        echo trên đường `lead_service.create_lead`: lead biến mất trong khi
        `lead_service` vẫn ghi log "business data preserved".

        Sáu chỗ gọi `dispatch()` bọc `begin_nested()` mà không truyền
        `strict=True` đều tin rằng savepoint bảo vệ họ; nó không.

        Hợp đồng MỚI, hai vế và cả hai đều được khẳng định ở đây:

          1. KHÔNG gọi `db.rollback()` — tầng này không sở hữu giao dịch;
          2. NÉM RA để `dispatch` huỷ cả sự kiện, thay vì đi tiếp với danh sách
             ID thiếu/lệch rồi `zip()` nhầm người nhận.

        Sự sống sót của phiên nay do savepoint riêng trong
        `NotificationRepository.bulk_create` bảo đảm, không do rollback.
        Hành vi đầu-cuối được khoá bằng dữ liệu thật ở
        `tests/services/test_dispatch_stale_rule_cache.py`.
        """
        from app.services import notification_dispatcher

        db = AsyncMock()
        db.rollback = AsyncMock()

        fake_repo = AsyncMock()
        fake_repo.bulk_create = AsyncMock(side_effect=RuntimeError("boom"))

        with patch.object(
            notification_dispatcher, "NotificationRepository",
            return_value=fake_repo,
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await notification_dispatcher._bulk_create_notifications(
                    db=db,
                    user_ids=[1, 2],
                    title="t", message="m", notification_type="info",
                    link=None, data={},
                    strict=False,
                )

        db.rollback.assert_not_awaited()
