# app/models/admission_config/__init__.py
"""
Admission Config Domain Models.

Architecture: RELATIONAL ONLY (no JSON for config)
Golden Rule: JSON = snapshot + user input history

Models:
- Subject: Individual subjects (math, physics...)
- SubjectGroup: Subject combinations (A00, D01...)
- AdmissionMethod: Admission methods (hoc_ba, thpt_qg...)
- AdmissionCriteria: Specific criteria per method
- OfferingAdmissionConfig: Link criteria to offering per year
- DocumentGroup: Document requirements by offering type
- ProfileSubjectScore: User-entered scores
- ProfileDocument: User-uploaded documents
"""

from .subject import Subject, SubjectGroup, SubjectGroupSubject
from .method import AdmissionMethod
from .criteria import AdmissionCriteria, CriteriaSubjectGroup
from .offering_config import OfferingAdmissionConfig
from .document_group import DocumentGroup, DocumentGroupItem
from .profile_data import ProfileSubjectScore, ProfileDocument

__all__ = [
    "Subject",
    "SubjectGroup", 
    "SubjectGroupSubject",
    "AdmissionMethod",
    "AdmissionCriteria",
    "CriteriaSubjectGroup",
    "OfferingAdmissionConfig",
    "DocumentGroup",
    "DocumentGroupItem",
    "ProfileSubjectScore",
    "ProfileDocument",
]
