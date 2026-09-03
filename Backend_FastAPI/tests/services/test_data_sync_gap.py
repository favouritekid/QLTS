
import random
import pytest
from datetime import datetime, timezone
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from app.services import lead_service

pytestmark = pytest.mark.asyncio


async def get_auth_headers(client, user_info: dict) -> dict:
    login_data = {"username": user_info["username"], "password": user_info["password"]}
    res = await client.post("/api/auth/login", data=login_data)
    assert res.status_code == 200, f"Login failed: {res.text}"
    access_token = res.cookies.get("access_token")
    client.cookies.delete("access_token")
    return {"Authorization": f"Bearer {access_token}"}


async def setup_admission_api_data(major_id, unit_id, officer_id, academic_year=2026):
    """Set up full chain for admission profile creation via API."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            offering_type_config = models.ConfigOfferingType(
                code=f"sync_type_{random.randint(10000, 99999)}",
                name="Sync Test Offering Type",
                is_active=True,
            )
            session.add(offering_type_config)
            await session.flush()

            offering = models.ProgramOffering(
                offering_type=f"SyncTest_{random.randint(10000, 99999)}",
                program_id=major_id,
                offering_type_id=offering_type_config.id,
            )
            session.add(offering)
            await session.flush()

            academic_info = models.OfferingAcademicInfo(
                offering_id=offering.id,
                academic_year=academic_year,
                is_published=True,
            )
            session.add(academic_info)
            await session.flush()

            method = models.AdmissionMethod(
                code=f"sync_method_{random.randint(10000, 99999)}",
                name="Sync Test Method",
                is_active=True,
            )
            session.add(method)
            await session.flush()

            criteria = models.AdmissionCriteria(
                method_id=method.id,
                code=f"sync_criteria_{random.randint(10000, 99999)}",
                name="Sync Test Criteria",
                min_gpa=0,
                is_active=True,
            )
            session.add(criteria)
            await session.flush()

            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(
                session, academic_year=academic_info.academic_year,
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

            lead = models.Lead(
                full_name="Sync Test Lead",
                phone="0900000001",
                email="sync_test@example.com",
                source="website",
                unit_id=unit_id,
                assigned_officer_id=officer_id,
                offering_id=offering.id,
            )
            session.add(lead)
            await session.flush()

            consultation = models.Consultation(
                lead_id=lead.id,
                consultation_date=datetime.now(timezone.utc),
                method="phone",
                notes="Sync test",
                officer_id=officer_id,
                consultation_status_id="sts06",
            )
            session.add(consultation)
            await session.flush()

    return {
        "lead_id": lead.id,
        "admission_method_id": method.id,
        # Round contract hardening (plan v4, 2026-05-25):
        # ``AdmissionProfileCreate`` now REQUIRES admission_round_id +
        # academic_year — app/schemas/admission.py:470 and :482. Without
        # them POST /api/admissions 422s before create_profile ever runs,
        # so the staleness gap this test documents is never reached.
        # The round is validated against the year server-side
        # (app/services/admission_service.py:4561-4570), so echo back the
        # SAME year the AdmissionPath was seeded on.
        "admission_round_id": round_id,
        "academic_year": academic_info.academic_year,
    }


class TestDataSyncGap:
    """
    Khoá hợp đồng đồng bộ CÓ ĐIỀU KIỆN giữa Lead và Admission Profile.

    Ma trận nguồn chuẩn ở `app/services/lead_profile_sync.py`:
    draft/submitted -> Sync; approved/enrolled -> Snapshot, và sửa định
    danh lead bị CHẶN. Tên lớp giữ theo lịch sử; "GAP #2" trong
    `docs/LEAD_ADMISSION_AUDIT_REPORT.md` nay là TÍNH NĂNG, không phải lỗ hổng.
    """

    async def test_lead_update_syncs_to_editable_profile_only(
        self,
        client,
        officer_user_in_db,
        seed_lead_dependencies,
    ):
        """
        Đồng bộ Lead -> Profile là CÓ ĐIỀU KIỆN theo trạng thái hồ sơ.

        Ca này từng tên `..._does_not_sync_to_profile` và khẳng định hồ sơ
        đứng yên — "GAP #2". Giao ước ĐÃ ĐỔI: `app/services/lead_profile_sync.py`
        khai ma trận rõ (draft/submitted: Sync; approved/enrolled: Snapshot),
        và `app/services/lead_service.py:1916-1938` gọi `sync_profile_from_lead`
        sau mỗi `update_lead`. "Gap" không còn là gap — nó là tính năng.

        Ca này khoá đúng tính CÓ ĐIỀU KIỆN ấy, hai vế:
          A. hồ sơ `draft`    -> lead đổi thì hồ sơ ĐỔI THEO;
          B. hồ sơ `approved` -> lead đổi thì hồ sơ ĐỨNG YÊN.

        Chỉ vế A là khẳng định rỗng: gỡ hẳn cổng trạng thái trong
        `sync_profile_from_lead` thì vế A vẫn xanh. Vế B canh cái cổng đó.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        major_id = seed_lead_dependencies["major_program_id"]

        data = await setup_admission_api_data(
            major_id=major_id,
            unit_id=unit_id,
            officer_id=officer_user_in_db["id"],
        )

        # 3. Create Admission Profile
        headers = await get_auth_headers(client, officer_user_in_db)
        create_res = await client.post(
            "/api/admissions",
            json={
                "lead_id": data["lead_id"],
                "admission_method_id": data["admission_method_id"],
                "admission_round_id": data["admission_round_id"],
                "academic_year": data["academic_year"],
            },
            headers=headers,
        )
        assert create_res.status_code == 201, f"Create failed: {create_res.text}"
        profile_id = create_res.json()["id"]

        # Verify initial sync (copy)
        async with AsyncSessionLocal() as session:
            profile = await session.get(models.AdmissionProfile, profile_id)
            assert profile.phone == "0900000001"
            assert profile.email == "sync_test@example.com"

        # 4. Update Lead Phone (Phone A -> Phone B)
        async with AsyncSessionLocal() as session:
            user = await session.get(models.User, officer_user_in_db["id"])

            from app.schemas.lead import LeadUpdate
            update_data = LeadUpdate(phone="0909999999", email="updated@example.com", version=1)

            await lead_service.update_lead(session, data["lead_id"], update_data, user)
            await session.commit()

        # 5. VẾ A — hồ sơ `draft`: đồng bộ PHẢI xảy ra
        async with AsyncSessionLocal() as session:
            profile = await session.get(models.AdmissionProfile, profile_id)
            lead = await session.get(models.Lead, data["lead_id"])

            # Lead is updated
            assert lead.phone == "0909999999"
            assert lead.email == "updated@example.com"

            assert profile.status == "draft", (
                f"tiền đề vế A hỏng: hồ sơ phải ở `draft`, đang là {profile.status!r}"
            )
            assert profile.phone == "0909999999", (
                "hồ sơ `draft` PHẢI nhận đồng bộ từ lead (ma trận: draft -> Sync); "
                f"đang là {profile.phone!r}"
            )
            assert profile.email == "updated@example.com", (
                f"email hồ sơ `draft` phải đồng bộ; đang là {profile.email!r}"
            )

        # 6. VẾ B — hồ sơ KHOÁ (`approved`): đồng bộ phải DỪNG
        async with AsyncSessionLocal() as session:
            profile = await session.get(models.AdmissionProfile, profile_id)
            profile.status = "approved"
            await session.commit()

        # ĐO ĐƯỢC: sản phẩm KHÔNG chỉ ngừng đồng bộ — nó CHẶN HẲN việc sửa
        # định danh lead khi hồ sơ đã ở trạng thái pháp lý. Đúng ô cuối của ma
        # trận `lead_profile_sync.py`: approved -> Lead Identity Edit BLOCKED.
        # Khẳng định theo đúng cơ chế ấy thay vì theo hệ quả yếu hơn.
        from app.utils.exceptions import BusinessRuleViolation

        async with AsyncSessionLocal() as session:
            user = await session.get(models.User, officer_user_in_db["id"])
            lead = await session.get(models.Lead, data["lead_id"])
            from app.schemas.lead import LeadUpdate
            with pytest.raises(BusinessRuleViolation, match="định danh"):
                await lead_service.update_lead(
                    session,
                    data["lead_id"],
                    LeadUpdate(
                        phone="0908888888",
                        email="locked@example.com",
                        version=lead.version,
                    ),
                    user,
                )
            await session.rollback()

        async with AsyncSessionLocal() as session:
            profile = await session.get(models.AdmissionProfile, profile_id)
            lead = await session.get(models.Lead, data["lead_id"])

            assert lead.phone == "0909999999", (
                f"lead KHÔNG được đổi khi hồ sơ đã duyệt; đang là {lead.phone!r}"
            )
            assert profile.phone == "0909999999", (
                "hồ sơ `approved` là SNAPSHOT, không được nhận đồng bộ "
                f"(ma trận: approved -> Snapshot); đang là {profile.phone!r}"
            )
            assert profile.email == "updated@example.com", (
                f"email hồ sơ `approved` không được đổi; đang là {profile.email!r}"
            )
