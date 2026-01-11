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

from app.models.admission_config import AdmissionPath, DocumentGroup
from app.models.user import User
from app.repositories.admission_path_repository import AdmissionPathRepository
from app.schemas.admission_path import (
    AdmissionPathCreate,
    AdmissionPathUpdate,
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
        
        # Step 1: Add shared documents
        for group in shared_groups:
            for item in group.items:
                doc_map[item.document_type_id] = (item, "shared")
        
        # Step 2: Override with method-specific documents
        for group in method_groups:
            for item in group.items:
                doc_map[item.document_type_id] = (item, "method_override")
        
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
