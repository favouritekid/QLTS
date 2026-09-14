#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fixture GIÁ HỌC KỲ (HK1) cho E2E — hàng ``offering_semester_tuition`` của
ĐÚNG ngành mà bộ E2E chọn.

VÌ SAO TỆP NÀY TỒN TẠI
======================

``finance-lifecycle.spec.ts`` bước "Calculate fee" trả **400**. Đo thật trên một
CSDL dựng theo ĐÚNG chuỗi của ``nightly-regression.yml``
(``alembic upgrade head`` → ``scripts.seed_from_xlsx``)::

    offering_academic_info    = 23
    admission_path            = 52
    offering_semester_tuition = 0        ← không migration/seed nào chèn

Với ``fee_type = tuition`` giá GỐC lấy **chỉ** từ ``offering_semester_tuition``
(``fee_calculation_service.calculate_fee`` → ``_semester_tuition_amount_for_ai``,
ADR-002). Bảng rỗng ⇒ ``BadRequest`` ⇒ router ``fees.py`` bọc thành
``HTTPException(400)`` ⇒ ``error_code = HTTP_400``.

Gọi thẳng hàm sản phẩm trên CSDL ấy cho ra NGUYÊN VĂN::

    Chưa cấu hình học phí cho HK1 (academic_info_id=1). Vui lòng nhập học phí
    theo học kỳ trong quản trị trước.

    len = 107 · FNV-1a = 80d29745

trùng KHÍT dòng log của lượt nightly (``detail=<str:107 h=80d29745>``). Hai câu
400 khác của cùng endpoint KHÔNG trùng (đã đo): thiếu kế hoạch ``FULL``
``len=66 h=7cfcd3fa``, hồ sơ không đủ điều kiện ``len=114 h=68dad46e``. Và kế
hoạch ``FULL`` **có** trong CSDL (migration seed, ``is_active=true``) nên nhánh
ấy không phải nguyên nhân.

⇒ Thiếu **DỮ LIỆU DANH MỤC**, không phải lỗi runtime. Service trả 400 ĐÚNG HỢP
ĐỒNG. Việc phải làm là thêm hàng danh mục, KHÔNG phải sửa đường định giá và
TUYỆT ĐỐI không cho nó rơi về ``tuition_fee_per_year``.

SỐ TIỀN LÀ HẰNG SỐ — CỐ Ý KHÁC ``tuition_fee_per_year``
=======================================================

``FIXTURE_HK1_AMOUNT`` là hằng số, **không** suy ra từ
``offering_academic_info.tuition_fee_per_year`` (ngành E2E chọn đang mang
5.500.000). Hai lý do:

* lệnh cấm "không fallback ``tuition_fee_per_year``" phải đúng cả ở fixture —
  một fixture tự suy số từ cột ấy là đã dạy người đọc rằng hai cột thay thế
  được cho nhau;
* nhờ hai số KHÁC NHAU, một hồi quy trong đó đường định giá lặng lẽ quay về
  ``tuition_fee_per_year`` sẽ **nhìn thấy được**: phí sẽ ra 5.500.000 thay vì
  6.500.000. Chọn số bằng nhau là tự bịt mắt mình.

KHÔNG GHI ĐÈ DANH MỤC CÓ SẴN
============================

