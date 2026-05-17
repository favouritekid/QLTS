"""Anchor test for W11-BE.F.7 BLOCKER fix.

PUT /api/admissions/{id} must persist the 7 priority bonus fields.
Before this fix, AdmissionProfileUpdate schema didn't declare them →
router silently dropped them → engine evaluate_cascade saw NULL → 0đ
bonus on every profile → CR-P0 decision-flip logic dormant.

The test exercises the contract end-to-end through the actual PUT
endpoint so a regression in either the schema OR the service set-
statements is caught before deploy.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal


pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


# Helpers — minimal copies from tests/services/test_admission_service_strict.py
# kept inline so this anchor doesn't depend on relocations of shared test code.
async def get_auth_headers(client: AsyncClient, user_info: dict) -> dict:
    res = await client.post(
        "/api/auth/login",
        data={"username": user_info["username"], "password": user_info["password"]},
    )
    assert res.status_code == 200, f"Login failed: {res.text}"
    access_token = res.cookies.get("access_token")
    client.cookies.delete("access_token")
    return {"Authorization": f"Bearer {access_token}"}


async def setup_admission_api_data(
    major_id: int, unit_id: int, officer_id: int, academic_year: int = 2026,
) -> dict:
    """Build minimal admission chain (offering → academic_info → method →
    criteria → path → document_group → lead) so the POST endpoint can
    create a draft profile against it."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            ot = models.ConfigOfferingType(
                code=f"f7_type_{random.randint(10000, 99999)}",
                name="F7 Test", is_active=True,
            )
            session.add(ot)
            await session.flush()
            offering = models.ProgramOffering(
                offering_type=f"F7_{random.randint(10000, 99999)}",
                program_id=major_id, offering_type_id=ot.id,
            )
            session.add(offering)
            await session.flush()
            academic_info = models.OfferingAcademicInfo(
                offering_id=offering.id, academic_year=academic_year,
                is_published=True,
            )
            session.add(academic_info)
            await session.flush()
            method = models.AdmissionMethod(
                code=f"f7_method_{random.randint(10000, 99999)}",
                name="F7 Method", is_active=True,
            )
            session.add(method)
            await session.flush()
            criteria = models.AdmissionCriteria(
                method_id=method.id,
                code=f"f7_crit_{random.randint(10000, 99999)}",
                name="F7 Crit", min_gpa=0, is_active=True,
            )
            session.add(criteria)
            await session.flush()
            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(
                session, academic_year=academic_year,
            )
            path = models.AdmissionPath(
                academic_info_id=academic_info.id,
                admission_method_id=method.id,
                admission_round_id=round_id,
                criteria_id=criteria.id, status="active",
            )
            session.add(path)
            await session.flush()
            lead = models.Lead(
                full_name="F7 Test Candidate",
                phone=f"09{random.randint(10000000, 99999999)}",
                email=f"f7_{random.randint(10000, 99999)}@test.local",
                source="website",
                unit_id=unit_id,
                offering_id=offering.id,
                assigned_officer_id=officer_id,
            )
            session.add(lead)
            await session.flush()
            consultation = models.Consultation(
                lead_id=lead.id,
                consultation_date=datetime.now(timezone.utc),
                method="phone",
                notes="F7 test consultation",
                officer_id=officer_id,
                consultation_status_id="sts06",
            )
            session.add(consultation)
            await session.flush()
            return {
                "lead_id": lead.id,
                "admission_method_id": method.id,
                "academic_info_id": academic_info.id,
            }


