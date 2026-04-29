"""Unit tests for the DocumentActionPolicy permission matrix.

Closes admission audit follow-up #2 (memory
``project_admission_audit_followups``). The policy class is the single
source of truth shared by ``_compute_document_permissions`` (response
shaping) and ``_authorize_document_action`` (service-side guard) — if
either side drifts, both sides drift, so we lock the matrix here at
unit level.

Each parametrize row models one cell of the 5-action × N-status ×
M-role matrix. Adding a new role or a new doc status requires
extending these tests; that's the point.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

from app.core.constants import UserRole
from app.services.admission_document_policy import DocumentActionPolicy


# ---------------------------------------------------------------------------
# Lightweight stand-ins so we don't have to spin up the full ORM for a
# pure logic test. The policy reads only ``profile.status``,
# ``profile.applied_rules`` (not used here — caller resolves
# requires_upload), ``profile.__dict__.get('lead')``, and the
# user fields. ``__dict__`` access is what the policy uses to avoid
# triggering SQLAlchemy lazy-load in async contexts; plain attribute
# assignment on a dataclass populates ``__dict__`` correctly.
# ---------------------------------------------------------------------------


@dataclass
class _StubLead:
    unit_id: Optional[int] = None
    assigned_officer_id: Optional[int] = None


@dataclass
class _StubProfile:
    status: str = "draft"
    lead: Optional[_StubLead] = None


@dataclass
class _StubUser:
    id: int = 1
    role: UserRole = UserRole.OFFICER
    unit_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Fixtures: 5 canonical actor profiles
# ---------------------------------------------------------------------------


@pytest.fixture
def admin():
    return _StubUser(id=99, role=UserRole.ADMIN, unit_id=None)


@pytest.fixture
def manager_in_scope():
    return _StubUser(id=10, role=UserRole.MANAGER, unit_id=42)


@pytest.fixture
def manager_other_unit():
    return _StubUser(id=11, role=UserRole.MANAGER, unit_id=999)


@pytest.fixture
def officer_owner():
    return _StubUser(id=20, role=UserRole.OFFICER, unit_id=42)


@pytest.fixture
def officer_not_owner():
    return _StubUser(id=21, role=UserRole.OFFICER, unit_id=42)


@pytest.fixture
def profile_draft_lead42_owner20():
    """Profile in editable state, lead in unit 42, assigned to officer 20."""
    return _StubProfile(
        status="draft",
        lead=_StubLead(unit_id=42, assigned_officer_id=20),
    )


@pytest.fixture
def profile_approved_lead42_owner20():
    """Profile already approved (NOT editable), same lead context."""
    return _StubProfile(
        status="approved",
        lead=_StubLead(unit_id=42, assigned_officer_id=20),
    )


# ---------------------------------------------------------------------------
# Upload action
# ---------------------------------------------------------------------------


class TestUpload:
    """`upload`: editable profile + (owner | admin | manager_in_scope) +
    requires_upload + status in (missing, rejected)."""

    @pytest.mark.parametrize("doc_status", ["missing", "rejected"])
    def test_owner_can_upload(self, profile_draft_lead42_owner20, officer_owner, doc_status):
        policy = DocumentActionPolicy.for_(profile_draft_lead42_owner20, officer_owner)
        assert policy.authorize("upload", doc_status, requires_upload=True)

    def test_admin_can_upload(self, profile_draft_lead42_owner20, admin):
        policy = DocumentActionPolicy.for_(profile_draft_lead42_owner20, admin)
        assert policy.authorize("upload", "missing", requires_upload=True)

    def test_manager_same_unit_can_upload(
        self, profile_draft_lead42_owner20, manager_in_scope,
    ):
        policy = DocumentActionPolicy.for_(profile_draft_lead42_owner20, manager_in_scope)
        assert policy.authorize("upload", "missing", requires_upload=True)

    def test_manager_other_unit_cannot_upload(
        self, profile_draft_lead42_owner20, manager_other_unit,
    ):
        policy = DocumentActionPolicy.for_(profile_draft_lead42_owner20, manager_other_unit)
        assert not policy.authorize("upload", "missing", requires_upload=True)

    def test_officer_not_owner_cannot_upload(
        self, profile_draft_lead42_owner20, officer_not_owner,
    ):
        policy = DocumentActionPolicy.for_(profile_draft_lead42_owner20, officer_not_owner)
        assert not policy.authorize("upload", "missing", requires_upload=True)

    def test_paper_only_doc_blocks_upload(
        self, profile_draft_lead42_owner20, officer_owner,
    ):
        policy = DocumentActionPolicy.for_(profile_draft_lead42_owner20, officer_owner)
        assert not policy.authorize("upload", "missing", requires_upload=False)

    def test_uploaded_or_verified_doc_blocks_re_upload(
        self, profile_draft_lead42_owner20, officer_owner,
    ):
        policy = DocumentActionPolicy.for_(profile_draft_lead42_owner20, officer_owner)
        assert not policy.authorize("upload", "uploaded", requires_upload=True)
        assert not policy.authorize("upload", "verified", requires_upload=True)
        assert not policy.authorize("upload", "paper_submitted", requires_upload=True)

    def test_non_editable_profile_blocks_upload(
        self, profile_approved_lead42_owner20, officer_owner,
    ):
        policy = DocumentActionPolicy.for_(profile_approved_lead42_owner20, officer_owner)
        assert not policy.authorize("upload", "missing", requires_upload=True)


# ---------------------------------------------------------------------------
# Paper-submitted action
# ---------------------------------------------------------------------------


class TestPaperSubmitted:
    """`paper_submitted`: editable + (owner | admin | manager_in_scope) +
    !requires_upload + status == missing."""

    def test_owner_paper_only_missing_passes(
        self, profile_draft_lead42_owner20, officer_owner,
    ):
        policy = DocumentActionPolicy.for_(profile_draft_lead42_owner20, officer_owner)
        assert policy.authorize("paper_submitted", "missing", requires_upload=False)

    def test_paper_already_submitted_blocks(
        self, profile_draft_lead42_owner20, officer_owner,
    ):
        policy = DocumentActionPolicy.for_(profile_draft_lead42_owner20, officer_owner)
        assert not policy.authorize(
            "paper_submitted", "paper_submitted", requires_upload=False
        )

    def test_requires_upload_doc_blocks_paper(
        self, profile_draft_lead42_owner20, officer_owner,
    ):
        policy = DocumentActionPolicy.for_(profile_draft_lead42_owner20, officer_owner)
        assert not policy.authorize(
            "paper_submitted", "missing", requires_upload=True
        )

    def test_officer_not_owner_blocks_paper(
        self, profile_draft_lead42_owner20, officer_not_owner,
    ):
        policy = DocumentActionPolicy.for_(profile_draft_lead42_owner20, officer_not_owner)
        assert not policy.authorize(
            "paper_submitted", "missing", requires_upload=False
        )


# ---------------------------------------------------------------------------
# Verify action — reviewer-only (admin or manager-in-scope)
# ---------------------------------------------------------------------------


class TestVerify:
    """`verify`: reviewer_scope (admin or manager_in_scope) +
    status in (uploaded, paper_submitted)."""

    @pytest.mark.parametrize("doc_status", ["uploaded", "paper_submitted"])
    def test_admin_or_manager_can_verify(
        self, profile_draft_lead42_owner20, admin, manager_in_scope, doc_status,
    ):
        for actor in (admin, manager_in_scope):
            policy = DocumentActionPolicy.for_(profile_draft_lead42_owner20, actor)
            assert policy.authorize("verify", doc_status, requires_upload=True), (
                f"actor={actor.role}, status={doc_status}"
            )

    def test_owner_officer_cannot_verify(
        self, profile_draft_lead42_owner20, officer_owner,
    ):
        policy = DocumentActionPolicy.for_(profile_draft_lead42_owner20, officer_owner)
        assert not policy.authorize("verify", "uploaded", requires_upload=True)

    def test_manager_other_unit_cannot_verify(
        self, profile_draft_lead42_owner20, manager_other_unit,
    ):
        policy = DocumentActionPolicy.for_(profile_draft_lead42_owner20, manager_other_unit)
        assert not policy.authorize("verify", "uploaded", requires_upload=True)

    @pytest.mark.parametrize("doc_status", ["missing", "rejected", "verified"])
    def test_wrong_status_blocks_verify(
        self, profile_draft_lead42_owner20, admin, doc_status,
    ):
        policy = DocumentActionPolicy.for_(profile_draft_lead42_owner20, admin)
        assert not policy.authorize("verify", doc_status, requires_upload=True)


# ---------------------------------------------------------------------------
# Reject action
# ---------------------------------------------------------------------------


class TestReject:
    """`reject`: reviewer_scope + status in (uploaded, paper_submitted, verified)."""

    @pytest.mark.parametrize(
        "doc_status", ["uploaded", "paper_submitted", "verified"]
    )
    def test_admin_can_reject(
        self, profile_draft_lead42_owner20, admin, doc_status,
    ):
        policy = DocumentActionPolicy.for_(profile_draft_lead42_owner20, admin)
        assert policy.authorize("reject", doc_status, requires_upload=True)

    def test_officer_owner_cannot_reject(
        self, profile_draft_lead42_owner20, officer_owner,
    ):
        policy = DocumentActionPolicy.for_(profile_draft_lead42_owner20, officer_owner)
        assert not policy.authorize("reject", "uploaded", requires_upload=True)

    @pytest.mark.parametrize("doc_status", ["missing", "rejected"])
    def test_terminal_or_pre_upload_blocks_reject(
        self, profile_draft_lead42_owner20, admin, doc_status,
    ):
        policy = DocumentActionPolicy.for_(profile_draft_lead42_owner20, admin)
        assert not policy.authorize("reject", doc_status, requires_upload=True)


# ---------------------------------------------------------------------------
# Reset action
# ---------------------------------------------------------------------------


class TestReset:
    """`reset`: reviewer_scope + status != missing."""

    @pytest.mark.parametrize(
        "doc_status", ["uploaded", "paper_submitted", "verified", "rejected"]
    )
    def test_admin_can_reset_non_missing(
        self, profile_draft_lead42_owner20, admin, doc_status,
    ):
        policy = DocumentActionPolicy.for_(profile_draft_lead42_owner20, admin)
        assert policy.authorize("reset", doc_status, requires_upload=True)

    def test_missing_blocks_reset(
        self, profile_draft_lead42_owner20, admin,
    ):
        policy = DocumentActionPolicy.for_(profile_draft_lead42_owner20, admin)
        assert not policy.authorize("reset", "missing", requires_upload=True)

    def test_officer_cannot_reset(
        self, profile_draft_lead42_owner20, officer_owner,
    ):
        policy = DocumentActionPolicy.for_(profile_draft_lead42_owner20, officer_owner)
        assert not policy.authorize("reset", "uploaded", requires_upload=True)


# ---------------------------------------------------------------------------
# Defensive: unknown action denies — typo in caller never grants access
# ---------------------------------------------------------------------------


def test_unknown_action_returns_false(profile_draft_lead42_owner20, admin):
    policy = DocumentActionPolicy.for_(profile_draft_lead42_owner20, admin)
    assert not policy.authorize(
        "delete",  # type: ignore[arg-type]  # intentional typo
        "uploaded",
        requires_upload=True,
    )


# ---------------------------------------------------------------------------
# Edge: missing lead (data integrity slip) treats profile as no-owner
# ---------------------------------------------------------------------------


def test_missing_lead_blocks_owner_actions(officer_owner):
    profile = _StubProfile(status="draft", lead=None)
    policy = DocumentActionPolicy.for_(profile, officer_owner)
    # No lead → no owner / no manager-in-scope. Only admin can act.
    assert not policy.authorize("upload", "missing", requires_upload=True)
    assert not policy.authorize(
        "paper_submitted", "missing", requires_upload=False
    )


# ---------------------------------------------------------------------------
# BR1 (2026-04-29): profile-state matrix
# ---------------------------------------------------------------------------
#
# Pin the contract from the business-rule note:
#   APPLICANT_DOC_MUTATION_STATES =
#     {draft, submitted, rejected, resubmitted, revision_requested}
#   REVIEWER_DOC_MUTATION_BLOCKED_STATES = {enrolled}
#
# These are the per-state cells the previous "profile_editable" set
# (``draft, rejected, revision_requested``) didn't cover; they are the
# regression surface that motivated unifying service guards into the
# policy.


@pytest.mark.parametrize(
    "profile_status",
    ["draft", "submitted", "rejected", "resubmitted", "revision_requested"],
)
def test_applicant_states_allow_upload_and_paper_submitted(
    profile_status, officer_owner
):
    """Five states where applicant/officer may add evidence."""
    profile = _StubProfile(
        status=profile_status,
        lead=_StubLead(unit_id=42, assigned_officer_id=20),
    )
    policy = DocumentActionPolicy.for_(profile, officer_owner)
    assert policy.authorize("upload", "missing", requires_upload=True)
    assert policy.authorize(
        "paper_submitted", "missing", requires_upload=False
    )


@pytest.mark.parametrize(
    "profile_status",
    ["approved", "confirmed", "overridden", "enrolled", "withdrawn"],
)
def test_post_decision_states_block_upload_and_paper_submitted(
    profile_status, officer_owner
):
    """After a manager decision (approved+) or terminal (withdrawn),
    the applicant path is closed; further evidence requires the manager
    to re-open via revision_requested."""
    profile = _StubProfile(
        status=profile_status,
        lead=_StubLead(unit_id=42, assigned_officer_id=20),
    )
    policy = DocumentActionPolicy.for_(profile, officer_owner)
    assert not policy.authorize("upload", "missing", requires_upload=True)
    assert not policy.authorize(
        "paper_submitted", "missing", requires_upload=False
    )


@pytest.mark.parametrize(
    "profile_status",
    [
        "draft",
        "submitted",
        "approved",
        "rejected",
        "revision_requested",
        "resubmitted",
        "confirmed",
        "overridden",
        "withdrawn",
    ],
)
@pytest.mark.parametrize("action", ["verify", "reject", "reset"])
def test_reviewer_actions_allowed_pre_enrolled(
    profile_status, action, manager_in_scope
):
    """Manager-in-scope/admin may verify/reject/reset until enrolled."""
    profile = _StubProfile(
        status=profile_status,
        lead=_StubLead(unit_id=42, assigned_officer_id=20),
    )
    policy = DocumentActionPolicy.for_(profile, manager_in_scope)
    # Use a doc_status compatible with each action.
    doc_status = "uploaded" if action != "reset" else "verified"
    assert policy.authorize(action, doc_status, requires_upload=True)


@pytest.mark.parametrize("action", ["verify", "reject", "reset"])
def test_enrolled_blocks_all_reviewer_actions(action, manager_in_scope, admin):
    """After enrolment, AdmissionProfile docs are frozen — even admin
    can't flip them. Compliance contract: don't drift from the Student
    record materialised at enrolment."""
    profile = _StubProfile(
        status="enrolled",
        lead=_StubLead(unit_id=42, assigned_officer_id=20),
    )
    doc_status = "uploaded" if action != "reset" else "verified"
    for actor in (manager_in_scope, admin):
        policy = DocumentActionPolicy.for_(profile, actor)
        assert not policy.authorize(action, doc_status, requires_upload=True)


def test_enrolled_blocks_applicant_paths_too(officer_owner):
    """Belt-and-braces: applicant-side actions also can't reach an
    enrolled profile. APPLICANT_DOC_MUTATION_STATES does not include
    enrolled, so this is implied — pin it explicitly so an accidental
    set expansion later trips the test."""
    profile = _StubProfile(
        status="enrolled",
        lead=_StubLead(unit_id=42, assigned_officer_id=20),
    )
    policy = DocumentActionPolicy.for_(profile, officer_owner)
    assert not policy.authorize("upload", "missing", requires_upload=True)
    assert not policy.authorize(
        "paper_submitted", "missing", requires_upload=False
    )
