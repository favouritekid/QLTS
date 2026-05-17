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
