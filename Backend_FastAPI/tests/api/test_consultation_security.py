# tests/api/test_consultation_security.py
# -*- coding: utf-8 -*-
"""Security regression tests cho PR consultation-security (2026-07-16).

Phủ 3 lỗ hổng đã vá (S5 accountant-deny nằm ở
``tests/integration/test_casbin_b1_4x14_matrix.py``):

- **S1** — Manager restore consultation CROSS-UNIT (IDOR ghi). Guard cũ chỉ
  check role → manager restore được consultation của mọi đơn vị. Fix: gọi
  ``get_lead_for_user`` ép unit-scope trước ``restore_consultation``.
- **S2** — Manager xem + search PII deleted-items TOÀN HỆ THỐNG (IDOR đọc).
  Rows/counts/search đều không lọc unit → manager gõ chuỗi bất kỳ ra
  tên/phone/email lead mọi đơn vị. Fix: unit-scope cho MỌI phần.
- **S3** — Oracle 400-vs-404 khi dò ``consultation_id``. ``delete``/``update``
  trả 400 "does not belong" khi consultation thuộc lead khác (400=tồn tại,
  404=không) → enumerate toàn hệ thống. Fix: đưa ``lead_id`` vào WHERE → 404
  đồng nhất.

Router-level behavior (unit-scope trong ``deleted_items.py`` + mã lỗi HTTP mà
attacker thực sự thấy) → test qua API, không phải service.
"""
import logging
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal
from tests.fixtures.constants import AuthURLs

log = logging.getLogger(__name__)

pytestmark = [pytest.mark.asyncio, pytest.mark.security]

DELETED_ITEMS_URL = "/api/admin/deleted-items"


def _restore_consult_url(consultation_id: int) -> str:
    return f"{DELETED_ITEMS_URL}/consultations/{consultation_id}/restore"


def _lead_consult_url(lead_id: int, consultation_id: int) -> str:
    return f"/api/leads/{lead_id}/consultations/{consultation_id}"


def _restore_via_leads_route(lead_id: int, consultation_id: int) -> str:
    return f"/api/leads/{lead_id}/consultations/{consultation_id}/restore"


# ===========================================================================
# FIXTURES
# ===========================================================================


@pytest_asyncio.fixture(scope="function")
async def manager_no_unit_token_headers(client: AsyncClient) -> dict:
    """Manager CHƯA gán đơn vị (``unit_id=None``) — kiểm chứng fail-closed.

    Không tái dùng ``manager_user_in_db`` (đã gán UNIT_1). Username riêng để
    coexist trong cùng DB session.
    """
    from tests.fixtures.users import create_user_with_role, get_auth_headers
    from app.main import fastapi_app
    from app.security import get_password_hash

    try:
        from casbin_async_sqlalchemy_adapter.adapter import CasbinRule
    except ImportError:  # pragma: no cover
        CasbinRule = None

    user_data = {
        "username": "testmanager_nounit",
        "email": "manager_nounit@example.com",
        "password": "ManagerPassword!789",
        "role": "manager",
        "status": "active",
    }
    user_info = await create_user_with_role(
        session_factory=AsyncSessionLocal,
        user_data=user_data,
        casbin_role="role:manager",
        unit_id=None,
        models=models,
        get_password_hash=get_password_hash,
        CasbinRule=CasbinRule,
        app=fastapi_app,
    )
    return await get_auth_headers(client, user_info, AuthURLs.LOGIN)


