# app/utils/admission_status.py
"""
Admission Status Bridge Helpers (Cold Cutover Task #15).

Pure stateless helpers that bridge the legacy admission status names
(``approved`` / ``overridden`` / ``resubmitted``) with the choice-engine
canonical names (``admitted`` / ``submitted``) introduced by the Phase 3
state machine.

#15 SCOPE
---------
* Read-only helpers + downstream normalization.
* Callers swap ``profile.status == "approved"`` and the ``("approved",
  "overridden")`` admitted-equivalence tuples for ``is_admitted_like``.
* No write site is touched. ``profile.status`` assignments stay on the
  legacy vocabulary until #16 wires the transition service and the
  Phase 1 schema migration relaxes the CHECK constraint.
* Helpers therefore must accept any legacy value AND every new value
  the future state machine will set, without needing the DB constraint
  to be widened first.

DESIGN NOTES
------------
* Pure module — no DB, no FastAPI, no logging, no I/O. Importable from
  any layer (router / service / repository / task) without dragging
  side effects.
* ``ADMITTED_LIKE_STATUSES`` is a ``frozenset`` so callers can use it
  directly in ``AdmissionProfile.status.in_(...)`` SQL expressions.
* ``LEGACY_TO_NEW_STATUS_MAP`` only renames *legacy → choice-engine*;
  values that already match the new vocabulary (``admitted`` /
  ``submitted`` / ``confirmed`` / ``enrolled`` / ``rejected`` /
  ``withdrawn`` / ``waitlisted`` / ``reviewing``) pass through.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:
    from ..models import AdmissionProfile


# Legacy → choice-engine canonical rename. Used by ``effective_status``
# so downstream consumers (commission accrual, KPI funnel, lead-stage
# projections) can branch on a single normalized value once Phase 1
# allows the new strings to land on the column.
#
# ``confirmed`` / ``enrolled`` / ``rejected`` / ``withdrawn`` are already
# canonical in both vocabularies — no entry, default passthrough.
LEGACY_TO_NEW_STATUS_MAP: Mapping[str, str] = {
    "approved": "admitted",
    "overridden": "admitted",
    "resubmitted": "submitted",
}


# Profiles in an "admitted-equivalent" decision-positive state. Covers:
#   * legacy ``approved`` — officer/manager approved via the regular flow
#   * legacy ``overridden`` — admin force-approved bypassing validation
#   * choice-engine ``admitted`` — Phase 3 state machine T7 outcome
#
# Excludes ``confirmed`` (post-decision intent), ``enrolled`` (terminal),
# ``waitlisted`` / ``reviewing`` (pre-decision). Callers that need any
# of those must combine the helper with an explicit literal check.
#
# DO NOT use this set for magic-link confirmation gates — see
# ``CONFIRMATION_ELIGIBLE_STATUSES`` below; ``overridden`` skips the
# confirmation step entirely (state machine: overridden → enrolled).
ADMITTED_LIKE_STATUSES: frozenset[str] = frozenset(
    {"approved", "overridden", "admitted"}
)


# Profiles that may receive / consume a magic-link confirmation token.
# Strictly tighter than ``ADMITTED_LIKE_STATUSES``: the state machine
# routes ``overridden → enrolled`` directly, bypassing ``confirmed``,
# so an admin-force-approved profile must not be offered the magic
# link nor accept a token redemption.
#
# Membership rule: a status belongs here iff its only legal next step
# is ``confirmed`` (which requires the candidate's confirmation event).
# ``approved`` (legacy) and ``admitted`` (choice-engine) match;
# ``overridden`` does not.
CONFIRMATION_ELIGIBLE_STATUSES: frozenset[str] = frozenset(
    {"approved", "admitted"}
)


def is_admitted_like(profile: "AdmissionProfile") -> bool:
    """True iff ``profile.status`` is in the admitted-equivalent set.

    Use this in place of ``profile.status == "approved"`` and
    ``profile.status in ("approved", "overridden")`` admitted-equivalence
    checks. Combine with explicit literals for sites that also need
    ``confirmed`` / ``enrolled`` (see ``phase_manager.derive_phase_from
    _admission`` / ``_fee_calc_authorized`` for canonical examples).

    DO NOT use for magic-link gates — call ``is_confirmation_eligible``
    instead so admin-overridden profiles correctly skip the candidate
    confirmation step.
    """
    return profile.status in ADMITTED_LIKE_STATUSES


def is_fee_eligible(profile: "AdmissionProfile") -> bool:
    """True iff an official Fee/Invoice may be created for ``profile``.

    Single source of truth for the fee-eligible state gate, shared by
    ``routers/fees.py:_fee_calc_authorized`` (the service-side authorization)
    and the ``calculate_fee`` permission flag in
    ``admission_service._compute_frontend_fields`` (the FE button). Both
    previously inlined the SAME three-way predicate kept in sync by a
    "must stay mirrored" comment; lifting it here removes the drift risk.

    Fee-eligible states:
      * admitted-like (legacy ``approved`` / ``overridden`` + choice-engine
        ``admitted``) — the post-decision happy path,
      * ``confirmed`` / ``enrolled`` — later post-decision milestones,
      * ``submitted`` / ``resubmitted`` for single-path profiles (C2 fast-track
        prepay / giữ chỗ),
      * ``submitted`` / ``resubmitted`` for a multi-NV profile
        (``uses_choice_engine``) that has EXACTLY ONE nguyện vọng. With a single
        choice the ngành is already determined (publish can only admit that one
        choice or reject the whole profile — ``add_choice`` is locked at
        ``submitted`` / ``resubmitted``), so prepay / giữ chỗ is as safe as the
        single-path case. A multi-NV profile with ≥2 choices has not locked its
        admitted choice (all choices ``pending`` until publish) → calculating
        tuition would risk the wrong ngành, so it qualifies later via
        ``admitted`` (``is_admitted_like``).

    ``resubmitted`` is treated exactly like ``submitted`` here: it is the state
    a profile lands in after the officer fixes issues and re-submits a
    ``rejected`` / ``revision_requested`` profile (``resubmit_profile``). It is
    still pre-decision (chờ duyệt lại) — ``effective_status`` maps it to
    ``submitted`` and every other workflow gate handles the pair
    ``("submitted", "resubmitted")`` together. Omitting it here was a bug: a
    multi-NV profile returned for "too many NVs", trimmed to one NV and
    re-submitted, would land in ``resubmitted`` and silently lose the
    "Tính học phí" button despite being just as fee-eligible as ``submitted``.

    The multi-NV single-choice branch reads ``profile.__dict__`` (no lazy-load
    → no MissingGreenlet) and FAILS CLOSED when ``choices`` is not eager-loaded:
    the fee-create path re-validates this under a row lock anyway, so a missing
    eager-load degrades to "not eligible" rather than a wrong-ngành fee.

    Earlier states (``draft`` etc.) are NOT eligible (a fee would be premature).
    Keep this in lockstep with both call sites if the gate ever changes.

    COUPLING (do not let drift): the "multi-NV ⇒ exactly 1 NV" rule here is the
    GATE (may a fee be created at all?). Its PRICING counterpart — which NV's
    ngành the fee is computed against — lives in
    ``fee_calculation_service.resolve_fee_academic_info``. Change one ⇒ change
    the other. The end-to-end anchor that fails on drift:
    ``tests/api/test_phase3_pr3d_b_choice_crud.py`` (single-choice→201;
    ≥2-pending / 0-choice → fail-closed).
    """
    if is_admitted_like(profile) or profile.status in ("confirmed", "enrolled"):
        return True
    if profile.status in ("submitted", "resubmitted"):
        if not profile.uses_choice_engine:
            return True
        choices = profile.__dict__.get("choices")
        return choices is not None and len(choices) == 1
    return False


def is_confirmation_eligible(profile: "AdmissionProfile") -> bool:
    """True iff the profile is eligible to issue / redeem a magic-link
    confirmation token.

    Tighter than ``is_admitted_like`` — excludes ``overridden`` because
    the admin-override transition routes directly to ``enrolled`` and
    must never surface a candidate-facing confirmation flow. Use at all
    four magic-link sites (permission flag, token issuance, token
    validity snapshot, confirm-by-magic-link pre-check).
    """
    return profile.status in CONFIRMATION_ELIGIBLE_STATUSES


def effective_status(profile: "AdmissionProfile") -> str:
    """Normalize legacy → choice-engine canonical status name.

    Returns the new vocabulary name when a legacy alias is present
    (``approved`` / ``overridden`` → ``admitted``;
    ``resubmitted`` → ``submitted``); otherwise passthrough.

    Use for downstream consumers that prefer to branch on a single
    canonical status. The raw ``profile.status`` is still authoritative
    on writes — never feed ``effective_status(profile)`` back into a
    write site, because Phase 1's CHECK constraint still rejects the
    new strings until the column is widened.
    """
    return LEGACY_TO_NEW_STATUS_MAP.get(profile.status, profile.status)
