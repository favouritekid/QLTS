# app/services/fee_calculation_service.py
"""
Fee Calculation Service - Business logic for fee calculation and lifecycle.

Architecture Compliance:
- Service Layer: Pure business logic, no HTTP dependencies
- Security: IDOR checks via repository (unit_id filtering)
- Transactions: Services use db.add()/db.flush(), Router commits
- Error Handling: Raise custom exceptions (ResourceNotFoundError, etc.)

Fee Lifecycle:
    pending → calculated → invoiced → partial → paid
                                   ↘ waived
                                   ↘ cancelled

Business Rules:
- Cannot recalculate if paid_amount > 0 (M10)
- Waive amount cannot exceed remaining balance (H5)
- Discount stacking: additive (capped at 100%)
- Version column for optimistic locking
"""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Tuple, Callable, Any
import structlog

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import models
from app.models.finance import (
    Fee, FeeAppliedDiscount, Invoice, InstallmentPlan,
    FeeTypeEnum, FeeStatusEnum,
)
from app.models.tuition_discount_policy import TuitionDiscountPolicy
from app.repositories.fee_repository import FeeRepository, InvoiceRepository
from app.utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    ConflictError,
    BusinessRuleViolation,
)
from app.config import settings

log = structlog.get_logger(__name__)


def is_hk1_cleared(
    fee_type: str,
    semester_no: Optional[int],
    status: str,
    paid_amount: Decimal,
) -> bool:
    """Check if a fee is in HK1 cleared state.

    Cleared = tuition + semester_no=1 + one of:
      - status in (paid, waived)
      - status == partial AND paid_amount > 0

    Used by PR 5 (ADR-002) to detect transition into cleared state
    at payment/waiver call sites. Callers snapshot pre-state, apply
    mutation, then check post-state: sync only on False -> True.
    """
    if fee_type != "tuition" or semester_no != 1:
        return False
    if status in ("paid", "waived"):
        return True
    if status == "partial" and paid_amount > 0:
        return True
    return False


def _academic_info_of_choice(choice: "models.AdmissionProfileChoice") -> Any:
    """OfferingAcademicInfo behind a choice's admission_path (or None).

    Reads ``admission_path`` → ``academic_info`` from ALREADY-LOADED state. The
    caller MUST eager-load that chain (``resolve_fee_academic_info`` does, via
    ``selectinload(admission_path).selectinload(academic_info)``). This helper
    does NOT guard against an async lazy-load — ``getattr(..., None)`` only
    swallows a genuinely-absent attribute (AttributeError), NOT the
    ``MissingGreenlet`` a lazy relationship access raises in async context. So
    only reuse it with an eager-loaded ``choice``.
    """
    path = getattr(choice, "admission_path", None)
    if path is None:
        return None
    return getattr(path, "academic_info", None)


