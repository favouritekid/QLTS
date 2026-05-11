# app/services/admission_choice_service.py
"""Service layer cho Phase 3 multi-NV choice operations.

Per plan v0.6 LOCKED:

- **G7 v0.6 add_choice guard**: 4-precheck branches
  1. profile.uses_choice_engine == True (legacy block)
  2. round.allow_multi_nv (Q-P3-02 per-round flag)
  3. count_choices < system_config.max_choices_per_profile (Q-P3-01)
  4. profile.status IN (draft, revision_requested) — Wave B retroactive
     rule per P1 fix #5 v2.12

- **P1 fix #4 v1.3 invariant**: `path_subject_group_config.admission_path_id
  == admission_path_id` (service-layer enforce — DB không có FK composite)

Engine xét tuyển + waitlist promote endpoint defer PR-3C.
"""
from typing import Any, Callable, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AdmissionProfile,
    AdmissionProfileChoice,
    OfferingAdmissionRound,
)
from app.repositories.admission_profile_choice_repository import (
    AdmissionProfileChoiceRepository,
)
from app.repositories.admission_path_repository import AdmissionPathRepository
from app.services.system_config_service import SystemConfigService
from app.utils.exceptions import BusinessRuleViolation, ResourceNotFoundError


# Status whitelist cho add_choice retroactive (P1 fix #5 v2.12)
ADD_CHOICE_ALLOWED_STATUSES = ("draft", "revision_requested")


async def _noop_callback() -> None:
    """Default no-op post-commit callback."""
    return None


class AdmissionChoiceService:
    """Service layer cho AdmissionProfileChoice operations.

    Mỗi mutation method returns ``(result, post_commit_callback)``
    per Backend CLAUDE.md V3.0 contract. Router commits + awaits
    callback (notification dispatch defer PR-3C).
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.choice_repo = AdmissionProfileChoiceRepository(db)
        self.path_repo = AdmissionPathRepository(db)
        self.sysconfig = SystemConfigService(db)

    async def add_choice(
        self,
        *,
        profile: AdmissionProfile,
        admission_path_id: int,
        path_subject_group_config_id: int,
        display_order: int,
    ) -> Tuple[AdmissionProfileChoice, Callable]:
        """G7 v0.6 add_choice guard với 4 prechecks.

        Args:
            profile: pre-loaded AdmissionProfile (caller load via
                get_admission_for_user/manager IDOR gate).
            admission_path_id: path FK (must be active + cùng year với
                profile.academic_year).
            path_subject_group_config_id: tổ hợp môn config.
            display_order: priority 1-10.

        Returns:
            (created_choice, post_commit_callback)

        Raises:
            BusinessRuleViolation: violation any precheck
            ResourceNotFoundError: path/config not found
        """
        # ============================================================
        # Precheck 1: uses_choice_engine flag — Phase 3 gate
        # ============================================================
        if not profile.uses_choice_engine:
            raise BusinessRuleViolation(
                "Hồ sơ này chạy quy trình cũ (single-NV), không hỗ trợ "
                "thêm nguyện vọng. Liên hệ admin để migrate sang Phase 3."
            )

        # ============================================================
        # Precheck 4 (early): status whitelist Wave B retroactive
        # P1 fix #5 v2.12 — add NV retroactive cho phép CHỈ KHI
        # status IN (draft, revision_requested)
        # ============================================================
        if profile.status not in ADD_CHOICE_ALLOWED_STATUSES:
            raise BusinessRuleViolation(
                f"Không thể thêm nguyện vọng khi hồ sơ ở trạng thái "
                f"'{profile.status}'. Chỉ cho phép khi 'draft' hoặc "
                f"'revision_requested'."
            )

        # ============================================================
        # Precheck 2: Round allow_multi_nv flag (Q-P3-02 per-round)
        # ============================================================
        round_obj = await self.choice_repo.get_round_by_path_id(
            admission_path_id
        )
        if round_obj is None:
            raise ResourceNotFoundError(
                f"Path {admission_path_id} không tồn tại hoặc đã archive."
            )

        # First choice luôn cho phép (Wave A single-NV vẫn ship 1 choice
        # via this path). Chỉ block ADD-NV-2-trở-lên khi flag tắt.
        existing_count = await self.choice_repo.count_choices_by_profile(
            profile.id
        )
        if existing_count >= 1 and not round_obj.allow_multi_nv:
            raise BusinessRuleViolation(
                f"Đợt {round_obj.round_code} ({round_obj.academic_year}) "
                f"chỉ cho phép 1 nguyện vọng/hồ sơ. Liên hệ admin để "
                f"bật multi-NV."
            )

        # ============================================================
        # Precheck 3: max_choices_per_profile (Q-P3-01 system_config)
        # ============================================================
        max_choices_raw = await self.sysconfig.get_value(
            "max_choices_per_profile", default=5
        )
        # system_config.value là JSONB — int hoặc str cần coerce
        try:
            max_choices = int(max_choices_raw) if max_choices_raw else 5
        except (TypeError, ValueError):
            max_choices = 5

        if existing_count >= max_choices:
            raise BusinessRuleViolation(
                f"Đã đạt tối đa {max_choices} nguyện vọng/hồ sơ. "
                f"Xoá NV không cần trước khi thêm."
            )

        # ============================================================
        # Invariant (P1 fix #4 v1.3): config thuộc path
        # ============================================================
        path = await self.path_repo.get_by_id(admission_path_id)
        if path is None:
            raise ResourceNotFoundError(
                f"Path {admission_path_id} không tồn tại."
            )

        # Verify config.admission_path_id == admission_path_id
        # (DB không có composite FK, service enforce)
        from app.models import PathSubjectGroupConfig

        config = await self.db.get(
            PathSubjectGroupConfig, path_subject_group_config_id
        )
        if config is None:
            raise ResourceNotFoundError(
                f"Path subject group config "
                f"{path_subject_group_config_id} không tồn tại."
            )
        if config.admission_path_id != admission_path_id:
            raise BusinessRuleViolation(
                "Tổ hợp môn không thuộc đường tuyển sinh đã chọn "
                "(invariant ADM P1 fix #4). Chọn lại tổ hợp đúng path."
            )

        # ============================================================
        # All prechecks pass — create choice
        # ============================================================
        choice = await self.choice_repo.create(
            admission_profile_id=profile.id,
            admission_path_id=admission_path_id,
            path_subject_group_config_id=path_subject_group_config_id,
            display_order=display_order,
        )

        return choice, _noop_callback

    async def list_choices(
        self, profile_id: int, *, eager: bool = True
    ) -> list[AdmissionProfileChoice]:
        """Read-only list, IDOR check responsibility ở caller (router → deps)."""
        return await self.choice_repo.list_by_profile(
            profile_id, eager=eager
        )

    async def get_choice(
        self, choice_id: int, *, eager: bool = True
    ) -> Optional[AdmissionProfileChoice]:
        """Read-only get với optional eager-load cho UI render."""
        if eager:
            return await self.choice_repo.get_by_id_with_relations(choice_id)
        return await self.choice_repo.get_by_id(choice_id)
