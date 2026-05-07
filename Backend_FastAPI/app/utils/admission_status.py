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
