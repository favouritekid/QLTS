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
The matrix needs five derived booleans (``is_admin``, ``is_owner``,
``manager_in_scope``, ``reviewer_scope``, ``profile_editable``) that
depend only on ``(profile, user)`` and never change between the five
``authorize()`` calls a single response makes. Computing them once on
construction avoids re-deriving on each ``authorize()`` invocation
and keeps the per-call signature small (``action``, ``doc_status``,
``requires_upload``).

Allowed actions
---------------
``"upload"``: applicant/officer/manager-in-scope/admin uploads a file
for an editable profile, document is missing or previously rejected.
``"paper_submitted"``: same actor, paper-only doc (``requires_upload
== False``), document still missing.
``"verify"``: reviewer (admin/manager-in-scope), status is
``uploaded`` or ``paper_submitted``.
``"reject"``: reviewer, status is anything past ``missing`` except
the rejected/missing terminal states (= ``uploaded`` / ``paper_submitted`` /
``verified``).
``"reset"``: reviewer, anything except ``missing``.
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


# Cached derived flags — computed once per (profile, user) pair so the
# five authorize() calls a single response makes don't re-derive them.
@dataclass(frozen=True)
class _UserProfileContext:
    is_admin: bool
    is_owner: bool
    manager_in_scope: bool
    reviewer_scope: bool
    profile_editable: bool


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
    profile_editable = profile.status in (
        "draft",
        "rejected",
        "revision_requested",
    )
    return _UserProfileContext(
        is_admin=is_admin,
        is_owner=is_owner,
        manager_in_scope=manager_in_scope,
        reviewer_scope=reviewer_scope,
        profile_editable=profile_editable,
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
                and ctx.profile_editable
                and (ctx.is_owner or ctx.is_admin or ctx.manager_in_scope)
                and doc_status in ("missing", "rejected")
            )
        if action == "paper_submitted":
            return (
                (not requires_upload)
                and ctx.profile_editable
                and (ctx.is_owner or ctx.is_admin or ctx.manager_in_scope)
                and doc_status == "missing"
            )
        if action == "verify":
            return ctx.reviewer_scope and doc_status in (
                "uploaded",
                "paper_submitted",
            )
        if action == "reject":
            return ctx.reviewer_scope and doc_status in (
                "uploaded",
                "paper_submitted",
                "verified",
            )
        if action == "reset":
            return ctx.reviewer_scope and doc_status != "missing"

        # Unknown action — treat as deny so a typo in calling code
        # never grants access. Service guard surfaces the bug as a
        # PermissionDeniedError; response shaping skips the flag.
        return False
