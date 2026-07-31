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
    COHORT_ATYPICAL_STATUSES,
    DORM_COHORT_STATUSES,
    count_atypical_statuses,
    describe_excluded_statuses,
    select_paid_hk1_cohort,
)
from app.utils.exceptions import ValidationError

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


async def _make_lead(
    unit_id: int,
    *,
    officer_id=None,
    deleted_at=None,
    phone="0902224444",
    phone2=None,
) -> int:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = models.Lead(
                full_name="Lead KTX",
                phone=phone,
                phone2=phone2,
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
    phone=None,
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
                phone=phone,
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
    academic_year: int = 2026,
) -> int:
    """Thêm một dòng phí cho hồ sơ.

    ``academic_year`` phải theo NĂM CỦA HỒ SƠ ở mọi lời gọi. Cố định 2026 cho
    mọi dòng phí sẽ tạo ra tổ hợp mà luồng tính phí không sinh ra được (hồ sơ
    2027 mang phí 2026), và test dựng trên dữ liệu bất khả thi thì có xanh cũng
    không chứng minh được điều nó nói.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            fee = Fee(
                admission_profile_id=profile_id,
                fee_type=fee_type,
                semester_no=semester_no if fee_type == "tuition" else None,
                academic_year=academic_year,
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


async def _make_degree_level(name: str) -> int:
    """Một bậc trong ``config_degree_level`` — nguồn CANONICAL của trình độ."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            level = models.ConfigDegreeLevel(
                code=f"DL{next(_CCCD_SEQ)}",
                name=name,
                display_order=1,
                is_active=True,
            )
            session.add(level)
            await session.flush()
            return level.id


async def _make_major(
    unit_id: int,
    name: str = "Cao đẳng Điều dưỡng",
    degree_level_id: int = None,
    degree_level_text: str = "Cao đẳng",
) -> int:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            major = models.MajorProgram(
                name=name,
                # Cột TEXT legacy. Cố ý để mặc định có giá trị và tách rời khỏi
                # ``degree_level_id``: đó là thứ làm phép kiểm "đọc đúng nguồn"
                # bên dưới quan sát được.
                degree_level=degree_level_text,
                degree_level_id=degree_level_id,
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

    await _add_tuition_fee(p2026, paid="3000000", academic_year=2026)
    await _add_tuition_fee(p2027, paid="0", academic_year=2027)

    assert await _cohort_ids(2026) == [p2026]
    assert await _cohort_ids(2027) == []


async def test_year_2026_unpaid_2027_paid_returns_only_2027():
    """Chiều ngược lại: chỉ mùa mới có tiền."""
    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id)
    p2026 = await _make_profile(lead_id, academic_year=2026)
    p2027 = await _make_profile(lead_id, academic_year=2027)

    await _add_tuition_fee(p2026, paid="0", academic_year=2026)
    await _add_tuition_fee(p2027, paid="500000", academic_year=2027)

    assert await _cohort_ids(2026) == []
    assert await _cohort_ids(2027) == [p2027]


async def test_academic_year_is_mandatory():
    """Gọi thiếu năm học phải nổ ngay, không lặng lẽ trải khắp mọi mùa.

    Phải là ``ValidationError`` (domain exception → 400), không phải
    ``ValueError`` trần: ngày query này lộ qua router thì ``ValueError`` thành
    500 kèm stack trace, và test ghim sai loại sẽ để việc đó trôi qua im lặng.
    """
    for bad in (None, "2026", True):
        with pytest.raises(ValidationError):
            select_paid_hk1_cohort(bad)


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


async def test_atypical_statuses_are_a_subset_of_the_allow_list():
    """Danh sách "đang xét" phải nằm TRỌN trong allow-list.

    Hai danh sách này tồn tại song song: allow-list quyết định ai được sang hệ
    KTX, còn danh sách đang-xét quyết định con số cảnh báo người vận hành nhìn
    trước khi ghi. Nếu chúng lệch nhau thì bước xem trước sẽ đếm những trạng
    thái không hề có trong cohort — một cảnh báo về người không tồn tại.
    """
    assert set(COHORT_ATYPICAL_STATUSES) <= set(DORM_COHORT_STATUSES)
    assert set(COHORT_ATYPICAL_STATUSES) == {
        "reviewing",
        "revision_requested",
        "result_published",
        "waitlisted",
    }


