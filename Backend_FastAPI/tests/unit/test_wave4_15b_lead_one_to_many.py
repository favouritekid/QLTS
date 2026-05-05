"""Unit tests for #184 Wave 4 PR #15b — Lead one-to-many migration.

Pure-text + import contract tests covering the model relationship flip,
the helper, repository new methods, schema dual-response auto-populate,
and the eligibility check composite-aware path.

Live integration test (insert Lead + 2 profiles different years →
both queryable + helper returns correct year + delete-orphan removed)
is deferred to the staging clone D12-D14 batch.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# 1. Lead model relationship flip
# ---------------------------------------------------------------------------


def test_lead_admission_profiles_relationship_is_plural() -> None:
    """Wave 3-E composite UNIQUE shipped → relationship flipped to
    plural list. The legacy ``admission_profile`` (singular) attribute
    must not exist on the mapper."""
    from app.models.lead import Lead

    rels = set(Lead.__mapper__.relationships.keys())
    assert "admission_profiles" in rels
    assert "admission_profile" not in rels


def test_lead_admission_profiles_uselist_true_no_delete_orphan() -> None:
    """The relationship is plural (``uselist=True`` is implicit on a
    list collection) and drops ``delete-orphan`` so removing an item
    from the list does NOT auto-delete the profile row — Wave 4 spec
    treats profile deletion as an explicit operation."""
    from app.models.lead import Lead

    rel = Lead.__mapper__.relationships["admission_profiles"]
    assert rel.uselist is True
    # ``rel.cascade`` is a CascadeOptions iterable of token strings.
    cascade_set = set(rel.cascade)
    assert "save-update" in cascade_set
    assert "delete-orphan" not in cascade_set


def test_lead_admission_profiles_ordered_by_academic_year_desc() -> None:
    """Plural list is ordered most-recent first so deprecated callers
    that read ``profiles[0]`` see the latest year — matches the
    legacy "single profile = most recent" expectation."""
    from app.models.lead import Lead

    rel = Lead.__mapper__.relationships["admission_profiles"]
    order_by_str = str(rel.order_by[0])
    assert "academic_year" in order_by_str
    assert "DESC" in order_by_str.upper()


def test_admission_profile_back_populates_admission_profiles() -> None:
    """Reverse relationship ``AdmissionProfile.lead`` must point at the
    plural attribute; mismatch breaks SQLAlchemy session bookkeeping."""
    from app.models.admission import AdmissionProfile

    rel = AdmissionProfile.__mapper__.relationships["lead"]
    assert rel.back_populates == "admission_profiles"


# ---------------------------------------------------------------------------
# 2. Lead.current_admission_profile() helper
# ---------------------------------------------------------------------------


def test_current_admission_profile_returns_match_when_year_present() -> None:
    """Helper walks the in-memory ``admission_profiles`` collection
    (caller eager-loads) and returns the one matching ``academic_year``."""
    from app.models.lead import Lead

    p2025 = SimpleNamespace(academic_year=2025, status="enrolled")
    p2026 = SimpleNamespace(academic_year=2026, status="draft")
    lead = Lead(id=1)
    # Bypass SQLAlchemy collection setter (it expects ORM instances) — we
    # only need the in-memory iteration semantic for the helper.
    lead.__dict__["admission_profiles"] =[p2026, p2025]  # most-recent first per ORDER BY

    assert lead.current_admission_profile(2025) is p2025
    assert lead.current_admission_profile(2026) is p2026


def test_current_admission_profile_returns_none_when_year_absent() -> None:
    """No archive UNION fallback yet (TODO paired with
    ``ArchivedAdmissionProfile`` ORM ship + cron). Active-only return
    means a year not present in the loaded list yields None — caller
    treats this as "no profile" until the cron starts archiving."""
    from app.models.lead import Lead

    p2025 = SimpleNamespace(academic_year=2025)
    lead = Lead(id=1)
    # Bypass SQLAlchemy collection setter (it expects ORM instances) — we
    # only need the in-memory iteration semantic for the helper.
    lead.__dict__["admission_profiles"] =[p2025]

    assert lead.current_admission_profile(2026) is None


def test_current_admission_profile_handles_empty_list() -> None:
    from app.models.lead import Lead

    lead = Lead(id=1)
    # Bypass SQLAlchemy collection setter (it expects ORM instances) — we
    # only need the in-memory iteration semantic for the helper.
    lead.__dict__["admission_profiles"] =[]
    assert lead.current_admission_profile(2026) is None


# ---------------------------------------------------------------------------
# 3. Repository new methods
# ---------------------------------------------------------------------------


def test_admission_repository_exposes_new_methods() -> None:
    """New methods ship in Wave 4 #15b — older
    ``get_profile_by_lead_id`` is deprecated but kept for migration."""
    from app.repositories.admission_repository import AdmissionRepository

    assert callable(getattr(AdmissionRepository, "list_profiles_by_lead_id", None))
    assert callable(getattr(AdmissionRepository, "get_profile_by_lead_year", None))
    # Legacy method still callable during deprecation window.
    assert callable(getattr(AdmissionRepository, "get_profile_by_lead_id", None))


def test_get_profile_by_lead_id_logs_warning_on_multiple_profiles() -> None:
    """Deprecated method must surface a warning when a lead has >1
    profile so the migration window's silent ambiguity is visible."""
    import inspect

    from app.repositories import admission_repository

    src = inspect.getsource(admission_repository.AdmissionRepository.get_profile_by_lead_id)
    assert "log.warning" in src
    assert "list_profiles_by_lead_id" in src or "get_profile_by_lead_year" in src