Hàng đã có được dùng LẠI nguyên si — danh mục là dữ liệu của người khác, một
lượt seed không được lặng lẽ đổi bảng giá. Nhưng hàng có sẵn mà ``amount <= 0``
thì DỪNG: ``CheckConstraint`` của model chỉ đòi ``amount >= 0``, nên 0 đồng là
hàng HỢP LỆ về lược đồ mà ``generate_invoices_for_fee`` vẫn chặn ("No amount to
invoice (fee fully waived)") — hỏng muộn, với câu sai.

GUARD — HAI TẦNG, FAIL-CLOSED
=============================

Dùng CHUNG hàm guard với ``seed_e2e_catalog_fixture`` (import, không chép lại —
hai bản guard là hai cơ hội drift):

Tầng 1  ``APP_ENV`` ∈ {``test``} (``--allow-dev`` nới thêm ``development``).
Tầng 2  TÊN CSDL ∈ {``qlts_test``} (``--allow-dev`` nới thêm ``qlts_dev``),
        kiểm HAI LẦN — trên ``DATABASE_URL`` TRƯỚC khi kết nối, và trên
        ``SELECT current_database()`` SAU khi kết nối — cộng một phép so hai
        giá trị ấy phải trùng.

``production`` / ``qlts_production`` bị chặn CỨNG, không cờ nào nới được.

Mặc định CLI là **dry-run**; phải nêu ``--apply`` mới ghi.

CHỌN NGÀNH — MIRROR THUẬT TOÁN CỦA E2E, KHÔNG ĐOÁN THEO TÊN
===========================================================

``finance-lifecycle.spec.ts`` gọi ``resolveAdmissionContext(page.request)``
KHÔNG tham số. Thuật toán (``frontend/src/test/e2e/helpers/e2e-fixtures.ts``):

1. ``GET /api/program-offerings?is_active=true&limit=200``
   (``organization_repository.get_all_offerings``: lọc ``is_active``, không
   ``ORDER BY``) — rồi TS **tự sắp id tăng dần**, nên thứ tự Postgres trả về
   không ảnh hưởng, chỉ có TẬP và mức cắt ``limit`` là quan trọng.
2. Duyệt id tăng dần; với mỗi offering gọi
   ``GET /api/admission-config/paths/for-offering/{id}``
   (``admission_path_repository.get_active_paths_by_offering_id``:
   ``academic_info.is_published`` ∧ ``path.status == "active"``,
   ``ORDER BY display_order, id``).
3. Lọc phía TS: round chưa ``archived_at`` · round không ``is_active = false`` ·
   có ``academic_info.academic_year`` là số · ``round_end_date`` NULL hoặc
   ``>= hôm nay (giờ VN)``.
4. Offering ĐẦU TIÊN còn ứng viên thì dừng; sắp ổn định "round đang mở lên
   trước" rồi lấy phần tử đầu.

``_chon_theo_e2e`` dưới đây là bản dịch từng bước của bốn bước ấy sang ORM. Đo
trên CSDL dựng theo chuỗi nightly: offerings ``[1,2,…,28]`` (23 cái),
offering #1 có 2 ứng viên ⇒ dừng ngay ⇒ path #22, round #1, năm 2026,
**academic_info_id = 1** — khớp đúng con số mà băm tương quan của lượt nightly
chỉ ra.

CHỐNG DRIFT: bản dịch có thể lệch khỏi TS. Nên hậu điều kiện KHÔNG tự đọc lại
bảng bằng SELECT của chính tệp này mà gọi ĐÚNG hàm sản phẩm
``FeeCalculationService._semester_tuition_amount_for_ai`` — cùng hàm mà
``calculate_fee`` gọi. Và ``--all-candidates`` seed cho TOÀN BỘ ngành có path
dùng được (tập cha của mọi lựa chọn khả dĩ) khi cần phòng xa.

IDEMPOTENT
==========

Get-or-create theo khoá tự nhiên ``(academic_info_id, semester_no)`` — khoá này
có UNIQUE thật trong CSDL (``uq_offering_semester_tuition_info_semester``), nên
tính idempotent được CSDL bảo đảm chứ không chỉ do script. Bản in nêu số hàng
TRƯỚC và SAU cho từng ngành.

CÁCH CHẠY
=========

    # xem trước, KHÔNG chạm CSDL
    docker compose exec -T backend \\
        python -m scripts.seeds.seed_e2e_semester_tuition_fixture

    # ghi thật
    docker compose exec -T backend \\
        python -m scripts.seeds.seed_e2e_semester_tuition_fixture --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

# Guard dùng CHUNG với fixture danh mục — một nguồn, không chép lại.
from scripts.seeds.seed_e2e_catalog_fixture import (  # noqa: F401
    GuardError,
    allowed_app_envs,
    allowed_db_names,
    assert_app_env_allowed,
    assert_db_name_allowed,
)

# =============================================================================
# HẰNG SỐ FIXTURE
# =============================================================================

#: Học kỳ mà ``POST /api/fees/calculate`` mặc định tính khi payload không nêu
#: ``semester_no`` — ``FeeCalculationService.calculate_fee`` chuẩn hoá
#: ``semester_no = 1`` cho ``fee_type = tuition``. ``finance-lifecycle.spec.ts``
#: KHÔNG gửi trường này, nên HK1 là đúng cái nó cần.
HOC_KY_E2E = 1

#: Giá HK1 của fixture. HẰNG SỐ — xem phần "SỐ TIỀN LÀ HẰNG SỐ" ở docstring.
#: Cố ý KHÁC ``tuition_fee_per_year`` của ngành E2E chọn (5.500.000) để một
#: hồi quy "rơi về tuition_fee_per_year" lộ ra bằng con số.
FIXTURE_HK1_AMOUNT = Decimal("6500000.00")

FIXTURE_NOTES = "E2E fixture — seed_e2e_semester_tuition_fixture"

_TZ_VN = "Asia/Ho_Chi_Minh"


def hom_nay_vn() -> date:
    """Hôm nay theo giờ VN — mirror ``todayVN()`` của ``e2e-fixtures.ts``."""
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(_TZ_VN)).date()