async def resolve_fee_academic_info(
    db: AsyncSession,
    profile: "models.AdmissionProfile",
) -> Any:
    """Resolve the OfferingAcademicInfo a fee must be priced against.

    SINGLE SOURCE OF TRUTH shared by ``routers/fees.py`` (discount policy IDs +
    non-tuition base amount) and ``FeeCalculationService`` (tuition amount
    lookup), so the ngành used for the amount, the discount and the eligibility
    gate never drift apart.

    The choice engine stores the ngành PER CHOICE; ``evaluate_cascade`` writes
    only ``choice.decision`` at publish — it does NOT update
    ``profile.offering_admission_config_id`` / ``applied_rules``. Resolving from
    the profile snapshot would therefore price a multi-NV admit against NV gốc
    (NV1), not the NV actually admitted. So for choice-engine profiles we
    resolve from the choices themselves:

      * exactly one choice ``decision == "admitted"`` → that choice's ngành
        (post-publish — the correct admitted ngành; fixes the snapshot bug),
      * more than one admitted → fail-closed (corrupt data: the cascade admits
        at most one NV — never guess),
      * not yet published + exactly one choice → that single choice's ngành
        (prepay / giữ chỗ at ``submitted`` — mirrors ``is_fee_eligible``),
      * otherwise (≥2 pending, or zero choices) → BadRequest.

    Legacy single-path profiles resolve from the profile snapshot, in order:
    eager-loaded ``offering_admission_config.academic_info`` (read via
    ``__dict__`` to avoid a lazy-load) → an OAC lookup by
    ``offering_admission_config_id`` (when the relationship is not eager-loaded,
    e.g. under the fee-create lock that loads only lead + choices) →
    ``applied_rules['academic_info_id']``. Choice-engine profiles never fall
    through to this path.

    COUPLING (do not let drift): the "exactly 1 choice" branch is the PRICING
    counterpart of the submitted-prepay GATE in
    ``admission_status.is_fee_eligible`` (multi-NV ⇒ exactly 1 NV). Keep both in
    lockstep; the end-to-end anchor is
    ``tests/api/test_phase3_pr3d_b_choice_crud.py``.
    """
    if getattr(profile, "uses_choice_engine", False):
        stmt = (
            select(models.AdmissionProfileChoice)
            .where(
                models.AdmissionProfileChoice.admission_profile_id == profile.id
            )
            .options(
                selectinload(
                    models.AdmissionProfileChoice.admission_path
                ).selectinload(models.AdmissionPath.academic_info)
            )
            .order_by(models.AdmissionProfileChoice.display_order)
        )
        choices = list((await db.execute(stmt)).scalars().all())
        admitted = [c for c in choices if c.decision == "admitted"]
        if len(admitted) > 1:
            raise BadRequest(
                "Dữ liệu lỗi: hồ sơ có nhiều hơn 1 nguyện vọng trúng tuyển — "
                "không thể xác định ngành để tính học phí."
            )
        if len(admitted) == 1:
            chosen = admitted[0]
        elif len(choices) == 1:
            chosen = choices[0]
        else:
            # 0 choices (degenerate / corrupt) OR ≥2 still pending: the ngành is
            # NOT determinable. FAIL CLOSED — a choice-engine profile must NEVER
            # fall back to the profile snapshot here, which could price a
            # multi-NV profile against the wrong (NV gốc) ngành. This is the
            # exact wrong-ngành case the fee gate exists to prevent.
            raise BadRequest(
                "Hồ sơ đa nguyện vọng chưa xác định được ngành để tính học phí "
                "(chưa có nguyện vọng, hoặc nhiều nguyện vọng chưa công bố kết "
                "quả). Cần công bố kết quả trước."
            )
        academic_info = _academic_info_of_choice(chosen)
        if academic_info is None:
            raise BadRequest(
                "Không tìm được thông tin tuyển sinh (academic_info) cho "
                "nguyện vọng đã chọn."
            )
        return academic_info

    # Legacy single-path snapshot. Choice-engine profiles NEVER reach here —
    # they resolve from choices or fail closed above.
    oac = profile.__dict__.get("offering_admission_config")
    if oac is not None and oac.__dict__.get("academic_info") is not None:
        return oac.__dict__["academic_info"]
    # OAC relationship not eager-loaded (the fee-create lock loads only lead +
    # choices) — resolve the "modern" OAC path by its scalar FK so a direct
    # service call / fresh session still works when applied_rules lacks
    # academic_info_id (preserves the pre-existing Step-1 OAC behaviour).
    oac_id = getattr(profile, "offering_admission_config_id", None)
    if oac_id is not None:
        academic_info = (
            await db.execute(
                select(models.OfferingAcademicInfo)
                .join(
                    models.OfferingAdmissionConfig,
                    models.OfferingAdmissionConfig.academic_info_id
                    == models.OfferingAcademicInfo.id,
                )
                .where(models.OfferingAdmissionConfig.id == oac_id)
            )
        ).scalars().first()
        if academic_info is not None:
            return academic_info

    applied = profile.applied_rules or {}
    ai_id = applied.get("academic_info_id")
    if ai_id is not None:
        # applied_rules is JSONB — academic_info_id may be a non-numeric string
        # on legacy/corrupt data. Convert defensively so a bad value yields a
        # 400 (BadRequest) rather than an unhandled ValueError → 500.
        try:
            ai_id_int = int(ai_id)
        except (TypeError, ValueError):
            raise BadRequest(
                "Không xác định được ngành: applied_rules.academic_info_id "
                f"không phải số hợp lệ ({ai_id!r})."
            )
        academic_info = (
            await db.execute(
                select(models.OfferingAcademicInfo).where(
                    models.OfferingAcademicInfo.id == ai_id_int
                )
            )
        ).scalars().first()
        if academic_info is not None:
            return academic_info

    raise BadRequest(
        "Không tìm được thông tin tuyển sinh cho hồ sơ này. "
        "Profile thiếu cả offering_admission_config lẫn "
        "applied_rules.academic_info_id."
    )