def test_get_profile_by_lead_year_uses_composite_unique_columns() -> None:
    """Source must filter on both ``lead_id`` and ``academic_year``
    so it hits the ``uq_admission_profile_lead_year`` UNIQUE shipped
    by Wave 3-E ``phase1_15a``."""
    import inspect

    from app.repositories import admission_repository

    src = inspect.getsource(admission_repository.AdmissionRepository.get_profile_by_lead_year)
    assert "lead_id" in src
    assert "academic_year" in src


# ---------------------------------------------------------------------------
# 4. Schema dual-response
# ---------------------------------------------------------------------------


def test_lead_schema_carries_both_singular_and_plural_fields() -> None:
    """Backward compat: the FE may still consume ``admission_profile``
    while migrating; both fields must serialize."""
    from app.schemas.lead import Lead as LeadSchema

    fields = LeadSchema.model_fields
    assert "admission_profiles" in fields
    assert "admission_profile" in fields


def _minimal_lead_payload(**overrides) -> dict:
    """Helper — build the minimum required fields for ``Lead`` schema
    validation so the tests stay focused on the dual-response behavior
    instead of stuffing irrelevant fields."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "id": 1,
        "full_name": "Nguyễn Văn A",
        "phone": "0900000000",
        "source": "manual",
        "status": "active",
        "lead_score": 0,
        "created_at": now,
        "updated_at": now,
    }
    payload.update(overrides)
    return payload


def _minimal_profile_payload(**overrides) -> dict:
    from datetime import datetime, timezone

    payload = {
        "id": 100,
        "status": "draft",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "academic_year": 2026,
    }
    payload.update(overrides)
    return payload


def test_lead_schema_validator_populates_legacy_singular_from_latest() -> None:
    """The ``model_validator`` after-mode hook copies plural[0] into
    the legacy singular field. Order matches SQLAlchemy
    ``order_by=academic_year.desc()`` so plural[0] = most-recent year."""
    from app.schemas.lead import Lead as LeadSchema

    profile_2026 = _minimal_profile_payload(id=100, academic_year=2026)
    profile_2025 = _minimal_profile_payload(
        id=101, academic_year=2025, status="enrolled"
    )

    lead = LeadSchema.model_validate(
        _minimal_lead_payload(admission_profiles=[profile_2026, profile_2025])
    )
    assert lead.admission_profile is not None
    assert lead.admission_profile.id == 100


def test_lead_schema_singular_stays_none_when_plural_empty() -> None:
    from app.schemas.lead import Lead as LeadSchema

    lead = LeadSchema.model_validate(
        _minimal_lead_payload(admission_profiles=[])
    )
    assert lead.admission_profile is None
    assert lead.admission_profiles == []


# ---------------------------------------------------------------------------
# 5. Eligibility check composite path
# ---------------------------------------------------------------------------


def test_eligibility_check_signature_accepts_optional_academic_year() -> None:
    """The signature gained an ``academic_year`` keyword in Wave 4
    #15b. Optional so legacy callers (no year) preserve the
    "any profile = block" semantic."""
    import inspect

    from app.services.admission_service import (
        check_lead_level_admission_eligibility,
    )

    sig = inspect.signature(check_lead_level_admission_eligibility)
    assert "academic_year" in sig.parameters
    assert sig.parameters["academic_year"].default is None


def test_eligibility_check_uses_admission_profiles_plural() -> None:
    """The body must read from ``admission_profiles`` (plural) — the
    legacy ``admission_profile`` (singular) attribute is gone."""
    import inspect

    from app.services import admission_service

    src = inspect.getsource(
        admission_service.check_lead_level_admission_eligibility
    )
    assert "admission_profiles" in src
    # Legacy access pattern must be removed (would always return None
    # post-Wave-4 since the singular relationship is gone).
    assert 'lead.__dict__.get("admission_profile")' not in src
