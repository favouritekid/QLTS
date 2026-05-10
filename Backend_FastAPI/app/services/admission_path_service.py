# app/services/admission_path_service.py
"""
Admission Path Service.

Business logic for AdmissionPath management.

MASTER_ARCHITECTURE.md Compliance:
- No HTTPException imports
- Returns (result, callback) tuple
- Uses Repository for DB access
- db.flush() only, no commit
"""

from datetime import datetime, timezone
from typing import Callable, Coroutine, List, Optional, Tuple, Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import UserRole
from app.models.admission_config import (
    AdmissionPath,
    AdmissionCriteria,
    CriteriaSubjectGroup,
    DocumentGroup,
    DocumentGroupItem,
)
from app.models.user import User
from app.repositories.admission_path_repository import AdmissionPathRepository
from app.schemas.admission_path import (
    AdmissionPathCreate,
    AdmissionPathUpdate,
    AdmissionCriteriaCreate,
    AdmissionPathDocumentUpsert,
    ResolvedDocumentResponse,
)
from app.utils.exceptions import (
    ResourceNotFoundError,
    DuplicateResourceError,
    BusinessRuleViolation,
    PermissionDeniedError,
)

log = structlog.get_logger(__name__)


# Type alias for post-commit callback
PostCommitCallback = Callable[[], Coroutine[Any, Any, None]]


async def _noop_callback() -> None:
    """No-op callback for operations without side effects."""
    pass


def _check_lifecycle_guard(path: AdmissionPath, user: User) -> None:
    """ADM-005: Lifecycle guard shared by ``update_path``,
    ``upsert_criteria`` and ``upsert_documents``.

    Per Q2 product decision (b — basic guard, durable audit deferred to
    Wave 2):

    - Archived paths cannot be modified at all.
    - Manager can only modify paths in ``draft`` status. ``Admin
      approves = activate``, so once a path is past draft only admin may
      edit its criteria / documents / fields.
    - Admin can edit any non-archived path.

    Raises ``BusinessRuleViolation`` when the caller fails the guard so
    routers can map to 400 / domain copy.
    """
    if path.status == "archived":
        raise BusinessRuleViolation("Cannot update archived path")
    if user.role != UserRole.ADMIN and path.status != "draft":
        raise BusinessRuleViolation(
            f"Manager can only update paths in 'draft' status. "
            f"Current status: '{path.status}'. Contact Admin to modify."
        )


