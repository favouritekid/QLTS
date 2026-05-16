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

**BONUS-35 v0.6 route convention** (apply when defining routers PR-3D-B/3E):
Per memory `lead-keymatch4-collision-followup` lesson, Phase 3 multi-segment
routes phải dùng regex constraint trong FastAPI path:
- `/api/v2/admissions/{id:[0-9]+}/choices` (NOT `{id}` alone)
- `/api/v2/admissions/{id:[0-9]+}/choices/{choice_id:[0-9]+}/scores`
- `/api/v2/admissions/{id:[0-9]+}/choices/{choice_id:[0-9]+}/promote`
- `/api/v2/admin/admission-backfill-exceptions/{id:[0-9]+}/resolve`
- `/api/v2/admissions/magic-link/{action}/{token}` (action constrained enum
  qua Pydantic, NOT path regex)

Tighten ngăn typosquat `/api/v2/admissions/abc/choices` đụng route khác.
"""
from typing import Any, Callable, Optional, Tuple  # noqa: F401

from sqlalchemy.exc import IntegrityError
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
from app.services.activity_service import log_activity
from app.services.system_config_service import SystemConfigService
from app.utils.exceptions import (
    BusinessRuleViolation,
    DuplicateResourceError,
    ResourceNotFoundError,
)


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
        # Wrap IntegrityError → DuplicateResourceError (E2E #5 fix
        # 2026-05-15). UNIQUE constraints fail mode previously bubbled
        # raw IntegrityError → 500. UNIQUE candidates:
        #   - uq_admission_profile_choice (profile_id, admission_path_id,
        #     path_subject_group_config_id) — duplicate ngành+tổ hợp
        #   - uq_admission_profile_choice_display_order (profile_id,
        #     display_order) — duplicate priority slot
        # MUST rollback BEFORE raise — otherwise next statement on the
        # session deadlocks (per `lead_service.py` pattern).
        try:
            choice = await self.choice_repo.create(
                admission_profile_id=profile.id,
                admission_path_id=admission_path_id,
                path_subject_group_config_id=path_subject_group_config_id,
                display_order=display_order,
            )
        except IntegrityError as exc:
            await self.db.rollback()
            raise DuplicateResourceError(
                "Nguyện vọng trùng lặp — đã tồn tại NV cùng (ngành, tổ hợp) "
                "hoặc cùng thứ tự ưu tiên."
            ) from exc

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

    # ============================================================
    # PR-3D-B BE-1 — Choice mutation helpers (CRUD endpoints)
    # ============================================================

    async def create_choice_with_scores(
        self,
        *,
        profile: AdmissionProfile,
        admission_path_id: int,
        path_subject_group_config_id: int,
        display_order: int,
        scores: list,
    ) -> Tuple[AdmissionProfileChoice, Callable]:
        """Atomic create choice + N score rows with snapshot resolution.

        Wraps ``add_choice`` (4 prechecks per G7 v0.6) then snapshots
        ``Subject.max_score`` / ``Subject.min_possible_score`` + per-mapping
        ``SubjectGroupSubject.weight`` into ``ProfileChoiceScore.*_snapshot``
        columns. Snapshot pattern freezes the values at write time so a later
        admin edit on Subject/Mapping does NOT retroactively change candidate
        results.

        Args:
            profile: pre-loaded profile (caller IDOR-gated).
            admission_path_id: FK to AdmissionPath.
            path_subject_group_config_id: FK to PathSubjectGroupConfig.
            display_order: priority 1-10.
            scores: list of ``ChoiceScoreInput`` (subject_id + score). Each
                subject_id MUST belong to the chosen subject_group via
                ``SubjectGroupSubject`` mapping — else BusinessRuleViolation.

        Returns:
            (created_choice, post_commit_callback)

        Raises:
            BusinessRuleViolation: precheck or subject-not-in-group violation
            ResourceNotFoundError: path / config / subject missing
        """
        # Step 1: create the choice (4 G7 prechecks inside)
        choice, _cb = await self.add_choice(
            profile=profile,
            admission_path_id=admission_path_id,
            path_subject_group_config_id=path_subject_group_config_id,
            display_order=display_order,
        )

        # Step 2: snapshot scores (only if any provided)
        if scores:
            await self._snapshot_and_store_scores(
                choice=choice,
                path_subject_group_config_id=path_subject_group_config_id,
                scores=scores,
            )

        return choice, _noop_callback

    async def delete_choice(
        self,
        *,
        profile: AdmissionProfile,
        choice: AdmissionProfileChoice,
        actor_id: Optional[int] = None,
        reason: Optional[str] = None,
    ) -> Tuple[dict, Callable]:
        """Delete a choice + cascade scores via FK ON DELETE CASCADE.

        **Prechecks**:
        - profile.uses_choice_engine == True
        - profile.status IN (draft, revision_requested) — retroactive scope

        Note: scope is INTENTIONALLY tight. Once a profile transitions to
        ``submitted`` or beyond, choices are immutable per state machine —
        admin uses T17 rollback to allow editing again.

        **Audit (PR-CO-3, FU #114)**: snapshot the choice + dispatch a
        ``log_activity`` row BEFORE the DB DELETE so the row is captured
        even if the FK cascade subsequently nukes ``profile_choice_score``
        children. Without an audit trail the narrow status whitelist
        (draft / revision_requested) leaves no forensic record for a
        "where did NV 3 go?" complaint months later.
        """
        self._assert_choice_editable(profile, action="xoá nguyện vọng")

        # Snapshot the row + score children BEFORE the cascade delete so
        # the audit log carries the full forensic state. Resolve the
        # scores via the repository to avoid relying on a lazy attribute.
        score_rows = await self.choice_repo.list_scores_by_choice(choice.id)
        snapshot = {
            "choice_id": choice.id,
            "profile_id": choice.admission_profile_id,
            "admission_path_id": choice.admission_path_id,
            "path_subject_group_config_id": choice.path_subject_group_config_id,
            "display_order": choice.display_order,
            "decision": choice.decision,
            "scores": [
                {
                    "subject_id": s.subject_id,
                    "score": str(s.score) if s.score is not None else None,
                }
                for s in score_rows
            ],
        }

        deleted = await self.choice_repo.delete(choice.id)
        if not deleted:
            raise ResourceNotFoundError(
                f"Nguyện vọng {choice.id} không tồn tại hoặc đã xoá."
            )

        # Audit AFTER the DELETE succeeds — both the snapshot and the
        # activity row land under the same transaction, so the router
        # commit makes them visible atomically. Reason is stamped into
        # the description so audit-log readers see it without unpacking
        # the JSONB changes payload.
        description = (
            f"Xoá NV {snapshot['display_order']} (path_id="
            f"{snapshot['admission_path_id']})"
        )
        if reason:
            description = f"{description} — Lý do: {reason}"

        await log_activity(
            self.db,
            action="delete_choice",
            resource_type="admission_profile_choice",
            actor_id=actor_id,
            resource_id=choice.id,
            description=description,
            changes={"before": snapshot, "reason": reason},
        )

        return ({"choice_id": choice.id, "profile_id": profile.id},
                _noop_callback)

    async def update_choice_display_order(
        self,
        *,
        profile: AdmissionProfile,
        choice: AdmissionProfileChoice,
        new_display_order: int,
    ) -> Tuple[AdmissionProfileChoice, Callable]:
        """Update display_order on a single choice.

        Caller responsible for resolving cycle conflicts when reordering >1
        rows (FE typically sends one PATCH per row in deferred batch — DB
        UNIQUE(profile_id, display_order) is the safety net).

        **Prechecks**:
        - profile.uses_choice_engine == True
        - profile.status IN (draft, revision_requested)
        - new_display_order != current (no-op short-circuit)
        - new_display_order ≤ system_config.max_choices_per_profile (Q-P3-01
          allows ≤10 by DB CHECK, but service narrows per system_config)
        """
        self._assert_choice_editable(profile, action="đổi thứ tự nguyện vọng")

        if new_display_order == choice.display_order:
            return choice, _noop_callback

        max_choices_raw = await self.sysconfig.get_value(
            "max_choices_per_profile", default=5
        )
        try:
            max_choices = int(max_choices_raw) if max_choices_raw else 5
        except (TypeError, ValueError):
            max_choices = 5

        if new_display_order > max_choices:
            raise BusinessRuleViolation(
                f"Thứ tự {new_display_order} vượt giới hạn "
                f"({max_choices} nguyện vọng/hồ sơ)."
            )

        updated = await self.choice_repo.update_display_order(
            choice.id, new_display_order=new_display_order
        )
        if updated is None:
            raise ResourceNotFoundError(
                f"Nguyện vọng {choice.id} không tồn tại."
            )

        return updated, _noop_callback

    async def replace_choice_scores(
        self,
        *,
        profile: AdmissionProfile,
        choice: AdmissionProfileChoice,
        scores: list,
    ) -> Tuple[AdmissionProfileChoice, Callable]:
        """Replace all scores on a choice (idempotent set semantics).

        Clears existing ``ProfileChoiceScore`` rows for the choice then
        re-creates them with fresh snapshots — same as create_choice_with_scores
        but on existing choice. Each input subject_id MUST belong to the
        choice's subject_group via SubjectGroupSubject mapping.

        **Prechecks**:
        - profile.uses_choice_engine == True
        - profile.status IN (draft, revision_requested)

        Note: empty scores list is a valid "clear all" intent — DB UNIQUE
        constraint allows zero rows per choice.
        """
        self._assert_choice_editable(profile, action="cập nhật điểm nguyện vọng")

        # Clear existing scores via direct delete (FK CASCADE would only fire
        # on choice delete, not score replace — use bulk delete here).
        # synchronize_session='fetch' so the session-level identity map drops
        # stale ProfileChoiceScore rows; otherwise the eager-load on the
        # subsequent get_choice() can return cached empty scores.
        from sqlalchemy import delete as sa_delete
        from app.models import ProfileChoiceScore

        await self.db.execute(
            sa_delete(ProfileChoiceScore).where(
                ProfileChoiceScore.admission_profile_choice_id == choice.id
            ).execution_options(synchronize_session="fetch")
        )
        await self.db.flush()

        if scores:
            await self._snapshot_and_store_scores(
                choice=choice,
                path_subject_group_config_id=choice.path_subject_group_config_id,
                scores=scores,
            )

        # Expire choice's loaded scores collection so the subsequent eager
        # re-fetch in router sees the new rows (identity-map cache safety).
        self.db.expire(choice, attribute_names=["scores"])

        return choice, _noop_callback

    # ============================================================
    # Internal helpers
    # ============================================================

    def _assert_choice_editable(
        self, profile: AdmissionProfile, *, action: str
    ) -> None:
        """Shared precheck for delete/reorder/score-replace.

        Reuses ADD_CHOICE_ALLOWED_STATUSES — same retroactive window.
        """
        if not profile.uses_choice_engine:
            raise BusinessRuleViolation(
                f"Hồ sơ này chạy quy trình cũ (single-NV), không thể {action}."
            )
        if profile.status not in ADD_CHOICE_ALLOWED_STATUSES:
            raise BusinessRuleViolation(
                f"Không thể {action} khi hồ sơ ở trạng thái "
                f"'{profile.status}'. Chỉ cho phép khi 'draft' hoặc "
                f"'revision_requested'."
            )

    async def _snapshot_and_store_scores(
        self,
        *,
        choice: AdmissionProfileChoice,
        path_subject_group_config_id: int,
        scores: list,
    ) -> None:
        """Resolve snapshot values + insert ProfileChoiceScore rows.

        For each input ``ChoiceScoreInput``:
        - max_score_snapshot ← Subject.max_score (NOT NULL on column; fallback
          to 10 for ACADEMIC_SUBJECT kind nếu NULL trên Subject)
        - min_possible_score_snapshot ← Subject.min_possible_score (nullable)
        - weight_snapshot ← SubjectGroupSubject.weight WHERE
          subject_group_id == config.subject_group_id AND subject_id matches

        Raises BusinessRuleViolation nếu subject_id không thuộc nhóm môn của
        config (anti-tampering — FE cannot inject foreign subject).
        """
        from sqlalchemy import select as sa_select
        from app.models import (
            PathSubjectGroupConfig,
            Subject,
            SubjectGroupSubject,
        )

        # Load the config to know which subject_group is in play
        config = await self.db.get(
            PathSubjectGroupConfig, path_subject_group_config_id
        )
        if config is None:
            raise ResourceNotFoundError(
                f"Tổ hợp môn {path_subject_group_config_id} không tồn tại."
            )

        # Pre-load valid subject_ids in this subject_group + weights map
        mapping_result = await self.db.execute(
            sa_select(SubjectGroupSubject).where(
                SubjectGroupSubject.subject_group_id == config.subject_group_id
            )
        )
        mappings = list(mapping_result.scalars().all())
        weight_by_subject: dict[int, Any] = {
            m.subject_id: m.weight for m in mappings
        }
        valid_subject_ids = set(weight_by_subject.keys())

        # Pre-load Subject rows for max/min snapshots
        input_subject_ids = [s.subject_id for s in scores]
        subject_result = await self.db.execute(
            sa_select(Subject).where(Subject.id.in_(input_subject_ids))
        )
        subjects_by_id: dict[int, Subject] = {
            sb.id: sb for sb in subject_result.scalars().all()
        }

        for input_score in scores:
            sid = input_score.subject_id
            if sid not in valid_subject_ids:
                raise BusinessRuleViolation(
                    f"Môn {sid} không thuộc tổ hợp của nguyện vọng này. "
                    f"Chọn lại môn đúng tổ hợp."
                )
            subj = subjects_by_id.get(sid)
            if subj is None:
                raise ResourceNotFoundError(
                    f"Môn {sid} không tồn tại."
                )

            # max_score fallback to 10 for ACADEMIC_SUBJECT per Subject column comment
            max_snap = subj.max_score
            if max_snap is None:
                max_snap = 10
            min_snap = subj.min_possible_score  # nullable
            wt_snap = weight_by_subject.get(sid, 1)

            await self.choice_repo.add_score(
                admission_profile_choice_id=choice.id,
                subject_id=sid,
                score=input_score.score,
                max_score_snapshot=max_snap,
                weight_snapshot=wt_snap,
                min_possible_score_snapshot=min_snap,
            )