@pytest_asyncio.fixture(scope="function")
async def deleted_items_dataset(
    seed_lead_dependencies: dict,
    seed_other_unit: dict,
    admin_user_in_db: dict,
) -> dict:
    """Dữ liệu soft-deleted trải 2 đơn vị cho S1/S2.

    UNIT_1 (đơn vị manager):
      - ``lead_a2`` — lead đã xóa (hiện ở danh sách deleted-leads).
      - ``lead_a1`` — lead còn sống + ``consult_a1`` đã xóa (hiện ở
        deleted-consultations; list chỉ trả consultation của lead còn sống).
    UNIT_2 (đơn vị khác): ``lead_b2`` (đã xóa) + ``lead_b1``/``consult_b1``.

    Tên lead mang token ``ZZUNIT1``/``ZZUNIT2`` để test search không lộ chéo.
    """
    unit1 = seed_lead_dependencies["unit_id"]
    unit2 = seed_other_unit["unit_id"]
    status_id = seed_lead_dependencies["initial_status_id"]
    officer_id = admin_user_in_db["id"]
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead_a2 = models.Lead(
                full_name="ZZUNIT1 Deleted Lead", phone="0900000001",
                email="zzunit1lead@test.com", source="website",
                unit_id=unit1, assigned_officer_id=officer_id,
                consultation_status_id=status_id, consultation_count=0,
                status="new", deleted_at=now,
            )
            lead_a1 = models.Lead(
                full_name="ZZUNIT1 Active Lead", phone="0900000002",
                email="zzunit1active@test.com", source="website",
                unit_id=unit1, assigned_officer_id=officer_id,
                consultation_status_id=status_id, consultation_count=0,
                status="new",
            )
            lead_b2 = models.Lead(
                full_name="ZZUNIT2 Deleted Lead", phone="0900000003",
                email="zzunit2lead@test.com", source="website",
                unit_id=unit2, assigned_officer_id=officer_id,
                consultation_status_id=status_id, consultation_count=0,
                status="new", deleted_at=now,
            )
            lead_b1 = models.Lead(
                full_name="ZZUNIT2 Active Lead", phone="0900000004",
                email="zzunit2active@test.com", source="website",
                unit_id=unit2, assigned_officer_id=officer_id,
                consultation_status_id=status_id, consultation_count=0,
                status="new",
            )
            session.add_all([lead_a2, lead_a1, lead_b2, lead_b1])
            await session.flush()

            consult_a1 = models.Consultation(
                lead_id=lead_a1.id, officer_id=officer_id,
                consultation_date=now, method="phone",
                notes="unit1 deleted consult",
                consultation_status_id=status_id, deleted_at=now,
            )
            consult_b1 = models.Consultation(
                lead_id=lead_b1.id, officer_id=officer_id,
                consultation_date=now, method="phone",
                notes="unit2 deleted consult",
                consultation_status_id=status_id, deleted_at=now,
            )
            session.add_all([consult_a1, consult_b1])
            await session.flush()

            data = {
                "unit1": unit1, "unit2": unit2,
                "lead_a2": lead_a2.id, "lead_a1": lead_a1.id,
                "lead_b2": lead_b2.id, "lead_b1": lead_b1.id,
                "consult_a1": consult_a1.id, "consult_b1": consult_b1.id,
            }
    return data


@pytest_asyncio.fixture(scope="function")
async def consultation_cross_lead_dataset(
    seed_lead_dependencies: dict,
    admin_user_in_db: dict,
) -> dict:
    """2 lead còn sống + 1 consultation (còn sống) thuộc ``lead_b`` — cho S3."""
    unit1 = seed_lead_dependencies["unit_id"]
    status_id = seed_lead_dependencies["initial_status_id"]
    officer_id = admin_user_in_db["id"]
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead_a = models.Lead(
                full_name="S3 Lead A", phone="0900000011",
                email="s3leada@test.com", source="website",
                unit_id=unit1, assigned_officer_id=officer_id,
                consultation_status_id=status_id, consultation_count=0,
                status="new",
            )
            lead_b = models.Lead(
                full_name="S3 Lead B", phone="0900000012",
                email="s3leadb@test.com", source="website",
                unit_id=unit1, assigned_officer_id=officer_id,
                consultation_status_id=status_id, consultation_count=0,
                status="new",
            )
            session.add_all([lead_a, lead_b])
            await session.flush()

            consult_b = models.Consultation(
                lead_id=lead_b.id, officer_id=officer_id,
                consultation_date=now, method="phone",
                notes="belongs to lead_b",
                consultation_status_id=status_id,
            )
            session.add(consult_b)
            await session.flush()

            data = {
                "lead_a": lead_a.id, "lead_b": lead_b.id,
                "consult_b": consult_b.id,
            }
    return data


