"""Cohort "đã đóng học phí HK1" cho export sang hệ KTX.

Trọng tâm: cohort phải bám ĐÚNG năm học được hỏi. Một lead được phép có nhiều hồ
sơ — mỗi mùa một cái (``uq_admission_profile_lead_year``) — nên nếu vị từ tiền
mượn mốc ``max(academic_year)`` của lead thay vì lọc thẳng theo năm, hồ sơ mùa cũ
sẽ biến mất ngay khi thí sinh nộp lại mùa sau. Hai test hai chiều bên dưới ghim
điều đó.

conftest truncate toàn bộ bảng giữa các test nên mỗi test tự dựng trọn dữ liệu.
"""

from decimal import Decimal

import pytest
import pytest_asyncio

from app import models
from app.database import AsyncSessionLocal
from app.models.finance import Fee, FeeStatusEnum
from app.repositories.dorm_export_repository import (
    DORM_COHORT_STATUSES,
    describe_excluded_statuses,
    select_paid_hk1_cohort,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _isolated_db(setup_test_database):
    """Truncate mọi bảng trước từng test.

    ``setup_test_database`` trong ``tests/conftest.py`` cố ý để ``autouse=False``
    nên test nào không yêu cầu tường minh sẽ CHẠY TRÊN DỮ LIỆU SÓT của test
    trước. Các assert ở đây so khớp CHÍNH XÁC danh sách hồ sơ trả về, nên phải
    tự dựng trọn bộ dữ liệu trên nền sạch.
    """
    yield


_CCCD_SEQ = iter(range(1, 10_000))


def _next_cccd() -> str:
    return f"0791000{next(_CCCD_SEQ):05d}"


async def _make_unit(name: str = "Đơn vị KTX test") -> int:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            unit = models.OrganizationUnit(name=name, type="department")
            session.add(unit)
            await session.flush()
            return unit.id


async def _make_lead(unit_id: int, *, officer_id=None, deleted_at=None) -> int:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = models.Lead(
                full_name="Lead KTX",
                phone="0902224444",
                email=f"dorm_{_next_cccd()}@test.com",
                source="website",
                unit_id=unit_id,
                assigned_officer_id=officer_id,
                deleted_at=deleted_at,
            )
            session.add(lead)
            await session.flush()
            return lead.id


async def _make_profile(
    lead_id: int,
    *,
    academic_year: int,
    status: str = "confirmed",
    is_dropped=None,
) -> int:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            profile = models.AdmissionProfile(
                lead_id=lead_id,
                status=status,
                citizen_id=_next_cccd(),
                academic_year=academic_year,
                version=1,
                applied_rules={"min_gpa": 0, "mandatory_docs": []},
                full_name="Học viên KTX",
                gender="Nam",
                is_dropped=is_dropped,
            )
            session.add(profile)
            await session.flush()
            return profile.id


async def _add_tuition_fee(
    profile_id: int,
    *,
    semester_no: int = 1,
    paid: str = "0",
    status: str = FeeStatusEnum.invoiced.value,
    resolved_major_id=None,
    fee_type: str = "tuition",
) -> int:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            fee = Fee(
                admission_profile_id=profile_id,
                fee_type=fee_type,
                semester_no=semester_no if fee_type == "tuition" else None,
                academic_year=2026,
                base_amount=Decimal("9200000"),
                final_amount=Decimal("9200000"),
                paid_amount=Decimal(paid),
                waived_amount=Decimal("0"),
                status=status,
                resolved_major_id=resolved_major_id,
            )
            session.add(fee)
            await session.flush()
            return fee.id


async def _make_major(unit_id: int, name: str = "Cao đẳng Điều dưỡng") -> int:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            major = models.MajorProgram(
                name=name,
                degree_level="Cao đẳng",
                code=f"MJ{next(_CCCD_SEQ)}",
                is_active=True,
                is_heavy=False,
                unit_id=unit_id,
            )
            session.add(major)
            await session.flush()
            return major.id


async def _cohort_ids(academic_year: int) -> list:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select_paid_hk1_cohort(academic_year))).all()
        return [r.qlts_profile_id for r in rows]


async def _cohort_rows(academic_year: int) -> list:
    async with AsyncSessionLocal() as session:
        return (await session.execute(select_paid_hk1_cohort(academic_year))).all()


