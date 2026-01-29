# app/repositories/admission_repository.py
"""
✅ SPRINT 6: Admission Repository

Admission-specific data access layer.
Handles AdmissionProfile, Student CRUD operations and validation queries.

Benefits:
- Centralized admission query logic
- Optimized eager loading for profile views
- Testable with repository mocks
- Separates SQL from business logic
"""

from datetime import datetime
from typing import List, Optional, Tuple
import unicodedata

from sqlalchemy import select, or_, and_, func, desc, asc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app import models
from app.models import ProfileSubjectScore, ProfileDocument
from app.repositories.base import BaseRepository


class AdmissionRepository(BaseRepository[models.AdmissionProfile]):
    """Repository for AdmissionProfile model operations."""

    def __init__(self, db: AsyncSession):
        """
        Initialize Admission repository.
        
        Args:
            db: SQLAlchemy async session
        """
        super().__init__(db, models.AdmissionProfile)

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        **filters
    ) -> List[models.AdmissionProfile]:
        """
        Get filtered list of admission profiles with pagination.
        
        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            unit_id: Filter by lead.unit_id (for IDOR protection)
            **filters: Filter parameters (status, lead_id)
            
        Returns:
            List of AdmissionProfile instances
        """
        query = (
            select(models.AdmissionProfile)
            .join(models.Lead)  # Join for unit_id filter
            .options(
                joinedload(models.AdmissionProfile.lead),
                selectinload(models.AdmissionProfile.student),
                selectinload(models.AdmissionProfile.subject_scores).selectinload(ProfileSubjectScore.subject),
                selectinload(models.AdmissionProfile.documents).joinedload(ProfileDocument.document_type),
            )
            .offset(skip)
            .limit(limit)
        )
        
        # IDOR Filter: Filter at DB level for non-admin users
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)
        
        if filters.get("status"):
            query = query.where(models.AdmissionProfile.status == filters["status"])
        
        if filters.get("lead_id"):
            query = query.where(models.AdmissionProfile.lead_id == filters["lead_id"])
            
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_filtered_with_count(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        search: Optional[str] = None,
        statuses: Optional[List[str]] = None,
        major_ids: Optional[List[int]] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        sort_by: str = "created_at",
        order: str = "desc",
        **filters
    ) -> Tuple[List[models.AdmissionProfile], int]:
        """
        Get filtered list of admission profiles with pagination AND total count.

        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            unit_id: Filter by lead.unit_id (for IDOR protection)
            search: Search term for name, email, citizen_id
            statuses: List of statuses to filter (multi-select)
            major_ids: List of major/program IDs to filter
            date_from: Filter profiles created after this date
            date_to: Filter profiles created before this date
            sort_by: Field to sort by (created_at, updated_at, full_name)
            order: Sort order (asc, desc)
            **filters: Additional filter parameters (status, lead_id)

        Returns:
            Tuple of (List of AdmissionProfile instances, total_count)
        """
        # Base query for filtering
        base_conditions = []

        # IDOR Filter: Filter at DB level for non-admin users
        if unit_id is not None:
            base_conditions.append(models.Lead.unit_id == unit_id)

        # Multi-status filter (new)
        if statuses and len(statuses) > 0:
            base_conditions.append(models.AdmissionProfile.status.in_(statuses))
        # Backward compatibility: single status from filters
        elif filters.get("status"):
            base_conditions.append(models.AdmissionProfile.status == filters["status"])

        if filters.get("lead_id"):
            base_conditions.append(models.AdmissionProfile.lead_id == filters["lead_id"])

        # Search filter (name, email, citizen_id)
        if search:
            # Normalize Unicode for Vietnamese diacritics
            normalized_search = unicodedata.normalize('NFC', search.strip())
            search_term = f"%{normalized_search}%"
            search_conditions = or_(
                models.Lead.full_name.ilike(search_term),
                models.Lead.email.ilike(search_term),
                models.AdmissionProfile.citizen_id.ilike(search_term),
            )
            base_conditions.append(search_conditions)

        # Major/Program filter via Lead.offering_id
        if major_ids and len(major_ids) > 0:
            base_conditions.append(models.Lead.offering_id.in_(major_ids))

        # Date range filter
        if date_from:
            base_conditions.append(models.AdmissionProfile.created_at >= date_from)
        if date_to:
            base_conditions.append(models.AdmissionProfile.created_at <= date_to)

        # Count query
        count_query = (
            select(func.count(models.AdmissionProfile.id))
            .join(models.Lead)
        )
        if base_conditions:
            count_query = count_query.where(and_(*base_conditions))

        count_result = await self.db.execute(count_query)
        total_count = count_result.scalar() or 0

        # Determine sort column and order
        sort_column = models.AdmissionProfile.created_at  # default
        if sort_by == "updated_at":
            sort_column = models.AdmissionProfile.updated_at
        elif sort_by == "full_name":
            sort_column = models.Lead.full_name
        elif sort_by == "status":
            sort_column = models.AdmissionProfile.status

        order_func = desc if order == "desc" else asc

        # Data query with pagination
        data_query = (
            select(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                selectinload(models.AdmissionProfile.lead).options(
                    selectinload(models.Lead.offering).options(
                        selectinload(models.ProgramOffering.program),
                    ),
                ),
                selectinload(models.AdmissionProfile.student),
                selectinload(models.AdmissionProfile.subject_scores).selectinload(ProfileSubjectScore.subject),
                selectinload(models.AdmissionProfile.documents).joinedload(ProfileDocument.document_type),
            )
            .order_by(order_func(sort_column))
            .offset(skip)
            .limit(limit)
        )
        if base_conditions:
            data_query = data_query.where(and_(*base_conditions))

        result = await self.db.execute(data_query)
        profiles = list(result.scalars().all())

        # Extract program_name while in async context (avoids MissingGreenlet during serialization)
        for profile in profiles:
            program_name = None
            if profile.lead and profile.lead.offering and profile.lead.offering.program:
                program_name = profile.lead.offering.program.name
            # Set as transient attribute for Pydantic serialization
            object.__setattr__(profile, 'program_name', program_name)

        return profiles, total_count

    # =========================================================================
    # CREATE PROFILE METHODS
    # =========================================================================

    async def get_profile_by_lead_id(
        self,
        lead_id: int
    ) -> Optional[models.AdmissionProfile]:
        """
        Get admission profile by lead ID.
        
        Args:
            lead_id: Lead ID
            
        Returns:
            AdmissionProfile or None
        """
        stmt = select(models.AdmissionProfile).where(
            models.AdmissionProfile.lead_id == lead_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_lead_with_offering(
        self,
        lead_id: int
    ) -> Optional[models.Lead]:
        """
        Get lead with offering and admission_profile loaded.
        
        ✅ SPRINT 6: For create_profile validation.
        
        Args:
            lead_id: Lead ID
            
        Returns:
            Lead with offering and admission_profile relationships loaded
        """
        stmt = (
            select(models.Lead)
            .where(models.Lead.id == lead_id)
            .options(
                joinedload(models.Lead.offering),
                selectinload(models.Lead.admission_profile),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_consultation_for_lead(
        self,
        lead_id: int
    ) -> Optional[models.Consultation]:
        """
        Get the latest consultation for a lead (by consultation_date).

        ✅ EDGE CASE #9 FIX: Validate consultation completeness before admission.

        Args:
            lead_id: Lead ID

        Returns:
            Latest Consultation with status loaded, or None if no consultations
        """
        stmt = (
            select(models.Consultation)
            .where(
                models.Consultation.lead_id == lead_id,
                models.Consultation.deleted_at.is_(None)  # Exclude soft-deleted
            )
            .options(
                joinedload(models.Consultation.consultation_status),
                joinedload(models.Consultation.officer),
            )
            .order_by(models.Consultation.consultation_date.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_profile_by_id_with_lead(
        self,
        profile_id: int
    ) -> Optional[models.AdmissionProfile]:
        """
        Get profile with lead relationship loaded.
        
        ✅ SPRINT 6: For get_profile and IDOR checks.
        
        Args:
            profile_id: AdmissionProfile ID
            
        Returns:
            AdmissionProfile with lead and student relationships
        """
        stmt = (
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == profile_id)
            .options(
                joinedload(models.AdmissionProfile.lead),
                selectinload(models.AdmissionProfile.student),
                selectinload(models.AdmissionProfile.subject_scores).selectinload(ProfileSubjectScore.subject),
                selectinload(models.AdmissionProfile.documents).joinedload(ProfileDocument.document_type),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def reload_profile_with_lead(
        self,
        profile_id: int
    ) -> Optional[models.AdmissionProfile]:
        """
        Reload profile after creation with lead relationship.
        
        ✅ SPRINT 6: For create_profile response.
        
        Args:
            profile_id: AdmissionProfile ID
            
        Returns:
            AdmissionProfile with lead and student loaded
        """
        stmt = (
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == profile_id)
            .options(
                joinedload(models.AdmissionProfile.lead),
                selectinload(models.AdmissionProfile.student),  # Prevent MissingGreenlet
                selectinload(models.AdmissionProfile.subject_scores).selectinload(ProfileSubjectScore.subject),
                selectinload(models.AdmissionProfile.documents).joinedload(ProfileDocument.document_type),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()

    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================

    async def check_citizen_id_exists(
        self,
        citizen_id: str,
        academic_year: int,
        exclude_profile_id: Optional[int] = None
    ) -> Optional[models.AdmissionProfile]:
        """
        Check if citizen_id is already used by another profile IN THE SAME YEAR.
        
        ✅ UPDATED: Now filters by academic_year to allow same citizen
        to apply in different years.
        
        Args:
            citizen_id: Citizen ID to check
            academic_year: Academic year to check within
            exclude_profile_id: Profile ID to exclude (current profile)
            
        Returns:
            Existing AdmissionProfile or None
        """
        stmt = select(models.AdmissionProfile).where(
            models.AdmissionProfile.citizen_id == citizen_id,
            models.AdmissionProfile.academic_year == academic_year,
        )
        if exclude_profile_id:
            stmt = stmt.where(models.AdmissionProfile.id != exclude_profile_id)
        
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def check_citizen_id_enrolled(
        self,
        citizen_id: str
    ) -> Optional[models.Student]:
        """
        Check if citizen_id is already enrolled (has Student record).
        
        ✅ SPRINT 6: For submit_and_evaluate validation.
        
        Args:
            citizen_id: Citizen ID to check
            
        Returns:
            Existing Student or None
        """
        stmt = (
            select(models.Student)
            .join(models.AdmissionProfile)
            .where(models.AdmissionProfile.citizen_id == citizen_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def check_student_code_exists(
        self,
        student_code: str
    ) -> bool:
        """
        Check if student_code already exists.
        
        ✅ SPRINT 6: For enroll_student code generation.
        
        Args:
            student_code: Student code to check
            
        Returns:
            True if exists, False otherwise
        """
        stmt = select(models.Student).where(
            models.Student.student_code == student_code
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    # =========================================================================
    # DOCUMENT MANAGEMENT METHODS (JSONB → Relational Migration)
    # =========================================================================

    async def initialize_documents_for_profile(
        self,
        profile_id: int,
        document_type_codes: List[str]
    ) -> List[models.ProfileDocument]:
        """
        Initialize ProfileDocument records for a new admission profile.

        Replaces: _generate_documents_checklist() JSONB generation

        Args:
            profile_id: AdmissionProfile ID
            document_type_codes: List of document type codes (e.g., ["HOC_BA", "CCCD"])

        Returns:
            List of created ProfileDocument records with status="missing"
        """
        # Fetch document types by codes
        stmt = select(models.ConfigDocumentType).where(
            models.ConfigDocumentType.code.in_(document_type_codes)
        )
        result = await self.db.execute(stmt)
        doc_types = list(result.scalars().all())

        # Create ProfileDocument records
        created_docs = []
        for doc_type in doc_types:
            doc = models.ProfileDocument(
                profile_id=profile_id,
                document_type_id=doc_type.id,
                status="missing",
                file_path=None,
                uploaded_at=None,
            )
            self.db.add(doc)
            created_docs.append(doc)

        await self.db.flush()  # Get IDs without committing
        return created_docs

    async def get_document_by_type(
        self,
        profile_id: int,
        document_type_code: str
    ) -> Optional[models.ProfileDocument]:
        """
        Get ProfileDocument by profile_id and document type code.

        Replaces: JSONB checklist filtering in upload_document()

        Args:
            profile_id: AdmissionProfile ID
            document_type_code: Document type code (e.g., "HOC_BA")

        Returns:
            ProfileDocument record or None
        """
        stmt = (
            select(models.ProfileDocument)
            .join(models.ConfigDocumentType)
            .where(
                models.ProfileDocument.profile_id == profile_id,
                models.ConfigDocumentType.code == document_type_code,
            )
            .options(joinedload(models.ProfileDocument.document_type))
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_document_status(
        self,
        profile_id: int,
        document_type_code: str,
        status: str,
        file_path: Optional[str] = None,
        uploaded_at = None,  # datetime or str (for backward compatibility)
        actual_submission_format: Optional[str] = None,
    ) -> Optional[models.ProfileDocument]:
        """
        Update ProfileDocument status and file metadata.

        Replaces: JSONB checklist mutation with flag_modified() in upload_document()

        Args:
            profile_id: AdmissionProfile ID
            document_type_code: Document type code
            status: New status (missing | uploaded | verified | rejected)
            file_path: File path (if uploaded)
            uploaded_at: Upload timestamp as datetime (if uploaded)
            actual_submission_format: Declared document format (original | certified_copy | photo)

        Returns:
            Updated ProfileDocument or None if not found
        """
        doc = await self.get_document_by_type(profile_id, document_type_code)
        if not doc:
            return None

        doc.status = status
        if file_path:
            doc.file_path = file_path
        if uploaded_at is not None:
            # Handle both datetime and string (backward compatibility)
            if isinstance(uploaded_at, str):
                from datetime import datetime
                # Parse ISO format string to datetime
                doc.uploaded_at = datetime.fromisoformat(uploaded_at.replace('Z', '+00:00'))
            else:
                doc.uploaded_at = uploaded_at
        if actual_submission_format:
            doc.actual_submission_format = actual_submission_format

        return doc

    async def get_uploaded_documents(
        self,
        profile_id: int
    ) -> List[models.ProfileDocument]:
        """
        Get all uploaded documents for a profile.

        Replaces: JSONB checklist filtering in enroll_student()

        Args:
            profile_id: AdmissionProfile ID

        Returns:
            List of ProfileDocument with status="uploaded" and file_path not null
        """
        stmt = (
            select(models.ProfileDocument)
            .where(
                models.ProfileDocument.profile_id == profile_id,
                or_(
                    and_(models.ProfileDocument.status == "uploaded", models.ProfileDocument.file_path.isnot(None)),
                    models.ProfileDocument.status == "verified",  # Also include verified (uploaded + checked)
                    models.ProfileDocument.status == "paper_submitted"
                )
            )
            .options(joinedload(models.ProfileDocument.document_type))
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_all_documents(
        self,
        profile_id: int
    ) -> List[models.ProfileDocument]:
        """
        Get ALL documents for a profile (regardless of status).

        Phase 7: For completion percentage calculation in _compute_frontend_fields

        Args:
            profile_id: AdmissionProfile ID

        Returns:
            List of all ProfileDocument for this profile
        """
        stmt = (
            select(models.ProfileDocument)
            .where(models.ProfileDocument.profile_id == profile_id)
            .options(joinedload(models.ProfileDocument.document_type))
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def mark_paper_submitted(
        self,
        profile_id: int,
        document_type_code: str,
        officer_id: int,
        actual_submission_format: Optional[str] = None,
    ) -> Optional[models.ProfileDocument]:
        """
        Mark a document as paper submitted (officer confirms receipt).

        For documents where requires_upload=false.

        Args:
            profile_id: AdmissionProfile ID
            document_type_code: Document type code
            officer_id: ID of officer confirming receipt
            actual_submission_format: Declared document format (original | certified_copy | photo)

        Returns:
            Updated ProfileDocument or None if not found
        """
        from datetime import datetime, timezone

        doc = await self.get_document_by_type(profile_id, document_type_code)
        if not doc:
            return None

        doc.status = "paper_submitted"
        doc.paper_submitted_at = datetime.now(timezone.utc)
        doc.paper_submitted_by = officer_id
        if actual_submission_format:
            doc.actual_submission_format = actual_submission_format

        return doc

    async def reset_document(
        self,
        profile_id: int,
        document_type_code: str,
    ) -> Optional[models.ProfileDocument]:
        """
        Reset a document to 'missing' status (undo submission).

        Use case: User accidentally clicked "Đã nộp" or uploaded wrong file.
        Simple undo without complex audit trail.

        Args:
            profile_id: AdmissionProfile ID
            document_type_code: Document type code

        Returns:
            Updated ProfileDocument or None if not found
        """
        doc = await self.get_document_by_type(profile_id, document_type_code)
        if not doc:
            return None

        # Reset to missing state
        doc.status = "missing"
        doc.file_path = None
        doc.actual_submission_format = None
        doc.verified_format = None
        doc.uploaded_at = None
        doc.verified_at = None
        doc.paper_submitted_at = None
        doc.paper_submitted_by = None
        doc.rejected_at = None
        doc.rejected_by = None
        doc.rejection_reason = None

        return doc

    async def reject_document(
        self,
        profile_id: int,
        document_type_code: str,
        officer_id: int,
        reason: str,
    ) -> Optional[models.ProfileDocument]:
        """
        Reject a document with reason.
        
        User will need to re-upload or resubmit.
        
        Args:
            profile_id: AdmissionProfile ID
            document_type_code: Document type code
            officer_id: ID of officer rejecting
            reason: Rejection reason
            
        Returns:
            Updated ProfileDocument or None if not found
        """
        from datetime import datetime, timezone
        
        doc = await self.get_document_by_type(profile_id, document_type_code)
        if not doc:
            return None
        
        doc.status = "rejected"
        doc.rejection_reason = reason
        doc.rejected_at = datetime.now(timezone.utc)
        doc.rejected_by = officer_id
        
        return doc

    async def confirm_document_format(
        self,
        profile_id: int,
        document_type_code: str,
        verified_format: str,
        officer_id: int,
    ) -> Optional[models.ProfileDocument]:
        """
        Confirm document format and mark as verified.

        This method performs the full verification:
        1. Updates verified_format (original | certified_copy | photo)
        2. Sets status to 'verified'
        3. Records verification timestamp
        4. Records officer who verified

        Args:
            profile_id: AdmissionProfile ID
            document_type_code: Document type code
            verified_format: original | certified_copy | photo
            officer_id: ID of officer performing verification

        Returns:
            Updated ProfileDocument or None
        """
        from datetime import datetime, timezone

        doc = await self.get_document_by_type(profile_id, document_type_code)
        if not doc:
            return None

        # Full verification update
        doc.verified_format = verified_format
        doc.status = "verified"
        doc.verified_at = datetime.now(timezone.utc)
        doc.verified_by = officer_id

        return doc

    # =========================================================================
    # CONFIRMATION TOKEN METHODS (Magic Link)
    # =========================================================================

    async def create_confirmation_token(
        self,
        profile_id: int,
        token: str,
        expires_at,
    ) -> models.AdmissionConfirmationToken:
        """
        Create a new confirmation token for a profile.
        
        Invalidates any existing token for the same profile first.
        
        Args:
            profile_id: AdmissionProfile ID
            token: URL-safe random token string
            expires_at: Token expiration timestamp
            
        Returns:
            Created AdmissionConfirmationToken
        """
        # Delete any existing token for this profile
        await self.invalidate_existing_tokens(profile_id)
        
        # Create new token
        token_obj = models.AdmissionConfirmationToken(
            profile_id=profile_id,
            token=token,
            expires_at=expires_at,
        )
        self.db.add(token_obj)
        await self.db.flush()
        return token_obj

    async def get_token_by_value(
        self,
        token: str
    ) -> Optional[models.AdmissionConfirmationToken]:
        """
        Get confirmation token with profile and lead relationships loaded.
        
        Args:
            token: Token string from URL
            
        Returns:
            AdmissionConfirmationToken with profile.lead loaded, or None
        """
        stmt = (
            select(models.AdmissionConfirmationToken)
            .where(models.AdmissionConfirmationToken.token == token)
            .options(
                joinedload(models.AdmissionConfirmationToken.profile)
                .joinedload(models.AdmissionProfile.lead)
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def increment_token_attempts(
        self,
        token_obj: models.AdmissionConfirmationToken,
        max_attempts: int = 5
    ) -> None:
        """
        Increment failed CCCD verification attempt count.
        
        Locks token if max attempts exceeded.
        
        Args:
            token_obj: Token to update
            max_attempts: Max attempts before locking (from config)
        """
        from datetime import datetime, timezone
        
        token_obj.attempt_count += 1
        if token_obj.attempt_count >= max_attempts:
            token_obj.locked_at = datetime.now(timezone.utc)
        await self.db.flush()

    async def mark_token_confirmed(
        self,
        token_obj: models.AdmissionConfirmationToken,
        confirmed_via: str = "magic_link"
    ) -> None:
        """
        Mark token as used and update profile status to confirmed.
        
        Args:
            token_obj: Token to mark as confirmed
            confirmed_via: Confirmation method (for analytics)
        """
        from datetime import datetime, timezone
        
        now = datetime.now(timezone.utc)
        
        # Mark token as used
        token_obj.confirmed_at = now
        
        # Update profile status and analytics fields
        profile = token_obj.profile
        profile.status = "confirmed"
        profile.confirmed_at = now
        profile.confirmed_via = confirmed_via
        
        await self.db.flush()

    async def invalidate_existing_tokens(
        self,
        profile_id: int
    ) -> None:
        """
        Delete any existing tokens for a profile.
        
        Called before creating a new token (for resend functionality).
        
        Args:
            profile_id: AdmissionProfile ID
        """
        from sqlalchemy import delete
        
        stmt = delete(models.AdmissionConfirmationToken).where(
            models.AdmissionConfirmationToken.profile_id == profile_id
        )
        await self.db.execute(stmt)
        await self.db.flush()
    async def get_profile_scores(self, profile_id: int) -> list:
        """
        Get all subject scores for a profile.
        
        Args:
            profile_id: AdmissionProfile ID
            
        Returns:
            List of ProfileSubjectScore
        """
        from app.models.admission_config.profile_data import ProfileSubjectScore
        from sqlalchemy.orm import selectinload
        
        result = await self.db.execute(
            select(ProfileSubjectScore)
            .options(selectinload(ProfileSubjectScore.subject))
            .where(ProfileSubjectScore.profile_id == profile_id)
        )
        return result.scalars().all()

    async def update_profile_scores(
        self, 
        profile_id: int, 
        subject_scores: dict[str, float]
    ) -> list:
        """
        Update subject scores for a profile (Bulk Upsert).

        Strategy:
        1. Resolve subject codes to IDs
        2. Bulk update/insert into ProfileSubjectScore
        
        Args:
            profile_id: AdmissionProfile ID
            subject_scores: Dict of {subject_code: score}
        """
        from app.models.admission_config.profile_data import ProfileSubjectScore
        from app.models.admission_config.subject import Subject
        from sqlalchemy import delete, select
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        if not subject_scores:
            return []

        # 1. Resolve Subject Codes -> IDs
        # TODO: Caching mechanism for Subject IDs if performance needed
        stmt = select(Subject.id, Subject.code).where(
            Subject.code.in_(subject_scores.keys())
        )
        result = await self.db.execute(stmt)
        subjects = result.all() # [(id, code), ...]
        
        subject_map = {row.code: row.id for row in subjects}
        
        # Check for invalid codes
        invalid_codes = set(subject_scores.keys()) - set(subject_map.keys())
        if invalid_codes:
            # We silently ignore invalid codes or could raise error
            # For now, let's ignore to be robust, but log warning in service
            pass

        # 2. Sync Strategy: Delete scores NOT in the new list
        # This prevents "orphaned" scores if applicant changes subject group (e.g., A00 -> D01)
        valid_subject_ids = list(subject_map.values())
        
        if valid_subject_ids:
            delete_stmt = delete(ProfileSubjectScore).where(
                ProfileSubjectScore.profile_id == profile_id,
                ProfileSubjectScore.subject_id.notin_(valid_subject_ids)
            )
        else:
            # If no valid subjects provided but function called (and not None), clear all scores
            delete_stmt = delete(ProfileSubjectScore).where(
                ProfileSubjectScore.profile_id == profile_id
            )
            
        await self.db.execute(delete_stmt)

        # 3. Prepare Data for Upsert
        upsert_data = []
        for code, score in subject_scores.items():
            if code in subject_map:
                upsert_data.append({
                    "profile_id": profile_id,
                    "subject_id": subject_map[code],
                    "score": score,
                })
        
        if not upsert_data:
            return []

        # 4. Execute Upsert (PostgreSQL specific)
        # INSERT ... ON CONFLICT (profile_id, subject_id) DO UPDATE SET score = EXCLUDED.score
        stmt = pg_insert(ProfileSubjectScore).values(upsert_data)
        stmt = stmt.on_conflict_do_update(
            index_elements=['profile_id', 'subject_id'], # uq_profile_subject_score
            set_=dict(score=stmt.excluded.score)
        )
        
        await self.db.execute(stmt)
        
        # Return updated scores
        return await self.get_profile_scores(profile_id)