class AdmissionPathService:
    """
    Service for AdmissionPath business logic.

    MASTER_ARCHITECTURE.md Rules:
    - No HTTPException
    - Returns (result, callback)
    - Domain exceptions only
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AdmissionPathRepository(db)

    # =========================================================================
    # QUERY OPERATIONS
    # =========================================================================

    async def get_path_by_id(
        self, path_id: int
    ) -> Tuple[AdmissionPath, PostCommitCallback]:
        """
        Get a single path by ID with relationships.

        Raises:
            ResourceNotFoundError: If path not found
        """
        path = await self.repo.get_by_id_with_relations(path_id)
        if not path:
            raise ResourceNotFoundError(f"AdmissionPath {path_id} not found")

        return path, _noop_callback

    async def list_paths_by_academic_info(
        self, academic_info_id: int
    ) -> Tuple[List[AdmissionPath], PostCommitCallback]:
        """
        List all paths for an academic info (offering + year).
        """
        paths = await self.repo.get_paths_by_academic_info(academic_info_id)
        return paths, _noop_callback

    async def get_distinct_years(self) -> Tuple[List[int], PostCommitCallback]:
        """
        Get all distinct academic years.
        """
        years = await self.repo.get_distinct_years()
        return years, _noop_callback

    # =========================================================================
    # MUTATION OPERATIONS
    # =========================================================================

    async def create_path(
        self, data: AdmissionPathCreate, user: User
    ) -> Tuple[AdmissionPath, PostCommitCallback]:
        """
        Create a new AdmissionPath.

        Phase 2 v8.2 PR-2B v2: auto-resolve DOT_1 shim. If
        ``data.admission_round_id`` is None, lookup DOT_1 của
        academic_info's academic_year (year-level Option A). Validate
        Tier 1 chain trên admit_quota change.

        Raises:
            DuplicateResourceError: If path already exists for offering + method
            BusinessRuleViolation: Tier 1 chain violated, Tier 2 invariant violated, or DOT_1 not found
        """
        # Phase 2 v8.2 PR-2B v2 — auto-resolve admission_round_id.
        # Note: PR-2C v2 sẽ swap UNIQUE thành 3-col (round, acad, method).
        # Phase 2 transition: vẫn dùng 2-col duplicate check tại đây
        # (PR-2C v2 sẽ relax sang 3-col).
        admission_round_id = data.admission_round_id
        if admission_round_id is None:
            from app.models.offering_academic_info import OfferingAcademicInfo
            from app.repositories.admission_round_repository import (
                AdmissionRoundRepository,
            )
            academic_info = await self.db.get(
                OfferingAcademicInfo, data.academic_info_id
            )
            if academic_info is None:
                raise ResourceNotFoundError(
                    f"OfferingAcademicInfo {data.academic_info_id} not found"
                )
            round_repo = AdmissionRoundRepository(self.db)
            default_round = await round_repo.get_default_dot1(
                academic_info.academic_year
            )
            if default_round is None:
                raise BusinessRuleViolation(
                    f"DOT_1 round không tồn tại cho năm "
                    f"{academic_info.academic_year}; admin tạo round trước "
                    f"hoặc truyền explicit admission_round_id."
                )
            admission_round_id = default_round.id
            log.info(
                "admission_path_create_auto_resolved_round",
                academic_info_id=data.academic_info_id,
                academic_year=academic_info.academic_year,
                resolved_round_id=admission_round_id,
                auto_resolved=True,
            )

        # Tier 1+2 chain validation — admit_quota Tier 1 chain check
        # if admit_quota provided; Tier 2 invariant check both fields.
        if data.admit_quota is not None or data.round_quota is not None:
            from app.services.admission_quota_service import (
                AdmissionQuotaService,
            )
            quota_service = AdmissionQuotaService(self.db)
            await quota_service.validate_tier2_path_invariant(
                admit_quota=data.admit_quota,
                round_quota=data.round_quota,
            )
            if data.admit_quota is not None:
                await quota_service.validate_tier1_chain_on_path_quota_change(
                    academic_info_id=data.academic_info_id,
                    delta_admit_quota=data.admit_quota,
                )

        # Check for duplicate
        existing = await self.repo.get_path_by_offering_and_method(
            data.academic_info_id, data.admission_method_id
        )
        if existing:
            raise DuplicateResourceError(
                f"AdmissionPath already exists for academic_info={data.academic_info_id}, "
                f"method={data.admission_method_id}"
            )

        # Governance guard: 4 fields are admin-only on create — the
        # ``minor_correction_allowed_fields`` allowlist (decides which
        # fields officer can post-edit on approved profiles) plus the
        # phase1_03 trio (``applicable_to`` / ``method_quota`` /
        # ``bonus_rule_override``) which together gate audience filter,
        # method-level quota cap, and bonus engine override. Manager
        # creating a draft path gets default values (empty / null) for
        # all four regardless of what they submit. FE already hides /
        # disables these sections for non-admins; this is the belt-
        # and-braces server side. Reject (not silent-drop) so the FE
        # form / API caller surfaces the failure rather than the admin
        # thinking the value was saved.
        if user.role != UserRole.ADMIN:
            forbidden_keys: list[str] = []
            if data.minor_correction_allowed_fields:
                forbidden_keys.append("minor_correction_allowed_fields")
            if data.applicable_to is not None:
                forbidden_keys.append("applicable_to")
            if data.method_quota is not None:
                forbidden_keys.append("method_quota")
            if data.bonus_rule_override is not None:
                forbidden_keys.append("bonus_rule_override")
            if forbidden_keys:
                raise BusinessRuleViolation(
                    "Chỉ admin được set governance fields khi tạo path "
                    f"({', '.join(forbidden_keys)}). Manager liên hệ admin nếu "
                    "cần thay đổi."
                )

        # Create path
        path = await self.repo.create(
            {
                "academic_info_id": data.academic_info_id,
                "admission_method_id": data.admission_method_id,
                "admission_round_id": admission_round_id,
                "round_quota": data.round_quota,
                "admit_quota": data.admit_quota,
                "display_name": data.display_name,
                "display_order": data.display_order,
                "visibility": data.visibility,
                "status": "draft",  # Always start as draft
                # PR #6 — strict-by-default; admin may flip to True on create.
                "allow_unverified_submission": data.allow_unverified_submission,
                # Per-path correction allowlist — empty by default, admin may
                # seed a list at create time. Schema validator already
                # filtered out non-SAFE entries before reaching here.
                "minor_correction_allowed_fields": list(
                    data.minor_correction_allowed_fields or []
                ),
                # phase1_03 (#184 Wave 1 PR-1B'-FE/BE micro-patch) — 3
                # admin-only fields. Pydantic shape already validated
                # the audience ENUM + method_quota ge=0 + BonusRuleOverride
                # range; convert the typed shape back to a JSONB-friendly
                # dict for the JSONB column. None passes through unchanged
                # (= legacy / no method cap / inherit method bonus default).
                "applicable_to": (
                    list(data.applicable_to)
                    if data.applicable_to is not None
                    else None
                ),
                "method_quota": data.method_quota,
                "bonus_rule_override": (
                    data.bonus_rule_override.model_dump()
                    if data.bonus_rule_override is not None
                    else None
                ),
            }
        )

        return path, _noop_callback

    async def update_quota(
        self,
        path: AdmissionPath,
        round_quota: int | None,
        admit_quota: int | None,
        user: User,
    ) -> AdmissionPath:
        """Phase 2 v8.2 PR-2D.1 — dedicated quota update với Tier 1+2 chain
        validation per cell change cho QuotaMatrix UI inline edit.

        Tier 1: ∑(path.admit_quota WHERE academic_info_id=X) ≤
        academic_info[X].annual_admission_quota.
        Tier 2: path.admit_quota ≤ path.round_quota nếu cả 2 set.

        Raises BusinessRuleViolation nếu Tier 1/2 violated.
        """
        from app.services.admission_quota_service import AdmissionQuotaService

        _check_lifecycle_guard(path, user)

        quota_service = AdmissionQuotaService(self.db)

        # Tier 2 path invariant
        await quota_service.validate_tier2_path_invariant(
            admit_quota=admit_quota, round_quota=round_quota,
        )

        # Tier 1 chain re-validate when admit_quota changes
        if admit_quota != path.admit_quota:
            delta = (admit_quota or 0)
            await quota_service.validate_tier1_chain_on_path_quota_change(
                academic_info_id=path.academic_info_id,
                delta_admit_quota=delta,
                excluded_path_id=path.id,
            )

        path.round_quota = round_quota
        path.admit_quota = admit_quota
        await self.db.flush()

        log.info(
            "admission_path_quota_updated",
            path_id=path.id,
            round_quota=round_quota,
            admit_quota=admit_quota,
            actor_id=user.id,
        )
        return path

    async def update_path(
        self, path: AdmissionPath, data: AdmissionPathUpdate, user: User
    ) -> Tuple[AdmissionPath, PostCommitCallback]:
        """
        Update an existing AdmissionPath.

        Business Rules:
        - Archived paths cannot be updated
        - Manager can ONLY update paths in 'draft' status
        - Admin can update any non-archived path

        Raises:
            BusinessRuleViolation: If path is archived
            BusinessRuleViolation: If manager tries to edit non-draft path
        """
        # ADM-005: shared lifecycle guard — also enforced on
        # upsert_criteria / upsert_documents so manager cannot bypass
        # the "manager edits draft only" rule by hitting a sub-route.
        _check_lifecycle_guard(path, user)

        update_data = data.model_dump(exclude_unset=True)

        # Governance guard: 4 fields are admin-only on update — same set
        # as on create. Manager can edit a draft path's display_name /
        # fee / display_order / visibility / allow_unverified_submission
        # freely, but must not flip the security / governance fields
        # (correction allowlist + audience filter + method quota +
        # bonus engine override). Reject (not silent-drop) so the FE
        # form / API caller surfaces the failure.
        if user.role != UserRole.ADMIN:
            admin_only_keys = {
                "minor_correction_allowed_fields",
                "applicable_to",
                "method_quota",
                "bonus_rule_override",
            }
            forbidden = admin_only_keys & set(update_data.keys())
            if forbidden:
                raise BusinessRuleViolation(
                    "Chỉ admin được sửa governance fields "
                    f"({', '.join(sorted(forbidden))}). Manager liên hệ admin "
                    "nếu cần thay đổi."
                )

        # phase1_03 — convert BonusRuleOverride Pydantic shape back to
        # a plain JSONB dict for the column. Pydantic ``model_dump`` on
        # the inner shape only fires when the key is present + non-None;
        # ``exclude_unset=True`` above means absent keys stay absent.
        if (
            "bonus_rule_override" in update_data
            and update_data["bonus_rule_override"] is not None
        ):
            inner = update_data["bonus_rule_override"]
            # Pydantic v2 already converts nested models in model_dump,
            # but defend against direct BaseModel passthrough by checking
            # for the .model_dump method.
            if hasattr(inner, "model_dump"):
                update_data["bonus_rule_override"] = inner.model_dump()
        if (
            "applicable_to" in update_data
            and update_data["applicable_to"] is not None
        ):
            # Convert any iterable form back to list for the ARRAY column.
            update_data["applicable_to"] = list(update_data["applicable_to"])

        path = await self.repo.update(path, update_data)

        return path, _noop_callback

    async def upsert_criteria(
        self, path: AdmissionPath, data: AdmissionCriteriaCreate, user: User
    ) -> Tuple[AdmissionPath, PostCommitCallback]:
        """
        Create or update admission criteria for a path.

        ADM-005: enforces the same lifecycle guard as ``update_path`` —
        archived paths reject; non-admin can only mutate ``draft``. Without
        this guard, manager could bypass the "draft-only" rule by hitting
        ``PUT /paths/{id}/criteria`` directly.
        """
        _check_lifecycle_guard(path, user)

        # ADM-003 defensive clone:
        # The alembic adm003path001 migration + UNIQUE constraint on
        # admission_path.criteria_id should make ``criteria`` shared
        # impossible going forward. We still detect-and-clone here so
        # that (a) test data, (b) hand-edited dirty rows, or (c) any
        # imports that bypassed the constraint do NOT silently mutate
        # another path's criteria. Running the rebuild against a
        # newly-cloned row also produces a clean, deterministic message
        # in the API response instead of a raw IntegrityError.
        if path.criteria:
            shared_count = (
                await self.db.execute(
                    select(func.count(AdmissionPath.id)).where(
                        AdmissionPath.criteria_id == path.criteria_id,
                        AdmissionPath.id != path.id,
                    )
                )
            ).scalar_one()
            if shared_count > 0:
                old_criteria_id = path.criteria_id
                clone_code = f"CRIT_orig_{old_criteria_id}_path_{path.id}"

                # Reuse a previous clone if one already exists for this
                # path (defensive idempotency — same naming scheme as
                # the migration).
                existing = (
                    await self.db.execute(
                        select(AdmissionCriteria).where(
                            AdmissionCriteria.code == clone_code
                        )
                    )
                ).scalar_one_or_none()

                if existing is None:
                    source = path.criteria
                    cloned = AdmissionCriteria(
                        method_id=source.method_id,
                        code=clone_code,
                        name=source.name,
                        min_gpa=source.min_gpa,
                        min_score=source.min_score,
                        conditions=source.conditions,
                        is_active=source.is_active,
                        required_subject_count=source.required_subject_count,
                        subject_selection_mode=source.subject_selection_mode,
                        scoring_method=source.scoring_method,
                        max_possible_score=source.max_possible_score,
                        min_subject_score=source.min_subject_score,
                        policy_version=source.policy_version,
                        effective_from=source.effective_from,
                        effective_to=source.effective_to,
                    )
                    self.db.add(cloned)
                    await self.db.flush()

                    # Clone subject-group mappings so the new criteria
                    # has the same allowed groups before we wipe + rebuild
                    # them below.
                    src_mappings = (
                        await self.db.execute(
                            select(CriteriaSubjectGroup).where(
                                CriteriaSubjectGroup.criteria_id == old_criteria_id
                            )
                        )
                    ).scalars().all()
                    for m in src_mappings:
                        self.db.add(
                            CriteriaSubjectGroup(
                                criteria_id=cloned.id,
                                subject_group_id=m.subject_group_id,
                            )
                        )
                    await self.db.flush()
                    cloned_obj = cloned
                else:
                    cloned_obj = existing

                log.warning(
                    "admission_path.criteria was shared; cloned before mutate "
                    "(ADM-003 defensive)",
                    path_id=path.id,
                    old_criteria_id=old_criteria_id,
                    new_criteria_id=cloned_obj.id,
                    shared_with_paths=shared_count,
                )

                path.criteria = cloned_obj
                path.criteria_id = cloned_obj.id
                self.db.add(path)
                await self.db.flush()

        # 1. Update/Create Criteria
        if path.criteria:
            # Update existing
            for field, value in data.model_dump(exclude={"subject_groups"}).items():
                setattr(path.criteria, field, value)
            criteria = path.criteria
        else:
            # Create new
            code = f"CRIT_{path.id}_{datetime.now().strftime('%Y%m%d%H%M')}"
            criteria = AdmissionCriteria(
                method_id=path.admission_method_id,
                code=code,
                name=f"Criteria for Path {path.id}",
                **data.model_dump(exclude={"subject_groups"}),
            )
            self.db.add(criteria)
            await self.db.flush()  # Get ID

            path.criteria_id = criteria.id
            self.db.add(path)

        # 2. Update Subject Groups
        # Clear existing
        from sqlalchemy import delete

        await self.db.execute(
            delete(CriteriaSubjectGroup).where(
                CriteriaSubjectGroup.criteria_id == criteria.id
            )
        )

        # Add new
        for group_id in data.subject_groups:
            self.db.add(
                CriteriaSubjectGroup(criteria_id=criteria.id, subject_group_id=group_id)
            )

        await self.db.flush()
        return path, _noop_callback

    async def upsert_documents(
        self,
        path: AdmissionPath,
        documents: List[AdmissionPathDocumentUpsert],
        user: User,
    ) -> Tuple[List[ResolvedDocumentResponse], PostCommitCallback]:
        """
        Update document requirements for a path.

        Logic:
        1. Find/Create method-specific DocumentGroup for this path's offering_type + method.
        2. Sync items in that group.

        ADM-005: enforces the same lifecycle guard as ``update_path`` —
        archived paths reject; non-admin can only mutate ``draft``. Without
        this guard, manager could bypass the "draft-only" rule by hitting
        ``PUT /paths/{id}/documents`` directly.
        """
        _check_lifecycle_guard(path, user)

        if not path.academic_info or not path.academic_info.offering:
            # Force load if missing (though repo loads it)
            path = await self.repo.get_by_id_with_relations(path.id)

        offering_type_id = path.academic_info.offering.offering_type_id
        method_id = path.admission_method_id

        # 1. Find Method-Specific Group
        # TODO: Move query to repo if complex
        from sqlalchemy import select

        stmt = select(DocumentGroup).where(
            DocumentGroup.offering_type_id == offering_type_id,
            DocumentGroup.admission_method_id == method_id,
        )
        result = await self.db.execute(stmt)
        group = result.scalars().first()

        if not group:
            # Create new group override
            code = (
                f"DOC_{offering_type_id}_{method_id}_{datetime.now().strftime('%M%S')}"
            )
            group = DocumentGroup(
                offering_type_id=offering_type_id,
                admission_method_id=method_id,
                code=code,
                name=f"Docs for Method {method_id} (Override)",
                is_active=True,
            )
            self.db.add(group)
            await self.db.flush()

        # 2. Sync Items
        # Clear existing
        from sqlalchemy import delete

        await self.db.execute(
            delete(DocumentGroupItem).where(DocumentGroupItem.group_id == group.id)
        )

        # Add new
        for doc in documents:
            # Default submission_format if requires_upload is True (constraint fix)
            sub_fmt = doc.submission_format
            if doc.requires_upload and not sub_fmt:
                sub_fmt = "photo"

            self.db.add(
                DocumentGroupItem(
                    group_id=group.id,
                    document_type_id=doc.document_type_id,
                    is_mandatory=doc.is_mandatory,
                    requires_upload=doc.requires_upload,
                    submission_format=sub_fmt,
                    display_order=doc.display_order,
                )
            )

        await self.db.flush()

        # Return resolved list
        return await self.resolve_documents_for_path(path, offering_type_id)

    # =========================================================================
    # ACTIVATION LOGIC
    # =========================================================================

    async def validate_activation(self, path: AdmissionPath) -> Tuple[bool, List[str]]:
        """
        Validate if path can be activated.

        ADM-004: criteria + documents are now checked inline using the same
        rules as ``get_coverage_matrix`` so the route guard, coverage UI and
        ``can_activate`` flag agree on a single readiness contract:

        1. Status must be ``draft`` or ``inactive``.
        2. ``academic_info.annual_admission_quota`` must be > 0.
        3. ``path.criteria_id`` must be set.
        4. A ``DocumentGroup`` must exist for the path's offering type +
           admission method (method-specific or shared fallback).

        Returns:
            (can_activate, validation_errors)
        """
        from app.repositories.document_group_repository import DocumentGroupRepository

        errors: List[str] = []

        # Check 1: Status must be draft or inactive
        if path.status not in ["draft", "inactive"]:
            errors.append(f"Cannot activate path with status '{path.status}'")

        # Check 2: academic_info + quota
        academic_info = path.academic_info
        if not academic_info:
            errors.append("Chưa thiết lập thông tin tuyển sinh (Academic Info)")
        else:
            quota = academic_info.annual_admission_quota or 0
            if quota <= 0:
                errors.append("Chưa thiết lập chỉ tiêu (Quota)")

        # Check 3: Criteria must be configured
        if path.criteria_id is None:
            errors.append("Chưa cấu hình tiêu chí (Criteria)")

        # Check 4: Documents must resolve (method-specific or shared)
        offering_type_id = None
        if academic_info and academic_info.offering:
            offering_type_id = academic_info.offering.offering_type_id

        has_documents = False
        if offering_type_id:
            doc_repo = DocumentGroupRepository(self.db)
            method_group = await doc_repo.get_method_specific_group(
                offering_type_id, path.admission_method_id
            )
            if method_group:
                has_documents = True
            else:
                shared_groups = await doc_repo.get_shared_groups(offering_type_id)
                has_documents = len(shared_groups) > 0

        if not has_documents:
            errors.append("Chưa cấu hình hồ sơ (Documents)")

        can_activate = len(errors) == 0
        return can_activate, errors

    async def activate_path(
        self, path: AdmissionPath, user: User
    ) -> Tuple[AdmissionPath, PostCommitCallback]:
        """
        Activate an AdmissionPath.

        ADM-008 (Q3=a): admin-only. Manager creates/edits drafts but
        cannot activate — Admin "approves = activates". Service-level
        gate is defense-in-depth; the route also guards via
        ``Depends(require_admin)``.

        Raises:
            PermissionDeniedError: If caller is not admin
            BusinessRuleViolation: If readiness validation fails
        """
        if user.role != UserRole.ADMIN:
            raise PermissionDeniedError(
                "Chỉ admin được activate admission path. "
                "Manager tạo/sửa draft, admin duyệt = activate."
            )

        can_activate, errors = await self.validate_activation(path)

        if not can_activate:
            raise BusinessRuleViolation(f"Cannot activate path: {'; '.join(errors)}")

        # Activate
        path = await self.repo.update(
            path,
            {
                "status": "active",
                "activated_at": datetime.now(timezone.utc),
                "activated_by": user.id,
            },
        )

        return path, _noop_callback

    async def deactivate_path(
        self, path: AdmissionPath, user: User
    ) -> Tuple[AdmissionPath, PostCommitCallback]:
        """
        Deactivate an active AdmissionPath.

        ADM-008 (Q3=a): admin-only, symmetric to ``activate_path``.

        Raises:
            PermissionDeniedError: If caller is not admin
            BusinessRuleViolation: If path is not active
        """
        if user.role != UserRole.ADMIN:
            raise PermissionDeniedError("Chỉ admin được deactivate admission path.")

        if path.status != "active":
            raise BusinessRuleViolation(
                f"Cannot deactivate path with status '{path.status}'"
            )

        path = await self.repo.update(
            path,
            {
                "status": "inactive",
            },
        )

        return path, _noop_callback

    async def archive_path(
        self, path: AdmissionPath, user: User
    ) -> Tuple[AdmissionPath, PostCommitCallback]:
        """
        Archive an AdmissionPath.

        Raises:
            BusinessRuleViolation: If path is active
        """
        if path.status == "active":
            raise BusinessRuleViolation("Cannot archive active path. Deactivate first.")

        path = await self.repo.update(
            path,
            {
                "status": "archived",
            },
        )

        return path, _noop_callback

    # =========================================================================
    # DOCUMENT OVERRIDE RESOLUTION
    # =========================================================================

    async def resolve_documents_for_path(
        self, path: AdmissionPath, offering_type_id: int
    ) -> Tuple[List[ResolvedDocumentResponse], PostCommitCallback]:
        """
        Resolve document requirements for a path.

        phase1_06 (#184 Wave 1 PR-1C') — 3-tier resolution rule
        per PLAN line 619-623:

        1. **Tier 1**: ``WHERE admission_path_id = path.id`` →
           if any rows match, USE THIS TIER FULLY (ignore tier 2 + 3).
        2. **Tier 2**: ``WHERE admission_method_id = path.method
           AND admission_path_id IS NULL`` → if any rows match,
           USE THIS TIER FULLY (ignore tier 3).
        3. **Tier 3**: ``WHERE offering_type_id = X AND
           admission_method_id IS NULL AND admission_path_id IS NULL``
           → fallback shared bucket.

        Within a tier, multiple groups merge with mandatory-wins
        (existing precedence preserved). Source indicators on the
        response surface which tier provided each document so the
        FE / admin can debug drift.

        Returns:
            List of resolved documents with source indicator
            (``path_override`` / ``method_override`` / ``shared``).
        """
        path_groups, method_groups, shared_groups = (
            await self.repo.get_document_groups_for_path(
                offering_type_id,
                path.admission_method_id,
                admission_path_id=path.id,
            )
        )

        # Build document map: document_type_id -> (item, source).
        # Tier precedence: highest tier with non-empty groups wins
        # FULLY; lower tiers are ignored (admin "deletes" default
        # items by configuring a higher tier).
        doc_map: dict = {}

        if path_groups:
            # Tier 1 — path-specific (PR-1C' new). Mandatory-wins
            # within the tier so two path groups can layer.
            for group in path_groups:
                for item in group.items:
                    existing = doc_map.get(item.document_type_id)
                    if existing is None:
                        doc_map[item.document_type_id] = (item, "path_override")
                    elif item.is_mandatory and not existing[0].is_mandatory:
                        doc_map[item.document_type_id] = (item, "path_override")
        elif method_groups:
            # Tier 2 — method-specific. Existing legacy bucket;
            # behavior unchanged from pre-PR-1C'.
            for group in method_groups:
                for item in group.items:
                    existing = doc_map.get(item.document_type_id)
                    if existing is None:
                        doc_map[item.document_type_id] = (item, "method_override")
                    elif item.is_mandatory and not existing[0].is_mandatory:
                        doc_map[item.document_type_id] = (item, "method_override")
        else:
            # Tier 3 — shared offering-type fallback.
            for group in shared_groups:
                for item in group.items:
                    existing = doc_map.get(item.document_type_id)
                    if existing is None:
                        doc_map[item.document_type_id] = (item, "shared")
                    elif item.is_mandatory and not existing[0].is_mandatory:
                        doc_map[item.document_type_id] = (item, "shared")

        # Step 3: Build response
        resolved: List[ResolvedDocumentResponse] = []
        for doc_type_id, (item, source) in doc_map.items():
            resolved.append(
                ResolvedDocumentResponse(
                    document_type_id=item.document_type_id,
                    document_type_code=(
                        item.document_type.code if item.document_type else ""
                    ),
                    document_type_name=(
                        item.document_type.name if item.document_type else ""
                    ),
                    is_mandatory=item.is_mandatory,
                    requires_upload=item.requires_upload,
                    submission_format=item.submission_format,
                    display_order=item.display_order,
                    source=source,
                )
            )

        # Sort by display_order
        resolved.sort(key=lambda x: x.display_order)

        return resolved, _noop_callback

    # =========================================================================
    # CONTROL FIELD COMPUTATION (for response)
    # =========================================================================

    def compute_available_actions(
        self,
        path: AdmissionPath,
        user: User | None = None,
    ) -> List[str]:
        """
        Compute actions the current user is allowed to perform.

        FRONTEND_ARCHITECTURE_V3.md: FE reads this, not computes.

        ADM-021: These flags must mirror backend role gates. Managers can
        create/edit draft paths, but activate/deactivate is admin-only.
        """
        actions: List[str] = []

        if self.compute_can_edit(path, user):
            actions.append("save")

        if not user or user.role != UserRole.ADMIN:
            return actions

        # Keep lifecycle intent visible to admin even when readiness is not
        # satisfied; callers must use ``can_activate`` to enable/disable the
        # button because it runs the heavier criteria/doc/quota validation.
        if path.status in ["draft", "inactive"]:
            actions.extend(["activate", "archive"])
        elif path.status == "active":
            actions.append("deactivate")

        return actions

    def compute_can_edit(
        self,
        path: AdmissionPath,
        user: User | None = None,
    ) -> bool:
        """
        Determine if the current user can edit this path.
        """
        if path.status == "archived" or not user:
            return False
        if user.role == UserRole.ADMIN:
            return True
        if user.role == UserRole.MANAGER:
            return path.status == "draft"
        return False

    async def compute_can_activate(
        self,
        path: AdmissionPath,
        user: User | None = None,
    ) -> bool:
        """
        Determine if the current user can activate this path.
        """
        if not user or user.role != UserRole.ADMIN:
            return False
        can_activate, _ = await self.validate_activation(path)
        return can_activate

    # =========================================================================
    # COVERAGE MATRIX
    # =========================================================================

    async def get_coverage_matrix(
        self, academic_info_id: int
    ) -> Tuple[dict, PostCommitCallback]:
        """
        Get coverage matrix for all paths in an academic_info.

        Returns matrix showing readiness status of each path:
        - has_criteria: criteria_id is set
        - has_documents: document group exists
        - has_quota: quota > 0
        - can_activate: all above are true

        FE uses this to display audit table before bulk activation.
        """
        from app.schemas.admission_path import CoverageRow, CoverageMatrixResponse
        from app.repositories.document_group_repository import DocumentGroupRepository

        paths = await self.repo.get_paths_by_academic_info(academic_info_id)
        doc_repo = DocumentGroupRepository(self.db)

        rows = []
        paths_ready = 0

        for path in paths:
            # Check has_criteria
            has_criteria = path.criteria_id is not None

            # Check has_documents (based on offering_type + method)
            # Need to get offering_type_id from academic_info.offering
            offering_type_id = None
            if path.academic_info and path.academic_info.offering:
                offering_type_id = path.academic_info.offering.offering_type_id

            has_documents = False
            if offering_type_id:
                # Check if method-specific group exists, else check shared
                method_group = await doc_repo.get_method_specific_group(
                    offering_type_id, path.admission_method_id
                )
                if method_group:
                    has_documents = True
                else:
                    shared_groups = await doc_repo.get_shared_groups(offering_type_id)
                    has_documents = len(shared_groups) > 0

            # Check has_quota
            has_quota = False
            if path.academic_info:
                quota = path.academic_info.annual_admission_quota or 0
                has_quota = quota > 0

            # Compute can_activate
            can_activate = has_criteria and has_documents and has_quota

            # Build validation errors
            validation_errors = []
            if not has_criteria:
                validation_errors.append("Chưa cấu hình tiêu chí (Criteria)")
            if not has_documents:
                validation_errors.append("Chưa cấu hình hồ sơ (Documents)")
            if not has_quota:
                validation_errors.append("Chưa thiết lập chỉ tiêu (Quota)")

            if can_activate:
                paths_ready += 1

            # Get method info
            method_name = ""
            method_code = ""
            if path.admission_method:
                method_name = path.admission_method.name
                method_code = path.admission_method.code

            rows.append(
                CoverageRow(
                    path_id=path.id,
                    method_name=method_name,
                    method_code=method_code,
                    status=path.status,
                    has_criteria=has_criteria,
                    has_documents=has_documents,
                    has_quota=has_quota,
                    can_activate=can_activate,
                    validation_errors=validation_errors,
                )
            )

        total_paths = len(paths)
        all_ready = paths_ready == total_paths and total_paths > 0

        result = CoverageMatrixResponse(
            academic_info_id=academic_info_id,
            rows=rows,
            total_paths=total_paths,
            paths_ready=paths_ready,
            all_ready=all_ready,
        )

        return result, _noop_callback