# ---------------------------------------------------------------------------
# Bám đúng năm học — hai chiều
# ---------------------------------------------------------------------------


async def test_year_2026_paid_2027_unpaid_returns_only_2026():
    """Đóng tiền mùa 2026, mùa 2027 chưa đóng.

    Đây là chiều bắt lỗi ``max(academic_year)``: mốc đó = 2027, nên vị từ tiền sẽ
    soi nhầm hồ sơ 2027 (chưa đóng) và hồ sơ 2026 đã đóng tiền thật sẽ biến mất.
    """
    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id)
    p2026 = await _make_profile(lead_id, academic_year=2026)
    p2027 = await _make_profile(lead_id, academic_year=2027)

    await _add_tuition_fee(p2026, paid="3000000")
    await _add_tuition_fee(p2027, paid="0")

    assert await _cohort_ids(2026) == [p2026]
    assert await _cohort_ids(2027) == []


async def test_year_2026_unpaid_2027_paid_returns_only_2027():
    """Chiều ngược lại: chỉ mùa mới có tiền."""
    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id)
    p2026 = await _make_profile(lead_id, academic_year=2026)
    p2027 = await _make_profile(lead_id, academic_year=2027)

    await _add_tuition_fee(p2026, paid="0")
    await _add_tuition_fee(p2027, paid="500000")

    assert await _cohort_ids(2026) == []
    assert await _cohort_ids(2027) == [p2027]


async def test_academic_year_is_mandatory():
    """Gọi thiếu năm học phải nổ ngay, không lặng lẽ trải khắp mọi mùa."""
    with pytest.raises(ValueError):
        select_paid_hk1_cohort(None)
    with pytest.raises(ValueError):
        select_paid_hk1_cohort("2026")
    with pytest.raises(ValueError):
        select_paid_hk1_cohort(True)


# ---------------------------------------------------------------------------
# Vị từ tiền
# ---------------------------------------------------------------------------


async def test_partial_payment_counts():
    """Đóng MỘT PHẦN vẫn thuộc cohort — khác với "đã hoàn tất học phí"."""
    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id)
    profile_id = await _make_profile(lead_id, academic_year=2026)
    await _add_tuition_fee(profile_id, paid="1")

    assert await _cohort_ids(2026) == [profile_id]


async def test_cancelled_fee_excluded():
    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id)
    profile_id = await _make_profile(lead_id, academic_year=2026)
    await _add_tuition_fee(
        profile_id, paid="3000000", status=FeeStatusEnum.cancelled.value
    )

    assert await _cohort_ids(2026) == []


async def test_hk2_paid_hk1_unpaid_excluded():
    """Đóng HK2 nhưng chưa đóng HK1 → chưa thuộc cohort."""
    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id)
    profile_id = await _make_profile(lead_id, academic_year=2026)
    await _add_tuition_fee(profile_id, semester_no=1, paid="0")
    await _add_tuition_fee(profile_id, semester_no=2, paid="4000000")

    assert await _cohort_ids(2026) == []


async def test_non_tuition_payment_excluded():
    """Đóng lệ phí xét tuyển không phải đóng học phí."""
    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id)
    profile_id = await _make_profile(lead_id, academic_year=2026)
    await _add_tuition_fee(profile_id, fee_type="application", paid="500000")

    assert await _cohort_ids(2026) == []


# ---------------------------------------------------------------------------
# Loại trừ theo vòng đời
# ---------------------------------------------------------------------------


async def test_soft_deleted_lead_excluded():
    from datetime import datetime, timezone

    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id, deleted_at=datetime.now(timezone.utc))
    profile_id = await _make_profile(lead_id, academic_year=2026)
    await _add_tuition_fee(profile_id, paid="3000000")

    assert await _cohort_ids(2026) == []


async def test_dropped_student_excluded():
    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id)
    profile_id = await _make_profile(
        lead_id, academic_year=2026, status="enrolled", is_dropped=True
    )
    await _add_tuition_fee(profile_id, paid="3000000")

    assert await _cohort_ids(2026) == []


async def test_is_dropped_null_is_kept():
    """``is_dropped`` để trống nghĩa là chưa bỏ học — phải giữ lại."""
    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id)
    profile_id = await _make_profile(lead_id, academic_year=2026, is_dropped=None)
    await _add_tuition_fee(profile_id, paid="3000000")

    assert await _cohort_ids(2026) == [profile_id]


