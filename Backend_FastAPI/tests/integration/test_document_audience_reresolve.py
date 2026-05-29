"""Integration anchors — re-resolve doc snapshot theo audience (feat/document-group-audience-merge).

Validate đường RE-RESOLVE FIRE end-to-end (create → PUT cultural → snapshot):
- THCS↔THPT differentiation (nhu cầu gốc owner): cultural=graduated_thcs → bộ THCS;
  graduated_thpt → bộ THPT (post-backfill group shape).
- §6 completed_* → LOẠI bằng TN khỏi snapshot (finding round-8 #2: LIVE pre-backfill).
- P0-B: re-resolve khi ProfileDocument đã tồn tại → add_path_documents_delta KHÔNG
  vi phạm uq_profile_document_path; PUT lặp → short-circuit, không lỗi.
- Round-3 invariant: merge per-key giữ schema_version=2 + admission_path_id.

Dùng group shape POST-BACKFILL (NỀN base-only + lớp POST_THPT + lớp POST_THCS) để
chứng minh machinery audience hoạt động NGAY (cái mà ĐỢT B backfill sẽ tạo).
"""
import random
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal

pytestmark = pytest.mark.asyncio


async def _get_or_create_doc_type(session, code: str, name: str) -> int:
    existing = (
        await session.execute(
            select(models.ConfigDocumentType).where(
                models.ConfigDocumentType.code == code
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing.id
    dt = models.ConfigDocumentType(code=code, name=name, is_active=True)
    session.add(dt)
    await session.flush()
    return dt.id


async def _setup_audience_data(major_id: int, unit_id: int, officer_id: int) -> dict:
    """Tạo offering_type + path + lead + 3 DocumentGroup (NỀN/POST_THPT/POST_THCS).

    Group shape = POST-BACKFILL: NỀN={cccd}; POST_THPT={hoc_ba_thpt,
    bang_tot_nghiep_thpt}; POST_THCS={hoc_ba_thcs, bang_tot_nghiep_thcs}.
    """
    suffix = random.randint(10000, 99999)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            ot = models.ConfigOfferingType(
                code=f"aud_type_{suffix}",
                name=f"Audience Test OT {suffix}",
                is_active=True,
            )
            session.add(ot)
            await session.flush()

            offering = models.ProgramOffering(
                offering_type=f"AudTest_{suffix}",
                program_id=major_id,
                offering_type_id=ot.id,
            )
            session.add(offering)
            await session.flush()

            academic_info = models.OfferingAcademicInfo(
                offering_id=offering.id, academic_year=2025, is_published=True
            )
            session.add(academic_info)
            await session.flush()

            method = models.AdmissionMethod(
                code=f"aud_method_{suffix}", name="Aud Method", is_active=True
            )
            session.add(method)
            await session.flush()

            criteria = models.AdmissionCriteria(
                method_id=method.id,
                code=f"aud_criteria_{suffix}",
                name="Aud Criteria",
                min_gpa=0,
                is_active=True,
            )
            session.add(criteria)
            await session.flush()

            from tests.fixtures.builders import AdmissionRoundBuilder

            round_id = await AdmissionRoundBuilder.get_or_create_default_round(
                session, academic_year=2025
            )
            path = models.AdmissionPath(
                academic_info_id=academic_info.id,
                admission_method_id=method.id,
                admission_round_id=round_id,
                criteria_id=criteria.id,
                status="active",
            )
            session.add(path)
            await session.flush()

            # Doc types (get-or-create — bằng TN THCS có thể chưa có trong qlts_test).
            cccd = await _get_or_create_doc_type(session, "cccd", "Căn cước công dân")
            hb_thpt = await _get_or_create_doc_type(session, "hoc_ba_thpt", "Học bạ THPT")
            bts_thpt = await _get_or_create_doc_type(
                session, "bang_tot_nghiep_thpt", "Bằng tốt nghiệp THPT"
            )
            hb_thcs = await _get_or_create_doc_type(session, "hoc_ba_thcs", "Học bạ THCS")
            bts_thcs = await _get_or_create_doc_type(
                session, "bang_tot_nghiep_thcs", "Bằng tốt nghiệp THCS"
            )

            def _mk_group(code, audience, items):
                g = models.DocumentGroup(
                    offering_type_id=ot.id,
                    admission_method_id=None,
                    admission_path_id=None,
                    code=code,
                    name=code,
                    is_active=True,
                    applicable_audience=audience,
                )
                session.add(g)
                return g

            g_base = _mk_group(f"AUD_BASE_{suffix}", None, None)
            g_thpt = _mk_group(f"AUD_THPT_{suffix}", ["POST_THPT"], None)
            g_thcs = _mk_group(f"AUD_THCS_{suffix}", ["POST_THCS"], None)
            await session.flush()

            def _mk_item(group_id, dt_id, order):
                session.add(
                    models.DocumentGroupItem(
                        group_id=group_id,
                        document_type_id=dt_id,
                        is_mandatory=True,
                        requires_upload=True,
                        submission_format="photo",
                        display_order=order,
                    )
                )

            _mk_item(g_base.id, cccd, 1)
            _mk_item(g_thpt.id, hb_thpt, 2)
            _mk_item(g_thpt.id, bts_thpt, 3)
            _mk_item(g_thcs.id, hb_thcs, 2)
            _mk_item(g_thcs.id, bts_thcs, 3)
            await session.flush()

            lead_uid = uuid.uuid4().hex[:12]
            lead = models.Lead(
                full_name=f"Aud Lead {lead_uid}",
                phone=f"090{random.randint(1000000, 9999999)}",
                email=f"aud_{lead_uid}@test.com",
                source="website",
                unit_id=unit_id,
                assigned_officer_id=officer_id,
                offering_id=offering.id,
            )
            session.add(lead)
            await session.flush()
            session.add(
                models.Consultation(
                    lead_id=lead.id,
                    consultation_date=datetime.now(timezone.utc),
                    method="phone",
                    notes="aud",
                    officer_id=officer_id,
                    consultation_status_id="sts06",
                )
            )
            await session.flush()

            return {
                "lead_id": lead.id,
                "admission_method_id": method.id,
                "admission_round_id": round_id,
            }


async def _auth(client: AsyncClient, user_info: dict) -> dict:
    res = await client.post(
        "/api/auth/login",
        data={"username": user_info["username"], "password": user_info["password"]},
    )
    assert res.status_code == 200, res.text
    token = res.cookies.get("access_token")
    client.cookies.delete("access_token")
    return {"Authorization": f"Bearer {token}"}


async def _create_profile(client, headers, data) -> int:
    res = await client.post(
        "/api/admissions",
        json={
            "lead_id": data["lead_id"],
            "admission_method_id": data["admission_method_id"],
            "admission_round_id": data["admission_round_id"],
            "academic_year": 2025,
        },
        headers=headers,
    )
    assert res.status_code == 201, f"create failed: {res.text}"
    return res.json()["id"]


async def _snapshot_mandatory(profile_id: int) -> set:
    async with AsyncSessionLocal() as session:
        p = (
            await session.execute(
                select(models.AdmissionProfile).where(
                    models.AdmissionProfile.id == profile_id
                )
            )
        ).scalar_one()
        return set((p.applied_rules or {}).get("mandatory_docs") or [])


async def _profile_doc_codes(profile_id: int) -> set:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(models.ConfigDocumentType.code)
                .join(
                    models.ProfileDocument,
                    models.ProfileDocument.document_type_id
                    == models.ConfigDocumentType.id,
                )
                .where(models.ProfileDocument.profile_id == profile_id)
            )
        ).scalars().all()
        return set(rows)


class TestReresolveAudience:
    async def test_create_snapshot_is_base_only(
        self, client, officer_user_in_db, seed_lead_dependencies
    ):
        data = await _setup_audience_data(
            seed_lead_dependencies["major_program_id"],
            seed_lead_dependencies["unit_id"],
            officer_user_in_db["id"],
        )
        headers = await _auth(client, officer_user_in_db)
        pid = await _create_profile(client, headers, data)
        # create audience_set=None → CHỈ NỀN.
        assert await _snapshot_mandatory(pid) == {"cccd"}

    async def test_reresolve_thcs_loads_thcs_docs(
        self, client, officer_user_in_db, seed_lead_dependencies
    ):
        """Nhu cầu gốc: TS tốt nghiệp THCS → bộ THCS, KHÔNG dính bộ THPT."""
        data = await _setup_audience_data(
            seed_lead_dependencies["major_program_id"],
            seed_lead_dependencies["unit_id"],
            officer_user_in_db["id"],
        )
        headers = await _auth(client, officer_user_in_db)
        pid = await _create_profile(client, headers, data)
        res = await client.put(
            f"/api/admissions/{pid}",
            json={"cultural_education_level": "graduated_thcs", "version": 1},
            headers=headers,
        )
        assert res.status_code == 200, res.text
        snap = await _snapshot_mandatory(pid)
        assert snap == {"cccd", "hoc_ba_thcs", "bang_tot_nghiep_thcs"}
        assert "hoc_ba_thpt" not in snap and "bang_tot_nghiep_thpt" not in snap

    async def test_reresolve_thpt_loads_thpt_docs(
        self, client, officer_user_in_db, seed_lead_dependencies
    ):
        data = await _setup_audience_data(
            seed_lead_dependencies["major_program_id"],
            seed_lead_dependencies["unit_id"],
            officer_user_in_db["id"],
        )
        headers = await _auth(client, officer_user_in_db)
        pid = await _create_profile(client, headers, data)
        res = await client.put(
            f"/api/admissions/{pid}",
            json={"cultural_education_level": "graduated_thpt", "version": 1},
            headers=headers,
        )
        assert res.status_code == 200, res.text
        snap = await _snapshot_mandatory(pid)
        assert snap == {"cccd", "hoc_ba_thpt", "bang_tot_nghiep_thpt"}
        assert "hoc_ba_thcs" not in snap

    async def test_reresolve_completed_thpt_drops_diploma(
        self, client, officer_user_in_db, seed_lead_dependencies
    ):
        """§6 / finding round-8 #2: completed_thpt → LOẠI bằng TN khỏi snapshot."""
        data = await _setup_audience_data(
            seed_lead_dependencies["major_program_id"],
            seed_lead_dependencies["unit_id"],
            officer_user_in_db["id"],
        )
        headers = await _auth(client, officer_user_in_db)
        pid = await _create_profile(client, headers, data)
        res = await client.put(
            f"/api/admissions/{pid}",
            json={"cultural_education_level": "completed_thpt", "version": 1},
            headers=headers,
        )
        assert res.status_code == 200, res.text
        snap = await _snapshot_mandatory(pid)
        assert "hoc_ba_thpt" in snap
        assert "bang_tot_nghiep_thpt" not in snap  # completed → bỏ bằng TN

    async def test_reresolve_delta_no_unique_violation_idempotent(
        self, client, officer_user_in_db, seed_lead_dependencies
    ):
        """P0-B: re-resolve khi ProfileDocument (cccd) đã có → delta INSERT chỉ
        code thiếu, KHÔNG vi phạm uq_profile_document_path; PUT lặp → OK."""
        data = await _setup_audience_data(
            seed_lead_dependencies["major_program_id"],
            seed_lead_dependencies["unit_id"],
            officer_user_in_db["id"],
        )
        headers = await _auth(client, officer_user_in_db)
        pid = await _create_profile(client, headers, data)
        # PUT 1 — re-resolve thêm thpt docs.
        r1 = await client.put(
            f"/api/admissions/{pid}",
            json={"cultural_education_level": "graduated_thpt", "version": 1},
            headers=headers,
        )
        assert r1.status_code == 200, r1.text
        codes = await _profile_doc_codes(pid)
        assert {"cccd", "hoc_ba_thpt", "bang_tot_nghiep_thpt"} <= codes
        # PUT 2 — cùng cultural → short-circuit / delta idempotent, KHÔNG lỗi unique.
        v2 = r1.json().get("version", 2)
        r2 = await client.put(
            f"/api/admissions/{pid}",
            json={"cultural_education_level": "graduated_thpt", "version": v2},
            headers=headers,
        )
        assert r2.status_code == 200, r2.text

    async def test_reresolve_preserves_applied_rules_keys(
        self, client, officer_user_in_db, seed_lead_dependencies
    ):
        """Round-3 invariant: merge per-key giữ schema_version + admission_path_id."""
        data = await _setup_audience_data(
            seed_lead_dependencies["major_program_id"],
            seed_lead_dependencies["unit_id"],
            officer_user_in_db["id"],
        )
        headers = await _auth(client, officer_user_in_db)
        pid = await _create_profile(client, headers, data)
        await client.put(
            f"/api/admissions/{pid}",
            json={"cultural_education_level": "graduated_thcs", "version": 1},
            headers=headers,
        )
        async with AsyncSessionLocal() as session:
            p = (
                await session.execute(
                    select(models.AdmissionProfile).where(
                        models.AdmissionProfile.id == pid
                    )
                )
            ).scalar_one()
            ar = p.applied_rules or {}
        assert ar.get("schema_version") == 2  # N1: không bump
        assert ar.get("admission_path_id") is not None
        assert "allow_unverified_submission" in ar
