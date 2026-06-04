"""PR #13 — schema validation tests cho graduation proof (no DB)."""
from datetime import date

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.schemas.admission import (
    DocumentSubmissionRequest,
    GraduationProofUpdateRequest,
)


def test_submission_official_no_due_ok():
    r = DocumentSubmissionRequest(
        actual_submission_format="certified_copy",
        graduation_proof_kind="official_diploma",
    )
    assert r.graduation_proof_kind == "official_diploma"
    assert r.supplement_due_date is None


def test_submission_provisional_requires_due():
    with pytest.raises(PydanticValidationError):
        DocumentSubmissionRequest(
            actual_submission_format="certified_copy",
            graduation_proof_kind="provisional_cert",
        )


def test_submission_provisional_with_due_ok():
    r = DocumentSubmissionRequest(
        actual_submission_format="certified_copy",
        graduation_proof_kind="provisional_cert",
        supplement_due_date=date(2027, 6, 30),
    )
    assert r.supplement_due_date == date(2027, 6, 30)


def test_submission_no_graduation_fields_ok():
    r = DocumentSubmissionRequest(actual_submission_format="photo")
    assert r.graduation_proof_kind is None
    assert r.supplement_due_date is None


def test_submission_invalid_kind_rejected():
    with pytest.raises(PydanticValidationError):
        DocumentSubmissionRequest(
            actual_submission_format="photo",
            graduation_proof_kind="invalid_kind",
        )


def test_graduation_update_request_ok_and_invalid():
    r = GraduationProofUpdateRequest(kind="official_diploma")
    assert r.kind == "official_diploma"
    with pytest.raises(PydanticValidationError):
        GraduationProofUpdateRequest(kind="bad")
