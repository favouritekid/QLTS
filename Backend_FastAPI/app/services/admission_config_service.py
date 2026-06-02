# app/services/admission_config_service.py
"""
Admission Config Service.

Business logic for Admission Configuration management.
Follows MASTER_ARCHITECTURE.md:
- No HTTPException (domain exceptions only)
- No db.commit() (caller commits)
- Returns (result, callback) tuple
"""

from typing import Callable, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from app.models import User
from app.models.admission_config import AdmissionCriteria
from app.repositories.admission_config_repository import AdmissionConfigRepository
from app.repositories.document_group_repository import DocumentGroupRepository
from app.schemas.admission_config import (
    AdmissionCriteriaCreate,
    AdmissionCriteriaUpdate,
    SharedDocumentGroupUpdate,
)
from app.utils.exceptions import (
    ResourceNotFoundError,
    DuplicateResourceError,
    BusinessRuleViolation,
    ValidationError,
)


async def _noop_callback():
    """No-op callback for operations without side effects."""
    pass


class AdmissionConfigService:
    """
    Service for Admission Configuration management.
    
    Handles business logic for:
    - AdmissionCriteria CRUD
    - Subject group mappings
    - Validation rules
    - Shared Document Groups associated with Offering Types
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AdmissionConfigRepository(db)
        self.document_group_repo = DocumentGroupRepository(db)

    # =========================================================================
    # CRITERIA CRUD
    # =========================================================================

    async def create_criteria(
        self,
        data: AdmissionCriteriaCreate,
        user: User,
    ) -> tuple[AdmissionCriteria, Callable[[], Any]]:
        """
        Create new AdmissionCriteria.
        
        Validation:
        - method_id must exist
        - code must be unique
        - At least one of min_gpa or min_score required
        
        Returns:
            Tuple of (created criteria, callback)
        """
        # Validate method exists
        method = await self.repo.get_method_by_code(data.method_code)
        if not method:
            raise ResourceNotFoundError(f"Method '{data.method_code}' not found")

        # Check for duplicate code
        existing = await self.repo.get_criteria_by_code(data.code, load_level="light")
        if existing:
            raise DuplicateResourceError(f"Criteria with code '{data.code}' already exists")

        # Business rule: at least one threshold required
        if data.min_gpa is None and data.min_score is None:
            raise BusinessRuleViolation("At least min_gpa or min_score is required")

        # Create criteria
        criteria = await self.repo.create_criteria(
            method_id=method.id,
            code=data.code,
            name=data.name,
            min_gpa=data.min_gpa,
            min_score=data.min_score,
            required_subject_count=data.required_subject_count,
            subject_selection_mode=data.subject_selection_mode or "fixed",
            scoring_method=data.scoring_method or "sum",
            max_possible_score=data.max_possible_score,
            min_subject_score=data.min_subject_score,
            conditions=data.conditions,
            is_active=data.is_active or False,
            policy_version=data.policy_version or "2025.1",
        )

        # Add subject groups if provided
        if data.subject_group_ids:
            await self.repo.add_subject_groups_to_criteria(
                criteria.id,
                data.subject_group_ids
            )

        return criteria, _noop_callback

    async def update_criteria(
        self,
        criteria: AdmissionCriteria,
        data: AdmissionCriteriaUpdate,
        user: User,
    ) -> tuple[AdmissionCriteria, Callable[[], Any]]:
        """
        Update existing AdmissionCriteria.
        
        Note: method_id cannot be changed after creation.
        
        Returns:
            Tuple of (updated criteria, callback)
        """
        # Build update dict from provided fields
        updates = {}
        
        if data.name is not None:
            updates["name"] = data.name
        if data.min_gpa is not None:
            updates["min_gpa"] = data.min_gpa
        if data.min_score is not None:
            updates["min_score"] = data.min_score
        if data.required_subject_count is not None:
            updates["required_subject_count"] = data.required_subject_count
        if data.subject_selection_mode is not None:
            updates["subject_selection_mode"] = data.subject_selection_mode
        if data.scoring_method is not None:
            updates["scoring_method"] = data.scoring_method
        if data.max_possible_score is not None:
            updates["max_possible_score"] = data.max_possible_score
        if data.min_subject_score is not None:
            updates["min_subject_score"] = data.min_subject_score
        if data.conditions is not None:
            updates["conditions"] = data.conditions
        if data.is_active is not None:
            updates["is_active"] = data.is_active
        if data.policy_version is not None:
            updates["policy_version"] = data.policy_version

        # Apply updates
        if updates:
            criteria = await self.repo.update_criteria(criteria, **updates)

        # Update subject groups if provided
        if data.subject_group_ids is not None:
            await self.repo.remove_all_subject_groups_from_criteria(criteria.id)
            if data.subject_group_ids:
                await self.repo.add_subject_groups_to_criteria(
                    criteria.id,
                    data.subject_group_ids
                )

        return criteria, _noop_callback

    async def delete_criteria(
        self,
        criteria: AdmissionCriteria,
        user: User,
    ) -> tuple[bool, Callable[[], Any]]:
        """
        Delete AdmissionCriteria.
        
        Business Rule: Cannot delete if linked to active AdmissionPaths.
        
        Returns:
            Tuple of (success, callback)
        """

        # PRE-CHECK: Integrity
        is_used = await self.repo.check_criteria_usage(criteria.id)
        if is_used:
            raise BusinessRuleViolation("Cannot delete criteria: It is currently used in active Admission Paths or Offering Configs.")
        
        success = await self.repo.delete_criteria(criteria.id)
        return success, _noop_callback

    async def get_criteria(
        self,
        criteria_id: int,
        load_level: str = "with_groups"
    ) -> AdmissionCriteria | None:
        """Get criteria by ID."""
        return await self.repo.get_criteria_by_id(criteria_id, load_level=load_level)

    # =========================================================================
    # SUBJECT CRUD (Phase 1 Refactor)
    # =========================================================================

    async def create_subject(
        self,
        data: "SubjectCreate",
        user: User,
    ) -> tuple["Subject", Callable[[], Any]]:
        """
        Create new Subject.
        
        Validation:
        - code must be unique
        
        Returns:
            Tuple of (created subject, callback)
        """
        from app.schemas.admission_config import SubjectCreate
        from app.models.admission_config import Subject
        
        # Check for duplicate code
        existing = await self.repo.get_subject_by_code(data.code)
        if existing:
            raise DuplicateResourceError(f"Subject with code '{data.code}' already exists")

        subject = await self.repo.create_subject(
            code=data.code,
            name_vi=data.name_vi,
            display_order=data.display_order,
            is_active=data.is_active,
        )

        return subject, _noop_callback

    async def update_subject(
        self,
        subject: "Subject",
        data: "SubjectUpdate",
        user: User,
    ) -> tuple["Subject", Callable[[], Any]]:
        """
        Update existing Subject.
        
        Returns:
            Tuple of (updated subject, callback)
        """
        updates = {}
        if data.name_vi is not None:
            updates["name_vi"] = data.name_vi
        if data.display_order is not None:
            updates["display_order"] = data.display_order
        if data.is_active is not None:
            updates["is_active"] = data.is_active

        if updates:
            subject = await self.repo.update_subject(subject, **updates)

        return subject, _noop_callback

    async def delete_subject(
        self,
        subject_id: int,
        user: User,
    ) -> tuple[bool, Callable[[], Any]]:
        """
        Delete Subject by ID.
        
        Returns:
            Tuple of (success, callback)
        
        Raises:
            ResourceNotFoundError if subject not found
        """
        # PRE-CHECK: Integrity
        is_used = await self.repo.check_subject_usage(subject_id)
        if is_used:
            raise BusinessRuleViolation("Cannot delete subject: It is currently used in one or more Subject Groups.")

        success = await self.repo.delete_subject(subject_id)
        if not success:
            raise ResourceNotFoundError(f"Subject with ID {subject_id} not found")

        return success, _noop_callback

    # =========================================================================
    # SUBJECT GROUP CRUD (Phase 1 Refactor)
    # =========================================================================

    async def create_subject_group(
        self,
        data: "SubjectGroupCreate",
        user: User,
    ) -> tuple["SubjectGroup", Callable[[], Any]]:
        """
        Create new SubjectGroup.
        
        Validation:
        - code must be unique
        
        Returns:
            Tuple of (created group, callback)
        """
        from app.schemas.admission_config import SubjectGroupCreate
        from app.models.admission_config import SubjectGroup
        
        # Check for duplicate code
        existing = await self.repo.get_subject_group_by_code(data.code, with_subjects=False)
        if existing:
            raise DuplicateResourceError(f"Subject group with code '{data.code}' already exists")

        group = await self.repo.create_subject_group(
            code=data.code,
            name=data.name,
            display_order=data.display_order,
            is_active=data.is_active,
        )

        # Add subject mappings if provided
        if data.subject_ids:
            group = await self.repo.update_subject_group_mappings(group.id, data.subject_ids)

        return group, _noop_callback

    async def update_subject_group(
        self,
        group: "SubjectGroup",
        data: "SubjectGroupUpdate",
        user: User,
    ) -> tuple["SubjectGroup", Callable[[], Any]]:
        """
        Update existing SubjectGroup.
        
        Returns:
            Tuple of (updated group, callback)
        """
        updates = {}
        if data.name is not None:
            updates["name"] = data.name
        if data.display_order is not None:
            updates["display_order"] = data.display_order
        if data.is_active is not None:
            updates["is_active"] = data.is_active

        if updates:
            group = await self.repo.update_subject_group(group, **updates)

        # Update subject mappings if provided
        if data.subject_ids is not None:
            group = await self.repo.update_subject_group_mappings(group.id, data.subject_ids)

        return group, _noop_callback

    async def delete_subject_group(
        self,
        group_id: int,
        user: User,
    ) -> tuple[bool, Callable[[], Any]]:
        """
        Delete SubjectGroup by ID.
        
        Returns:
            Tuple of (success, callback)
        
        Raises:
            ResourceNotFoundError if group not found
        """
        # PRE-CHECK: Integrity
        is_used = await self.repo.check_subject_group_usage(group_id)
        if is_used:
            raise BusinessRuleViolation("Cannot delete subject group: It is currently used in one or more Admission Criteria.")

        success = await self.repo.delete_subject_group(group_id)
        if not success:
            raise ResourceNotFoundError(f"Subject group with ID {group_id} not found")

        return success, _noop_callback

    # =========================================================================
    # SUBJECT GROUP ↔ SUBJECT (granular M2M sub-resource)
    # =========================================================================

    async def _get_group_or_404(self, group_id: int) -> "SubjectGroup":
        """Load a subject group (no mappings) or raise 404."""
        group = await self.repo.get_subject_group_by_id(
            group_id, with_subjects=False
        )
        if not group:
            raise ResourceNotFoundError(
                f"Subject group with ID {group_id} not found"
            )
        return group

    async def _get_mapping_or_404(self, group_id: int, subject_id: int):
        """Load the subject→group join row or raise 404."""
        mapping = await self.repo.get_subject_group_subject(
            group_id, subject_id
        )
        if not mapping:
            raise ResourceNotFoundError(
                f"Subject {subject_id} is not in subject group {group_id}"
            )
        return mapping

    async def add_subject_to_group(
        self,
        group_id: int,
        subject_id: int,
        position: int,
        user: User,
    ) -> tuple["SubjectGroup", Callable[[], Any]]:
        """Add one subject to a group at a position (granular M2M).

        Raises ResourceNotFoundError (404) if the group or subject is missing,
        DuplicateResourceError (409) if the subject is already in the group —
        pre-checked so no raw DB IntegrityError leaks; the
        ``uq_subject_group_subject`` UNIQUE constraint backstops races.
        """
        await self._get_group_or_404(group_id)
        subject = await self.repo.get_subject_by_id(subject_id)
        if not subject:
            raise ResourceNotFoundError(
                f"Subject with ID {subject_id} not found"
            )
        existing = await self.repo.get_subject_group_subject(
            group_id, subject_id
        )
        if existing:
            raise DuplicateResourceError(
                f"Subject {subject_id} is already in subject group {group_id}"
            )

        await self.repo.add_subject_group_subject(
            group_id, subject_id, position
        )
        group = await self.repo.get_subject_group_by_id(
            group_id, with_subjects=True
        )
        return group, _noop_callback

    async def remove_subject_from_group(
        self,
        group_id: int,
        subject_id: int,
        user: User,
    ) -> tuple["SubjectGroup", Callable[[], Any]]:
        """Remove one subject from a group (granular M2M).

        Raises ResourceNotFoundError (404) if the group is missing or the
        subject is not mapped to it.
        """
        await self._get_group_or_404(group_id)
        deleted = await self.repo.delete_subject_group_subject(
            group_id, subject_id
        )
        if not deleted:
            raise ResourceNotFoundError(
                f"Subject {subject_id} is not in subject group {group_id}"
            )
        group = await self.repo.get_subject_group_by_id(
            group_id, with_subjects=True
        )
        return group, _noop_callback

    async def update_subject_position(
        self,
        group_id: int,
        subject_id: int,
        position: int,
        user: User,
    ) -> tuple["SubjectGroup", Callable[[], Any]]:
        """Update one subject's position within a group (granular M2M).

        Raises ResourceNotFoundError (404) if the group is missing or the
        subject is not mapped to it.
        """
        await self._get_group_or_404(group_id)
        mapping = await self._get_mapping_or_404(group_id, subject_id)
        mapping.position = position
        await self.db.flush()
        group = await self.repo.get_subject_group_by_id(
            group_id, with_subjects=True
        )
        return group, _noop_callback

    # =========================================================================
    # ADMISSION METHOD CRUD (Phase 1 Refactor)
    # =========================================================================

    async def create_method(
        self,
        data: "AdmissionMethodCreate",
        user: User,
    ) -> tuple["AdmissionMethod", Callable[[], Any]]:
        """
        Create new AdmissionMethod.
        
        Validation:
        - code must be unique
        
        Returns:
            Tuple of (created method, callback)
        """
        from app.schemas.admission_config import AdmissionMethodCreate
        from app.models.admission_config import AdmissionMethod
        
        # Check for duplicate code
        existing = await self.repo.get_method_by_code(data.code)
        if existing:
            raise DuplicateResourceError(f"Method with code '{data.code}' already exists")

        method = await self.repo.create_method(
            code=data.code,
            name=data.name,
            description=data.description,
            requires_gpa=data.requires_gpa,
            requires_subject_scores=data.requires_subject_scores,
            display_order=data.display_order,
            is_active=data.is_active,
        )

        return method, _noop_callback

    async def update_method(
        self,
        method: "AdmissionMethod",
        data: "AdmissionMethodUpdate",
        user: User,
    ) -> tuple["AdmissionMethod", Callable[[], Any]]:
        """
        Update existing AdmissionMethod.
        
        Returns:
            Tuple of (updated method, callback)
        """
        updates = {}
        if data.name is not None:
            updates["name"] = data.name
        if data.description is not None:
            updates["description"] = data.description
        if data.requires_gpa is not None:
            updates["requires_gpa"] = data.requires_gpa
        if data.requires_subject_scores is not None:
            updates["requires_subject_scores"] = data.requires_subject_scores
        if data.display_order is not None:
            updates["display_order"] = data.display_order
        if data.is_active is not None:
            updates["is_active"] = data.is_active

        if updates:
            method = await self.repo.update_method(method, **updates)

        return method, _noop_callback

    async def delete_method(
        self,
        method_id: int,
        user: User,
    ) -> tuple[bool, Callable[[], Any]]:
        """
        Delete AdmissionMethod by ID.
        
        Returns:
            Tuple of (success, callback)
        
        Raises:
            ResourceNotFoundError if method not found
        """
        success = await self.repo.delete_method(method_id)
        if not success:
            raise ResourceNotFoundError(f"Method with ID {method_id} not found")

        return success, _noop_callback

    # =========================================================================
    # SHARED DOCUMENT GROUPS (Phase 1)
    # =========================================================================

    async def get_shared_document_group(
        self,
        offering_type_id: int,
        audience: Optional[str] = None,
    ):
        """Get shared document group cho ``(offering_type, audience)``.

        feat/document-group-audience-merge §10.8: ``audience=None`` → lớp NỀN
        (``applicable_audience`` NULL); ``audience=<X>`` → lớp theo đối tượng.
        Lookup CHÍNH XÁC (fix R10 ``groups[0]`` nondeterministic sau ĐỢT B).
        """
        return await self.document_group_repo.get_shared_group_by_audience(
            offering_type_id, audience
        )

    async def list_shared_document_groups(self, offering_type_id: int):
        """List TẤT CẢ shared group (NỀN + lớp audience) — panel enumerate lớp
        để admin chọn lớp sửa (§10.17). Ordered by id (NỀN trước)."""
        return await self.document_group_repo.get_shared_groups(offering_type_id)

    async def upsert_shared_document_group(
        self,
        offering_type_id: int,
        data: SharedDocumentGroupUpdate,
        user: User,
        audience: Optional[str] = None,
    ) -> tuple["DocumentGroup", Callable[[], Any]]:
        """Create/Update shared document group cho ``(offering_type, audience)``.

        Replaces all items. feat/document-group-audience-merge §10.8/G4:
        lookup theo ``(ot, audience)`` (KHÔNG ``groups[0]``); tạo mới nếu chưa
        có với code deterministic + set ``applicable_audience``.
        """
        from app.services.document_resolution_service import AUDIENCE_LABELS

        if audience is not None and audience not in AUDIENCE_LABELS:
            raise ValidationError(
                f"audience '{audience}' không hợp lệ "
                f"(phải thuộc {sorted(AUDIENCE_LABELS)})"
            )

        group = await self.document_group_repo.get_shared_group_by_audience(
            offering_type_id, audience
        )

        if not group:
            if audience is None:
                code = f"SHARED_DOC_OT_{offering_type_id}"
                name = f"Hồ sơ chung (OT-{offering_type_id})"
                description = "Lớp NỀN — giấy tờ chung cho mọi thí sinh."
                applicable = None
            else:
                code = f"SHARED_DOC_OT_{offering_type_id}_{audience}"
                label = AUDIENCE_LABELS[audience]
                name = f"Hồ sơ {label} (OT-{offering_type_id})"
                description = f"Lớp theo đối tượng: {label}."
                applicable = [audience]
            # code UNIQUE VARCHAR(50) — fail-loud nếu vượt (thực tế ≤ ~30;
            # raise thật, KHÔNG assert — tránh bị strip với python -O).
            if len(code) > 50:
                raise ValueError(
                    f"group code '{code}' ({len(code)}) > 50 — đổi scheme hậu tố"
                )

            group = await self.document_group_repo.create_group(
                offering_type_id=offering_type_id,
                admission_method_id=None,  # tier shared
                admission_path_id=None,
                code=code,
                name=name,
                description=description,
                is_active=True,
                applicable_audience=applicable,
            )

        # Replace items
        await self.document_group_repo.remove_all_items_from_group(group.id)

        for item in data.items:
            await self.document_group_repo.add_item_to_group(
                group_id=group.id,
                document_type_id=item.document_type_id,
                is_mandatory=item.is_mandatory,
                requires_upload=item.requires_upload,
                submission_format=item.submission_format,
                display_order=item.display_order,
            )

        # Refetch with items
        updated = await self.document_group_repo.get_by_id_with_items(group.id)
        return updated, _noop_callback

    async def preview_shared_documents(
        self,
        offering_type_id: int,
        cultural_education_level: Optional[str],
        vocational_qualification: Optional[str],
    ):
        """Preview bộ hồ sơ shared cho 1 thí sinh giả định (§5b/G5).

        Thin-client: admin nhập raw cultural/vocational → BE derive audience +
        resolve (NỀN + lớp khớp) + loại bằng TN khi completed_* (§6). Tái dùng
        nguyên machinery ĐỢT A (filter_shared_by_audience + mandatory_wins_merge
        + build_resolved_response) để preview KHỚP resolve thật.

        Chỉ tier shared (config panel không gắn path/method) → đủ cho nhu cầu
        gốc THCS↔THPT. LIEN_THONG/VLVH layer chưa tồn tại GĐ1 (known-limitation).
        """
        from types import SimpleNamespace

        from app.services.document_resolution_service import (
            build_resolved_response,
            compute_completed_doc_codes,
            compute_preview_audience_set,
            filter_shared_by_audience,
            mandatory_wins_merge,
        )

        # offering_type code cho chiều VLVH (cultural là chính cho THCS/THPT).
        ot_code = await self.document_group_repo.get_offering_type_code(
            offering_type_id
        )
        audience_set = compute_preview_audience_set(
            cultural_education_level, ot_code
        )

        shared_groups = await self.document_group_repo.get_shared_groups(
            offering_type_id
        )
        layers = filter_shared_by_audience(
            shared_groups, audience_set if audience_set else None
        )

        doc_map: dict = {}
        # Config preview = snapshot-shape (KHÔNG exclude_inactive) khớp create.
        mandatory_wins_merge(doc_map, layers, "shared", exclude_inactive=False)

        completed = compute_completed_doc_codes(
            SimpleNamespace(cultural_education_level=cultural_education_level)
        )
        return build_resolved_response(doc_map, completed)


