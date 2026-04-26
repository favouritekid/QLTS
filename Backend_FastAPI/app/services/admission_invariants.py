"""Cross-field invariants for AdmissionProfile state.

Single source of truth for invariants that span multiple fields.
``AdmissionProfileUpdate.validate_logical_dates`` (schema-level model
validator) and the service layer (`apply_minor_correction`,
`update_profile`) both delegate here so partial-update flows can run
the same checks against a candidate state without duplicating logic.

Why this module exists
----------------------
Pydantic ``@model_validator(mode='after')`` only sees fields present
on the instance. When a router does ``data.model_dump(exclude_unset=True)``
for a partial update, the validator runs on the trimmed payload —
fields the client did NOT send (but exist in the DB) are ``None``,
so cross-field checks like "union ≤ party" silently pass when only
``union_entry_date`` is being changed but ``party_entry_date`` already
holds an earlier value in the database.

Service layers using ``TypeAdapter(field_type)`` for per-field parsing
have a parallel hole: they never instantiate the schema, so the
model validator never runs at all.

The fix is the same in both cases — build a candidate state (DB
attributes + caller's changes overlaid), pass it to the standalone
validator. This module exposes that validator. Callers that already
have a complete state (full schema instance) can pass
``self.model_dump()`` and get the same checks; callers with a partial
payload merge against the existing model row first.

Lesson reference
----------------
See feedback memory ``partial-update-loses-cross-field-invariants``
for the broader pattern. ``apply_minor_correction`` (PR #129) shipped
inline checks; this utility consolidates them so ``update_profile``
(pre-existing partial-update flow) can apply the same rules.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Optional


def _coerce_date(value: Any) -> Optional[date]:
    """Normalize a date/datetime/None into a ``date`` for comparison.

    The model stores ``dob`` as ``date`` and the entry-date columns as
    naive ``datetime``. Compare on the date boundary so a 23:00 entry
    same calendar day as ``dob`` doesn't trip the rule.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    # Defensive: surfaces unexpected payload shape immediately rather than
    # silently bypassing the rule.
    raise TypeError(
        f"validate_logical_dates: unsupported value type {type(value).__name__}"
    )


def validate_logical_dates(state: Mapping[str, Any]) -> None:
    """Enforce admission logical-date ordering invariants.

    ``state`` is a flat mapping containing (at minimum) any of:
    ``dob``, ``union_entry_date``, ``party_entry_date``,
    ``party_official_entry_date``. Missing keys are treated as not
    asserted — callers building a candidate state from DB + partial
    payload should include the existing DB values so the rule applies
    against the merged result rather than only the payload subset.

    Raises ``ValueError`` with a Vietnamese message describing the
    violated invariant. Callers in the service layer convert that to
    the project's domain ``ValidationError`` (utils.exceptions); the
    schema-level model validator lets it propagate as Pydantic
    validation error (422).

    Rules (mirror of ``AdmissionProfileUpdate.validate_logical_dates``):
    1. ``union_entry_date`` ≤ ``party_entry_date`` (probationary)
    2. ``party_entry_date`` ≤ ``party_official_entry_date``
    3. ``dob`` ≤ ``union_entry_date`` (treat dob as date boundary)
    """
    union = state.get("union_entry_date")
    party = state.get("party_entry_date")
    party_official = state.get("party_official_entry_date")
    dob = state.get("dob")

    if union and party and union > party:
        raise ValueError("Ngày vào Đoàn phải trước Ngày vào Đảng (dự bị)")

    if party and party_official and party > party_official:
        raise ValueError(
            "Ngày vào Đảng (dự bị) phải trước Ngày vào Đảng (chính thức)"
        )

    union_date = _coerce_date(union)
    dob_date = _coerce_date(dob)
    if dob_date and union_date and dob_date > union_date:
        raise ValueError("Ngày sinh phải trước Ngày vào Đoàn")