@pytest_asyncio.fixture(scope="function")
async def officer_authored_deleted_consultation(
    seed_lead_dependencies: dict,
    officer_user_in_db: dict,
) -> dict:
    """Lead còn sống + 1 consultation ĐÃ XÓA do OFFICER (≠ admin) tạo.

    Cho route admin-only leads.py restore: người restore (admin) KHÁC officer
    tạo cuộc → officer không nằm sẵn identity-map → serialize officer phải
    eager-load, nếu không → MissingGreenlet 500.
    """
    unit1 = seed_lead_dependencies["unit_id"]
    status_id = seed_lead_dependencies["initial_status_id"]
    officer_id = officer_user_in_db["id"]
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = models.Lead(
                full_name="Officer Authored Lead", phone="0900000021",
                email="officerauthored@test.com", source="website",
                unit_id=unit1, assigned_officer_id=officer_id,
                consultation_status_id=status_id, consultation_count=0,
                status="new",
            )
            session.add(lead)
            await session.flush()

            consult = models.Consultation(
                lead_id=lead.id, officer_id=officer_id,
                consultation_date=now, method="phone",
                notes="created by officer, soft-deleted",
                consultation_status_id=status_id, deleted_at=now,
            )
            session.add(consult)
            await session.flush()

            data = {
                "lead_id": lead.id, "consult_id": consult.id,
                "officer_id": officer_id,
            }
    return data


# ===========================================================================
# S2 — deleted-items list/count/search unit-scope (IDOR đọc)
# ===========================================================================


async def test_s2_admin_sees_all_units(
    client: AsyncClient, admin_token_headers: dict, deleted_items_dataset: dict
):
    r = await client.get(DELETED_ITEMS_URL, headers=admin_token_headers)
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["total_leads"] == 2
    assert data["total_consultations"] == 2
    lead_ids = {row["id"] for row in data["deleted_leads"]}
    assert deleted_items_dataset["lead_a2"] in lead_ids
    assert deleted_items_dataset["lead_b2"] in lead_ids
    consult_ids = {row["id"] for row in data["deleted_consultations"]}
    assert deleted_items_dataset["consult_a1"] in consult_ids
    assert deleted_items_dataset["consult_b1"] in consult_ids


async def test_s2_manager_scoped_to_own_unit(
    client: AsyncClient, manager_token_headers: dict, deleted_items_dataset: dict
):
    r = await client.get(DELETED_ITEMS_URL, headers=manager_token_headers)
    assert r.status_code == 200, r.text
    data = r.json()

    # Counts CŨNG phải unit-scope (không chỉ rows) — nếu không manager suy ra
    # được số lượng lead/consultation của đơn vị khác.
    assert data["total_leads"] == 1
    assert data["total_consultations"] == 1

    lead_ids = {row["id"] for row in data["deleted_leads"]}
    assert deleted_items_dataset["lead_a2"] in lead_ids
    assert deleted_items_dataset["lead_b2"] not in lead_ids

    consult_ids = {row["id"] for row in data["deleted_consultations"]}
    assert deleted_items_dataset["consult_a1"] in consult_ids
    assert deleted_items_dataset["consult_b1"] not in consult_ids


