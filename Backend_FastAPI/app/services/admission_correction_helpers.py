"""Per-field parse + normalize helpers for the minor correction flow.

Service layer module — may import schemas (``FamilyMemberSchema``) and
constants. Routers/services that apply minor corrections call
``parse_and_normalize`` to coerce the raw JSON value submitted by the
client into the type SQLAlchemy expects on the column, then
``post_parse_business_check`` for business-rule validation that runs
AFTER type-level validation has succeeded.

The TypeAdapter-driven design lets the validator stay declarative —
adding a new field means adding a row to ``FIELD_ADAPTERS`` plus
``SAFE_MINOR_CORRECTION_FIELDS``; the parity assert at module load
fails loudly if either side drifts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from pydantic import Field, StringConstraints, TypeAdapter

from app.core.admission_correction_constants import (
    ALLOWED_GENDERS,
    SAFE_MINOR_CORRECTION_FIELDS,
)
from app.schemas.admission import FamilyMemberSchema


# ---------------------------------------------------------------------------
# Field-level type adapters
# ---------------------------------------------------------------------------
# Each adapter mirrors the constraint of the corresponding model column
# (admission.py:115-182). Max-length values are cross-checked by tests.
#
# DateTime caveat: union/party_*_date are ``DateTime`` columns WITHOUT
# ``timezone=True`` (admission.py:153-155). We accept ISO strings with or
# without offset, but ``parse_and_normalize`` strips tzinfo to UTC-naive
# so the value matches what SQLAlchemy expects to write to the column.

FIELD_ADAPTERS: dict[str, TypeAdapter] = {
    # ``Field(max_length=10)`` mirrors the constraint on
    # ``AdmissionProfileUpdate.family_info`` (admission.py:402-406) so
    # minor correction can't bypass the array cap and persist >10
    # guardian rows when the admin path enables this field.
    "family_info": TypeAdapter(
        Annotated[list[FamilyMemberSchema], Field(max_length=10)]
    ),
    "union_entry_date": TypeAdapter(Optional[datetime]),
    "party_entry_date": TypeAdapter(Optional[datetime]),
    "party_official_entry_date": TypeAdapter(Optional[datetime]),
    "social_insurance_number": TypeAdapter(
        Optional[Annotated[str, StringConstraints(pattern=r"^\d{10}$")]]
    ),
    # gender — whitelist enforced in post_parse_business_check.
    "gender": TypeAdapter(
        Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)]]
    ),
    "nationality": TypeAdapter(
        Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]]
    ),
    "ethnicity": TypeAdapter(
        Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]]
    ),
    "religion": TypeAdapter(
        Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]]
    ),
    "disability_type": TypeAdapter(
        Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]]
    ),
    "place_of_birth": TypeAdapter(
        Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)]]
    ),
    "native_place": TypeAdapter(
        Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)]]
    ),
    "permanent_province": TypeAdapter(
        Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]]
    ),
    "permanent_district": TypeAdapter(
        Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]]
    ),
    "permanent_ward": TypeAdapter(
        Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]]
    ),
    "permanent_residential_group": TypeAdapter(
        Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=150)]]
    ),
    "permanent_street_address": TypeAdapter(
        Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)]]
    ),
}


# Drift guard — if SAFE catalog adds a field, FIELD_ADAPTERS must follow.
# Module load fails before the service is wired up, surfacing the bug
# during dev/CI rather than at request time.
assert set(FIELD_ADAPTERS.keys()) == SAFE_MINOR_CORRECTION_FIELDS, (
    "FIELD_ADAPTERS keys must match SAFE_MINOR_CORRECTION_FIELDS exactly. "
    f"Missing adapters: {SAFE_MINOR_CORRECTION_FIELDS - set(FIELD_ADAPTERS)}; "
    f"Stale adapters: {set(FIELD_ADAPTERS) - SAFE_MINOR_CORRECTION_FIELDS}"
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def parse_and_normalize(field: str, raw_value: Any) -> Any:
    """Validate + coerce one field value to the model's expected Python type.

    Raises ``pydantic.ValidationError`` on type/constraint failure — the
    caller wraps that into the project's domain ``ValidationError`` so
    the router can map it to a 400 response.

    Special handling:
    - ``family_info``: parsed list of ``FamilyMemberSchema`` is dumped
      back to plain dicts (JSON-mode) so SQLAlchemy can store the array
      in the JSONB column.
    - Naive-UTC datetime: union/party_*_date columns are timezone-naive,
      so an offset-aware datetime is converted to UTC and stripped of
      tzinfo before return. Passing through tz-aware values would let
      SQLAlchemy raise on insert — out of scope to migrate columns to
      ``DateTime(timezone=True)`` for this feature.
    """
    adapter = FIELD_ADAPTERS[field]
    parsed = adapter.validate_python(raw_value)

    if field == "family_info" and parsed is not None:
        return [m.model_dump(mode="json") for m in parsed]

    if isinstance(parsed, datetime) and parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

    return parsed


def post_parse_business_check(field: str, value: Any) -> Optional[str]:
    """Business-rule check that runs AFTER type-level validation.

    Returns an error message string when the value fails a business
    rule, or None when the value is acceptable. Returning a string
    rather than raising lets the caller batch errors per-field if it
    wants — current callers raise on the first error to keep the API
    surface simple.

    Rules:
    - Đoàn / Đảng entry dates cannot be in the future. The value
      arrives as naive-UTC after ``parse_and_normalize``; compare
      against ``datetime.now(UTC).replace(tzinfo=None)`` to stay in
      the same timezone-naive frame.
    - ``gender`` must be one of the dropdown options enforced on the
      admission detail page (Nam / Nữ / Khác); accepts None to allow
      clearing the field.
    """
    if field.endswith("_date") and isinstance(value, datetime):
        now_naive_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        if value > now_naive_utc:
            return f"{field} không được lớn hơn hôm nay"

    if field == "gender" and value is not None and value not in ALLOWED_GENDERS:
        return f"gender phải thuộc {sorted(ALLOWED_GENDERS)}"

    return None


def safe_serialize(value: Any) -> Any:
    """Serialize a model attribute value for the audit JSON payload.

    The audit log stores ``{"old": ..., "new": ...}`` per field. Most
    SAFE fields are scalar str / int / list / dict already, but date
    columns surface as ``datetime`` objects which json.dumps refuses to
    handle. Coerce anything non-JSON-native to its string form so the
    audit row stays insertable.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, dict, str, int, float, bool)):
        return value
    return str(value)
