"""ADM-009 regression: admission-config detail endpoints must respect
the same ``active_only`` filter as the list endpoints.

The list routes already plug ``Depends(get_config_filter)`` so non-admin
callers (officer / regular user) only see active items. Before the fix,
the by-code detail endpoints (subject, subject-group, method) and the
shared document-group endpoint had no filter — a non-admin could read
inactive/draft config rows by knowing the code, leaking what's in the
admin pipeline. The filter is now applied consistently.
"""

import time

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal


pytestmark = pytest.mark.asyncio


async def _login(client: AsyncClient, user_info: dict) -> dict:
    res = await client.post(
        "/api/auth/login",
        data={"username": user_info["username"], "password": user_info["password"]},
    )
    if res.status_code != 200:
        pytest.fail(f"Login failed: {res.status_code} - {res.text}")
    token = res.cookies.get("access_token")
    if not token:
        pytest.fail("Login succeeded but access_token cookie not found")
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def inactive_subject(setup_test_database):
    ts = int(time.time() * 1000)
    code = f"INACT_SUBJ_{ts}"
    async with AsyncSessionLocal() as s:
        async with s.begin():
            subject = models.Subject(
                code=code,
                name_vi="Môn ẩn",
                is_active=False,
            )
            s.add(subject)
    return code


@pytest_asyncio.fixture
async def inactive_subject_group(setup_test_database):
    # SubjectGroup.code is VARCHAR(10); keep tail short.
    ts_tail = str(int(time.time() * 1000))[-6:]
    code = f"IG{ts_tail}"
    async with AsyncSessionLocal() as s:
        async with s.begin():
            sg = models.SubjectGroup(
                code=code,
                name="Khối ẩn",
                is_active=False,
            )
            s.add(sg)
    return code


@pytest_asyncio.fixture
async def inactive_admission_method(setup_test_database):
    ts = int(time.time() * 1000)
    code = f"INACT_AM_{ts}"
    async with AsyncSessionLocal() as s:
        async with s.begin():
            am = models.AdmissionMethod(
                code=code,
                name="Phương thức ẩn",
                requires_gpa=False,
                requires_subject_scores=False,
                is_active=False,
            )
            s.add(am)
    return code


@pytest_asyncio.fixture
async def inactive_shared_doc_group(setup_test_database):
    """Create an inactive shared DocumentGroup (no admission_method_id =
    shared) for an offering type."""
    ts_tail = str(int(time.time() * 1000))[-9:]
    async with AsyncSessionLocal() as s:
        async with s.begin():
            ot = models.ConfigOfferingType(
                code=f"OT_{ts_tail}",
                name=f"OT inactive {ts_tail}",
            )
            s.add(ot)
            await s.flush()
            grp = models.DocumentGroup(
                offering_type_id=ot.id,
                admission_method_id=None,  # shared
                code=f"DG_{ts_tail}",
                name="Hồ sơ ẩn",
                is_active=False,
            )
            s.add(grp)
            await s.flush()
            return ot.id


class TestSubjectByCodeFilter:
    async def test_officer_cannot_read_inactive_subject_by_code(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        inactive_subject: str,
    ):
        headers = await _login(client, officer_user_in_db)
        response = await client.get(
            f"/api/admission-config/subjects/{inactive_subject}",
            headers=headers,
        )
        assert response.status_code == 404, (
            f"ADM-009: officer must not see inactive subject by code; "
            f"got {response.status_code} - {response.text[:200]}"
        )

    async def test_admin_can_read_inactive_subject_with_active_only_false(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        inactive_subject: str,
    ):
        headers = await _login(client, admin_user_in_db)
        response = await client.get(
            f"/api/admission-config/subjects/{inactive_subject}"
            "?active_only=false",
            headers=headers,
        )
        assert response.status_code == 200, (
            f"Admin with active_only=false must see inactive subject; "
            f"got {response.status_code} - {response.text[:200]}"
        )


class TestSubjectGroupByCodeFilter:
    async def test_officer_cannot_read_inactive_subject_group_by_code(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        inactive_subject_group: str,
    ):
        headers = await _login(client, officer_user_in_db)
        response = await client.get(
            f"/api/admission-config/subject-groups/{inactive_subject_group}",
            headers=headers,
        )
        assert response.status_code == 404, (
            f"ADM-009: officer must not see inactive subject group by code; "
            f"got {response.status_code} - {response.text[:200]}"
        )

    async def test_admin_can_read_inactive_subject_group_with_override(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        inactive_subject_group: str,
    ):
        headers = await _login(client, admin_user_in_db)
        response = await client.get(
            f"/api/admission-config/subject-groups/{inactive_subject_group}"
            "?active_only=false",
            headers=headers,
        )
        assert response.status_code == 200, (
            f"Admin with active_only=false must see inactive subject group; "
            f"got {response.status_code} - {response.text[:200]}"
        )


class TestMethodByCodeFilter:
    async def test_officer_cannot_read_inactive_method_by_code(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        inactive_admission_method: str,
    ):
        headers = await _login(client, officer_user_in_db)
        response = await client.get(
            f"/api/admission-config/methods/{inactive_admission_method}",
            headers=headers,
        )
        assert response.status_code == 404, (
            f"ADM-009: officer must not see inactive admission method by code; "
            f"got {response.status_code} - {response.text[:200]}"
        )

    async def test_admin_can_read_inactive_method_with_override(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        inactive_admission_method: str,
    ):
        headers = await _login(client, admin_user_in_db)
        response = await client.get(
            f"/api/admission-config/methods/{inactive_admission_method}"
            "?active_only=false",
            headers=headers,
        )
        assert response.status_code == 200, (
            f"Admin with active_only=false must see inactive method; "
            f"got {response.status_code} - {response.text[:200]}"
        )


class TestSharedDocumentGroupFilter:
    async def test_officer_cannot_read_inactive_shared_doc_group(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        inactive_shared_doc_group: int,
    ):
        headers = await _login(client, officer_user_in_db)
        response = await client.get(
            f"/api/admission-config/document-groups/shared/{inactive_shared_doc_group}",
            headers=headers,
        )
        # The shared-doc endpoint returns ``None`` (200 with null body)
        # for "no group / filtered out" — that's the existing list-shape
        # contract. Either an explicit 404 or a null body counts as
        # "not visible to officer".
        if response.status_code == 200:
            assert response.json() is None, (
                "ADM-009: officer must not see inactive shared doc group; "
                f"got body {response.text[:200]}"
            )
        else:
            assert response.status_code in (403, 404), (
                f"ADM-009: officer must not see inactive shared doc group; "
                f"got {response.status_code} - {response.text[:200]}"
            )

    async def test_admin_with_override_currently_still_filtered_by_repo(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        inactive_shared_doc_group: int,
    ):
        """Note: ``DocumentGroupRepository.get_shared_groups`` hard-codes
        ``is_active == True`` on the SQL query, so even when the route
        passes ``active_only=False`` the repo never returns an inactive
        row. ADM-009 only adds the *route-level* filter for parity with
        the other three detail endpoints; making admin override actually
        return inactive shared groups would require widening the repo
        signature, which is intentionally out of PR scope.
        """
        headers = await _login(client, admin_user_in_db)
        response = await client.get(
            f"/api/admission-config/document-groups/shared/{inactive_shared_doc_group}"
            "?active_only=false",
            headers=headers,
        )
        # Endpoint contract is "200 with null body when not found".
        # Either null body or 404 counts as filtered.
        if response.status_code == 200:
            assert response.json() is None, (
                "Repo always filters inactive — body must be null"
            )
        else:
            assert response.status_code == 404
