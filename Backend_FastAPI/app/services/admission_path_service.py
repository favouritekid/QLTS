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

from sqlalchemy.ext.asyncio import AsyncSession

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
)

# Type alias for post-commit callback
PostCommitCallback = Callable[[], Coroutine[Any, Any, None]]


async def _noop_callback() -> None:
    """No-op callback for operations without side effects."""
    pass


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
        self,
        path_id: int
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
        self,
        academic_info_id: int
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
        self,
        data: AdmissionPathCreate,
        user: User
    ) -> Tuple[AdmissionPath, PostCommitCallback]:
        """
        Create a new AdmissionPath.
        
        Raises:
            DuplicateResourceError: If path already exists for offering + method
        """
        # Check for duplicate
        existing = await self.repo.get_path_by_offering_and_method(
            data.academic_info_id,
            data.admission_method_id
        )
        if existing:
            raise DuplicateResourceError(
                f"AdmissionPath already exists for academic_info={data.academic_info_id}, "
                f"method={data.admission_method_id}"
            )
        
        # Create path
        path = await self.repo.create({
            "academic_info_id": data.academic_info_id,
            "admission_method_id": data.admission_method_id,
            "display_name": data.display_name,
            "display_order": data.display_order,
            "visibility": data.visibility,
            "status": "draft",  # Always start as draft
        })
        
        return path, _noop_callback
    
    async def update_path(
        self,
        path: AdmissionPath,
        data: AdmissionPathUpdate,
        user: User
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
        if path.status == "archived":
            raise BusinessRuleViolation("Cannot update archived path")
        
        # Manager can only edit draft paths (Admin approves = activate)
        if user.role == "manager" and path.status != "draft":
            raise BusinessRuleViolation(
                f"Manager can only update paths in 'draft' status. "
                f"Current status: '{path.status}'. Contact Admin to modify."
            )
        
        update_data = data.model_dump(exclude_unset=True)
        path = await self.repo.update(path, update_data)
        
        return path, _noop_callback
    
    async def upsert_criteria(
        self,
        path: AdmissionPath,
        data: AdmissionCriteriaCreate,
        user: User
    ) -> Tuple[AdmissionPath, PostCommitCallback]:
        """
        Create or update admission criteria for a path.
        """
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
                **data.model_dump(exclude={"subject_groups"})
            )
            self.db.add(criteria)
            await self.db.flush() # Get ID
            
            path.criteria_id = criteria.id
            self.db.add(path)
        
        # 2. Update Subject Groups
        # Clear existing
        from sqlalchemy import delete
        await self.db.execute(
            delete(CriteriaSubjectGroup).where(CriteriaSubjectGroup.criteria_id == criteria.id)
        )
        
        # Add new
        for group_id in data.subject_groups:
            self.db.add(CriteriaSubjectGroup(
                criteria_id=criteria.id,
                subject_group_id=group_id
            ))
            
        await self.db.flush()
        return path, _noop_callback

    async def upsert_documents(
        self,
        path: AdmissionPath,
        documents: List[AdmissionPathDocumentUpsert],
        user: User
    ) -> Tuple[List[ResolvedDocumentResponse], PostCommitCallback]:
        """
        Update document requirements for a path.
        
        Logic:
        1. Find/Create method-specific DocumentGroup for this path's offering_type + method.
        2. Sync items in that group.
        """
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
            DocumentGroup.admission_method_id == method_id
        )
        result = await self.db.execute(stmt)
        group = result.scalars().first()
        
        if not group:
            # Create new group override
            code = f"DOC_{offering_type_id}_{method_id}_{datetime.now().strftime('%M%S')}"
            group = DocumentGroup(
                offering_type_id=offering_type_id,
                admission_method_id=method_id,
                code=code,
                name=f"Docs for Method {method_id} (Override)",
                is_active=True
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

            self.db.add(DocumentGroupItem(
                group_id=group.id,
                document_type_id=doc.document_type_id,
                is_mandatory=doc.is_mandatory,
                requires_upload=doc.requires_upload,
                submission_format=sub_fmt,
                display_order=doc.display_order
            ))
            
        await self.db.flush()
        
        # Return resolved list
        return await self.resolve_documents_for_path(path, offering_type_id)
    
    # =========================================================================
    # ACTIVATION LOGIC
    # =========================================================================
    
    async def validate_activation(
        self,
        path: AdmissionPath
    ) -> Tuple[bool, List[str]]:
        """
        Validate if path can be activated.
        
        Activation Checklist:
        1. Has criteria (via OfferingAdmissionConfig)
        2. Has document config
        3. Has quota > 0
        
        Returns:
            (can_activate, validation_errors)
        """
        errors: List[str] = []
        
        # Check 1: Status must be draft or inactive
        if path.status not in ["draft", "inactive"]:
            errors.append(f"Cannot activate path with status '{path.status}'")
        
        # Check 2: Must have academic_info with quota
        academic_info = path.academic_info
        if not academic_info:
            errors.append("Path has no academic info")
        elif not academic_info.annual_admission_quota or academic_info.annual_admission_quota <= 0:
            errors.append("Quota must be greater than 0")
        
        # Check 3: Should have criteria (via admission_configs)
        # This would require loading OfferingAdmissionConfig
        # For now, we'll add a placeholder check
        # In production, this would check for actual criteria
        
        # Check 4: Should have document config
        # This would check if DocumentGroup exists for this offering type + method
        
        can_activate = len(errors) == 0
        return can_activate, errors
    
    async def activate_path(
        self,
        path: AdmissionPath,
        user: User
    ) -> Tuple[AdmissionPath, PostCommitCallback]:
        """
        Activate an AdmissionPath.
        
        Raises:
            BusinessRuleViolation: If validation fails
        """
        can_activate, errors = await self.validate_activation(path)
        
        if not can_activate:
            raise BusinessRuleViolation(
                f"Cannot activate path: {'; '.join(errors)}"
            )
        
        # Activate
        path = await self.repo.update(path, {
            "status": "active",
            "activated_at": datetime.now(timezone.utc),
            "activated_by": user.id,
        })
        
        return path, _noop_callback
    
    async def deactivate_path(
        self,
        path: AdmissionPath,
        user: User
    ) -> Tuple[AdmissionPath, PostCommitCallback]:
        """
        Deactivate an active AdmissionPath.
        
        Raises:
            BusinessRuleViolation: If path is not active
        """
        if path.status != "active":
            raise BusinessRuleViolation(
                f"Cannot deactivate path with status '{path.status}'"
            )
        
        path = await self.repo.update(path, {
            "status": "inactive",
        })
        
        return path, _noop_callback
    
    async def archive_path(
        self,
        path: AdmissionPath,
        user: User
    ) -> Tuple[AdmissionPath, PostCommitCallback]:
        """
        Archive an AdmissionPath.
        
        Raises:
            BusinessRuleViolation: If path is active
        """
        if path.status == "active":
            raise BusinessRuleViolation(
                "Cannot archive active path. Deactivate first."
            )
        
        path = await self.repo.update(path, {
            "status": "archived",
        })
        
        return path, _noop_callback
    
    # =========================================================================
    # DOCUMENT OVERRIDE RESOLUTION
    # =========================================================================
    
    async def resolve_documents_for_path(
        self,
        path: AdmissionPath,
        offering_type_id: int
    ) -> Tuple[List[ResolvedDocumentResponse], PostCommitCallback]:
        """
        Resolve document requirements for a path.
        
        Override Resolution Rule:
        1. Load shared groups (admission_method_id = NULL)
        2. Load method-specific groups (admission_method_id = path.method)
        3. Merge: method-specific OVERRIDES shared for same document_type
        
        Returns:
            List of resolved documents with source indicator
        """
        shared_groups, method_groups = await self.repo.get_document_groups_for_path(
            offering_type_id,
            path.admission_method_id
        )
        
        # Build document map: document_type_id -> (item, source)
        doc_map: dict = {}
        
        if method_groups:
            # Case 1: Method-specific config exists -> FULL OVERRIDE
            # We ignore shared groups completely to allow "deleting" default items
            for group in method_groups:
                for item in group.items:
                    doc_map[item.document_type_id] = (item, "method_override")
        else:
            # Case 2: No specific config -> Use Shared Defaults
            for group in shared_groups:
                for item in group.items:
                    doc_map[item.document_type_id] = (item, "shared")
        
        # Step 3: Build response
        resolved: List[ResolvedDocumentResponse] = []
        for doc_type_id, (item, source) in doc_map.items():
            resolved.append(ResolvedDocumentResponse(
                document_type_id=item.document_type_id,
                document_type_code=item.document_type.code if item.document_type else "",
                document_type_name=item.document_type.name if item.document_type else "",
                is_mandatory=item.is_mandatory,
                requires_upload=item.requires_upload,
                submission_format=item.submission_format,
                display_order=item.display_order,
                source=source,
            ))
        
        # Sort by display_order
        resolved.sort(key=lambda x: x.display_order)
        
        return resolved, _noop_callback
    
    # =========================================================================
    # CONTROL FIELD COMPUTATION (for response)
    # =========================================================================
    
    def compute_available_actions(self, path: AdmissionPath) -> List[str]:
        """
        Compute available actions based on status.
        
        FRONTEND_ARCHITECTURE_V3.md: FE reads this, not computes.
        """
        actions: List[str] = []
        
        if path.status == "draft":
            actions = ["save", "activate", "archive"]
        elif path.status == "active":
            actions = ["save", "deactivate"]
        elif path.status == "inactive":
            actions = ["save", "activate", "archive"]
        elif path.status == "archived":
            actions = []  # No actions on archived
        
        return actions
    
    def compute_can_edit(self, path: AdmissionPath) -> bool:
        """
        Determine if path can be edited.
        """
        return path.status != "archived"
    
    async def compute_can_activate(self, path: AdmissionPath) -> bool:
        """
        Determine if path can be activated.
        """
        can_activate, _ = await self.validate_activation(path)
        return can_activate

    # =========================================================================
    # COVERAGE MATRIX
    # =========================================================================

    async def get_coverage_matrix(
        self,
        academic_info_id: int
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
            
            rows.append(CoverageRow(
                path_id=path.id,
                method_name=method_name,
                method_code=method_code,
                status=path.status,
                has_criteria=has_criteria,
                has_documents=has_documents,
                has_quota=has_quota,
                can_activate=can_activate,
                validation_errors=validation_errors,
            ))
        
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