async def test_withdrawal_pending_excluded_even_though_paid():
    """Đang rút hồ sơ chờ hoàn tiền — nhóm này gần như luôn có tiền đã đóng."""
    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id)
    profile_id = await _make_profile(
        lead_id, academic_year=2026, status="withdrawal_pending"
    )
    await _add_tuition_fee(profile_id, paid="3000000")

    assert "withdrawal_pending" in describe_excluded_statuses()
    assert await _cohort_ids(2026) == []


async def test_excluded_statuses_are_exactly_the_agreed_four():
    """Chốt quyết định: CHỈ loại bốn trạng thái, không hơn.

    Bằng chứng quyết định là tiền đã vào, không phải nhãn trạng thái. Bốn trạng
    thái đang xét (reviewing / revision_requested / result_published /
    waitlisted) PHẢI nằm trong cohort — hồ sơ ở đó mà đã đóng học phí HK1 là bất
    thường, nhưng em ấy vẫn bỏ tiền thật và vẫn cần chỗ ở.

    Test này đỏ khi ai đó thu hẹp allow-list mà không bàn lại.
    """
    assert set(describe_excluded_statuses()) == {
        "draft",
        "rejected",
        "withdrawn",
        "withdrawal_pending",
    }
    assert len(DORM_COHORT_STATUSES) == 11
    for still_under_review in (
        "reviewing",
        "revision_requested",
        "result_published",
        "waitlisted",
    ):
        assert still_under_review in DORM_COHORT_STATUSES


@pytest.mark.parametrize("status", ["draft", "rejected", "withdrawn"])
async def test_terminal_or_pre_entry_statuses_excluded(status):
    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id)
    profile_id = await _make_profile(lead_id, academic_year=2026, status=status)
    await _add_tuition_fee(profile_id, paid="3000000")

    assert await _cohort_ids(2026) == []


@pytest.mark.parametrize("status", list(DORM_COHORT_STATUSES))
async def test_every_allowed_status_is_included(status):
    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id)
    profile_id = await _make_profile(lead_id, academic_year=2026, status=status)
    await _add_tuition_fee(profile_id, paid="3000000")

    assert await _cohort_ids(2026) == [profile_id]


# ---------------------------------------------------------------------------
# Ngành trúng tuyển — fail-soft
# ---------------------------------------------------------------------------


async def test_profile_without_resolved_major_is_kept_with_null_program():
    """Hồ sơ chưa chốt ngành VẪN vào cohort, ``program_name`` để trống.

    Em đó đã đóng tiền và vẫn cần chỗ ở; loại đi là mất người thật.
    """
    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id)
    profile_id = await _make_profile(lead_id, academic_year=2026)
    await _add_tuition_fee(profile_id, paid="3000000", resolved_major_id=None)

    rows = await _cohort_rows(2026)
    assert [r.qlts_profile_id for r in rows] == [profile_id]
    assert rows[0].program_name is None


async def test_resolved_major_name_is_returned():
    unit_id = await _make_unit()
    major_id = await _make_major(unit_id, name="Cao đẳng Dược")
    lead_id = await _make_lead(unit_id)
    profile_id = await _make_profile(lead_id, academic_year=2026)
    await _add_tuition_fee(profile_id, paid="3000000", resolved_major_id=major_id)

    rows = await _cohort_rows(2026)
    assert rows[0].program_name == "Cao đẳng Dược"


async def test_officer_and_unit_come_from_lead():
    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id, officer_id=None)
    profile_id = await _make_profile(lead_id, academic_year=2026)
    await _add_tuition_fee(profile_id, paid="3000000")

    rows = await _cohort_rows(2026)
    assert rows[0].unit_id == unit_id
    assert rows[0].officer_qlts_id is None
    assert rows[0].qlts_profile_id == profile_id


async def test_one_row_per_profile_even_with_multiple_fee_rows():
    """Nhiều dòng phí không được nhân bản học viên trong kết quả."""
    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id)
    profile_id = await _make_profile(lead_id, academic_year=2026)
    await _add_tuition_fee(profile_id, semester_no=1, paid="3000000")
    await _add_tuition_fee(profile_id, semester_no=2, paid="4000000")
    await _add_tuition_fee(profile_id, fee_type="insurance", paid="200000")

    assert await _cohort_ids(2026) == [profile_id]