async def test_s2_manager_search_cannot_enumerate_cross_unit(
    client: AsyncClient, manager_token_headers: dict, deleted_items_dataset: dict
):
    # Search token của đơn vị KHÁC → manager UNIT_1 không được thấy gì.
    r = await client.get(
        DELETED_ITEMS_URL, headers=manager_token_headers,
        params={"search": "ZZUNIT2"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    lead_ids = {row["id"] for row in data["deleted_leads"]}
    assert deleted_items_dataset["lead_b2"] not in lead_ids
    assert data["deleted_leads"] == []
    assert data["deleted_consultations"] == []

    # Sanity: search chính đơn vị mình vẫn ra.
    r2 = await client.get(
        DELETED_ITEMS_URL, headers=manager_token_headers,
        params={"search": "ZZUNIT1"},
    )
    assert r2.status_code == 200, r2.text
    own_ids = {row["id"] for row in r2.json()["deleted_leads"]}
    assert deleted_items_dataset["lead_a2"] in own_ids


async def test_s2_manager_without_unit_sees_nothing(
    client: AsyncClient,
    manager_no_unit_token_headers: dict,
    deleted_items_dataset: dict,
):
    r = await client.get(
        DELETED_ITEMS_URL, headers=manager_no_unit_token_headers
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_leads"] == 0
    assert data["total_consultations"] == 0
    assert data["deleted_leads"] == []
    assert data["deleted_consultations"] == []


# ===========================================================================
# S1 — restore consultation cross-unit (IDOR ghi)
# ===========================================================================


async def test_s1_manager_cannot_restore_cross_unit_consultation(
    client: AsyncClient, manager_token_headers: dict, deleted_items_dataset: dict
):
    # consult_b1 thuộc UNIT_2 → manager UNIT_1 phải bị 404 (không lộ tồn tại).
    r = await client.post(
        _restore_consult_url(deleted_items_dataset["consult_b1"]),
        headers=manager_token_headers,
    )
    assert r.status_code == 404, r.text


async def test_s1_manager_can_restore_own_unit_consultation(
    client: AsyncClient, manager_token_headers: dict, deleted_items_dataset: dict
):
    r = await client.post(
        _restore_consult_url(deleted_items_dataset["consult_a1"]),
        headers=manager_token_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == deleted_items_dataset["consult_a1"]


async def test_s1_manager_without_unit_cannot_restore(
    client: AsyncClient,
    manager_no_unit_token_headers: dict,
    deleted_items_dataset: dict,
):
    r = await client.post(
        _restore_consult_url(deleted_items_dataset["consult_a1"]),
        headers=manager_no_unit_token_headers,
    )
    assert r.status_code == 404, r.text


async def test_s1_admin_can_restore_any_unit_consultation(
    client: AsyncClient, admin_token_headers: dict, deleted_items_dataset: dict
):
    r = await client.post(
        _restore_consult_url(deleted_items_dataset["consult_b1"]),
        headers=admin_token_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == deleted_items_dataset["consult_b1"]


# ===========================================================================
# S3 — oracle 400-vs-404 khi dò consultation_id (enumeration)
# ===========================================================================


async def test_s3_delete_consultation_wrong_lead_is_404_not_400(
    client: AsyncClient,
    admin_token_headers: dict,
    consultation_cross_lead_dataset: dict,
):
    lead_a = consultation_cross_lead_dataset["lead_a"]
    consult_b = consultation_cross_lead_dataset["consult_b"]  # thuộc lead_b

    # Tồn tại nhưng thuộc lead khác → PHẢI 404 (trước fix: 400 "does not belong").
    r_mismatch = await client.delete(
        _lead_consult_url(lead_a, consult_b), headers=admin_token_headers
    )
    assert r_mismatch.status_code == 404, r_mismatch.text

    # Không tồn tại → cũng 404. Hai trường hợp KHÔNG phân biệt được (hết oracle).
    r_missing = await client.delete(
        _lead_consult_url(lead_a, 999_999_999), headers=admin_token_headers
    )
    assert r_missing.status_code == 404, r_missing.text
    assert r_mismatch.status_code == r_missing.status_code


async def test_s3_update_consultation_wrong_lead_is_404_not_400(
    client: AsyncClient,
    admin_token_headers: dict,
    consultation_cross_lead_dataset: dict,
):
    lead_a = consultation_cross_lead_dataset["lead_a"]
    consult_b = consultation_cross_lead_dataset["consult_b"]

    r_mismatch = await client.put(
        _lead_consult_url(lead_a, consult_b),
        json={"notes": "tries to touch another lead's consultation"},
        headers=admin_token_headers,
    )
    assert r_mismatch.status_code == 404, r_mismatch.text

    r_missing = await client.put(
        _lead_consult_url(lead_a, 999_999_999),
        json={"notes": "x"},
        headers=admin_token_headers,
    )
    assert r_missing.status_code == 404, r_missing.text


async def test_s3_delete_consultation_correct_lead_still_works(
    client: AsyncClient,
    admin_token_headers: dict,
    consultation_cross_lead_dataset: dict,
):
    # Control: đúng chủ sở hữu vẫn xóa được (fix không chặn nhầm đường hợp lệ).
    lead_b = consultation_cross_lead_dataset["lead_b"]
    consult_b = consultation_cross_lead_dataset["consult_b"]
    r = await client.delete(
        _lead_consult_url(lead_b, consult_b), headers=admin_token_headers
    )
    assert r.status_code == 204, r.text


# ===========================================================================
# Route anh em leads.py restore — officer eager-load (chống 500 MissingGreenlet)
# ===========================================================================


async def test_leads_route_restore_officer_authored_consultation_no_500(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_authored_deleted_consultation: dict,
):
    """POST /api/leads/{id}/consultations/{cid}/restore (admin-only): admin
    restore cuộc do OFFICER tạo → 200, KHÔNG 500 MissingGreenlet.

    Route dùng response_model schemas.Consultation (có ``officer``); khi người
    restore ≠ officer tạo cuộc, officer phải được eager-load ở re-fetch.
    """
    lead_id = officer_authored_deleted_consultation["lead_id"]
    cid = officer_authored_deleted_consultation["consult_id"]
    r = await client.post(
        _restore_via_leads_route(lead_id, cid), headers=admin_token_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == cid
    assert body["officer_id"] == officer_authored_deleted_consultation["officer_id"]
