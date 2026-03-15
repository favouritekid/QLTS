# app/models/student.py
"""
Student & StudentDocument Models.

Student:
- Created via AdmissionProfile.enroll() workflow (ACID transaction)
- student_code format: SV + YYYY + 4-digit random (e.g., SV20250012)
- One-to-one relationship with AdmissionProfile

StudentDocument:
- Converted from AdmissionProfile.documents_checklist during enrollment
- Stores uploaded documents for verification workflow

Security:
- student_code UNIQUE constraint prevents duplicate enrollment
- ACID transaction ensures all-or-nothing enrollment
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text, func
from sqlalchemy.orm import relationship, Mapped, mapped_column

from .base import Base


class Student(Base):
    """
    Student (Học viên đã nhập học).

    Created via ACID transaction in AdmissionProfile.enroll() flow:
    1. Generate unique student_code (SV + YYYY + random 4 digits)
    2. Create Student record
    3. Convert documents_checklist -> StudentDocument records
    4. Update AdmissionProfile.status = 'enrolled'
    5. Update Lead.status = 'converted'

    Security:
    - student_code UNIQUE index prevents duplicate codes
    - IntegrityError on conflict -> return 409 Conflict
    """
    __tablename__ = "student"

    # Primary Key
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    # Foreign Key to AdmissionProfile (One-to-One relationship)
    admission_profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("admission_profile.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # One admission profile = one student
        index=True,
        comment="Link to AdmissionProfile"
    )

    # Generated Student Code (Format: SV + YYYY + 0000)
    # Example: SV20250012
    student_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        unique=True,  # Critical: Prevent duplicate student codes
        index=True,
        comment="Student code (SV + year + 4-digit random)"
    )

    # Enrollment Date (When student was officially enrolled)
    enrollment_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="Official enrollment date (UTC)"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="Record creation time (UTC)"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        comment="Last update time (UTC)"
    )

    # Relationships
    admission_profile: Mapped["AdmissionProfile"] = relationship(
        "AdmissionProfile",
        back_populates="student"
    )

    documents: Mapped[list["StudentDocument"]] = relationship(
        "StudentDocument",
        back_populates="student",
        cascade="all, delete-orphan",
        order_by="StudentDocument.uploaded_at.desc()"
    )

    def __repr__(self):
        return f"<Student {self.student_code} (ID: {self.id})>"


class StudentDocument(Base):
    """
    StudentDocument (Tài liệu học viên).

    Converted from AdmissionProfile.documents_checklist during enrollment.
    Stores uploaded documents for verification workflow.

    Lifecycle:
    1. CREATED: During enrollment (from documents_checklist)
    2. VERIFICATION: Officer reviews and marks is_verified = True/False
    3. REJECTION: Officer adds reviewer_note if rejected

    Fields:
    - doc_type: Document code (HOC_BA, CCCD, BANG_TN, etc.)
    - file_path: S3 or local file path
    - is_verified: Verification status (default: False)
    - reviewer_note: Officer notes (for rejected docs)
    """
    __tablename__ = "student_document"

    # Primary Key
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    # Foreign Key to Student
    student_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("student.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Link to Student"
    )

    # Document Metadata
    doc_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Document code (HOC_BA, CCCD, BANG_TN, etc.)"
    )

    file_path: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        comment="S3 path or local file path"
    )

    # Verification Status
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
        comment="Verification status (True = verified, False = pending/rejected)"
    )

    reviewer_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Officer notes (especially for rejected documents)"
    )

    # Timestamps
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="Upload time (copied from documents_checklist)"
    )

    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Verification time (when officer marks is_verified)"
    )

    # Relationship
    student: Mapped["Student"] = relationship(
        "Student",
        back_populates="documents"
    )

    def __repr__(self):
        status = "✓" if self.is_verified else "✗"
        return f"<StudentDocument {status} {self.doc_type} for Student {self.student_id}>"