async def test_count_atypical_statuses_counts_only_under_review_rows():
    """``profile_status`` phải thực sự được DÙNG, không chỉ được select.

    Cột này là thứ duy nhất phân biệt một em ``confirmed`` bình thường với một
    em ``waitlisted`` đã bỏ tiền — ca bất thường mà officer cần biết.
    """
    unit_id = await _make_unit()
    binh_thuong = await _make_profile(
        await _make_lead(unit_id), academic_year=2026, status="confirmed"
    )
    dang_xet = await _make_profile(
        await _make_lead(unit_id), academic_year=2026, status="waitlisted"
    )
    await _add_tuition_fee(binh_thuong, paid="3000000")
    await _add_tuition_fee(dang_xet, paid="3000000")

    rows = await _cohort_rows(2026)

    assert sorted(r.qlts_profile_id for r in rows) == sorted([binh_thuong, dang_xet])
    assert count_atypical_statuses(rows) == 1


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


# ---------------------------------------------------------------------------
# Trình độ của ngành trúng tuyển
# ---------------------------------------------------------------------------


async def test_degree_level_is_returned():
    unit_id = await _make_unit()
    cao_dang = await _make_degree_level("Cao đẳng")
    major_id = await _make_major(unit_id, name="Dược", degree_level_id=cao_dang)
    lead_id = await _make_lead(unit_id)
    profile_id = await _make_profile(lead_id, academic_year=2026)
    await _add_tuition_fee(profile_id, paid="3000000", resolved_major_id=major_id)

    rows = await _cohort_rows(2026)
    assert rows[0].degree_level == "Cao đẳng"


async def test_same_program_name_at_two_levels_stays_separated():
    """🔴 Lý do TỒN TẠI của cột này.

    Trên dữ liệu thật, "Công nghệ ô tô", "Chăn nuôi - Thú y" và "Kế toán" mỗi
    cái có cả bản Trung cấp lẫn Cao đẳng — phủ 257/457 hồ sơ khối KTX. Nếu
    trình độ bị lấy nhầm từ ngành CÙNG TÊN nhưng khác bậc, thống kê vẫn ra một
    bảng trông hoàn toàn bình thường và không có gì báo.

    Hai hồ sơ, cùng tên ngành, hai bậc — mỗi hồ sơ phải giữ đúng bậc của mình.
    """
    unit_id = await _make_unit()
    trung_cap = await _make_degree_level("Trung cấp")
    cao_dang = await _make_degree_level("Cao đẳng")

    major_tc = await _make_major(
        unit_id, name="Công nghệ ô tô", degree_level_id=trung_cap
    )
    major_cd = await _make_major(
        unit_id, name="Công nghệ ô tô", degree_level_id=cao_dang
    )

    lead_tc = await _make_lead(unit_id)
    ho_so_tc = await _make_profile(lead_tc, academic_year=2026)
    await _add_tuition_fee(ho_so_tc, paid="3000000", resolved_major_id=major_tc)

    lead_cd = await _make_lead(unit_id)
    ho_so_cd = await _make_profile(lead_cd, academic_year=2026)
    await _add_tuition_fee(ho_so_cd, paid="3000000", resolved_major_id=major_cd)

    theo_ho_so = {r.qlts_profile_id: r for r in await _cohort_rows(2026)}

    assert theo_ho_so[ho_so_tc].program_name == "Công nghệ ô tô"
    assert theo_ho_so[ho_so_tc].degree_level == "Trung cấp"
    assert theo_ho_so[ho_so_cd].program_name == "Công nghệ ô tô"
    assert theo_ho_so[ho_so_cd].degree_level == "Cao đẳng"


async def test_degree_level_reads_the_canonical_source_not_the_legacy_text():
    """Trình độ đến từ ``degree_level_id`` → ``config_degree_level``.

    Ngành dưới đây có cột TEXT legacy ghi "Cao đẳng" nhưng KHÔNG có FK. Kỳ vọng
    là ``NULL``: đọc được "Cao đẳng" nghĩa là ai đó đã đổi sang cột legacy.

    Không phải chuyện thẩm mỹ. Chính model khai cột text là LEGACY, và hôm nay
    hai nguồn khớp nhau tuyệt đối trên prod — nên nếu đổi nguồn, KHÔNG có phép
    kiểm nào khác đỏ. Test này là thứ duy nhất quan sát được lựa chọn đó.
    """
    unit_id = await _make_unit()
    major_id = await _make_major(
        unit_id,
        name="Ngành thiếu FK trình độ",
        degree_level_id=None,
        degree_level_text="Cao đẳng",
    )
    lead_id = await _make_lead(unit_id)
    profile_id = await _make_profile(lead_id, academic_year=2026)
    await _add_tuition_fee(profile_id, paid="3000000", resolved_major_id=major_id)

    rows = await _cohort_rows(2026)
    # Vẫn TRONG cohort — thiếu trình độ không được làm mất người.
    assert [r.qlts_profile_id for r in rows] == [profile_id]
    assert rows[0].program_name == "Ngành thiếu FK trình độ"
    assert rows[0].degree_level is None


