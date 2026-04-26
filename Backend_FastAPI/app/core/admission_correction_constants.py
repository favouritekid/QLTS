"""Constants for the post-approval minor correction flow.

Pure-data module — no schemas, no services, no FastAPI imports. Lives
in ``app.core`` so any layer (schema validators, services, routers,
tests) can import without creating circular dependencies. Schemas-aware
parsing helpers live in ``app.services.admission_correction_helpers``.

The two frozensets here form the system-level safety net for
``POST /admissions/{id}/minor-correction``:

- ``SAFE_MINOR_CORRECTION_FIELDS``: fields admin CAN choose to expose
  for officer correction on a given AdmissionPath. Per-path allowlist
  is ANDed with this set, so admin can never grant more.
- ``HARD_DENY_FIELDS``: fields that must NEVER be touchable through the
  flow, even if a future admin/dev mistakenly adds them to the safe
  catalog or per-path allowlist. Service-side check raises 400 before
  reaching the path config — defense in depth.

Adding a field to ``SAFE_MINOR_CORRECTION_FIELDS`` requires also adding
its TypeAdapter to ``FIELD_ADAPTERS`` in
``admission_correction_helpers``; the parity is asserted at import time
in that module so drift fails loudly.
"""
from __future__ import annotations


SAFE_MINOR_CORRECTION_FIELDS: frozenset[str] = frozenset({
    # Demographic supplements
    "gender",
    "nationality",
    "ethnicity",
    "religion",
    "disability_type",
    "social_insurance_number",
    "place_of_birth",
    "native_place",
    # Đoàn / Đảng entry dates
    "union_entry_date",
    "party_entry_date",
    "party_official_entry_date",
    # Permanent residence (CCCD-style sub-ward + street free text)
    "permanent_province",
    "permanent_district",
    "permanent_ward",
    "permanent_residential_group",
    "permanent_street_address",
    # Family / guardian array
    "family_info",
})


# Defense-in-depth blocklist for fields that must never flow through this
# endpoint, regardless of admin path config. Includes:
# - Identity / contact (require Lead-side sync + magic-link refresh)
# - Scoring / academic history (would alter eligibility post-approval)
# - Workflow state (status, version, timestamps)
# - Foreign keys to upstream config (admission_path / program / offering)
# - Documents / finance (have their own dedicated flows)
# - Free-form keys client might invent: documents/fees/fee/invoice/payment
HARD_DENY_FIELDS: frozenset[str] = frozenset({
    # Identity
    "full_name",
    "dob",
    "citizen_id",
    "phone",
    "email",
    # Scoring
    "academic_history",
    "admission_scores",
    # State machine
    "status",
    "version",
    # Foreign keys
    "lead_id",
    "admission_method_id",
    "admission_path_id",
    "program_id",
    "offering_id",
    "academic_info_id",
    "applied_rules",
    # Workflow timestamps
    "approved_at",
    "approved_by_id",
    "approval_notes",
    "rejected_at",
    "rejection_reason",
    "confirmed_at",
    "enrolled_at",
    "is_dropped",
    "survey_sent_at",
    "survey_tracking_id",
    # Catch-all for client-invented keys outside the model
    "documents",
    "fees",
    "fee_status",
    "fee",
    "invoice",
    "payment",
    "lead",
    "assigned_reviewer_id",
    "assigned_reviewer",
})


# Whitelist for ``gender`` correction. Matches the dropdown options on
# the admission detail PersonalInfoTab (frontend src/.../PersonalInfoTab.tsx)
# — Vietnamese labels stored as-is in the model column.
ALLOWED_GENDERS: frozenset[str] = frozenset({"Nam", "Nữ", "Khác"})


# Vietnamese labels surfaced in the correction dialog and the admin
# allowlist multi-select. FE mirrors this map (single source of truth
# is backend; FE imports a copy for typing convenience).
FIELD_LABELS_VI: dict[str, str] = {
    "gender": "Giới tính",
    "nationality": "Quốc tịch",
    "ethnicity": "Dân tộc",
    "religion": "Tôn giáo",
    "disability_type": "Loại khuyết tật",
    "social_insurance_number": "Số sổ BHXH",
    "place_of_birth": "Nơi sinh",
    "native_place": "Nguyên quán",
    "union_entry_date": "Ngày vào Đoàn",
    "party_entry_date": "Ngày vào Đảng",
    "party_official_entry_date": "Ngày chính thức vào Đảng",
    "permanent_province": "Tỉnh/TP thường trú",
    "permanent_district": "Quận/Huyện thường trú",
    "permanent_ward": "Phường/Xã thường trú",
    "permanent_residential_group": "Tổ/Thôn/Khu phố",
    "permanent_street_address": "Địa chỉ chi tiết",
    "family_info": "Thông tin gia đình / người giám hộ",
}


# Self-check: every label entry must be in SAFE catalog. Catches drift
# if someone adds a label without expanding the safe set (which would
# render an unsupported field in the dialog).
assert set(FIELD_LABELS_VI.keys()) == SAFE_MINOR_CORRECTION_FIELDS, (
    "FIELD_LABELS_VI keys must match SAFE_MINOR_CORRECTION_FIELDS exactly"
)


# Hard-deny invariant: SAFE and HARD_DENY must be disjoint. Catches the
# nightmare scenario of someone accidentally adding citizen_id or status
# to the safe catalog.
assert SAFE_MINOR_CORRECTION_FIELDS.isdisjoint(HARD_DENY_FIELDS), (
    "SAFE_MINOR_CORRECTION_FIELDS and HARD_DENY_FIELDS must be disjoint"
)