async def test_put_persists_all_seven_priority_fields(
    client: AsyncClient,
    officer_user_in_db: dict,
    seed_lead_dependencies: dict,
) -> None:
    """PUT with the full priority field set — verify all 7 columns
    persist (not silently dropped by schema)."""
    unit_id = seed_lead_dependencies["unit_id"]
    major_id = seed_lead_dependencies["major_program_id"]
    data = await setup_admission_api_data(
        major_id=major_id,
        unit_id=unit_id,
        officer_id=officer_user_in_db["id"],
        academic_year=2026,
    )
    headers = await get_auth_headers(client, officer_user_in_db)

    create_response = await client.post(
        "/api/admissions",
        json={
            "lead_id": data["lead_id"],
            "admission_method_id": data["admission_method_id"],
        },
        headers=headers,
    )
    assert create_response.status_code == 201, create_response.text
    profile_id = create_response.json()["id"]

    # PUT with the full priority field set
    update_payload = {
        "version": 1,
        "high_school_kv_resolved": "KV1",
        "permanent_commune_code": "00001",
        "area_resolution_basis": "manual_override",
        "area_resolution_reason": "Bố là quân nhân hộ khẩu KV1",
        "priority_object_codes": ["04", "06"],
        "priority_object_evidence": {
            "04": {"document_id": 123, "status": "pending"},
            "06": {"document_id": 456, "status": "pending"},
        },
    }
    response = await client.put(
        f"/api/admissions/{profile_id}",
        json=update_payload,
        headers=headers,
    )
    assert response.status_code == 200, (
        f"PUT failed: {response.status_code} — {response.text}. "
        f"If 422 about unknown fields, AdmissionProfileUpdate schema "
        f"regressed (W11-BE.F.7)."
    )

    # Re-fetch profile and assert all 7 columns persisted
    get_response = await client.get(
        f"/api/admissions/{profile_id}", headers=headers,
    )
    assert get_response.status_code == 200
    body = get_response.json()

    assert body["high_school_kv_resolved"] == "KV1"
    assert body["permanent_commune_code"] == "00001"
    assert body["area_resolution_basis"] == "manual_override"
    assert body["area_resolution_reason"] == "Bố là quân nhân hộ khẩu KV1"
    assert body["priority_object_codes"] == ["04", "06"]
    assert body["priority_object_evidence"]["04"]["document_id"] == 123
    assert body["priority_object_evidence"]["06"]["status"] == "pending"


