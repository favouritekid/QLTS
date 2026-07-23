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
    Fee, FeeAppliedDiscount, Invoice, Payment, InstallmentPlan,
    FeeTypeEnum, FeeStatusEnum, InvoiceStatusEnum, PaymentStatusEnum,
    PaymentIntent, PaymentIntentStatusEnum,
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
from app.utils.text_helpers import escape_like_pattern, LIKE_ESCAPE_CHAR

log = structlog.get_logger(__name__)


def is_hk1_settled(
    fee_type: str,
    semester_no: Optional[int],
    status: str,
    paid_amount: Decimal,
    final_amount: Decimal,
    waived_amount: Decimal,
) -> bool:
    """Check if an HK1 tuition fee is fully SETTLED (for lead pipeline projection).

    Settled = tuition + semester_no=1 + NOT cancelled + one of:
      - status in (paid, waived)
      - remaining (final - paid - waived) <= 0

    This is the SOLE chokepoint deciding whether the lead reaches sts10
    "Đã hoàn tất học phí". A PARTIAL payment (remaining > 0) is NOT settled —
    the lead stays at sts14 "Chưa hoàn tất học phí". This is intentionally
    STRICTER than the enrollment gate (_check_fee_gate_semester_hk1) which,
    per ADR-002, still lets a partial payment pass enrollment.

    The ``cancelled`` guard is required: a cancelled fee can be zeroed-out
    (final=paid=waived=0) so ``remaining <= 0`` would be True — without the
    guard the void-revert call site would wrongly keep the lead at sts10.

    Used to detect transition into settled state at payment/waiver call sites.
    Callers snapshot pre-state, apply mutation, then check post-state: sync
    only on False -> True.
    """
    if fee_type != "tuition" or semester_no != 1:
        return False
    if status == "cancelled":
        return False
    if status in ("paid", "waived"):
        return True
    return (final_amount - paid_amount - waived_amount) <= 0


def is_hk1_settled_fee(fee) -> bool:
    """``is_hk1_settled`` for a Fee-like object — the form call sites should use.

    The pure ``is_hk1_settled`` takes three ADJACENT same-type Decimal args
    (paid/final/waived) that are easy to transpose at a call site; a silent swap
    re-introduces the exact bug this guard fixes (partial wrongly read as
    settled) with NO TypeError. Every runtime call site has the ``fee`` in hand,
    so they call THIS wrapper and the positional order lives in exactly one
    reviewed place.
    """
    return is_hk1_settled(
        fee.fee_type, fee.semester_no, fee.status,
        fee.paid_amount, fee.final_amount, fee.waived_amount,
    )


