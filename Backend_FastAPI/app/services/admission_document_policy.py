"""Single source of truth for the document-action permission matrix.

Two sites consult the same 5-action matrix and previously hand-rolled
the rules in parallel:

- ``_compute_document_permissions`` (in ``_compute_frontend_fields``)
  — produces ``can_upload`` / ``can_verify`` / ``can_reject`` /
  ``can_reset`` / ``can_mark_paper_submitted`` flags for the
  ``documents_checklist`` response.
- ``_authorize_document_action`` (service-side gate, called from
  document mutation services) — enforces the same matrix at request
  time, raises :class:`PermissionDeniedError` on fail.

Keeping two implementations in sync via comments + tests is brittle:
update one branch and forget the other and the FE flag promises
something the BE will refuse, or vice versa. ``DocumentActionPolicy``
lifts the matrix into a small class both call sites consume.

Why a class instead of a free function?
---------------------------------------
The matrix needs derived booleans (``is_admin``, ``is_owner``,
``manager_in_scope``, ``reviewer_scope``, ``applicant_can_modify_docs``,
``reviewer_can_modify_docs``) that depend only on ``(profile, user)``
and never change between the five ``authorize()`` calls a single
response makes. Computing them once on construction avoids re-deriving
on each ``authorize()`` invocation and keeps the per-call signature
small (``action``, ``doc_status``, ``requires_upload``).

Profile-state contract (BR1, 2026-04-29)
----------------------------------------
- ``APPLICANT_DOC_MUTATION_STATES`` = the set in which an applicant or
  the owning officer may upload a file or mark a paper receipt
  (``draft / submitted / rejected / resubmitted / revision_requested``).
  Includes ``submitted`` / ``resubmitted`` because real applicants do
  add missing evidence after the initial submit before a manager rules
  on it.
- ``REVIEWER_DOC_MUTATION_BLOCKED_STATES`` = the set in which even a
  reviewer (manager-in-scope or admin) is barred from verify / reject /
  reset because the profile has crossed into student-record territory
  (currently just ``enrolled``). After enrolment a Student +
  StudentDocument exist and changing AdmissionProfile docs would drift
  from the historical record.

Allowed actions
---------------
``"upload"``: applicant/officer/manager-in-scope/admin uploads a file
for a profile in ``APPLICANT_DOC_MUTATION_STATES``, document is
missing or previously rejected.
``"paper_submitted"``: same actor, paper-only doc (``requires_upload
== False``), document still missing, profile in
``APPLICANT_DOC_MUTATION_STATES``.
``"verify"``: reviewer (admin/manager-in-scope), status is
``uploaded`` or ``paper_submitted``, profile NOT in
``REVIEWER_DOC_MUTATION_BLOCKED_STATES``.
``"reject"``: reviewer, status is anything past ``missing`` except
the rejected/missing terminal states (= ``uploaded`` /
``paper_submitted`` / ``verified``), profile NOT blocked.
``"reset"``: reviewer (admin/manager-in-scope) on any non-``missing`` doc of
a non-enrolled profile; OR the owning officer when the profile is in
``OWNER_DOC_MUTATION_STATES`` (draft / rejected / revision_requested) AND the
doc is NOT yet ``verified`` — a self-service undo of the officer's OWN
submission (uploaded / paper_submitted / rejected). The officer cannot reset
a manager-``verified`` doc ("đã duyệt thì không cho chỉnh sửa"); only a
reviewer can. verify/reject stay reviewer-only (review ≠ editing content).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.constants import UserRole
from app import models


DocumentAction = Literal[
    "upload",
    "paper_submitted",
    "verify",
    "reject",
    "reset",
]


# BR1 (2026-04-29): profile-state set in which an applicant/officer may
# add or replace evidence. Real-world workflow: applicant submits, a
# missing certificate arrives in the post a day later, officer uploads
# it before the manager begins review. Excluding ``submitted`` /
# ``resubmitted`` from this set (the previous "profile_editable" did)
# made the FE hide the upload button and the BE service guard reject
# the call — a real bug for that workflow.
APPLICANT_DOC_MUTATION_STATES: frozenset[str] = frozenset(
    {
        "draft",
        "submitted",
        "rejected",
        "resubmitted",
        "revision_requested",
    }
)

# BR1 (2026-04-29): profile states in which even a reviewer (admin /
# manager-in-scope) is barred from verify / reject / reset. After
# ``enrolled`` the system has materialised a Student + StudentDocument;
# mutating AdmissionProfile docs from this point would silently drift
# from the historical student record. Withdrawn is also terminal but
# pre-Student so we leave reviewer access open for evidence cleanup.
REVIEWER_DOC_MUTATION_BLOCKED_STATES: frozenset[str] = frozenset({"enrolled"})

# BR3 (2026-06-09): trạng thái hồ sơ mà OWNER (officer phụ trách) được tự RESET
# tài liệu — gỡ submission của chính mình để sửa khi hồ sơ chưa nộp/bị trả về.
# Khớp đúng các trạng thái officer được sửa hồ sơ (``profile.permissions.edit``).
# HẸP HƠN ``APPLICANT_DOC_MUTATION_STATES`` (vốn gồm submitted/resubmitted để
# officer THÊM evidence sau nộp): officer upload được ở submitted NHƯNG KHÔNG
# reset khi hồ sơ đang chờ reviewer thẩm định.
OWNER_DOC_MUTATION_STATES: frozenset[str] = frozenset(
    {"draft", "rejected", "revision_requested"}
)


# Cached derived flags — computed once per (profile, user) pair so the
# five authorize() calls a single response makes don't re-derive them.
@dataclass(frozen=True)
class _UserProfileContext:
    is_admin: bool
    is_owner: bool
    manager_in_scope: bool
    reviewer_scope: bool
    applicant_can_modify_docs: bool
    reviewer_can_modify_docs: bool
    owner_can_modify_docs: bool


def _build_context(
    profile: models.AdmissionProfile,
    user: models.User,
) -> _UserProfileContext:
    """Resolve role/ownership/scope flags from the (profile, user) pair.

    Uses ``profile.__dict__.get("lead")`` so a missing eager-load
    silently treats the profile as ``no lead`` (no owner, no
    manager-in-scope) rather than triggering a sync lazy-load that
    would crash with MissingGreenlet inside an async session — same
    defensive pattern as ``_compute_frontend_fields``.
    """
    lead = profile.__dict__.get("lead")
    is_admin = user.role == UserRole.ADMIN
    is_manager = user.role == UserRole.MANAGER
    is_owner = bool(
        lead is not None
        and lead.assigned_officer_id is not None
        and lead.assigned_officer_id == user.id
    )
    manager_in_scope = bool(
        is_manager
        and lead is not None
        and lead.unit_id is not None
        and lead.unit_id == user.unit_id
    )
    reviewer_scope = is_admin or manager_in_scope
    applicant_can_modify_docs = profile.status in APPLICANT_DOC_MUTATION_STATES
    reviewer_can_modify_docs = (
        profile.status not in REVIEWER_DOC_MUTATION_BLOCKED_STATES
    )
    owner_can_modify_docs = profile.status in OWNER_DOC_MUTATION_STATES
    return _UserProfileContext(
        is_admin=is_admin,
        is_owner=is_owner,
        manager_in_scope=manager_in_scope,
        reviewer_scope=reviewer_scope,
        applicant_can_modify_docs=applicant_can_modify_docs,
        reviewer_can_modify_docs=reviewer_can_modify_docs,
        owner_can_modify_docs=owner_can_modify_docs,
    )


@dataclass(frozen=True)
class DocumentActionPolicy:
    """Pre-resolved policy object for a single (profile, user) pair.

    Construct once per response/request and call ``authorize()`` per
    document action. The five flags computed on construction stay
    stable across the call sequence, so the per-action logic is just
    a small status-table lookup.

    Usage (response shaping)::

        policy = DocumentActionPolicy.for_(profile, user)
        for doc in docs:
            flags = {
                "can_upload": policy.authorize("upload", doc.status, doc.requires_upload),
                "can_verify": policy.authorize("verify", doc.status, doc.requires_upload),
                ...
            }

    Usage (service guard)::

        policy = DocumentActionPolicy.for_(profile, current_user)
        if not policy.authorize("verify", doc.status, doc.requires_upload):
            raise PermissionDeniedError(...)
    """

    ctx: _UserProfileContext
    profile_status: str = ""  # kept for future hooks / debug logging

    @classmethod
    def for_(
        cls,
        profile: models.AdmissionProfile,
        user: models.User,
    ) -> "DocumentActionPolicy":
        """Build a policy bound to ``(profile, user)``."""
        return cls(
            ctx=_build_context(profile, user),
            profile_status=profile.status,
        )

    def authorize(
        self,
        action: DocumentAction,
        doc_status: str,
        requires_upload: bool,
    ) -> bool:
        """Return True iff ``user`` may perform ``action`` on a document.

        Pure function over the cached context — no DB access. Callers
        that need to fail-closed map ``False`` to their own exception
        (e.g. the service-side guard raises ``PermissionDeniedError``).
        """
        ctx = self.ctx

        if action == "upload":
            return (
                requires_upload
                and ctx.applicant_can_modify_docs
                and (ctx.is_owner or ctx.is_admin or ctx.manager_in_scope)
                and doc_status in ("missing", "rejected")
            )
        if action == "paper_submitted":
            return (
                (not requires_upload)
                and ctx.applicant_can_modify_docs
                and (ctx.is_owner or ctx.is_admin or ctx.manager_in_scope)
                and doc_status == "missing"
            )
        if action == "verify":
            return (
                ctx.reviewer_scope
                and ctx.reviewer_can_modify_docs
                and doc_status in ("uploaded", "paper_submitted")
            )
        if action == "reject":
            return (
                ctx.reviewer_scope
                and ctx.reviewer_can_modify_docs
                and doc_status in ("uploaded", "paper_submitted", "verified")
            )
        if action == "reset":
            # BR3 (2026-06-09): reviewer (admin/manager-in-scope) reset bất kỳ
            # doc non-missing của hồ sơ non-enrolled; HOẶC owner (officer phụ
            # trách) tự reset khi hồ sơ ở draft/rejected/revision_requested —
            # NHƯNG owner KHÔNG được reset doc đã ``verified`` ("đã duyệt thì
            # không cho chỉnh sửa": officer chỉ gỡ submission CỦA CHÍNH MÌNH —
            # uploaded/paper_submitted/rejected — không xoá verification của
            # manager). Chỉ reviewer mới reset được doc đã verified. verify/
            # reject vẫn reviewer-only (thẩm định ≠ sửa nội dung).
            reviewer_ok = ctx.reviewer_scope and ctx.reviewer_can_modify_docs
            owner_ok = (
                ctx.is_owner
                and ctx.owner_can_modify_docs
                and doc_status != "verified"
            )
            return (reviewer_ok or owner_ok) and doc_status != "missing"

        # Unknown action — treat as deny so a typo in calling code
        # never grants access. Service guard surfaces the bug as a
        # PermissionDeniedError; response shaping skips the flag.
        return False