class FeeCalculationService:
    """
    Service for fee calculation and lifecycle management.

    Responsibilities:
    - Calculate fees with discount application
    - Generate invoices based on installment plans
    - Handle fee waiving
    - Block recalculation when paid
    """

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db
        self.fee_repo = FeeRepository(db)
        self.invoice_repo = InvoiceRepository(db)

    # ==========================================================================
    # FEE CALCULATION
    # ==========================================================================

    async def _resolve_academic_info_id(
        self, profile: models.AdmissionProfile,
    ) -> int:
        """Resolve academic_info_id for the tuition-amount lookup.

        Delegates to the shared module-level ``resolve_fee_academic_info``
        (single source of truth with ``routers/fees.py``) and returns its id.
        Handles legacy single-path AND choice-engine (admitted-choice /
        single-choice) profiles — see that resolver's docstring.
        """
        academic_info = await resolve_fee_academic_info(self.db, profile)
        return academic_info.id

    async def _lookup_semester_tuition_amount(
        self, profile: models.AdmissionProfile, semester_no: int,
    ) -> Decimal:
        """Resolve the ngành then look up its HK tuition amount.

        Direct query — does NOT navigate ORM relationships to avoid
        async lazy-load issues.
        """
        academic_info_id = await self._resolve_academic_info_id(profile)
        return await self._semester_tuition_amount_for_ai(
            academic_info_id, semester_no
        )

    async def _semester_tuition_amount_for_ai(
        self, academic_info_id: int, semester_no: int,
    ) -> Decimal:
        """HK tuition amount from ``offering_semester_tuition`` for an ALREADY
        resolved ``academic_info_id`` — lets ``calculate_fee`` reuse a single
        ``resolve_fee_academic_info`` call (amount + discount from the SAME
        ngância) instead of resolving twice (#7)."""
        result = await self.db.execute(
            select(models.OfferingSemesterTuition.amount).where(
                models.OfferingSemesterTuition.academic_info_id == academic_info_id,
                models.OfferingSemesterTuition.semester_no == semester_no,
            )
        )
        amount = result.scalar_one_or_none()
        if amount is None:
            raise BadRequest(
                f"Chưa cấu hình học phí cho HK{semester_no} "
                f"(academic_info_id={academic_info_id}). "
                "Vui lòng nhập học phí theo học kỳ trong quản trị trước."
            )
        return Decimal(str(amount))

    async def calculate_fee(
        self,
        admission_profile_id: int,
        fee_type: FeeTypeEnum,
        base_amount: Optional[Decimal],
        academic_year: str,
        discount_policy_ids: Optional[List[int]] = None,
        installment_plan_id: Optional[int] = None,
        user_id: Optional[int] = None,
        unit_id: Optional[int] = None,
        semester_no: Optional[int] = None,
    ) -> Tuple[Fee, Optional[Callable]]:
        """
        Calculate fee for an admission profile.

        For tuition fees (PR 3 — ADR-002): the canonical amount is looked
        up from ``offering_semester_tuition`` based on ``semester_no``. The
        ``base_amount`` parameter is ignored for tuition — the caller need
        not provide it. For non-tuition fees, ``base_amount`` is used as
        before and ``semester_no`` stays None.

        Pricing resolution (#7/#9): pass ``base_amount=None`` (the HTTP router
        does) to have the service resolve the ngành ONCE under the row lock and
        derive BOTH the amount and ``discount_policy_ids`` from the same
        ``resolve_fee_academic_info`` — no pre-lock resolve, no double resolve,
        no discount/amount ngành mismatch. Direct/test callers pass an explicit
        ``base_amount`` → values used as-is (``discount_policy_ids=None`` keeps
        the legacy "no discount" meaning, not auto-derive).

        Args:
            admission_profile_id: Profile to create fee for
            fee_type: Type of fee (application, tuition, etc.)
            base_amount: Base fee amount before discounts (ignored for tuition)
            academic_year: Academic year (e.g., "2024-2025")
            discount_policy_ids: List of discount policy IDs to apply
            installment_plan_id: Installment plan for payment scheduling
            user_id: User performing calculation (for audit)
            unit_id: Unit ID for IDOR protection
            semester_no: Semester number for tuition fees (None for non-tuition).
                Defaults to 1 for tuition if not provided — lives in service
                so both HTTP callers and direct callers get the default.

        Returns:
            Tuple of (Fee, post_commit_callback)

        Raises:
            ResourceNotFoundError: If profile not found
            BadRequest: If fee already exists or semester tuition not configured
        """
        # Normalize semester_no: tuition defaults to HK1, non-tuition
        # MUST be None (the DB CHECK chk_fee_nontuition_semester_no_null
        # rejects non-tuition rows with a non-NULL semester_no). Lives in
        # service so both HTTP callers and direct callers get it.
        if fee_type == FeeTypeEnum.tuition and semester_no is None:
            semester_no = 1
        elif fee_type != FeeTypeEnum.tuition:
            semester_no = None

        # Profile-first row lock — serialize vs choice mutation. Acquiring the
        # AdmissionProfile row lock BEFORE reading choices closes the race where
        # another request adds/removes a NV between the router's authz check and
        # this fee insert. ``with_choices`` loads choices so the eligibility
        # re-check below counts the committed NVs under the lock; choice
        # mutations acquire this SAME row lock first (admission_choice_service).
        from app.repositories.admission_repository import AdmissionRepository
        from app.utils.admission_status import is_fee_eligible

        admission_repo = AdmissionRepository(self.db)
        profile = await admission_repo.get_by_id_for_update(
            admission_profile_id, populate_existing=True, with_choices=True
        )
        if not profile:
            raise ResourceNotFoundError("Admission profile not found")

        # IDOR parity with the previous _get_profile(unit_id) filter: the router
        # already authorized, but keep the service-layer unit scope as
        # defense-in-depth.
        if unit_id is not None:
            lead = profile.__dict__.get("lead")
            if lead is None or lead.unit_id != unit_id:
                raise ResourceNotFoundError("Admission profile not found")

        # Re-validate the fee-eligible STATE under the lock. A multi-NV profile
        # that gained a 2nd NV — or left a fee-eligible state — since the router
        # check now fails closed instead of pricing the wrong ngành.
        if not is_fee_eligible(profile):
            raise BadRequest(
                "Hồ sơ không ở trạng thái cho phép tạo học phí (đa nguyện vọng "
                "chưa công bố kết quả, hoặc nguyện vọng đã thay đổi)."
            )

        # #7/#9: when base_amount is None (the HTTP router path) resolve the
        # ngành ONCE under the lock and derive BOTH the amount and the discount
        # policies from the SAME academic_info — closing the race where the
        # router resolved discount pre-lock while the service resolved amount
        # post-lock (a concurrent waitlist-promote could mismatch the two), and
        # removing the double resolve. Direct/test callers pass an explicit
        # base_amount → their values are used as-is; a ``discount_policy_ids`` of
        # None then keeps the legacy "no discount" meaning (NOT auto-derive).
        if base_amount is None:
            academic_info = await resolve_fee_academic_info(self.db, profile)
            if discount_policy_ids is None:
                discount_policy_ids = list(
                    academic_info.applied_discount_policy_ids or []
                )
            if fee_type == FeeTypeEnum.tuition:
                base_amount = await self._semester_tuition_amount_for_ai(
                    academic_info.id, semester_no
                )
            else:
                base_amount = academic_info.tuition_fee_per_year or Decimal("0")
                if base_amount <= 0:
                    raise BadRequest(
                        "Cannot calculate fee: No fee amount configured "
                        "for this offering"
                    )
        elif fee_type == FeeTypeEnum.tuition:
            # Explicit base_amount provided, but tuition's amount is always the
            # canonical offering_semester_tuition value (base_amount ignored).
            base_amount = await self._lookup_semester_tuition_amount(
                profile, semester_no
            )

        # Semester-aware duplicate check for tuition, year-based for others
        existing = await self.fee_repo.check_duplicate(
            admission_profile_id, fee_type.value, academic_year,
            semester_no=semester_no,
        )
        if existing:
            if fee_type == FeeTypeEnum.tuition:
                raise BadRequest(
                    f"Học phí HK{semester_no} đã được tính cho hồ sơ này."
                )
            raise BadRequest(
                f"Fee of type '{fee_type.value}' already exists for "
                f"academic year {academic_year}"
            )

        # Calculate discounts
        total_discount, applied_discounts = await self._calculate_discounts(
            base_amount, discount_policy_ids or []
        )

        # Calculate final amount
        final_amount = max(Decimal("0"), base_amount - total_discount)

        # Get installment plan
        installment_plan = None
        if installment_plan_id:
            installment_plan = await self._get_installment_plan(installment_plan_id)

        # Convert academic_year to int (model stores as Integer)
        if isinstance(academic_year, str):
            academic_year_int = int(academic_year.split("-")[0])
        else:
            academic_year_int = academic_year

        # Create fee record. semester_no is set from the service-level
        # default or caller-provided value (tuition) / None (non-tuition).
        fee = Fee(
            admission_profile_id=admission_profile_id,
            fee_type=fee_type.value,
            academic_year=academic_year_int,
            semester_no=semester_no,
            installment_plan_id=installment_plan_id,
            base_amount=base_amount,
            total_discount=total_discount,
            final_amount=final_amount,
            paid_amount=Decimal("0"),
            waived_amount=Decimal("0"),
            status=FeeStatusEnum.calculated.value,
            calculated_by_id=user_id,
            calculated_at=datetime.now(timezone.utc),
            version=1,
        )

        self.db.add(fee)
        await self.db.flush()
        await self.db.refresh(fee)

        # Create applied discount records
        for order, (policy_id, discount_amount, snapshot) in enumerate(applied_discounts, 1):
            discount_record = FeeAppliedDiscount(
                fee_id=fee.id,
                policy_id=policy_id,
                discount_amount=discount_amount,
                calculation_snapshot=snapshot,
                application_order=order,
            )
            self.db.add(discount_record)

        await self.db.flush()

        log.info(
            "fee_calculated",
            fee_id=fee.id,
            profile_id=admission_profile_id,
            fee_type=fee_type.value,
            semester_no=semester_no,
            base_amount=str(base_amount),
            total_discount=str(total_discount),
            final_amount=str(final_amount),
            user_id=user_id,
        )

        # ADR-002 PR 5: Only HK1 fee creation projects into admission pipeline.
        # PR #8 — capture pipeline stage around the sync call so the closure
        # below can tell the FE whether to invalidate lead/pipeline caches.
        # The lead object may not be loaded; profile.__dict__.get avoids
        # an async lazy-load that would raise MissingGreenlet.
        _lead_obj = profile.__dict__.get("lead")
        _old_stage_id = getattr(_lead_obj, "pipeline_stage_id", None) if _lead_obj else None
        if fee_type == FeeTypeEnum.tuition and semester_no == 1:
            from app.services.lead_admission_sync import sync_lead_tuition_calculated
            await sync_lead_tuition_calculated(
                db=self.db,
                profile=profile,
                fee_amount=str(final_amount),
                changed_by_user_id=user_id,
                reason=f"Tuition fee calculated: {final_amount:,.0f} VND (HK{semester_no})",
            )
        _new_stage_id = getattr(_lead_obj, "pipeline_stage_id", None) if _lead_obj else None
        _lead_stage_changed = _old_stage_id != _new_stage_id

        # Pre-compute everything the closure needs while the session is
        # still attached; rooms must come from the admission helper since
        # the emit runs AFTER the router commits.
        from app.services.notification_dispatcher import rooms_for_admission
        _rooms = rooms_for_admission(profile)
        _event_payload = {
            "admission_profile_id": admission_profile_id,
            "lead_id": getattr(_lead_obj, "id", None) if _lead_obj else None,
            "fee_id": fee.id,
            "fee_status": fee.status,
            "lead_stage_changed": _lead_stage_changed,
            "actor_id": user_id,
        }
        _db = self.db

        async def post_commit():
            # PR #8 — broadcast realtime fee_calculated event. Fire-and-forget:
            # safe_dispatch already absorbs errors so a socket glitch can't
            # break the business flow the router already committed.
            from app.services.notification_dispatcher import safe_dispatch
            from app.core.events import SystemEvents
            await safe_dispatch(
                db=_db,
                event=SystemEvents.FEE_CALCULATED,
                payload=_event_payload,
                rooms=_rooms,
            )

        return fee, post_commit

    async def recalculate_fee(
        self,
        fee_id: int,
        new_base_amount: Decimal,
        reason: str,
        user_id: int,
        unit_id: Optional[int] = None,
    ) -> Tuple[Fee, Optional[Callable]]:
        """
        Recalculate an existing fee with new base amount.

        Business Rule M10: Cannot recalculate if paid_amount > 0

        Args:
            fee_id: Fee to recalculate
            new_base_amount: New base amount
            reason: Reason for recalculation (audit)
            user_id: User performing recalculation
            unit_id: Unit ID for IDOR protection

        Returns:
            Tuple of (Fee, post_commit_callback)

        Raises:
            ResourceNotFoundError: If fee not found
            BusinessRuleViolation: If fee has payments
        """
        fee = await self.fee_repo.get_by_id_with_relations(fee_id, unit_id)
        if not fee:
            raise ResourceNotFoundError("Fee not found")

        # M10: Block recalculation if paid
        if fee.paid_amount > 0:
            raise BusinessRuleViolation(
                f"Cannot recalculate fee with existing payments. "
                f"Paid amount: {fee.paid_amount} VND"
            )

        # Get existing discount policy IDs
        existing_policy_ids = [
            ad.policy_id for ad in fee.applied_discounts if ad.policy_id
        ]

        # Recalculate discounts with new base
        total_discount, applied_discounts = await self._calculate_discounts(
            new_base_amount, existing_policy_ids
        )

        # Update fee
        old_base = fee.base_amount
        old_final = fee.final_amount

        fee.base_amount = new_base_amount
        fee.total_discount = total_discount
        fee.final_amount = max(Decimal("0"), new_base_amount - total_discount)
        fee.version += 1
        fee.notes = f"{fee.notes or ''}\n[{datetime.now(timezone.utc).isoformat()}] " \
                    f"Recalculated by user {user_id}: {old_base} → {new_base_amount}. " \
                    f"Reason: {reason}"

        await self.db.flush()

        log.info(
            "fee_recalculated",
            fee_id=fee_id,
            old_base=str(old_base),
            new_base=str(new_base_amount),
            old_final=str(old_final),
            new_final=str(fee.final_amount),
            reason=reason,
            user_id=user_id,
        )

        return fee, None

    async def waive_fee(
        self,
        fee_id: int,
        waive_amount: Decimal,
        reason: str,
        user_id: int,
        unit_id: Optional[int] = None,
    ) -> Tuple[Fee, Optional[Callable]]:
        """
        Waive part of the fee amount.

        Business Rule H5: waive_amount cannot exceed remaining balance

        Args:
            fee_id: Fee to waive
            waive_amount: Amount to waive
            reason: Reason for waiving (required)
            user_id: User performing waive
            unit_id: Unit ID for IDOR protection

        Returns:
            Tuple of (Fee, post_commit_callback)

        Raises:
            ResourceNotFoundError: If fee not found
            BusinessRuleViolation: If waive exceeds remaining
        """
        fee = await self.fee_repo.get_for_update(fee_id, unit_id)
        if not fee:
            raise ResourceNotFoundError("Fee not found")

        remaining = fee.final_amount - fee.paid_amount - fee.waived_amount

        # H5: Validate waive amount
        if waive_amount > remaining:
            raise BusinessRuleViolation(
                f"Waive amount ({waive_amount}) exceeds remaining balance ({remaining})"
            )

        if waive_amount <= 0:
            raise BadRequest("Waive amount must be positive")

        # Apply waive
        fee.waived_amount = fee.waived_amount + waive_amount
        fee.version += 1

        # Update status if fully waived
        new_remaining = fee.final_amount - fee.paid_amount - fee.waived_amount
        fee_became_paid = False
        if new_remaining <= 0:
            fee.status = FeeStatusEnum.paid.value  # Treat as paid
            fee_became_paid = True

        fee.notes = f"{fee.notes or ''}\n[{datetime.now(timezone.utc).isoformat()}] " \
                    f"Waived {waive_amount} VND by user {user_id}. Reason: {reason}"

        await self.db.flush()

        # ADR-002 PR 5: Only HK1 waiver projects into admission pipeline.
        if fee_became_paid and fee.fee_type == FeeTypeEnum.tuition.value and fee.semester_no == 1:
            # Need to load profile with lead for sync
            profile = await self._get_profile(fee.admission_profile_id, unit_id)
            if profile:
                from app.services.lead_admission_sync import sync_lead_tuition_paid
                await sync_lead_tuition_paid(
                    db=self.db,
                    profile=profile,
                    transaction_id=f"WAIVER-{fee_id}",
                    changed_by_user_id=user_id,
                    reason=f"Tuition fee waived: {waive_amount:,.0f} VND. Reason: {reason}",
                )

        log.info(
            "fee_waived",
            fee_id=fee_id,
            waive_amount=str(waive_amount),
            new_remaining=str(new_remaining),
            reason=reason,
            user_id=user_id,
        )

        return fee, None

    async def cancel_fee(
        self,
        fee_id: int,
        reason: str,
        user_id: int,
        unit_id: Optional[int] = None,
    ) -> Tuple[Fee, Optional[Callable]]:
        """
        Cancel a fee (only if no payments made).

        Args:
            fee_id: Fee to cancel
            reason: Cancellation reason
            user_id: User performing cancellation
            unit_id: Unit ID for IDOR protection

        Returns:
            Tuple of (Fee, post_commit_callback)

        Raises:
            ResourceNotFoundError: If fee not found
            BusinessRuleViolation: If fee has payments
        """
        fee = await self.fee_repo.get_for_update(fee_id, unit_id)
        if not fee:
            raise ResourceNotFoundError("Fee not found")

        if fee.paid_amount > 0:
            raise BusinessRuleViolation(
                f"Cannot cancel fee with existing payments. "
                f"Paid amount: {fee.paid_amount} VND"
            )

        fee.status = FeeStatusEnum.cancelled.value
        fee.version += 1
        fee.notes = f"{fee.notes or ''}\n[{datetime.now(timezone.utc).isoformat()}] " \
                    f"Cancelled by user {user_id}. Reason: {reason}"

        await self.db.flush()

        log.info(
            "fee_cancelled",
            fee_id=fee_id,
            reason=reason,
            user_id=user_id,
        )

        return fee, None

    # ==========================================================================
    # FEE RETRIEVAL
    # ==========================================================================

    async def get_fee(
        self,
        fee_id: int,
        unit_id: Optional[int] = None,
    ) -> Fee:
        """Get fee by ID with all relations."""
        fee = await self.fee_repo.get_by_id_with_relations(fee_id, unit_id)
        if not fee:
            raise ResourceNotFoundError("Fee not found")
        return fee

    async def get_fees_for_profile(
        self,
        profile_id: int,
        unit_id: Optional[int] = None,
        fee_type: Optional[str] = None,
    ) -> List[Fee]:
        """Get all fees for an admission profile."""
        return await self.fee_repo.get_by_profile_id(
            profile_id, unit_id, fee_type
        )

    async def get_fee_summary(
        self,
        profile_id: int,
        unit_id: Optional[int] = None,
    ) -> dict:
        """
        Get financial summary for a profile.

        Returns:
            Dict with total_fees, total_paid, total_remaining, fees list
        """
        fees = await self.fee_repo.get_by_profile_id(profile_id, unit_id)

        total_fees = sum(f.final_amount for f in fees)
        total_paid = sum(f.paid_amount for f in fees)
        total_waived = sum(f.waived_amount for f in fees)
        total_remaining = total_fees - total_paid - total_waived

        return {
            "profile_id": profile_id,
            "total_fees": total_fees,
            "total_paid": total_paid,
            "total_waived": total_waived,
            "total_remaining": total_remaining,
            "fee_count": len(fees),
            "fees": fees,
        }

    # ==========================================================================
    # HELPER METHODS
    # ==========================================================================

    async def _get_profile(
        self,
        profile_id: int,
        unit_id: Optional[int] = None,
    ) -> Optional[models.AdmissionProfile]:
        """Get admission profile with IDOR check and Lead relationship loaded."""
        query = (
            select(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                selectinload(models.AdmissionProfile.lead),
                selectinload(models.AdmissionProfile.offering_admission_config)
                .selectinload(models.OfferingAdmissionConfig.academic_info),
                # Needed by _fee_calc_authorized → is_fee_eligible to count NVs
                # (multi-NV single-choice prepay gate). Without this the gate
                # reads __dict__['choices'] as unset and fails closed.
                selectinload(models.AdmissionProfile.choices),
            )
            .where(models.AdmissionProfile.id == profile_id)
        )

        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def _get_installment_plan(
        self,
        plan_id: int,
    ) -> Optional[InstallmentPlan]:
        """Get installment plan by ID."""
        query = select(InstallmentPlan).where(
            InstallmentPlan.id == plan_id,
            InstallmentPlan.is_active == True,
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def _calculate_discounts(
        self,
        base_amount: Decimal,
        policy_ids: List[int],
    ) -> Tuple[Decimal, List[Tuple[int, Decimal, dict]]]:
        """
        Calculate total discount using additive stacking.

        Policy H4: Additive stacking, capped at 100%

        Args:
            base_amount: Base fee amount
            policy_ids: List of discount policy IDs

        Returns:
            Tuple of (total_discount, list of (policy_id, amount, snapshot))
        """
        if not policy_ids:
            return Decimal("0"), []

        # Get discount policies
        query = select(TuitionDiscountPolicy).where(
            TuitionDiscountPolicy.id.in_(policy_ids),
            TuitionDiscountPolicy.is_active == True,
        )
        result = await self.db.execute(query)
        policies = list(result.scalars().all())

        if not policies:
            return Decimal("0"), []

        # Calculate each discount
        applied_discounts = []
        total_percent = Decimal("0")

        for policy in policies:
            if policy.discount_type == "percent":
                percent = Decimal(str(policy.discount_value))
                total_percent += percent
                discount_amount = (base_amount * percent / 100).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            else:  # fixed amount
                discount_amount = Decimal(str(policy.discount_value))

            snapshot = {
                "policy_name": policy.name,
                "discount_type": policy.discount_type,
                "discount_value": str(policy.discount_value),
                "calculated_at": datetime.now(timezone.utc).isoformat(),
            }

            applied_discounts.append((policy.id, discount_amount, snapshot))

        # Cap at 100% (H4)
        if total_percent > 100:
            log.warning(
                "discount_capped",
                original_percent=str(total_percent),
                capped_to=100,
            )

        total_discount = sum(d[1] for d in applied_discounts)

        # Cap discount at base amount
        if total_discount > base_amount:
            total_discount = base_amount

        return total_discount, applied_discounts


# ==========================================================================
# HELPER FUNCTIONS (Module-level)
# ==========================================================================

def calculate_installment_amounts(
    total_amount: Decimal,
    installment_count: int,
) -> List[Decimal]:
    """
    Calculate installment amounts with proper rounding.

    Uses remainder-in-last strategy: base amount for first n-1 installments,
    remainder goes to last installment. Ensures sum equals total.

    Args:
        total_amount: Total fee amount
        installment_count: Number of installments

    Returns:
        List of amounts per installment
    """
    if installment_count <= 0:
        raise ValueError("Installment count must be positive")

    if installment_count == 1:
        return [total_amount]

    # Calculate base amount (floor division)
    base_amount = (total_amount / installment_count).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    # First n-1 installments get base amount
    amounts = [base_amount] * (installment_count - 1)

    # Last installment gets remainder
    remainder = total_amount - (base_amount * (installment_count - 1))
    amounts.append(remainder)

    # Verify sum equals total
    assert sum(amounts) == total_amount, \
        f"Installment sum {sum(amounts)} != total {total_amount}"

    return amounts


# =============================================================================
# Discount recalculation on semester tuition change — PR 3 (ADR-002 Decision 4)
# =============================================================================

async def recalculate_fees_for_semester_tuition_change(
    db: AsyncSession,
    academic_info_id: int,
) -> int:
    """Recalculate tuition fees when admin edits a semester tuition amount.

    Finds tuition Fee rows linked to the affected academic_info_id,
    re-reads the canonical amount from offering_semester_tuition, and
    updates base_amount / total_discount / final_amount.

    **Safety invariants** (mirrors M10 rule from recalculate_fee):
    - Only recalculates fees with ``paid_amount == 0``. Any fee that
      has received partial or full payment is left untouched — editing
      a live receivable after money has been collected is forbidden.
    - Only recalculates fees whose invoices are all in draft status
      (or no invoices at all). If any invoice has been issued/partial/
      paid, the fee is skipped to avoid fee↔invoice total mismatch.
    - Skips terminal status fees (paid, waived, cancelled).
    - Skips fees whose semester_tuition row was deleted (clear-all).

    Returns the count of fees recalculated.
    """
    from sqlalchemy.orm import selectinload

    # Single query: join Fee -> AdmissionProfile to resolve
    # academic_info_id linkage in SQL rather than per-fee Python loop.
    # Uses applied_rules->>'academic_info_id' for legacy path and
    # offering_admission_config.academic_info_id for modern path.
    # Step 1: Find eligible fee IDs via JOIN query (no selectinload
    # here — selectinload doesn't work reliably with multi-table JOINs
    # in async SQLAlchemy).
    id_result = await db.execute(
        select(Fee.id)
        .join(
            models.AdmissionProfile,
            models.AdmissionProfile.id == Fee.admission_profile_id,
        )
        .outerjoin(
            models.OfferingAdmissionConfig,
            models.OfferingAdmissionConfig.id == models.AdmissionProfile.offering_admission_config_id,
        )
        .where(
            Fee.fee_type == "tuition",
            Fee.status.notin_(["paid", "waived", "cancelled"]),
            Fee.paid_amount == 0,
            sa.or_(
                models.OfferingAdmissionConfig.academic_info_id == academic_info_id,
                models.AdmissionProfile.applied_rules["academic_info_id"].as_string().cast(sa.Integer) == academic_info_id,
            ),
        )
    )
    eligible_fee_ids = [row[0] for row in id_result.fetchall()]

    if not eligible_fee_ids:
        return 0

    # Step 2: Re-load fees with relationships. Use populate_existing=True
    # to force SQLAlchemy to refresh cached Fee objects and their
    # selectinload'd relationships (invoices may have been generated
    # after the fee was first loaded into the session's identity map).
    fee_result = await db.execute(
        select(Fee)
        .where(Fee.id.in_(eligible_fee_ids))
        .options(
            selectinload(Fee.applied_discounts),
            selectinload(Fee.invoices),
            selectinload(Fee.installment_plan),
        )
        .execution_options(populate_existing=True)
    )
    eligible_fees = fee_result.scalars().all()

    recalc_count = 0
    for fee in eligible_fees:
        # Skip if any invoice is beyond draft — recalculating would
        # leave fee.final_amount out of sync with issued invoice totals.
        if fee.invoices:
            has_non_draft = any(
                inv.status != "draft" for inv in fee.invoices
            )
            if has_non_draft:
                log.info(
                    "fee_recalc_skipped_non_draft_invoices",
                    fee_id=fee.id,
                    semester_no=fee.semester_no,
                )
                continue

        # Look up new semester tuition amount
        sem_result = await db.execute(
            select(models.OfferingSemesterTuition.amount).where(
                models.OfferingSemesterTuition.academic_info_id == academic_info_id,
                models.OfferingSemesterTuition.semester_no == fee.semester_no,
            )
        )
        new_amount = sem_result.scalar_one_or_none()
        if new_amount is None:
            continue

        new_base = Decimal(str(new_amount))
        if new_base == fee.base_amount:
            continue

        # Recalculate: re-apply existing discount percentages
        total_discount = Decimal("0")
        for ad in fee.applied_discounts:
            if ad.discount_percent is not None:
                disc = (new_base * ad.discount_percent / 100).quantize(Decimal("1"))
            else:
                disc = ad.discount_amount
            ad.discount_amount = disc
            total_discount += disc

        old_final = fee.final_amount
        fee.base_amount = new_base
        fee.total_discount = min(total_discount, new_base)
        fee.final_amount = max(Decimal("0"), new_base - fee.total_discount)
        fee.version += 1

        # If fee has draft invoices, rewrite their amounts to match
        # the new final_amount so fee↔invoice totals stay in sync.
        # Uses direct UPDATE statements to avoid ORM identity-map issues
        # where selectinload'd Invoice objects may not be dirty-tracked.
        if fee.invoices and fee.installment_plan:
            new_schedule = fee.installment_plan.get_installment_schedule(
                fee.final_amount
            )
            for inv, sched in zip(
                sorted(fee.invoices, key=lambda x: x.installment_no),
                new_schedule,
            ):
                await db.execute(
                    sa.update(Invoice)
                    .where(Invoice.id == inv.id)
                    .values(amount=sched["amount"])
                )
        elif fee.invoices and len(fee.invoices) == 1:
            await db.execute(
                sa.update(Invoice)
                .where(Invoice.id == fee.invoices[0].id)
                .values(amount=fee.final_amount)
            )

        recalc_count += 1
        log.info(
            "fee_recalculated_by_semester_change",
            fee_id=fee.id,
            semester_no=fee.semester_no,
            old_final=str(old_final),
            new_base=str(new_base),
            new_final=str(fee.final_amount),
        )

    if recalc_count > 0:
        await db.flush()

    return recalc_count
