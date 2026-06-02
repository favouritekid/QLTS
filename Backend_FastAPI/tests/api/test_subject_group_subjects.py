"""Granular subject↔group M2M sub-resource endpoints.

The "Phân môn vào tổ hợp" tab calls the granular sub-resource
``.../subject-groups/{group_id}/subjects[/{subject_id}]`` (POST/DELETE/PUT),
but the backend only had replace-all (`PUT /subject-groups/{id}` with
``subject_ids``) — the granular routes 404'd, leaving subject groups empty.
These tests lock the new contract: add at a position, remove, reorder, with
404 (missing group/subject) + 409 (duplicate) + position>=1 gates.
"""
import time

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal


pytestmark = pytest.mark.asyncio

BASE = "/api/admission-config/subject-groups"


async def _login(client: AsyncClient, user_info: dict) -> dict:
    res = await client.post(
        "/api/auth/login",
        data={
            "username": user_info["username"],
            "password": user_info["password"],
        },
    )
    assert res.status_code == 200, res.text
    token = res.cookies.get("access_token")
    assert token, "Login succeeded but access_token cookie missing"
    # Clear the cookie jar so the Bearer header is the sole auth (avoids
    # cross-request cookie contamination per memory test-httpx-cookie-jar).
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def group_and_subjects(setup_test_database) -> dict:
    """A fresh empty subject group + 2 standalone subjects (not yet linked)."""
    tail = str(int(time.time() * 1000))[-6:]
    async with AsyncSessionLocal() as s:
        async with s.begin():
            group = models.SubjectGroup(
                code=f"G{tail}", name="Tổ hợp test", is_active=True,
            )
            subj1 = models.Subject(
                code=f"sub1_{tail}", name_vi="Toán", is_active=True,
            )
            subj2 = models.Subject(
                code=f"sub2_{tail}", name_vi="Vật lý", is_active=True,
            )
            s.add_all([group, subj1, subj2])
            await s.flush()
            ids = {
                "group_id": group.id,
                "subject1_id": subj1.id,
                "subject2_id": subj2.id,
            }
    return ids


class TestAddSubjectToGroup:
    async def test_add_returns_group_with_subject(
        self, client, admin_user_in_db, group_and_subjects
    ):
        headers = await _login(client, admin_user_in_db)
        g = group_and_subjects
        resp = await client.post(
            f"{BASE}/{g['group_id']}/subjects",
            json={"subject_id": g["subject1_id"], "position": 1},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert len(body["subjects"]) == 1
        assert body["subjects"][0]["position"] == 1

    async def test_add_duplicate_returns_409(
        self, client, admin_user_in_db, group_and_subjects
    ):
        headers = await _login(client, admin_user_in_db)
        g = group_and_subjects
        first = await client.post(
            f"{BASE}/{g['group_id']}/subjects",
            json={"subject_id": g["subject1_id"], "position": 1},
            headers=headers,
        )
        assert first.status_code == 201, first.text
        dup = await client.post(
            f"{BASE}/{g['group_id']}/subjects",
            json={"subject_id": g["subject1_id"], "position": 2},
            headers=headers,
        )
        assert dup.status_code == 409, dup.text

    async def test_add_to_missing_group_returns_404(
        self, client, admin_user_in_db, group_and_subjects
    ):
        headers = await _login(client, admin_user_in_db)
        sid = group_and_subjects["subject1_id"]
        resp = await client.post(
            f"{BASE}/999999/subjects",
            json={"subject_id": sid, "position": 1},
            headers=headers,
        )
        assert resp.status_code == 404, resp.text

    async def test_add_missing_subject_returns_404(
        self, client, admin_user_in_db, group_and_subjects
    ):
        headers = await _login(client, admin_user_in_db)
        resp = await client.post(
            f"{BASE}/{group_and_subjects['group_id']}/subjects",
            json={"subject_id": 999999, "position": 1},
            headers=headers,
        )
        assert resp.status_code == 404, resp.text

    async def test_position_zero_returns_422(
        self, client, admin_user_in_db, group_and_subjects
    ):
        headers = await _login(client, admin_user_in_db)
        g = group_and_subjects
        resp = await client.post(
            f"{BASE}/{g['group_id']}/subjects",
            json={"subject_id": g["subject1_id"], "position": 0},
            headers=headers,
        )
        assert resp.status_code == 422, resp.text


class TestRemoveSubjectFromGroup:
    async def test_remove_clears_mapping(
        self, client, admin_user_in_db, group_and_subjects
    ):
        headers = await _login(client, admin_user_in_db)
        g = group_and_subjects
        await client.post(
            f"{BASE}/{g['group_id']}/subjects",
            json={"subject_id": g["subject1_id"], "position": 1},
            headers=headers,
        )
        resp = await client.delete(
            f"{BASE}/{g['group_id']}/subjects/{g['subject1_id']}",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["subjects"] == []

    async def test_remove_unmapped_returns_404(
        self, client, admin_user_in_db, group_and_subjects
    ):
        headers = await _login(client, admin_user_in_db)
        g = group_and_subjects
        resp = await client.delete(
            f"{BASE}/{g['group_id']}/subjects/{g['subject1_id']}",
            headers=headers,
        )
        assert resp.status_code == 404, resp.text


class TestUpdateSubjectPosition:
    async def test_update_position(
        self, client, admin_user_in_db, group_and_subjects
    ):
        headers = await _login(client, admin_user_in_db)
        g = group_and_subjects
        await client.post(
            f"{BASE}/{g['group_id']}/subjects",
            json={"subject_id": g["subject1_id"], "position": 1},
            headers=headers,
        )
        resp = await client.put(
            f"{BASE}/{g['group_id']}/subjects/{g['subject1_id']}",
            json={"position": 5},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        subjects = resp.json()["subjects"]
        assert subjects[0]["position"] == 5

    async def test_update_unmapped_returns_404(
        self, client, admin_user_in_db, group_and_subjects
    ):
        headers = await _login(client, admin_user_in_db)
        g = group_and_subjects
        resp = await client.put(
            f"{BASE}/{g['group_id']}/subjects/{g['subject1_id']}",
            json={"position": 2},
            headers=headers,
        )
        assert resp.status_code == 404, resp.text