# =============================================================================
# MIRROR THUẬT TOÁN CHỌN CỦA E2E
# =============================================================================

class KhongCoNganh(GuardError):
    """Không mirror ra được ngành nào — DỪNG, không đoán bừa."""


async def _ung_vien_cua_offering(session, offering_id: int, today: date) -> list:
    """Ứng viên path của MỘT offering, theo đúng bộ lọc của ``e2e-fixtures.ts``.

    Trả về ``[(path, round_dang_mo)]`` theo thứ tự ``display_order, id``.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app import models
    from app.models.admission_config.admission_path import AdmissionPath

    stmt = (
        select(AdmissionPath)
        .join(
            models.OfferingAcademicInfo,
            AdmissionPath.academic_info_id == models.OfferingAcademicInfo.id,
        )
        .where(
            models.OfferingAcademicInfo.offering_id == offering_id,
            models.OfferingAcademicInfo.is_published.is_(True),
            AdmissionPath.status == "active",
        )
        .options(
            selectinload(AdmissionPath.academic_info),
            selectinload(AdmissionPath.admission_round),
        )
        .order_by(AdmissionPath.display_order, AdmissionPath.id)
    )
    ra: list = []
    for path in (await session.execute(stmt)).scalars().all():
        vong = path.admission_round
        if vong is not None and vong.archived_at is not None:
            continue
        if vong is not None and vong.is_active is False:
            continue
        ai = path.academic_info
        if ai is None or not isinstance(ai.academic_year, int):
            continue
        bat_dau = getattr(vong, "start_date", None) if vong is not None else None
        ket_thuc = getattr(vong, "end_date", None) if vong is not None else None
        # ``assert_round_open`` chỉ chặn khi end_date < hôm nay; NULL = mở vô hạn.
        if ket_thuc is not None and ket_thuc < today:
            continue
        dang_mo = (
            bat_dau <= today <= ket_thuc
            if (bat_dau is not None and ket_thuc is not None)
            else ket_thuc is None
        )
        ra.append((path, dang_mo))
    return ra


async def _chon_theo_e2e(session) -> tuple[Any, list[str], list[Any]]:
    """Bản dịch ORM của ``resolveAdmissionContext(ctx)`` không tham số.

    Trả về ``(academic_info đã chọn, vết thử, mọi academic_info có ứng viên)``.
    """
    from sqlalchemy import select

    from app import models

    today = hom_nay_vn()
    ids = sorted(
        (
            await session.execute(
                select(models.ProgramOffering.id)
                .where(models.ProgramOffering.is_active.is_(True))
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    if not ids:
        raise KhongCoNganh(
            "Không có ProgramOffering nào is_active=true — E2E sẽ dừng ở "
            "`resolveAdmissionContext` trước cả bước tính phí."
        )

    vet: list[str] = []
    chon = None
    tat_ca: list[Any] = []
    da_thay: set[int] = set()
    for oid in ids:
        cands = await _ung_vien_cua_offering(session, oid, today)
        vet.append(f"#{oid}:{len(cands)}")
        for path, _ in cands:
            ai = path.academic_info
            if ai.id not in da_thay:
                da_thay.add(ai.id)
                tat_ca.append(ai)
        if chon is None and cands:
            # sort ỔN ĐỊNH: round đang mở lên trước (mirror `out.sort` của TS)
            uu_tien = sorted(cands, key=lambda t: 0 if t[1] else 1)
            chon = uu_tien[0][0]
    if chon is None:
        raise KhongCoNganh(
            "Không offering nào có admission path dùng được. Đã thử "
            f"(offering:số path): {' '.join(vet)}"
        )
    return chon.academic_info, vet, tat_ca


# =============================================================================
# SEED
# =============================================================================

async def _dem_hang(session, academic_info_id: int) -> int:
    from sqlalchemy import func, select

    from app import models

    return (
        await session.execute(
            select(func.count())
            .select_from(models.OfferingSemesterTuition)
            .where(
                models.OfferingSemesterTuition.academic_info_id == academic_info_id,
                models.OfferingSemesterTuition.semester_no == HOC_KY_E2E,
            )
        )
    ).scalar_one()


async def _gia_hk1(session, academic_info_id: int) -> tuple[Any, bool]:
    """Get-or-create hàng giá HK1. Trả ``(hàng, vừa_tạo)``. Chỉ flush."""
    from sqlalchemy import select

    from app import models

    co_san = (
        await session.execute(
            select(models.OfferingSemesterTuition).where(
                models.OfferingSemesterTuition.academic_info_id == academic_info_id,
                models.OfferingSemesterTuition.semester_no == HOC_KY_E2E,
            )
        )
    ).scalar_one_or_none()
    if co_san is not None:
        # KHÔNG ghi đè giá của danh mục có sẵn — nhưng 0 đồng thì DỪNG.
        if Decimal(str(co_san.amount)) <= 0:
            raise GuardError(
                f"Hàng giá HK{HOC_KY_E2E} có sẵn của academic_info_id="
                f"{academic_info_id} mang amount={co_san.amount} (≤ 0). "
                "Tính phí sẽ hỏng MUỘN ở generate_invoices_for_fee với câu "
                "'No amount to invoice (fee fully waived)'. Sửa danh mục trước."
            )
        return co_san, False

    hang = models.OfferingSemesterTuition(
        academic_info_id=academic_info_id,
        semester_no=HOC_KY_E2E,
        amount=FIXTURE_HK1_AMOUNT,
        notes=FIXTURE_NOTES,
    )
    session.add(hang)
    await session.flush()
    return hang, True


async def _verify(session, *, ai_ids: list[int], nhan: str) -> dict[str, Any]:
    """Hậu điều kiện — gọi ĐÚNG hàm sản phẩm, không tự SELECT lấy lệ."""
    from app.services.fee_calculation_service import FeeCalculationService

    svc = FeeCalculationService(session)
    loi: list[str] = []
    so_tien: dict[int, str] = {}
    for ai_id in ai_ids:
        n = await _dem_hang(session, ai_id)
        if n != 1:
            loi.append(
                f"academic_info_id={ai_id}: có {n} hàng giá HK{HOC_KY_E2E} "
                "(phải đúng 1)"
            )
            continue
        try:
            tien = await svc._semester_tuition_amount_for_ai(ai_id, HOC_KY_E2E)
        except Exception as exc:  # noqa: BLE001 — báo nguyên văn, không nuốt
            loi.append(
                f"academic_info_id={ai_id}: hàm sản phẩm "
                f"_semester_tuition_amount_for_ai vẫn ném {type(exc).__name__}: {exc}"
            )
            continue
        if Decimal(str(tien)) <= 0:
            loi.append(f"academic_info_id={ai_id}: hàm sản phẩm trả {tien} (≤ 0)")
            continue
        so_tien[ai_id] = str(tien)
    if loi:
        raise GuardError(
            f"HẬU ĐIỀU KIỆN KHÔNG ĐẠT ({nhan}) — {len(loi)} khẳng định:\n  - "
            + "\n  - ".join(loi)
        )
    return {"semester_no": HOC_KY_E2E, "amounts": so_tien}


# =============================================================================
# CLI
# =============================================================================

async def _mo_phien_da_guard(*, allow_dev: bool):
    """Tầng 1 + tầng 2a/2b. Trả về ``(AsyncSessionLocal, app_env, db)``."""
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    from app.config import settings
    from app.database import AsyncSessionLocal

    app_env = assert_app_env_allowed(settings.APP_ENV, allow_dev=allow_dev)
    db_tu_url = assert_db_name_allowed(
        make_url(str(settings.DATABASE_URL)).database,
        allow_dev=allow_dev,
        nguon="DATABASE_URL",
    )
    async with AsyncSessionLocal() as kiem:
        db_thuc = assert_db_name_allowed(
            await kiem.scalar(text("SELECT current_database()")),
            allow_dev=allow_dev,
            nguon="current_database()",
        )
        if db_thuc != db_tu_url:
            raise GuardError(
                f"TẦNG 2 TỪ CHỐI: DATABASE_URL nói {db_tu_url!r} nhưng kết nối "
                f"thật đang ở {db_thuc!r}."
            )
    return AsyncSessionLocal, app_env, db_thuc


def _in_lua_chon(ai, vet: list[str], tat_ca: list) -> None:
    print(f"  offering thử (offering:số path): {' '.join(vet)}")
    print(
        f"  E2E CHỌN academic_info_id={ai.id} "
        f"(offering_id={ai.offering_id}, academic_year={ai.academic_year}, "
        f"tuition_fee_per_year={ai.tuition_fee_per_year})"
    )
    print(f"  tổng ngành có path dùng được: {len(tat_ca)} "
          f"→ {sorted(x.id for x in tat_ca)}")


async def _chay(*, apply: bool, allow_dev: bool, all_candidates: bool) -> int:
    AsyncSessionLocal, app_env, db_thuc = await _mo_phien_da_guard(allow_dev=allow_dev)
    print(f"[guard] APP_ENV={app_env} · current_database()={db_thuc} · OK")

    async with AsyncSessionLocal() as session:
        ai, vet, tat_ca = await _chon_theo_e2e(session)
        _in_lua_chon(ai, vet, tat_ca)
        muc_tieu = [x.id for x in tat_ca] if all_candidates else [ai.id]
        truoc = {i: await _dem_hang(session, i) for i in muc_tieu}

    print(f"  học kỳ           : HK{HOC_KY_E2E}")
    print(f"  số tiền fixture  : {FIXTURE_HK1_AMOUNT} (HẰNG SỐ, không suy từ "
          "tuition_fee_per_year)")
    print(f"  phạm vi          : {'TẤT CẢ ứng viên' if all_candidates else 'ngành E2E chọn'}")
    print(f"  hàng HK{HOC_KY_E2E} TRƯỚC   : {truoc}")

    if not apply:
        print("DRY-RUN — KHÔNG chạm CSDL. Thêm --apply để ghi.")
        return 0

    async with AsyncSessionLocal() as session:
        tao = 0
        dung_lai = 0
        try:
            for ai_id in muc_tieu:
                _, vua_tao = await _gia_hk1(session, ai_id)
                tao += 1 if vua_tao else 0
                dung_lai += 0 if vua_tao else 1
            # Hậu điều kiện TRƯỚC commit — hỏng thì không ghi gì.
            await _verify(session, ai_ids=muc_tieu, nhan="trước commit")
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    # Phiên MỚI: identity map rỗng ⇒ buộc SELECT thật.
    async with AsyncSessionLocal() as kiem:
        tom_tat = await _verify(kiem, ai_ids=muc_tieu, nhan="sau commit, phiên mới")
        sau = {i: await _dem_hang(kiem, i) for i in muc_tieu}

    print(f"[apply] tạo mới={tao} · dùng lại hàng có sẵn={dung_lai}")
    print(f"  hàng HK{HOC_KY_E2E} SAU     : {sau}")
    print(f"[verify] ĐẠT — {tom_tat}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Seed hàng offering_semester_tuition HK1 cho ngành mà E2E chọn "
            "(test-only, fail-closed, idempotent)."
        )
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Thực sự ghi CSDL. Không có cờ này = dry-run.",
    )
    ap.add_argument(
        "--allow-dev",
        action="store_true",
        help="Nới allowlist sang development / qlts_dev (KHÔNG nới sang production).",
    )
    ap.add_argument(
        "--all-candidates",
        action="store_true",
        help=(
            "Seed cho MỌI ngành có admission path dùng được, không chỉ ngành "
            "E2E chọn — phòng khi bản mirror lệch khỏi thuật toán TS."
        ),
    )
    args = ap.parse_args(argv)
    try:
        return asyncio.run(
            _chay(
                apply=args.apply,
                allow_dev=args.allow_dev,
                all_candidates=args.all_candidates,
            )
        )
    except GuardError as exc:
        print(f"DỪNG: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
