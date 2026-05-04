# app/schemas/document_group.py
"""
Document Group Schemas.

Pydantic schemas for DocumentGroup API request/response.
"""

from typing import List, Optional
from pydantic import BaseModel, ConfigDict


# =============================================================================
# NESTED SCHEMAS
# =============================================================================

class DocumentTypeNested(BaseModel):
    """Nested document type info."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    code: str
    name: str


class AdmissionMethodNested(BaseModel):
    """Nested admission method info."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    code: str
    name: str


# =============================================================================
# ITEM SCHEMAS
# =============================================================================

class DocumentGroupItemCreate(BaseModel):
    """Request schema for creating a document item."""
    document_type_id: int
    is_mandatory: Optional[bool] = True
    requires_upload: Optional[bool] = True
    submission_format: Optional[str] = None
    display_order: Optional[int] = 0


class DocumentGroupItemResponse(BaseModel):
    """Response schema for document item."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    document_type_id: int
    is_mandatory: bool
    requires_upload: bool
    submission_format: Optional[str] = None
    display_order: int
    
    # Nested document type
    document_type: Optional[DocumentTypeNested] = None


# =============================================================================
# GROUP SCHEMAS
# =============================================================================

class DocumentGroupCreate(BaseModel):
    """Request schema for creating a document group."""
    offering_type_id: int
    admission_method_id: Optional[int] = None  # NULL = shared
    # phase1_06 (#184 Wave 1 PR-1C') — path-level override (tier 1
    # of 3-tier resolution). NULL = legacy method/shared override.
    # Service raises BusinessRuleViolation if set + offering_type
    # / method don't match the path.
    admission_path_id: Optional[int] = None
    code: str
    name: str
    description: Optional[str] = None
    is_active: Optional[bool] = True

    # Items to add
    items: Optional[List[DocumentGroupItemCreate]] = None


class DocumentGroupUpdate(BaseModel):
    """Request schema for updating a document group."""
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    # phase1_06 — admin can re-target a group to a different path
    # (or clear it back to method/shared with explicit ``null``).
    # ``model_dump(exclude_unset=True)`` distinguishes "key absent"
    # (= leave unchanged) from "key=null" (= clear path FK).
    admission_path_id: Optional[int] = None

    # Replace all items
    items: Optional[List[DocumentGroupItemCreate]] = None


class DocumentGroupResponse(BaseModel):
    """Response schema for document group."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    offering_type_id: int
    admission_method_id: Optional[int] = None
    # phase1_06 — REQUIRED in response (no default) so Pydantic /
    # FE Zod parse fails loudly when BE forgets to map the column.
    admission_path_id: Optional[int]
    code: str
    name: str
    description: Optional[str] = None
    is_active: bool

    # Nested method (for display)
    admission_method: Optional[AdmissionMethodNested] = None

    # Items
    items: List[DocumentGroupItemResponse] = []


class DocumentGroupListResponse(BaseModel):
    """Response for list of document groups."""
    total: int
    items: List[DocumentGroupResponse]