async def test_put_omitted_priority_fields_preserve_existing(
    client: AsyncClient,
    officer_user_in_db: dict,
    seed_lead_dependencies: dict,
) -> None:
    """Partial PUT: only some fields touched, others left as-is.
    Pydantic's optional + service ``if key in data`` semantic means
    omitted keys do NOT overwrite existing DB values."""
    unit_id = seed_lead_dependencies["unit_id"]
    major_id = seed_lead_dependencies["major_program_id"]
    data = await setup_admission_api_data(
        major_id=major_id,
        unit_id=unit_id,
        officer_id=officer_user_in_db["id"],
        academic_year=2026,
    )
    headers = await get_auth_headers(client, officer_user_in_db)

    create_response = await client.post(
        "/api/admissions",
        json={
            "lead_id": data["lead_id"],
            "admission_method_id": data["admission_method_id"],
        },
        headers=headers,
    )
    profile_id = create_response.json()["id"]

    # First PUT: set KV + codes
    await client.put(
        f"/api/admissions/{profile_id}",
        json={
            "version": 1,
            "high_school_kv_resolved": "KV1",
            "priority_object_codes": ["04"],
        },
        headers=headers,
    )

    # Second PUT: change only the reason; KV + codes must stay
    response = await client.put(
        f"/api/admissions/{profile_id}",
        json={
            "version": 2,
            "area_resolution_reason": "Updated reason",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text

    body = (await client.get(
        f"/api/admissions/{profile_id}", headers=headers,
    )).json()
    assert body["high_school_kv_resolved"] == "KV1"  # preserved
    assert body["priority_object_codes"] == ["04"]   # preserved
    assert body["area_resolution_reason"] == "Updated reason"  # changed


async def test_put_rejects_invalid_kv_code_format(
    client: AsyncClient,
    officer_user_in_db: dict,
    seed_lead_dependencies: dict,
) -> None:
    """Pydantic regex on high_school_kv_resolved rejects 'KV2_NT'
    (underscore) — only canonical 'KV2-NT' (hyphen) per TT 05/2021."""
    unit_id = seed_lead_dependencies["unit_id"]
    major_id = seed_lead_dependencies["major_program_id"]
    data = await setup_admission_api_data(
        major_id=major_id,
        unit_id=unit_id,
        officer_id=officer_user_in_db["id"],
        academic_year=2026,
    )
    headers = await get_auth_headers(client, officer_user_in_db)
    create_response = await client.post(
        "/api/admissions",
        json={
            "lead_id": data["lead_id"],
            "admission_method_id": data["admission_method_id"],
        },
        headers=headers,
    )
    profile_id = create_response.json()["id"]

    response = await client.put(
        f"/api/admissions/{profile_id}",
        json={"version": 1, "high_school_kv_resolved": "KV2_NT"},
        headers=headers,
    )
    assert response.status_code == 422, response.text


async def test_put_rejects_invalid_area_resolution_basis(
    client: AsyncClient,
    officer_user_in_db: dict,
    seed_lead_dependencies: dict,
) -> None:
    """Pydantic enum-like regex on area_resolution_basis rejects
    'highschool' typo. Only 3 canonical values accepted."""
    unit_id = seed_lead_dependencies["unit_id"]
    major_id = seed_lead_dependencies["major_program_id"]
    data = await setup_admission_api_data(
        major_id=major_id,
        unit_id=unit_id,
        officer_id=officer_user_in_db["id"],
        academic_year=2026,
    )
    headers = await get_auth_headers(client, officer_user_in_db)
    create_response = await client.post(
        "/api/admissions",
        json={
            "lead_id": data["lead_id"],
            "admission_method_id": data["admission_method_id"],
        },
        headers=headers,
    )
    profile_id = create_response.json()["id"]

    response = await client.put(
        f"/api/admissions/{profile_id}",
        json={"version": 1, "area_resolution_basis": "highschool"},
        headers=headers,
    )
    assert response.status_code == 422, response.text


# =============================================================================
# Review-2 hardening: H1 cross-field + M1 codes regex + M2 evidence shape
# These tests probe the schema directly (no HTTP round-trip needed) since
# they exercise Pydantic validation, not service/DB behavior.
# =============================================================================


def test_h1_basis_manual_override_requires_reason() -> None:
    """H1: basis='manual_override' without reason → ValidationError."""
    from pydantic import ValidationError
    from app.schemas.admission import AdmissionProfileUpdate

    with pytest.raises(ValidationError, match="manual_override"):
        AdmissionProfileUpdate(version=1, area_resolution_basis="manual_override")


def test_h1_basis_manual_override_with_reason_passes() -> None:
    """H1 happy path: reason present → accepted."""
    from app.schemas.admission import AdmissionProfileUpdate

    obj = AdmissionProfileUpdate(
        version=1,
        area_resolution_basis="manual_override",
        area_resolution_reason="Bố là quân nhân hộ khẩu KV1",
    )
    assert obj.area_resolution_basis == "manual_override"


def test_h1_basis_high_school_requires_id_or_kv() -> None:
    """H1: basis='high_school' without high_school_id AND without
    high_school_kv_resolved → ValidationError."""
    from pydantic import ValidationError
    from app.schemas.admission import AdmissionProfileUpdate

    with pytest.raises(ValidationError, match="high_school"):
        AdmissionProfileUpdate(version=1, area_resolution_basis="high_school")


def test_h1_basis_high_school_with_id_only_passes() -> None:
    """H1: id alone is sufficient (kv_resolved server-derived later)."""
    from app.schemas.admission import AdmissionProfileUpdate

    obj = AdmissionProfileUpdate(
        version=1, area_resolution_basis="high_school", high_school_id=42,
    )
    assert obj.high_school_id == 42


def test_h1_basis_permanent_address_special_requires_commune_code() -> None:
    """H1: basis='permanent_address_special' (PT DTNT, quân nhân) requires
    permanent_commune_code so engine knows which commune to look up."""
    from pydantic import ValidationError
    from app.schemas.admission import AdmissionProfileUpdate

    with pytest.raises(ValidationError, match="permanent_commune_code"):
        AdmissionProfileUpdate(
            version=1, area_resolution_basis="permanent_address_special",
        )


def test_m1_priority_codes_per_item_regex_rejects_garbage() -> None:
    """M1: garbage code 'INVALID_99' fails per-item regex ``^[0-9]{2}$``."""
    from pydantic import ValidationError
    from app.schemas.admission import AdmissionProfileUpdate

    with pytest.raises(ValidationError):
        AdmissionProfileUpdate(
            version=1, priority_object_codes=["INVALID_99"],
        )


def test_m1_priority_codes_accepts_valid_2digit_codes() -> None:
    """M1 happy path: valid 2-digit codes pass."""
    from app.schemas.admission import AdmissionProfileUpdate

    obj = AdmissionProfileUpdate(
        version=1, priority_object_codes=["04", "06"],
    )
    assert obj.priority_object_codes == ["04", "06"]


def test_m2_evidence_inner_shape_rejects_garbage_dict() -> None:
    """M2: evidence inner dict without ``status`` key → ValidationError
    (engine reads status; garbage dict was silently 0đ pre-fix)."""
    from pydantic import ValidationError
    from app.schemas.admission import AdmissionProfileUpdate

    with pytest.raises(ValidationError):
        AdmissionProfileUpdate(
            version=1,
            priority_object_evidence={"04": {"random": "stuff"}},
        )


def test_m2_evidence_status_must_be_canonical_enum() -> None:
    """M2: status must be one of the 3 canonical values."""
    from pydantic import ValidationError
    from app.schemas.admission import AdmissionProfileUpdate

    with pytest.raises(ValidationError):
        AdmissionProfileUpdate(
            version=1,
            priority_object_evidence={
                "04": {"status": "approved_typo"},
            },
        )


def test_m2_evidence_canonical_shape_passes() -> None:
    """M2 happy path: full canonical evidence dict accepted."""
    from app.schemas.admission import AdmissionProfileUpdate

    obj = AdmissionProfileUpdate(
        version=1,
        priority_object_evidence={
            "04": {
                "status": "verified",
                "document_id": 123,
                "verified_by": 45,
            },
        },
    )
    assert obj.priority_object_evidence["04"].status == "verified"
    assert obj.priority_object_evidence["04"].document_id == 123


async def test_m3_put_high_school_id_garbage_returns_friendly_400(
    client: AsyncClient,
    officer_user_in_db: dict,
    seed_lead_dependencies: dict,
) -> None:
    """M3: garbage high_school_id (no such row) → 400 from service-side
    FK lookup (QLTS ValidationError maps to 400, not FastAPI's 422)
    instead of 500 IntegrityError at commit. Friendly message so
    candidate / admin knows to pick from the dropdown."""
    unit_id = seed_lead_dependencies["unit_id"]
    major_id = seed_lead_dependencies["major_program_id"]
    data = await setup_admission_api_data(
        major_id=major_id,
        unit_id=unit_id,
        officer_id=officer_user_in_db["id"],
        academic_year=2026,
    )
    headers = await get_auth_headers(client, officer_user_in_db)
    create_response = await client.post(
        "/api/admissions",
        json={
            "lead_id": data["lead_id"],
            "admission_method_id": data["admission_method_id"],
        },
        headers=headers,
    )
    profile_id = create_response.json()["id"]

    # Use a huge ID guaranteed to not exist in vn_high_school
    response = await client.put(
        f"/api/admissions/{profile_id}",
        json={
            "version": 1,
            "high_school_id": 9999999999,
            "area_resolution_basis": "high_school",
            "high_school_kv_resolved": "KV1",  # satisfies H1 basis invariant
        },
        headers=headers,
    )
    assert response.status_code == 400, (
        f"Expected 400 for garbage FK (QLTS ValidationError convention), "
        f"got {response.status_code}. Response: {response.text}"
    )
    assert "không tồn tại" in response.text or "9999999999" in response.text