async def is_major_change_cycle_open(
    db: AsyncSession, profile: "models.AdmissionProfile"
) -> bool:
    """True khi hồ sơ đang trong CHU KỲ đổi ngành — dùng chung bởi cờ transient
    FE (``_populate_major_change_flag``) VÀ 6 gate (xuất giấy / approve /
    publish_result / enroll / confirm / calculate_fee).

    = ``profile.major_change_requested`` (admin đã cho phép, chờ officer sửa +
    nộp lại) HOẶC active HK1 tuition fee ``awaiting_accountant_confirmation`` (đã
    reprice, chờ kế toán chốt).

    Flag ``MAJOR_CHANGE_REPRICE_ENABLED`` OFF → LUÔN False ⇒ mọi gate no-op +
    badge không hiện (deploy cờ OFF không đổi hành vi). ``major_change_requested``
    đọc trực tiếp (không DB hit); chỉ query khi cờ profile chưa bật.
    """
    if not settings.MAJOR_CHANGE_REPRICE_ENABLED:
        return False
    if getattr(profile, "major_change_requested", False):
        return True
    row = (
        await db.execute(
            select(Fee.id)
            .where(
                Fee.admission_profile_id == profile.id,
                Fee.fee_type == FeeTypeEnum.tuition.value,
                Fee.semester_no == 1,
                Fee.status != FeeStatusEnum.cancelled.value,
                Fee.awaiting_accountant_confirmation.is_(True),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


# Status pre-decision được phép mở chu kỳ đổi ngành (trước công bố kết quả — tránh
# stale choice.decision=='admitted' bám ngành cũ). Post-decision cần reset
# decision + xử quota/seat = ngoài scope v1.
_MAJOR_CHANGE_PRE_DECISION_STATUSES = ("submitted", "resubmitted")


async def maybe_open_major_change_cycle(
    db: AsyncSession,
    profile: "models.AdmissionProfile",
    *,
    allow_major_change: bool,
) -> bool:
    """Mở chu kỳ đổi ngành: set ``profile.major_change_requested=True`` nếu ĐỦ
    điều kiện. Gọi từ ``admin_rollback_profile`` + ``request_revision`` TRƯỚC khi
    transition (đọc status GỐC).

    Điều kiện (mọi cái phải đúng, nếu không → bỏ qua, KHÔNG raise):
      * flag ON + ``allow_major_change`` + ``uses_choice_engine``;
      * status GỐC ∈ pre-decision ``{submitted, resubmitted}`` (post-decision bỏ
        qua — stale admitted bám ngành cũ, reset decision ngoài scope);
      * có HK1 tuition fee active (không có → không có gì để reprice).

    Raise ``BusinessRuleViolation`` KHI ``allow_major_change`` nhưng active fee
    đang ``awaiting_accountant_confirmation`` (single-cycle lock — không mở chu
    kỳ 2 trước khi kế toán chốt).

    Trả ``True`` nếu đã set cờ; ``False`` nếu bỏ qua.
    """
    if not settings.MAJOR_CHANGE_REPRICE_ENABLED or not allow_major_change:
        return False
    if not getattr(profile, "uses_choice_engine", False):
        return False
    if profile.status not in _MAJOR_CHANGE_PRE_DECISION_STATUSES:
        return False
    from app.services.enrollment_letter_service import (
        _get_active_hk1_tuition_fee,
    )
    fee = await _get_active_hk1_tuition_fee(db, profile.id)
    if fee is None:
        return False
    if fee.awaiting_accountant_confirmation:
        raise BusinessRuleViolation(
            "Còn một chu kỳ đổi ngành đang chờ kế toán xác nhận — không thể mở "
            "chu kỳ đổi ngành mới."
        )
    profile.major_change_requested = True
    log.info(
        "major_change_cycle_opened",
        profile_id=profile.id,
        from_status=profile.status,
        fee_id=fee.id,
    )
    return True


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
        (prepay / giữ chỗ at ``submitted`` / ``resubmitted`` — mirrors
        ``is_fee_eligible``),
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


async def resnapshot_fee_academic_info_for_profile(
    db: AsyncSession,
    profile_id: int,
    *,
    profile: "Optional[models.AdmissionProfile]" = None,
) -> int:
    """Re-snapshot ``Fee.resolved_*`` (academic_info / major / degree) for the
    non-cancelled fees of a profile — the SINGLE writer of the denormalized major
    snapshot the "Thu học phí" workspace reads (filter + list row + drawer +
    status-counts).

    Resolves via the SAME ``resolve_fee_academic_info`` used for pricing, so for
    multi-NV profiles the snapshot reflects the ADMITTED choice — never the
    lead's intent offering.

    **Best-effort + fail-soft**: any failure resolving the ngành (BadRequest for
    multi-NV-undecided / 0 / ≥2 admitted, OR an unexpected DB error in the
    resolve/major-lookup) → snapshot stays NULL and the function still returns,
    NEVER raising into the caller. This keeps the denormalization (a display
    nicety) OFF the critical path of the money-creating flows that call it
    (calculate_fee / fee payment / decision publish). Idempotent. Service only
    ``flush``es; the caller commits.

    **Cancelled fees are skipped** so a later admit doesn't relabel a historical
    cancelled fee (e.g. officer cancelled an NV1 fee, profile later admitted NV2).

    ``profile`` may be passed by callers that already hold the ORM object
    (``calculate_fee`` / decision hooks) to skip a redundant SELECT.

    ⚠️ MUST be called by ANY code that (a) creates a Fee outside
    ``calculate_fee`` or (b) changes which ngành a profile is admitted to
    (``AdmissionProfileChoice.decision``) — else the snapshot goes stale and the
    filter/display disagree. Current callers: ``calculate_fee``,
    ``recalculate_fee``, ``recalculate_fees_for_semester_tuition_change``,
    ``_create_or_repair_paid_chain`` (application fee), and the decision writers
    ``evaluate_cascade`` / ``promote_waitlisted_choice`` /
    ``AdmissionProfileChoiceRepository.update_decision``.

    Returns the number of fees updated.
    """
    if profile is None:
        profile = (
            await db.execute(
                select(models.AdmissionProfile).where(
                    models.AdmissionProfile.id == profile_id
                )
            )
        ).scalars().first()
    if profile is None:
        return 0

    # Cheap existence guard FIRST: a profile with no non-cancelled fee has
    # nothing to stamp, so skip the (multi-query) ngành resolve entirely. This
    # is the common state while a draft is built choice-by-choice — the new
    # add_choice/delete_choice callers fire on every NV mutation, long before
    # any fee exists. Bỏ qua fee đã huỷ — không relabel lịch sử theo ngành.
    # Kept under the best-effort umbrella: this function MUST NOT raise into the
    # money-creating callers, so a failing db.execute here returns 0 (same
    # fail-soft contract the resolve block below has) rather than propagating.
    try:
        fees = (
            await db.execute(
                select(Fee).where(
                    Fee.admission_profile_id == profile_id,
                    Fee.status != "cancelled",
                )
            )
        ).scalars().all()
    except Exception as exc:  # best-effort: KHÔNG để snapshot vỡ money flow
        log.error(
            "resnapshot_fee_academic_info_failed",
            profile_id=profile_id,
            error=str(exc),
        )
        return 0
    if not fees:
        return 0

    resolved_ai_id: Optional[int] = None
    resolved_major_id: Optional[int] = None
    resolved_degree_level: Optional[str] = None
    try:
        academic_info = await resolve_fee_academic_info(db, profile)
        if academic_info is not None:
            resolved_ai_id = academic_info.id
            row = (
                await db.execute(
                    select(
                        models.MajorProgram.id,
                        models.MajorProgram.degree_level,
                    )
                    .select_from(models.OfferingAcademicInfo)
                    .join(
                        models.ProgramOffering,
                        models.ProgramOffering.id
                        == models.OfferingAcademicInfo.offering_id,
                    )
                    .join(
                        models.MajorProgram,
                        models.MajorProgram.id
                        == models.ProgramOffering.program_id,
                    )
                    .where(models.OfferingAcademicInfo.id == resolved_ai_id)
                )
            ).first()
            if row is not None:
                resolved_major_id, resolved_degree_level = row
    except BadRequest:
        # Fail-soft: chưa chốt được ngành → để NULL (UI hiện "(chưa chốt ngành)").
        pass
    except Exception as exc:  # best-effort: KHÔNG để snapshot vỡ money flow
        log.error(
            "resnapshot_fee_academic_info_failed",
            profile_id=profile_id,
            error=str(exc),
        )
        return 0

    for fee in fees:
        # E2 hardening (audit 29-06): fee đã gắn ngành (resolved_ai cũ) mà nay
        # resolve ra ngành KHÁC → cấu hình AdmissionPath/academic_info có thể đã bị
        # sửa SAU khi tính phí; ``final_amount`` (đóng băng theo ngành cũ) có thể
        # KHÔNG còn khớp ngành mới. Snapshot vẫn cập nhật để display khớp ngành
        # hiện tại, nhưng phát log.warning để kế-toán/admin soát tiền (biến vi phạm
        # invariant thành tín hiệu quan sát được thay vì ghi đè im lặng).
        prior_ai = fee.resolved_academic_info_id
        if (
            resolved_ai_id is not None
            and prior_ai is not None
            and prior_ai != resolved_ai_id
        ):
            log.warning(
                "fee_resolved_major_drift",
                fee_id=fee.id,
                profile_id=profile_id,
                prior_academic_info_id=prior_ai,
                new_academic_info_id=resolved_ai_id,
                fee_final_amount=str(fee.final_amount),
            )
        fee.resolved_academic_info_id = resolved_ai_id
        fee.resolved_major_id = resolved_major_id
        fee.resolved_degree_level = resolved_degree_level
    await db.flush()
    return len(fees)


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
        target_final_amount: Optional[Decimal] = None,
        manual_discount_reason: Optional[str] = None,
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
        # 🔴 GUARD SERVICE-SIDE (miễn/giảm học phí THẬT — Pha 2) — đặt TRƯỚC mọi
        # resolve giá / DB. ``calculate_fee`` là business boundary có direct/test
        # caller KHÔNG đi qua schema model_validator → tự bảo vệ invariant tiền
        # nghĩa vụ: giảm tay chỉ cho tuition + lý do ≥10 + target >= 0. KIỂM tra
        # AUTHZ field-level (chỉ admin/manager/accountant) nằm ở ROUTER (deps có
        # role); service đảm bảo bất biến SỐ. Ràng buộc target < net-after-policy
        # đo SAU khi resolve discount (manual_discount > 0 bên dưới).
        if target_final_amount is not None:
            if fee_type != FeeTypeEnum.tuition:
                raise BadRequest(
                    "Miễn/giảm học phí thủ công chỉ áp dụng cho học phí (tuition)."
                )
            if target_final_amount < 0:
                raise BadRequest("Học phí áp dụng không được âm.")
            if not manual_discount_reason or len(manual_discount_reason.strip()) < 10:
                raise BadRequest("Cần lý do miễn/giảm học phí (tối thiểu 10 ký tự).")
        elif manual_discount_reason:
            raise BadRequest("Có lý do miễn/giảm nhưng thiếu mức học phí áp dụng.")

        # Normalize semester_no: tuition defaults to HK1, non-tuition
        # MUST be None (the DB CHECK chk_fee_nontuition_semester_no_null
        # rejects non-tuition rows with a non-NULL semester_no). Lives in
        # service so both HTTP callers and direct callers get it.
        if fee_type == FeeTypeEnum.tuition and semester_no is None:
            semester_no = 1
        elif fee_type != FeeTypeEnum.tuition:
            semester_no = None

        # #5 review: ``base_amount=None`` is the "service resolves pricing"
        # sentinel (router path) and it also derives discount_policy_ids, so an
        # explicit discount_policy_ids alongside it is contradictory. Reject the
        # ambiguous combo fail-fast — a programming/contract error; no real
        # caller mixes them (router passes both None, direct callers pass both).
        if base_amount is None and discount_policy_ids is not None:
            raise ValueError(
                "calculate_fee: base_amount=None (service-resolve mode) cannot "
                "be combined with an explicit discount_policy_ids — pass both "
                "None (router) or both explicit (direct caller)."
            )

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
                # Giá chuẩn HK từ offering_semester_tuition là BASE (bắt buộc có
                # cấu hình HK). Số tiền nghĩa vụ KHÔNG do người dùng nhập tay —
                # mọi tuỳ chỉnh (giãn lịch) nằm ở tầng hoá đơn, không đổi base.
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

        # Calculate discounts (policy-derived)
        total_discount, applied_discounts = await self._calculate_discounts(
            base_amount, discount_policy_ids or []
        )

        # Miễn/giảm học phí THẬT (Pha 2) — giảm NGHĨA VỤ (final) qua 1 dòng
        # FeeAppliedDiscount ad-hoc (policy_id=NULL), GIỮ base_amount=canonical.
        # "Học phí áp dụng" (target_final_amount) là final SAU MỌI giảm → manual
        # discount = canonical − giảm-policy-sẵn-có − target (KHÔNG phải
        # canonical − target, tránh giảm quá tay khi đã có policy discount). Sau
        # đó final == target. Đánh dấu source="manual_discount" trong snapshot
        # (KHÔNG dựa policy_id IS NULL — policy bị xoá cũng NULL).
        if target_final_amount is not None:
            existing_policy_discount = total_discount
            manual_discount_amount = (
                base_amount - existing_policy_discount - target_final_amount
            )
            if manual_discount_amount <= 0:
                raise BadRequest(
                    f"Học phí áp dụng ({target_final_amount}) phải NHỎ HƠN mức sau "
                    f"giảm hiện hành ({base_amount - existing_policy_discount}). "
                    "Nếu không cần giảm thêm thì bỏ miễn/giảm thủ công."
                )
            manual_snapshot = {
                # source = dấu hiệu MÁY ĐỌC ĐƯỢC để soát giảm-tay (KHÔNG dựa
                # policy_id IS NULL — policy bị xoá cũng NULL).
                "source": "manual_discount",
                "reason": manual_discount_reason,
                "approved_by": user_id,
                "canonical_amount": str(base_amount),
                "existing_policy_discount": str(existing_policy_discount),
                "target_final_amount": str(target_final_amount),
                "discount_amount": str(manual_discount_amount),
                "calculated_at": datetime.now(timezone.utc).isoformat(),
                # policy_name/discount_type/discount_value để builder response
                # (_build_fee_detail_response) hiển nhãn thay vì "Unknown".
                "policy_name": "Miễn/giảm học phí (thủ công)",
                "discount_type": "manual_amount",
                "discount_value": str(manual_discount_amount),
            }
            applied_discounts.append((None, manual_discount_amount, manual_snapshot))
            total_discount = existing_policy_discount + manual_discount_amount

        # Calculate final amount (== target_final_amount khi có miễn/giảm tay)
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

        # Snapshot ngành đã resolve lên Fee.resolved_* (single writer) — giữ
        # filter/list/drawer/status-counts khớp với ngành ĐÚNG (admitted choice
        # cho multi-NV). Truyền profile đã load (bỏ re-SELECT); best-effort.
        await resnapshot_fee_academic_info_for_profile(
            self.db, admission_profile_id, profile=profile
        )

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

    async def preview_tuition(
        self,
        profile: "models.AdmissionProfile",
        semester_no: int,
    ) -> Tuple[Decimal, Decimal, Decimal]:
        """Giá chuẩn học phí (read-only, KHÔNG persist) cho dialog "Tính phí" —
        hiển base / giảm giá / dự kiến phải thu để người dùng đối chiếu khi chọn
        lịch thu (vd chia "đóng trước + còn lại").

        Tái dùng ĐÚNG resolver giá + discount như ``calculate_fee`` (cùng nguồn
        sự thật ``resolve_fee_academic_info`` + ``_semester_tuition_amount_for_ai``
        + ``_calculate_discounts``) nên số preview khớp với số luồng cũ tạo ra.
        Router lo IDOR (``_fee_calc_authorized``) trước khi gọi — service chỉ tính.

        Returns:
            (base_amount, total_discount, final_amount) cho HK ``semester_no``.

        Raises:
            BadRequest: ngành chưa xác định (multi-NV chưa công bố) / chưa cấu
                hình học phí HK.
        """
        academic_info = await resolve_fee_academic_info(self.db, profile)
        base_amount = await self._semester_tuition_amount_for_ai(
            academic_info.id, semester_no
        )
        discount_policy_ids = list(academic_info.applied_discount_policy_ids or [])
        total_discount, _ = await self._calculate_discounts(
            base_amount, discount_policy_ids
        )
        final_amount = max(Decimal("0"), base_amount - total_discount)
        return base_amount, total_discount, final_amount

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

        # Pha 2: chặn tính lại phí có MIỄN/GIẢM THỦ CÔNG (message cụ thể; cũng bắt
        # cả khi HĐ đã bị HỦY HẾT — lúc đó issued-block dưới không fire). recalc
        # chỉ tính lại discount theo policy (existing_policy_ids loại policy_id=NULL)
        # → sẽ BỎ RƠI dòng giảm tay khỏi final (final nhảy lên) + để lại dòng
        # orphan. Giảm tay là quyết định riêng (học bổng…), không tự suy lại theo
        # base mới → bắt hủy & tạo lại thay vì âm thầm mất.
        if any(
            (ad.calculation_snapshot or {}).get("source") == "manual_discount"
            for ad in fee.applied_discounts
        ):
            raise BusinessRuleViolation(
                "Không thể tính lại phí có miễn/giảm học phí thủ công — hãy hủy "
                "phí rồi tạo lại với mức áp dụng mới."
            )

        # Block when any non-cancelled invoice is beyond draft (#445). Recalc đổi
        # ``fee.final_amount`` nhưng payment thu theo ``invoice.amount`` (KHÔNG
        # đọc fee) → fee 10tr/HĐ issued 10tr, recalc 8tr ⇒ vẫn thu 10tr (dư 2tr);
        # ngược lại tăng giá ⇒ thu thiếu. Đối xứng
        # ``recalculate_fees_for_semester_tuition_change`` (chỉ recalc khi mọi HĐ
        # còn draft). Muốn đổi phí đã phát hành: hủy hóa đơn rồi tính lại.
        # Query invoices TƯƠI (không dựa ``fee.invoices`` relationship — có thể
        # stale dưới session tái dùng; prod mỗi request session mới nhưng đây là
        # tiền lõi nên load tường minh).
        fee_invoices = list(
            (
                await self.db.execute(
                    select(Invoice).where(Invoice.fee_id == fee_id)
                )
            ).scalars().all()
        )
        active_invoices = [
            inv for inv in fee_invoices if inv.status != "cancelled"
        ]
        if any(inv.status != "draft" for inv in active_invoices):
            raise BusinessRuleViolation(
                "Không thể tính lại phí khi đã phát hành hóa đơn "
                "(issued/partial/paid). Hãy hủy hóa đơn liên quan trước rồi "
                "tính lại."
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

        # Đồng bộ hóa đơn DRAFT (nếu có) theo final mới để fee↔invoice không lệch
        # — chỉ tới đây khi mọi HĐ còn draft (guard non-draft ở trên). Mirror
        # recalculate_fees_for_semester_tuition_change.
        draft_invoices = [
            inv for inv in fee_invoices if inv.status == "draft"
        ]
        if len(draft_invoices) == 1:
            # 1 đợt draft (FULL plan, hoặc multi-plan còn đúng 1 đợt sau khi hủy) →
            # toàn bộ final vào đó, giữ sum(invoice)==final.
            await self.db.execute(
                sa.update(Invoice)
                .where(Invoice.id == draft_invoices[0].id)
                .values(amount=fee.final_amount)
            )
        elif len(draft_invoices) >= 2:
            # ≥2 HĐ draft: chỉ rewrite AN TOÀN khi có installment_plan VÀ số HĐ
            # draft KHỚP số đợt kế hoạch. Lệch vì: (a) 1 đợt giữa kế hoạch đã hủy
            # (cancelled không bị block ở trên), HOẶC (b) fee KHÔNG có plan nhưng bị
            # tạo thêm HĐ draft qua POST /api/invoices (create_single_invoice). Cả 2
            # trường hợp: zip theo vị trí sẽ gán lệch số tiền → fee↔invoice lệch
            # (thu thiếu/dư) — đúng kiểu sai tiền #2 định chặn. KHÔNG rewrite mù →
            # chặn, yêu cầu hủy & phát hành lại.
            new_schedule = (
                fee.installment_plan.get_installment_schedule(fee.final_amount)
                if fee.installment_plan
                else None
            )
            if new_schedule is None or len(draft_invoices) != len(new_schedule):
                raise BusinessRuleViolation(
                    "Bộ hóa đơn không khớp kế hoạch trả góp (đợt đã hủy hoặc không "
                    "có kế hoạch trả góp) — hãy hủy các hóa đơn còn lại rồi phát "
                    "hành lại để tính lại phí."
                )
            # Sort CẢ HAI theo installment_no để ghép ĐÚNG đợt (schedule JSONB có
            # thể lưu lệch thứ tự, remainder rơi vào phần tử cuối list).
            for inv, sched in zip(
                sorted(draft_invoices, key=lambda x: x.installment_no),
                sorted(new_schedule, key=lambda s: s["installment_no"]),
            ):
                await self.db.execute(
                    sa.update(Invoice)
                    .where(Invoice.id == inv.id)
                    .values(amount=sched["amount"])
                )

        await self.db.flush()

        # Recalc KHÔNG gọi resolver như calculate_fee → snapshot ngành tường minh
        # (ngành thường không đổi, nhưng đảm bảo điền/refresh resolved_* cho fee
        # cũ chưa có snapshot). Fail-soft, idempotent.
        await resnapshot_fee_academic_info_for_profile(
            self.db, fee.admission_profile_id
        )

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
        Cancel a fee — back out a mistakenly-created/calculated fee.

        Only allowed when nothing has been collected (``fee.paid_amount == 0``)
        and no payment is mid-flight. Hardening (Nhóm B):
          * Block if any unverified ``pending`` payment exists on the fee's
            invoices (would land money on a dead fee once verified).
          * Block if an active online ``PaymentIntent`` (created/pending, not
            expired) exists — a late gateway success would be rejected by
            ``can_process_callback`` AFTER the fee is cancelled, black-holing the
            money. Let the intent complete/expire first.
          * Cascade-cancel EVERY non-cancelled invoice of the fee (incl
            ``draft``) in the SAME transaction — matches the FE FeeCancelDialog
            promise and removes the payable surface.
          * For HK1 tuition only, revert the lead off sts14 (symmetric to the
            forward ``sync_lead_tuition_calculated`` projection).

        Args:
            fee_id: Fee to cancel
            reason: Cancellation reason
            user_id: User performing cancellation
            unit_id: Unit ID for IDOR protection

        Returns:
            Tuple of (Fee, post_commit_callback)

        Raises:
            ResourceNotFoundError: If fee not found
            BusinessRuleViolation: If fee has payments / pending payment /
                active online intent
        """
        fee = await self.fee_repo.get_for_update(fee_id, unit_id)
        if not fee:
            raise ResourceNotFoundError("Fee not found")

        if fee.paid_amount > 0:
            raise BusinessRuleViolation(
                f"Cannot cancel fee with existing payments. "
                f"Paid amount: {fee.paid_amount} VND"
            )

        # ALL invoices of the fee (incl cancelled). The guards must see a
        # payment/intent even on an invoice cancelled INDEPENDENTLY (e.g. the
        # MISA cancel-and-reissue flow): a still-live intent on a cancelled
        # invoice would otherwise slip past and later land gateway money the
        # callback must refuse. The cascade below only re-cancels the
        # non-cancelled ones.
        all_invoices = await self.invoice_repo.get_by_fee_id(
            fee_id, unit_id, active_only=False
        )
        all_invoice_ids = [inv.id for inv in all_invoices]
        active_invoices = [
            inv for inv in all_invoices
            if inv.status != InvoiceStatusEnum.cancelled.value
        ]

        if all_invoice_ids:
            # Guard A: a pending (unverified) manual payment must be resolved
            # first — it is not in fee.paid_amount yet but would write money on a
            # cancelled fee when verified. Invoice.payments is eager-loaded by
            # get_by_fee_id → check in-Python (no extra round-trip).
            if any(
                p.status == PaymentStatusEnum.pending.value
                for inv in all_invoices
                for p in inv.payments
            ):
                raise BusinessRuleViolation(
                    "Không thể huỷ khoản phí: đang có khoản thanh toán chờ xác "
                    "minh. Vui lòng xác minh hoặc từ chối trước khi huỷ."
                )

            # Guard B: a still-processable online intent on ANY invoice of the
            # fee could report success after cancel; the callback would then be
            # rejected (cancelled target) → money received but unrecorded. Block.
            now = datetime.now(timezone.utc)
            active_intents = (
                await self.db.execute(
                    sa.select(sa.func.count(PaymentIntent.id)).where(
                        PaymentIntent.invoice_id.in_(all_invoice_ids),
                        PaymentIntent.status.in_(
                            [
                                PaymentIntentStatusEnum.created.value,
                                PaymentIntentStatusEnum.pending.value,
                            ]
                        ),
                        PaymentIntent.expires_at > now,
                    )
                )
            ).scalar() or 0
            if active_intents:
                raise BusinessRuleViolation(
                    "Không thể huỷ khoản phí: đang có giao dịch online chờ xử "
                    "lý. Vui lòng đợi giao dịch hoàn tất/hết hạn rồi huỷ."
                )

        now = datetime.now(timezone.utc)
        # Snapshot prior statuses BEFORE mutating — for the audit trail (A1).
        _prev_fee_status = fee.status
        _cancelled_invoices = [(inv.id, inv.status) for inv in active_invoices]
        # Cascade-cancel every non-cancelled invoice in the same transaction.
        for inv in active_invoices:
            inv.status = InvoiceStatusEnum.cancelled.value
            inv.cancelled_at = now
            inv.cancelled_by_id = user_id
            inv.cancelled_reason = reason

        fee.status = FeeStatusEnum.cancelled.value
        fee.version += 1
        fee.notes = f"{fee.notes or ''}\n[{now.isoformat()}] " \
                    f"Cancelled by user {user_id}. Reason: {reason}"

        await self.db.flush()

        # A1: persist the fee + invoice cancellation to entity_audit_log so a
        # unified audit timeline shows the void (previously only on the invoice
        # row's cancelled_* fields + fee.notes, invisible to an audit query).
        from app.services import audit_service
        await audit_service.log_audit(
            self.db,
            entity_type="Fee",
            entity_id=fee.id,
            action="status_changed",
            actor_user_id=user_id,
            field_name="status",
            old_value=_prev_fee_status,
            new_value=FeeStatusEnum.cancelled.value,
            reason=reason,
            source="api",
        )
        for _inv_id, _inv_prev in _cancelled_invoices:
            await audit_service.log_audit(
                self.db,
                entity_type="Invoice",
                entity_id=_inv_id,
                action="status_changed",
                actor_user_id=user_id,
                field_name="status",
                old_value=_inv_prev,
                new_value=InvoiceStatusEnum.cancelled.value,
                reason=reason,
                source="api",
            )

        # Lead projection reverse: ONLY HK1 tuition projects onto the lead, and
        # ONLY when NO OTHER non-cancelled HK1 tuition fee remains for the lead.
        # A multi-year lead may still owe HK1 on another profile/year — the
        # forward sync floors the lead at sts14 once (lead-level idempotent), so
        # cancelling one HK1 fee must not clear that label while another HK1
        # obligation stands. revert_lead_tuition_calculated additionally guards
        # on the lead still being at sts14. Best-effort: wrap in a SAVEPOINT so a
        # projection failure never rolls back the cancel itself.
        if fee.fee_type == FeeTypeEnum.tuition.value and fee.semester_no == 1:
            profile = await self._get_profile(fee.admission_profile_id, unit_id)
            if profile is not None:
                other_hk1 = (
                    await self.db.execute(
                        sa.select(sa.func.count(Fee.id))
                        .join(
                            models.AdmissionProfile,
                            models.AdmissionProfile.id
                            == Fee.admission_profile_id,
                        )
                        .where(
                            models.AdmissionProfile.lead_id == profile.lead_id,
                            Fee.fee_type == FeeTypeEnum.tuition.value,
                            Fee.semester_no == 1,
                            Fee.status != FeeStatusEnum.cancelled.value,
                        )
                    )
                ).scalar() or 0
                if other_hk1 == 0:
                    from app.services.lead_admission_sync import (
                        revert_lead_tuition_calculated,
                    )
                    try:
                        async with self.db.begin_nested():
                            await revert_lead_tuition_calculated(
                                db=self.db,
                                profile=profile,
                                changed_by_user_id=user_id,
                                reason=(
                                    "Huỷ khoản học phí HK1 (tính nhầm). "
                                    f"Lý do: {reason}"
                                ),
                            )
                    except Exception:
                        log.warning(
                            "cancel_fee: lead projection revert failed "
                            "(best-effort, cancel kept)",
                            fee_id=fee_id,
                            exc_info=True,
                        )

        log.info(
            "fee_cancelled",
            fee_id=fee_id,
            reason=reason,
            user_id=user_id,
            invoices_cancelled=len(active_invoices),
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

        # Exclude CANCELLED fees from the money aggregates: a cancelled fee is
        # void (final_amount>0, paid==0) so counting its remaining would surface
        # a phantom "Còn nợ" on a settled/withdrawn profile. The ``fees`` list
        # still returns every fee (incl cancelled) for display/history.
        _active = [
            f for f in fees
            if f.status != FeeStatusEnum.cancelled.value
        ]
        total_fees = sum(f.final_amount for f in _active)
        total_paid = sum(f.paid_amount for f in _active)
        total_waived = sum(f.waived_amount for f in _active)
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

    async def get_profile_collection(
        self,
        profile_id: int,
        unit_id: Optional[int] = None,
    ) -> Optional[models.AdmissionProfile]:
        """Resolve a profile with its full finance graph for the "Thu học phí"
        drawer (identity + fees → invoices → payments).

        IDOR: unit-scoped via the ``lead.unit_id`` join (same scope as the rest
        of the finance module). Returns ``None`` when the profile does not exist
        OR is outside ``unit_id`` so the router can 404 WITHOUT leaking identity/
        existence — the access decision is made HERE (resolve-first), never from
        whether the collection turns out empty.

        Bounded eager-load (a handful of selectin/joined queries, NO per-row
        N+1): lead → assigned_officer (identity) · fees → resolved_major (ngành/
        trình độ snapshot) · fees → invoices → payments → (method, created_by,
        verified_by) (the three tiers + the columns the list builders read).
        """
        query = (
            select(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                selectinload(models.AdmissionProfile.lead)
                .selectinload(models.Lead.assigned_officer),
                # Ngành/trình độ drawer đọc snapshot Fee.resolved_major (khớp list
                # + filter, đúng NV admitted) — KHÔNG còn dùng lead.offering.program
                # nên bỏ luôn eager-load offering→program (dead load).
                selectinload(models.AdmissionProfile.fees)
                .joinedload(Fee.resolved_major),
                # fees → invoices → payments, with the payment columns the list
                # builder reads (method/created_by/verified_by). Explicit chain
                # overrides the model-level lazy="selectin" so nested loads are
                # eager too.
                selectinload(models.AdmissionProfile.fees)
                .selectinload(Fee.invoices)
                .selectinload(Invoice.payments)
                .joinedload(Payment.method),
                selectinload(models.AdmissionProfile.fees)
                .selectinload(Fee.invoices)
                .selectinload(Invoice.payments)
                .joinedload(Payment.created_by),
                selectinload(models.AdmissionProfile.fees)
                .selectinload(Fee.invoices)
                .selectinload(Invoice.payments)
                .joinedload(Payment.verified_by),
                # Suppress the model-level lazy="selectin" eager-loads the list
                # builders never read — otherwise opening the drawer fires 2 extra
                # batched SELECTs (invoice.payment_intents + payment.transactions).
                selectinload(models.AdmissionProfile.fees)
                .selectinload(Fee.invoices)
                .noload(Invoice.payment_intents),
                selectinload(models.AdmissionProfile.fees)
                .selectinload(Fee.invoices)
                .selectinload(Invoice.payments)
                .noload(Payment.transactions),
            )
            .where(models.AdmissionProfile.id == profile_id)
        )
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def search_calculable_profiles(
        self,
        search: str,
        unit_id: Optional[int] = None,
        limit: int = 8,
    ) -> List[models.AdmissionProfile]:
        """Fee-ELIGIBLE admission-profile lookup for the "Tính phí" picker —
        match by HS-code, name, or phone; identity-only (lead eager-loaded).

        Accountant is DENIED ``/api/admissions`` by design, so this finance-
        scoped search gives finance staff just enough to pick a profile to
        calculate a fee for. Returns ONLY profiles a fee can actually be
        calculated for (``is_fee_eligible`` — the endpoint is *calculable*-
        profiles): keeps the result minimal-by-design and does not re-open a
        name/phone enumeration of draft/rejected profiles wider than necessary.
        Unit-scoped via ``lead.unit_id`` (admin/accountant global → ``None``).
        NFC-normalised + LIKE-escaped like the admission search."""
        import re
        import unicodedata

        from app.utils.admission_status import is_fee_eligible

        term = unicodedata.normalize("NFC", (search or "").strip())
        if not term:
            return []

        query = (
            select(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                selectinload(models.AdmissionProfile.lead),
                # is_fee_eligible's multi-NV branch reads ``.choices`` (fails
                # closed if not eager-loaded) → load it so the filter is accurate.
                selectinload(models.AdmissionProfile.choices),
            )
        )

        code = re.match(r"^HS-?0*(\d+)$", term, re.IGNORECASE)
        if code:
            profile_id = int(code.group(1))
            # A profile id is a PostgreSQL int4. The ``\d+`` under
            # ``max_length=100`` can be ~98 digits → out of int32 → asyncpg
            # DataError → 500. No such profile, so return empty (mirrors the
            # fee_repository HS-code guard).
            if profile_id < 1 or profile_id > 2147483647:
                return []
            query = query.where(models.AdmissionProfile.id == profile_id)
        else:
            pattern = f"%{escape_like_pattern(term)}%"
            query = query.where(
                sa.or_(
                    models.Lead.full_name.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
                    models.Lead.phone.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
                )
            )

        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        # Over-fetch then keep only fee-eligible profiles (the eligibility gate
        # is Python-level, not a column). A name/phone search is narrow, so 4×
        # the display cap is plenty to fill ``limit`` after filtering.
        query = query.order_by(models.AdmissionProfile.id.desc()).limit(limit * 4)
        result = await self.db.execute(query)
        profiles = result.scalars().all()
        return [p for p in profiles if is_fee_eligible(p)][:limit]

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

    # ======================================================================
    # MAJOR-CHANGE REPRICE (đổi ngành có khấu trừ phiếu thu + kế toán xác nhận)
    # ======================================================================

    async def _write_discount_lines(
        self,
        fee: Fee,
        applied_discounts: List[Tuple[Optional[int], Decimal, dict]],
    ) -> None:
        """Xoá + ghi lại toàn bộ dòng ``FeeAppliedDiscount`` của fee theo ngành mới.

        Reuse logic ghi từ ``calculate_fee`` (chỗ DUY NHẤT INSERT
        FeeAppliedDiscount). ``recalculate_fee`` KHÔNG ghi lại line items (tính
        ``applied_discounts`` rồi vứt) → drawer/audit lệch; reprice PHẢI tự đồng
        bộ. DELETE trước là BẮT BUỘC: unique ``uq_fee_applied_discount_fee_policy``
        KHÔNG chặn nhiều dòng ``policy_id IS NULL`` (Postgres coi NULL distinct)
        nên không DELETE sẽ chồng dòng qua mỗi lần reprice.
        """
        await self.db.execute(
            sa.delete(FeeAppliedDiscount).where(
                FeeAppliedDiscount.fee_id == fee.id
            )
        )
        await self.db.flush()
        for order, (policy_id, discount_amount, snapshot) in enumerate(
            applied_discounts, 1
        ):
            self.db.add(
                FeeAppliedDiscount(
                    fee_id=fee.id,
                    policy_id=policy_id,
                    discount_amount=discount_amount,
                    calculation_snapshot=snapshot,
                    application_order=order,
                )
            )
        await self.db.flush()

    async def reprice_for_major_change(
        self,
        profile: "models.AdmissionProfile",
        *,
        actor_id: Optional[int] = None,
    ) -> Tuple[Optional[Fee], bool]:
        """Định giá lại HK1 tuition fee sang ngành MỚI, GIỮ ``paid_amount``, ghi
        LUÔN ``invoice.amount`` (CẮT 1 — fee↔invoice không lệch), rồi bật cờ chờ
        kế toán. Entry point DUY NHẤT cho phép ``paid > 0`` (KHÔNG nới
        ``recalculate_fee`` — M10 giữ strict).

        Gọi bởi hook ``_reprice_on_resubmit_if_major_change`` sau khi officer đổi
        nguyện vọng + nộp lại. Caller đã giữ profile lock.

        Returns ``(fee, changed)``: ``changed=False`` khi no-op (drift gate — ngành
        không đổi) hoặc flag OFF; caller KHÔNG dispatch. Raise
        ``BusinessRuleViolation`` cho các ca fail-closed ngoài scope v1 (nhiều/
        không có invoice · giảm tay · post-decision · sinh dư · ngành mới miễn phí
        · còn payment chờ · còn chu kỳ chờ kế toán).
        """
        if not settings.MAJOR_CHANGE_REPRICE_ENABLED:
            return None, False

        semester_no = 1

        # (1) Giá ngành MỚI — READ-ONLY, TRƯỚC khi vào khoá (giảm thời gian giữ
        # khoá; resolve_fee_academic_info + _semester_tuition_amount_for_ai +
        # _calculate_discounts thuần đọc, autoflush=False nên không flush ngầm).
        academic_info = await resolve_fee_academic_info(self.db, profile)
        new_base = await self._semester_tuition_amount_for_ai(
            academic_info.id, semester_no
        )
        policy_ids = list(academic_info.applied_discount_policy_ids or [])
        new_total_discount, applied_discounts = await self._calculate_discounts(
            new_base, policy_ids
        )
        new_final = max(Decimal("0"), new_base - new_total_discount)

        # (2) Tìm active HK1 fee → active invoice CỦA NÓ → assert đúng 1 → khoá
        # invoice TRƯỚC, fee SAU (khớp thứ tự luồng payment/verify — tránh ABBA).
        # Lazy import: enrollment_letter_service import ngược fee_calc (lazy) —
        # giữ lazy 2 chiều để không vòng ở module load.
        from app.services.enrollment_letter_service import (
            _get_active_hk1_tuition_fee,
        )
        target_fee = await _get_active_hk1_tuition_fee(self.db, profile.id)
        if target_fee is None:
            raise BusinessRuleViolation(
                "Hồ sơ không có học phí HK1 đang hoạt động — đổi ngành cần xử "
                "tài chính thủ công."
            )
        active_invoices = list(
            (
                await self.db.execute(
                    select(Invoice).where(
                        Invoice.fee_id == target_fee.id,
                        Invoice.status != InvoiceStatusEnum.cancelled.value,
                    )
                )
            ).scalars().all()
        )
        if len(active_invoices) != 1:
            raise BusinessRuleViolation(
                "Hồ sơ có nhiều/không có đợt học phí HK1 đang hoạt động — đổi "
                "ngành cần xử tài chính thủ công (v1 chỉ hỗ trợ đúng 1 hoá đơn)."
            )
        invoice = await self.invoice_repo.get_for_update(active_invoices[0].id)
        if invoice is None:
            raise BusinessRuleViolation(
                "Không khoá được hoá đơn học phí HK1 để đổi ngành."
            )
        fee = await self.fee_repo.get_for_update(invoice.fee_id)
        if fee is None:
            raise BusinessRuleViolation(
                "Không khoá được khoản phí học phí HK1 để đổi ngành."
            )
        # get_for_update KHÔNG repopulate instance đã ở session → refresh dưới
        # khoá để đọc paid/waived/status/version TƯƠI (mold recompute_fee_from_invoices).
        await self.db.refresh(fee)

        # Re-check khớp dưới khoá.
        if (
            fee.admission_profile_id != profile.id
            or fee.fee_type != FeeTypeEnum.tuition.value
            or fee.semester_no != semester_no
            or fee.status == FeeStatusEnum.cancelled.value
        ):
            raise BusinessRuleViolation(
                "Khoản phí học phí HK1 không hợp lệ để đổi ngành (đã đổi trạng "
                "thái dưới khoá)."
            )

        # (3) Guard fail-closed — dừng ở cái đầu tiên hỏng.
        # (c) Single-cycle: còn chu kỳ đổi ngành chờ kế toán → không mở chu kỳ 2.
        if fee.awaiting_accountant_confirmation:
            raise BusinessRuleViolation(
                "Còn một chu kỳ đổi ngành đang chờ kế toán xác nhận — hãy hoàn "
                "tất chu kỳ đó trước."
            )
        # (g) Drift gate: ngành KHÔNG đổi → no-op (không reprice, không dispatch).
        if (
            fee.resolved_academic_info_id is not None
            and fee.resolved_academic_info_id == academic_info.id
        ):
            return fee, False
        # (a) Giảm học phí THỦ CÔNG → ngoài scope v1 (reprice DELETE/INSERT lại
        # dòng discount theo ngành mới sẽ làm RƠI giảm tay). Query tường minh
        # thay vì fee.applied_discounts (selectin có thể chưa nạp sau get_for_update).
        existing_lines = list(
            (
                await self.db.execute(
                    select(FeeAppliedDiscount).where(
                        FeeAppliedDiscount.fee_id == fee.id
                    )
                )
            ).scalars().all()
        )
        if any(
            (ad.calculation_snapshot or {}).get("source") == "manual_discount"
            for ad in existing_lines
        ):
            raise BusinessRuleViolation(
                "Hồ sơ có giảm học phí thủ công — đổi ngành cần xử tài chính "
                "thủ công."
            )
        # (b) Post-decision: còn nguyện vọng decision=='admitted' → reprice/doc-
        # resolve sẽ bám ngành cũ (reset decision + quota/seat ngoài scope v1).
        choice_decisions = list(
            (
                await self.db.execute(
                    select(models.AdmissionProfileChoice.decision).where(
                        models.AdmissionProfileChoice.admission_profile_id
                        == profile.id
                    )
                )
            ).scalars().all()
        )
        if any(d == "admitted" for d in choice_decisions):
            raise BusinessRuleViolation(
                "Hồ sơ đã có nguyện vọng trúng tuyển — đổi ngành sau công bố "
                "kết quả cần xử lý quota/kết quả thủ công (ngoài phạm vi tự động)."
            )
        target_amount = new_final - fee.waived_amount
        # (e) Ngành mới miễn phí hoàn toàn (final − waived = 0) → CHECK invoice
        # amount>0 sẽ vỡ → chặn, kế toán xử tay (hiếm).
        if target_amount <= 0:
            raise BusinessRuleViolation(
                "Học phí ngành mới sau miễn/giảm bằng 0 — đổi ngành cần xử tài "
                "chính thủ công."
            )
        # (d) Số đã đóng VƯỢT học phí ngành mới (sinh dư) → ngoài scope v1 (không
        # tạo OverpaymentRecord). Kế toán hoàn/khấu trừ thủ công.
        if fee.paid_amount > target_amount:
            raise BusinessRuleViolation(
                "Số học phí đã đóng vượt học phí ngành mới — đổi ngành cần xử "
                "tài chính thủ công (hoàn/khấu trừ phần dư)."
            )
        # (f) Còn payment chờ xác minh / PaymentIntent online còn sống trên hoá
        # đơn đích → reprice trên số tiền sắp đổi. Chặn (mold cancel_fee).
        pending_payment = (
            await self.db.execute(
                sa.select(sa.func.count(Payment.id)).where(
                    Payment.invoice_id == invoice.id,
                    Payment.status == PaymentStatusEnum.pending.value,
                )
            )
        ).scalar() or 0
        if pending_payment:
            raise BusinessRuleViolation(
                "Hoá đơn học phí đang có khoản thanh toán chờ xác minh — hãy "
                "xác minh/từ chối trước khi đổi ngành."
            )
        now = datetime.now(timezone.utc)
        active_intents = (
            await self.db.execute(
                sa.select(sa.func.count(PaymentIntent.id)).where(
                    PaymentIntent.invoice_id == invoice.id,
                    PaymentIntent.status.in_(
                        [
                            PaymentIntentStatusEnum.created.value,
                            PaymentIntentStatusEnum.pending.value,
                        ]
                    ),
                    PaymentIntent.expires_at > now,
                )
            )
        ).scalar() or 0
        if active_intents:
            raise BusinessRuleViolation(
                "Hoá đơn học phí đang có giao dịch online chờ xử lý — hãy đợi "
                "hoàn tất/hết hạn rồi đổi ngành."
            )

        # (4) Mutate fee tại chỗ (bỏ M10). GIỮ paid_amount.
        was_settled = is_hk1_settled_fee(fee)
        old_ai_id = fee.resolved_academic_info_id  # snapshot ngành CŨ TRƯỚC resnapshot
        old_final = fee.final_amount
        fee.base_amount = new_base
        fee.total_discount = new_total_discount
        fee.final_amount = new_final
        fee.version += 1
        fee.notes = (
            f"{fee.notes or ''}\n[{now.isoformat()}] Đổi ngành (major-change "
            f"reprice) bởi user {actor_id}: final {old_final} → {new_final} "
            f"(academic_info {old_ai_id} → {academic_info.id})."
        )

        # (5) Ghi lại dòng discount theo ngành mới.
        await self._write_discount_lines(fee, applied_discounts)

        # (6) CẮT 1 — ghi LUÔN invoice.amount = final − waived (cùng transaction),
        # rồi recompute invoice status từ paid vs amount mới (mold reverse_payment_balances).
        invoice.amount = target_amount
        if (invoice.paid_amount or Decimal("0")) >= invoice.amount:
            invoice.status = InvoiceStatusEnum.paid.value
            invoice.paid_at = invoice.paid_at or now
        elif (invoice.paid_amount or Decimal("0")) > 0:
            invoice.status = InvoiceStatusEnum.partial.value
            invoice.paid_at = None
        else:
            invoice.status = InvoiceStatusEnum.issued.value
            invoice.paid_at = None

        # (7) Bật cờ chờ kế toán (+ snapshot ngành cũ + thời điểm).
        fee.awaiting_accountant_confirmation = True
        fee.major_change_from_academic_info_id = old_ai_id
        fee.major_change_flagged_at = now
        await self.db.flush()

        # (8) Recompute fee status (reuse invoice_service — xử paid→partial khi
        # ngành mới đắt hơn, skip terminal). Nó re-lock fee (re-entrant, cùng
        # transaction) + refresh dưới khoá.
        from app.services.invoice_service import InvoiceService
        await InvoiceService(self.db).recompute_fee_from_invoices(fee.id)

        # (9) Cập nhật resolved_* sang ngành mới (filter/list/drawer/status-counts).
        await resnapshot_fee_academic_info_for_profile(
            self.db, profile.id, profile=profile
        )

        # (10) Supersede giấy báo cũ (phương án c) — chỉ giải phóng slot "hiện
        # hành", bản mới phát lại sau khi kế toán confirm. File PDF cũ giữ nguyên.
        from app.services.enrollment_letter_service import supersede_current_letter
        superseded = await supersede_current_letter(
            self.db,
            profile.id,
            reason="Đổi ngành — giấy báo cũ hết hiệu lực",
        )

        # (11) Lead overlay: CHỈ khi settlement chuyển False→True (ngành rẻ hơn làm
        # paid đủ). Forward-only — KHÔNG dùng force (kéo lùi lead là regression SL1).
        now_settled = is_hk1_settled_fee(fee)
        if now_settled and not was_settled:
            from app.services.lead_admission_sync import sync_lead_tuition_paid
            await sync_lead_tuition_paid(
                self.db,
                profile,
                changed_by_user_id=actor_id,
                reason="Đổi ngành: học phí ngành mới đã đủ (settled)",
            )

        # (12) Audit + cảnh báo cơ sở hoa hồng có thể đổi (commission đọc
        # fee.final_amount; prod hiện 0 policy nhưng ghi để lần bật hoa hồng thấy).
        from app.services import audit_service
        await audit_service.log_audit(
            self.db,
            entity_type="Fee",
            entity_id=fee.id,
            action="major_change_repriced",
            actor_user_id=actor_id,
            field_name="final_amount",
            old_value=str(old_final),
            new_value=str(new_final),
            reason=(
                f"Đổi ngành academic_info {old_ai_id} → {academic_info.id}; "
                f"giấy báo superseded={superseded}; chờ kế toán xác nhận. "
                f"(Lưu ý: cơ sở hoa hồng có thể đổi theo final_amount.)"
            ),
            source="api",
        )
        log.info(
            "fee_major_change_repriced",
            fee_id=fee.id,
            profile_id=profile.id,
            invoice_id=invoice.id,
            old_final=str(old_final),
            new_final=str(new_final),
            old_academic_info_id=old_ai_id,
            new_academic_info_id=academic_info.id,
            superseded_letters=superseded,
            settled_transition=(now_settled and not was_settled),
            actor_id=actor_id,
        )
        return fee, True

    async def confirm_major_change(
        self,
        fee_id: int,
        *,
        actor_id: Optional[int] = None,
        unit_id: Optional[int] = None,
    ) -> Tuple[Fee, Optional[Callable]]:
        """Kế toán xác nhận reprice đổi ngành → clear cờ, báo officer tiếp tục.

        CẮT 1 — reprice đã ghi ``invoice.amount`` đúng ngay từ đầu, nên confirm
        KHÔNG reconcile tiền: chỉ ASSERT bất biến ``Σ(invoice active) == final −
        waived`` như lưới phòng thủ (lệch → raise, KHÔNG tự sửa — kế toán rà tay),
        clear ``awaiting_accountant_confirmation``, audit, dispatch báo officer.

        Lock invoice → fee (khớp luồng tiền, tránh ABBA). Require cờ đang bật.
        Idempotent: gọi lại khi cờ đã clear → ConflictError rõ nghĩa.
        """
        active_invoices = list(
            (
                await self.db.execute(
                    select(Invoice)
                    .join(Fee, Fee.id == Invoice.fee_id)
                    .where(
                        Invoice.fee_id == fee_id,
                        Invoice.status != InvoiceStatusEnum.cancelled.value,
                    )
                )
            ).scalars().all()
        )
        # reprice đảm bảo đúng 1 invoice active; >1 không thể tới đây.
        if len(active_invoices) != 1:
            raise BusinessRuleViolation(
                "Khoản phí không có đúng 1 hoá đơn học phí đang hoạt động — "
                "kế toán cần rà thủ công."
            )
        invoice = await self.invoice_repo.get_for_update(
            active_invoices[0].id, unit_id
        )
        if invoice is None:
            raise ResourceNotFoundError("Fee not found")
        fee = await self.fee_repo.get_for_update(invoice.fee_id, unit_id)
        if fee is None or fee.id != fee_id:
            raise ResourceNotFoundError("Fee not found")
        await self.db.refresh(fee)

        if not fee.awaiting_accountant_confirmation:
            raise ConflictError(
                "Khoản phí này không đang chờ xác nhận đổi ngành (có thể đã "
                "được xác nhận trước đó)."
            )

        target = fee.final_amount - fee.waived_amount
        if target <= 0:
            raise BusinessRuleViolation(
                "Học phí sau miễn/giảm bằng 0 — kế toán cần xử tài chính thủ "
                "công (không thể ghi hoá đơn = 0)."
            )
        # Bất biến phòng thủ (reprice đã ghi đúng): 1 invoice active = final−waived.
        if invoice.amount != target:
            raise BusinessRuleViolation(
                f"Bất biến hoá đơn lệch (hoá đơn {invoice.amount} ≠ học phí "
                f"phải thu {target}) — kế toán cần rà thủ công trước khi xác nhận."
            )

        # Clear cờ (GIỮ major_change_from_academic_info_id + flagged_at làm lịch sử).
        fee.awaiting_accountant_confirmation = False
        fee.version += 1
        fee.notes = (
            f"{fee.notes or ''}\n[{datetime.now(timezone.utc).isoformat()}] "
            f"Kế toán (user {actor_id}) xác nhận đổi ngành."
        )
        await self.db.flush()

        # Recompute fee status phòng thủ (thường không đổi — invoice.amount đã đúng).
        from app.services.invoice_service import InvoiceService
        await InvoiceService(self.db).recompute_fee_from_invoices(fee.id)

        # Load profile + lead cho dispatch (IDOR-scoped). Tên ngành mới đọc tường
        # minh (fee.resolved_major lazy=raise — KHÔNG chạm trực tiếp).
        profile = await self._get_profile(fee.admission_profile_id, unit_id)
        new_major_name = None
        if fee.resolved_major_id is not None:
            new_major_name = (
                await self.db.execute(
                    select(models.MajorProgram.name).where(
                        models.MajorProgram.id == fee.resolved_major_id
                    )
                )
            ).scalar_one_or_none()

        from app.services import audit_service
        await audit_service.log_audit(
            self.db,
            entity_type="Fee",
            entity_id=fee.id,
            action="major_change_confirmed",
            actor_user_id=actor_id,
            field_name="awaiting_accountant_confirmation",
            old_value="true",
            new_value="false",
            reason=f"Kế toán xác nhận đổi ngành (ngành mới: {new_major_name}).",
            source="api",
        )

        # Dispatch báo officer phụ trách tiếp tục (xuất giấy…).
        _lead = getattr(profile, "lead", None) if profile is not None else None
        officer_id = getattr(_lead, "assigned_officer_id", None) if _lead else None
        user_ids = [officer_id] if officer_id else []
        payload = {
            "fee_id": fee.id,
            "invoice_id": invoice.id,
            "admission_profile_id": fee.admission_profile_id,
            "lead_id": getattr(_lead, "id", None) if _lead else None,
            "unit_id": getattr(_lead, "unit_id", None) if _lead else None,
            "new_major_name": new_major_name,
            "profile_code": f"HS-{fee.admission_profile_id}",
            "actor_id": actor_id,
            "user_ids": user_ids,
        }
        from app.services.notification_dispatcher import (
            dispatch,
            rooms_for_finance_review,
        )
        from app.core.events import SystemEvents
        _rooms = rooms_for_finance_review(profile, user_ids)
        _notif_ids, notif_cb = await dispatch(
            self.db,
            event=SystemEvents.MAJOR_CHANGE_CONFIRMED,
            payload=payload,
            dedupe_key=f"fee:{fee.id}:major_change_confirmed",
            rooms=_rooms,
        )

        log.info(
            "fee_major_change_confirmed",
            fee_id=fee.id,
            profile_id=fee.admission_profile_id,
            invoice_id=invoice.id,
            actor_id=actor_id,
            officer_notified=bool(user_ids),
        )

        async def post_commit():
            if notif_cb:
                await notif_cb()

        return fee, post_commit


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
    affected_profile_ids: set = set()
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

        # ≥2 HĐ draft KHÔNG khớp kế hoạch trả góp (không có plan, hoặc số HĐ ≠ số
        # đợt) → KHÔNG rewrite an toàn bằng zip vị trí được → SKIP fee này TRƯỚC khi
        # đổi base (tránh fee↔invoice lệch im lặng — cùng invariant recalculate_fee
        # #1). Tới đây mọi HĐ đều draft (non-draft đã skip ở trên).
        draft_count = sum(1 for inv in fee.invoices if inv.status == "draft")
        if draft_count >= 2 and (
            fee.installment_plan is None
            or draft_count != fee.installment_plan.installment_count
        ):
            log.info(
                "fee_recalc_skipped_unmappable_invoices",
                fee_id=fee.id,
                semester_no=fee.semester_no,
                draft_count=draft_count,
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
            # Sort CẢ HAI theo installment_no để ghép ĐÚNG đợt (schedule JSONB có
            # thể lưu lệch thứ tự, remainder rơi vào phần tử cuối list).
            for inv, sched in zip(
                sorted(fee.invoices, key=lambda x: x.installment_no),
                sorted(new_schedule, key=lambda s: s["installment_no"]),
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
        affected_profile_ids.add(fee.admission_profile_id)
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
        # Recalc path không gọi resolver → refresh snapshot ngành cho từng hồ sơ
        # bị ảnh hưởng (dùng resolver đúng admitted-choice; fail-soft, idempotent).
        for pid in affected_profile_ids:
            await resnapshot_fee_academic_info_for_profile(db, pid)

    return recalc_count