async def test_profile_without_resolved_major_has_null_degree_level():
    """Chưa chốt ngành thì cả hai cột đều trống, và hồ sơ vẫn ở lại."""
    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id)
    profile_id = await _make_profile(lead_id, academic_year=2026)
    await _add_tuition_fee(profile_id, paid="3000000", resolved_major_id=None)

    rows = await _cohort_rows(2026)
    assert [r.qlts_profile_id for r in rows] == [profile_id]
    assert rows[0].program_name is None
    assert rows[0].degree_level is None


async def test_officer_and_unit_come_from_lead():
    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id, officer_id=None)
    profile_id = await _make_profile(lead_id, academic_year=2026)
    await _add_tuition_fee(profile_id, paid="3000000")

    rows = await _cohort_rows(2026)
    assert rows[0].unit_id == unit_id
    assert rows[0].officer_qlts_id is None
    assert rows[0].qlts_profile_id == profile_id


async def test_contact_phone_prefers_the_profile_number():
    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id, phone="0900000001", phone2="0900000002")
    profile_id = await _make_profile(lead_id, academic_year=2026, phone="0911111111")
    await _add_tuition_fee(profile_id, paid="3000000")

    rows = await _cohort_rows(2026)
    assert rows[0].contact_phone == "0911111111"
    assert rows[0].contact_phone2 == "0900000002"


async def test_contact_phone_falls_back_to_lead_when_profile_is_empty():
    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id, phone="0900000001")
    profile_id = await _make_profile(lead_id, academic_year=2026, phone=None)
    await _add_tuition_fee(profile_id, paid="3000000")

    assert (await _cohort_rows(2026))[0].contact_phone == "0900000001"


async def test_contact_phone_treats_whitespace_as_missing():
    """Chuỗi TOÀN KHOẢNG TRẮNG phải lùi về số của lead.

    ``coalesce`` trần KHÔNG lùi khi cột đầu là chuỗi rỗng hay một dấu cách — mà
    "ô nhập để trống nhưng có dấu cách" là ca thường gặp nhất ở dữ liệu gõ tay.
    Không có ``nullif(trim(...), '')`` thì hồ sơ này sang hệ KTX với ô liên hệ
    trống, dù bên lead vẫn có số gọi được.

    Đây là nhánh chỉ kiểm được trên SQL thật: ``nullif``/``trim`` chạy ở
    database, không phải ở Python.
    """
    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id, phone="0900000001", phone2="   ")
    profile_id = await _make_profile(lead_id, academic_year=2026, phone="   ")
    await _add_tuition_fee(profile_id, paid="3000000")

    rows = await _cohort_rows(2026)
    assert rows[0].contact_phone == "0900000001"
    # Số phụ toàn khoảng trắng là "không có số phụ", không phải một ô rỗng gửi đi.
    assert rows[0].contact_phone2 is None


async def test_contact_phone_is_null_when_nobody_has_a_number():
    """Không ai có số vẫn là hàng hợp lệ — giao diện nói được "chưa có"."""
    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id, phone="")
    profile_id = await _make_profile(lead_id, academic_year=2026, phone=None)
    await _add_tuition_fee(profile_id, paid="3000000")

    rows = await _cohort_rows(2026)
    assert rows[0].contact_phone is None
    assert rows[0].contact_phone2 is None


async def test_one_row_per_profile_even_with_multiple_fee_rows():
    """Nhiều dòng phí không được nhân bản học viên trong kết quả."""
    unit_id = await _make_unit()
    lead_id = await _make_lead(unit_id)
    profile_id = await _make_profile(lead_id, academic_year=2026)
    await _add_tuition_fee(profile_id, semester_no=1, paid="3000000")
    await _add_tuition_fee(profile_id, semester_no=2, paid="4000000")
    await _add_tuition_fee(profile_id, fee_type="insurance", paid="200000")

    assert await _cohort_ids(2026) == [profile_id]
