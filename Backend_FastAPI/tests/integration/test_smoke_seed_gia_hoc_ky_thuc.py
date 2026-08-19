"""Fixture tính phí của seeder smoke, chạy trên DB THẬT.

Vì sao tệp này tồn tại
======================

`BL20260818A` seed xanh, validator xanh, registry ghi ``tinh_phi_duoc: true`` —
và FIN-03 vẫn **400**::

    RESOLVE_NGANH: OK academic_info_id=1 tuition_fee_per_year=5500000.00
    GIA_HK1:  LOI BadRequest : Chưa cấu hình học phí cho HK1 (academic_info_id=1).

Gốc: với ``fee_type = tuition``, giá GỐC lấy **chỉ** từ ``offering_semester_tuition``
(``fee_calculation_service._semester_tuition_amount_for_ai``). Seeder dựng
``OfferingAdmissionConfig`` rồi coi ``tuition_fee_per_year`` là bằng chứng "tính ra
tiền" — một trường **không** nằm trên đường giá của tuition. Validator kiểm đúng
cái trường ấy, nên nó **chứng nhận** một fixture mà đường thật từ chối.

Đó là lớp lỗi mà quét mã nguồn không bắt được: mã có gọi đủ hàm, tên biến đúng,
chỉ có điều nó hỏi nhầm bảng. Phải chạy thật, và phải chạy **cả chiều đỏ** — ca
số 7 xoá hàng giá HK1 để chứng minh phép kiểm mới thật sự nhìn thấy nó.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select


def _goc_backend() -> Path:
    for goc in Path(__file__).resolve().parents:
        if (goc / "scripts").is_dir() and (goc / "tests").is_dir():
            return goc
    pytest.fail("không xác định được gốc Backend_FastAPI")


_GOC = _goc_backend()
if str(_GOC) not in sys.path:
    sys.path.insert(0, str(_GOC))

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

TIEN_NAM = Decimal("4400000.00")
TIEN_CATALOG_CO_SAN = Decimal("1234567.00")


def _nap_seed():
    from scripts import smoke_finance_seed  # noqa: PLC0415

    return smoke_finance_seed


async def _danh_muc(db, seed_lead_dependencies, *, tien_nam=TIEN_NAM):
    """Chuỗi danh mục tối thiểu: Offering → AcademicInfo (chưa có hàng giá HK1)."""
    from app import models
    from tests.fixtures.dinh_danh import khoa_duy_nhat, ma_tu_khoa

    khoa = await khoa_duy_nhat(db)
    offering = models.ProgramOffering(
        program_id=seed_lead_dependencies["major_program_id"],
        offering_type="full_time",
        duration_semesters=8,
    )
    db.add(offering)
    await db.flush()

    ai = models.OfferingAcademicInfo(
        offering_id=offering.id,
        academic_year=2026,
        annual_admission_quota=10,
        tuition_fee_per_year=tien_nam,
    )
    db.add(ai)
    await db.flush()
    return ai, khoa, ma_tu_khoa


async def _oac_cho(db, ai, khoa, ma_tu_khoa):
    """OfferingAdmissionConfig hoạt động trỏ tới ``ai`` (kèm method + criteria)."""
    from app import models

    method = models.AdmissionMethod(
        code=ma_tu_khoa("M", khoa, 50),
        name=f"Method {khoa}",
        requires_subject_scores=False,
        is_active=True,
    )
    db.add(method)
    await db.flush()

    crit = models.AdmissionCriteria(
        method_id=method.id,
        code=ma_tu_khoa("C", khoa, 50),
        name=f"Criteria {khoa}",
    )
    db.add(crit)
    await db.flush()

    oac = models.OfferingAdmissionConfig(
        academic_info_id=ai.id, criteria_id=crit.id, is_active=True
    )
    db.add(oac)
    await db.flush()
    return oac


async def _so_hang_gia(db, ai_id: int) -> int:
    from app import models

    return (
        await db.execute(
            select(func.count())
            .select_from(models.OfferingSemesterTuition)
            .where(models.OfferingSemesterTuition.academic_info_id == ai_id)
        )
    ).scalar_one()


# ---------------------------------------------------------------------------
# 1. Ca kiểm có đủ mạnh không
# ---------------------------------------------------------------------------

async def test_ca_kiem_nay_co_du_manh_khong(setup_test_database, seed_lead_dependencies):
    """Vô nghĩa nếu danh mục dựng ra đã sẵn hàng giá HK1.

    Khi ấy ca "tạo hàng khi thiếu" xanh mà không chứng minh gì — nó chỉ đọc lại
    một hàng có sẵn từ trước.
    """
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        ai, _, _ = await _danh_muc(db, seed_lead_dependencies)
        assert await _so_hang_gia(db, ai.id) == 0, (
            "danh mục vừa dựng đã có hàng giá HK1 — mọi ca dưới đây sẽ xanh vì "
            "không có gì để tạo, chứ không phải vì bản vá đúng"
        )
        await db.rollback()


# ---------------------------------------------------------------------------
# 2..5. Hành vi của `_gia_hoc_ky`
# ---------------------------------------------------------------------------

async def test_dung_hang_gia_HK1_khi_thieu(setup_test_database, seed_lead_dependencies):
    """Mắt xích thứ hai: seeder phải TẠO hàng ``offering_semester_tuition`` HK1."""
    sd = _nap_seed()
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        ai, _, _ = await _danh_muc(db, seed_lead_dependencies)
        ost = await sd._gia_hoc_ky(db, ai)

        assert ost.academic_info_id == ai.id
        assert ost.semester_no == sd.HOC_KY_TINH_PHI == 1
        assert Decimal(str(ost.amount)) == TIEN_NAM
        await db.rollback()


async def test_idempotent_khong_de_hang_thu_hai(setup_test_database, seed_lead_dependencies):
    """Gọi hai lượt phải cho ĐÚNG một hàng — seed chạy lại không đẻ rác danh mục."""
    sd = _nap_seed()
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        ai, _, _ = await _danh_muc(db, seed_lead_dependencies)
        mot = await sd._gia_hoc_ky(db, ai)
        hai = await sd._gia_hoc_ky(db, ai)

        assert hai.id == mot.id
        assert await _so_hang_gia(db, ai.id) == 1
        await db.rollback()


async def test_KHONG_ghi_de_hang_catalog_da_co(setup_test_database, seed_lead_dependencies):
    """Danh mục là dữ liệu của người khác — fixture không được sửa giá cho tròn số.

    Hàng có sẵn mang số KHÁC ``tuition_fee_per_year``; seeder phải dùng lại nguyên
    si. Ghi đè ở đây nghĩa là một lượt smoke có thể lặng lẽ đổi bảng giá thật.
    """
    sd = _nap_seed()
    from app import models
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        ai, _, _ = await _danh_muc(db, seed_lead_dependencies)
        co_san = models.OfferingSemesterTuition(
            academic_info_id=ai.id,
            semester_no=1,
            amount=TIEN_CATALOG_CO_SAN,
            notes="hàng catalog có sẵn",
        )
        db.add(co_san)
        await db.flush()
        ma_cu = co_san.id

        ost = await sd._gia_hoc_ky(db, ai)

        assert ost.id == ma_cu
        assert Decimal(str(ost.amount)) == TIEN_CATALOG_CO_SAN, (
            "seeder đã ghi đè giá của một hàng danh mục có sẵn"
        )
        await db.rollback()


async def test_thieu_tuition_fee_per_year_thi_ChanLai(
    setup_test_database, seed_lead_dependencies
):
    """Fail-closed: không suy ra được số thì DỪNG, không dựng hàng giá 0.

    Hàng giá 0 làm ``calculate_fee`` chạy được và đẻ hoá đơn 0 đồng — biến một
    fixture hỏng thành một lượt smoke "xanh".
    """
    sd = _nap_seed()
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        ai, _, _ = await _danh_muc(db, seed_lead_dependencies)
        ai.tuition_fee_per_year = None
        await db.flush()

        with pytest.raises(sd.ChanLai):
            await sd._gia_hoc_ky(db, ai)

        assert await _so_hang_gia(db, ai.id) == 0, "đã dựng hàng giá dù ChanLai"
        await db.rollback()


# ---------------------------------------------------------------------------
# 6..7. Phép kiểm của validator — và chiều ĐỎ của nó
# ---------------------------------------------------------------------------

async def _ho_so_tinh_phi_duoc(db, seed_lead_dependencies, *, dung_gia_hk1: bool):
    """Hồ sơ legacy trỏ tới OAC thật; tuỳ chọn có/không hàng giá HK1."""
    sd = _nap_seed()

    ai, khoa, ma_tu_khoa = await _danh_muc(db, seed_lead_dependencies)
    oac = await _oac_cho(db, ai, khoa, ma_tu_khoa)
    if dung_gia_hk1:
        await sd._gia_hoc_ky(db, ai)

    hs = await sd._ho_so(
        db, "TEST", "FCALC", seed_lead_dependencies["unit_id"], khoa
    )
    hs.offering_admission_config_id = oac.id
    hs.uses_choice_engine = False
    await db.flush()
    await db.commit()
    return hs, ai


async def test_kiem_duong_that_XANH_khi_du_hai_mat_xich(
    setup_test_database, seed_lead_dependencies
):
    """Đủ OAC **và** hàng giá HK1 ⇒ phép kiểm phải trả ``None``."""
    sd = _nap_seed()
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        hs, _ = await _ho_so_tinh_phi_duoc(db, seed_lead_dependencies, dung_gia_hk1=True)

    async with AsyncSessionLocal() as db:
        assert await sd._kiem_duong_tinh_phi_that(db, hs.id) is None


async def test_kiem_duong_that_DO_khi_xoa_hang_gia_HK1(
    setup_test_database, seed_lead_dependencies
):
    """KIỂM NGƯỢC — gỡ đúng thứ đang được canh thì phép kiểm phải ĐỎ.

    Đây là hình dạng THẬT của sự cố `BL20260818A`: OAC còn nguyên, ngành giải
    được, chỉ thiếu hàng giá. Phép kiểm cũ (``tuition_fee_per_year is None``) vẫn
    XANH ở đúng trạng thái này — nên nếu ca này không đỏ thì bản vá chưa canh gì.
    """
    sd = _nap_seed()
    from app import models
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        hs, ai = await _ho_so_tinh_phi_duoc(db, seed_lead_dependencies, dung_gia_hk1=True)

    async with AsyncSessionLocal() as db:
        ost = (
            await db.execute(
                select(models.OfferingSemesterTuition).where(
                    models.OfferingSemesterTuition.academic_info_id == ai.id,
                    models.OfferingSemesterTuition.semester_no == 1,
                )
            )
        ).scalars().one()
        await db.delete(ost)
        await db.commit()

    async with AsyncSessionLocal() as db:
        ai_moi = await db.get(models.OfferingAcademicInfo, ai.id)
        assert ai_moi.tuition_fee_per_year is not None, (
            "ca này chỉ có nghĩa khi trường CŨ vẫn còn — nếu nó cũng None thì "
            "phép kiểm cũ cũng đỏ, và ta không chứng minh được điều gì mới"
        )
        ly_do = await sd._kiem_duong_tinh_phi_that(db, hs.id)

    assert ly_do is not None, "xoá hàng giá HK1 mà phép kiểm vẫn XANH"
    assert "HK1" in ly_do


# ---------------------------------------------------------------------------
# 8. Sổ ↔ DB
# ---------------------------------------------------------------------------

async def test_so_ghi_so_tien_KHAC_DB_thi_DO(setup_test_database, seed_lead_dependencies):
    """Oracle đọc ``semester_amount`` trong sổ; sổ lệch DB ⇒ bản khai sai từ đầu."""
    sd = _nap_seed()
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        ai, _, _ = await _danh_muc(db, seed_lead_dependencies)
        ost = await sd._gia_hoc_ky(db, ai)
        await db.commit()
        ma, so_that = ost.id, str(ost.amount)

    async with AsyncSessionLocal() as db:
        khop = {
            "semester_tuition_id": ma,
            "semester_no": 1,
            "semester_amount": so_that,
            "academic_info_id": ai.id,
        }
        assert await sd._kiem_so_khop_gia_hoc_ky(db, khop) is None

        lech = dict(khop, semester_amount="1.00")
        ly_do = await sd._kiem_so_khop_gia_hoc_ky(db, lech)
        assert ly_do is not None and "amount" in ly_do


async def test_so_THIEU_semester_tuition_id_thi_DO(
    setup_test_database, seed_lead_dependencies
):
    """Sổ của seeder CŨ (chỉ có ``tuition_fee_per_year``) phải bị từ chối.

    Nếu không, một registry sinh bởi bản seeder cũ vẫn qua được validator mới, và
    bản vá chỉ có tác dụng cho những lượt seed lại.
    """
    sd = _nap_seed()
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        so_cu = {
            "profile_id": 1,
            "academic_info_id": 1,
            "tuition_fee_per_year": "5500000.00",
            "tinh_phi_duoc": True,
        }
        ly_do = await sd._kiem_so_khop_gia_hoc_ky(db, so_cu)

    assert ly_do is not None and "semester_tuition_id" in ly_do
