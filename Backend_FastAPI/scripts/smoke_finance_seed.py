"""Seed + validator fixture cho Chrome smoke Finance (gói P1 — core collection).

Chạy TRONG container backend. Đây là công cụ PHÁ HOẠI dữ liệu: nó tạo hồ sơ,
khoản phí, hoá đơn và phiếu thu thật trong cơ sở dữ liệu được trỏ tới. Vì vậy
mọi hàng rào ở đây là fail-closed — thiếu một điều kiện thì thoát với mã khác 0
và KHÔNG chạm vào dữ liệu:

* ``APP_ENV`` phải thuộc allowlist ``{development}`` — không phải chỉ
  "không nhận ra là production";
* tên database phải ĐÚNG `qlts_smoke`, đọc bằng parser của SQLAlchemy chứ không
  bằng tách chuỗi — không suy từ biến môi trường nào khác, không có mặc định;
* ``SMOKE_ALLOW_DESTRUCTIVE=1`` phải do người chạy đặt tường minh;
* ``SMOKE_WEB_BASE``/``SMOKE_API_BASE`` phải được truyền VÀ phải trỏ về máy cục
  bộ (``localhost``/``127.0.0.1``) — lượt smoke không được lái vào máy chủ thật;
* URL/mật khẩu không có giá trị mặc định trong mã.

Hai chế độ:

  python scripts/smoke_finance_seed.py --run-id R1 --seed
  python scripts/smoke_finance_seed.py --run-id R1 --thu-muc <gốc registry> --validate

``--validate`` đọc **sổ cái** ``registry.json`` rồi kiểm lại HÌNH DẠNG từng fixture
trên cơ sở dữ liệu và in bảng ``fixture -> IDs -> status -> amount``. Nó phải
thoát khác 0 khi bất kỳ điều kiện nào của §A05 sai — một validator luôn xanh
thì không khác gì không có validator.

Không tra cứu bản ghi theo TÊN học sinh: mọi id được ghi vào ``registry.json``
ngay lúc tạo, và mọi phép kiểm sau đó đi theo id.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

sys.path.insert(0, "/app")
# `smoke_lib` nằm CẠNH tệp này (trong repo là `scripts/`, trong `smoke-runner` là
# `/tools/`), nên neo theo vị trí tệp thay vì theo một đường tuyệt đối.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import select, text  # noqa: E402

from app import models  # noqa: E402
from smoke_lib import baseline as smoke_baseline, registry  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.models.finance import (  # noqa: E402
    Fee,
    FeeTypeEnum,
    Invoice,
    InvoiceStatusEnum,
    Payment,
    PaymentImportBatch,
    PaymentImportBatchStatusEnum,
    PaymentImportRow,
    PaymentMethod,
    PaymentStatusEnum,
)

# ALLOWLIST môi trường. Xem `kiem_moi_truong`: blocklist để lọt chuỗi rỗng,
# `staging`, và mọi tên gõ sai.
APP_ENV_CHO_PHEP = {"development"}
# ĐÍCH DUY NHẤT. Trước đây allowlist mở cho `qlts_dev`/`qlts_test`, nên seed có
# thể ghi vào `qlts_dev` trong khi sổ ghi `database: qlts_smoke` và cleanup
# restore `qlts_smoke` — dữ liệu thử nằm lại trong database dev, không ai dọn và
# không gì trong sổ cho biết.
#
# Lấy hằng từ NGUỒN CHUẨN `smoke_lib.baseline`, không khai lại: hai bản hằng là
# hai thứ sẽ lệch nhau.
DB_CHO_PHEP = {smoke_baseline._DB_DUY_NHAT}

# GÓI mà tệp này dựng fixture cho. Một nguồn chuẩn, dùng ở CẢ hai chỗ: khai vào
# sổ khi ghi, và đối chiếu với sổ khi đọc. Hai chuỗi "P1" rời nhau là hai thứ sẽ
# lệch — và lệch ở đây nghĩa là fixture gói này nằm trong sổ gói kia.
PACK = "P1"

TIEN_FULL = Decimal("5000000")
TIEN_DOT = Decimal("3000000")
TIEN_DUP = Decimal("1500000")
TIEN_APP = Decimal("500000")


class ChanLai(SystemExit):
    """Thoát fail-closed, mã 2 — phân biệt với lỗi bất ngờ (mã 1)."""

    def __init__(self, ly_do: str):
        print(f"\n[CHẶN] {ly_do}", file=sys.stderr)
        super().__init__(2)


def _ten_db() -> str:
    """Tên database đọc bằng PARSER của SQLAlchemy, không bằng tách chuỗi.

    `rsplit("/")` bị lách bằng một tham số truy vấn có dấu gạch chéo:

        …/qlts_dev?application_name=/qlts_smoke   →  rsplit trả "qlts_smoke"

    Tức hàng rào đọc ra `qlts_smoke` trong khi kết nối thật đi tới `qlts_dev`.
    Đã tái hiện. Định danh của ĐÍCH PHÁ HUỶ không được tự tách chuỗi lỏng tay —
    dùng đúng parser mà chính driver dùng.
    """
    from sqlalchemy.engine import make_url  # noqa: WPS433

    try:
        return make_url(str(settings.DATABASE_URL)).database or ""
    except Exception as e:  # URL hỏng ⇒ không xác định được đích ⇒ DỪNG
        raise ChanLai(f"DATABASE_URL không phân giải được: {e}")


def kiem_moi_truong(can_ghi: bool) -> None:
    """BỐN cổng fail-closed. Đích phá huỷ là ``qlts_smoke``, và chỉ nó.

    1. ``APP_ENV`` phải nằm trong ``APP_ENV_CHO_PHEP`` — allowlist, không phải
       blocklist;
    2. tên database phải nằm trong ``DB_CHO_PHEP``, nay CHỈ ``qlts_smoke``, đọc
       bằng ``_ten_db()``. Allowlist cũ mở cho ``qlts_dev``/``qlts_test`` đã bị
       đóng — lý do ở chú thích của ``DB_CHO_PHEP``;
    3. ``SMOKE_ALLOW_DESTRUCTIVE=1`` — chỉ xét khi ``can_ghi``, và phải do người
       chạy đặt tường minh cho từng lượt;
    4. ``SMOKE_WEB_BASE``/``SMOKE_API_BASE`` phải có VÀ trỏ về máy cục bộ.

    Thiếu bất kỳ cổng nào ⇒ ``ChanLai`` (mã 2) và KHÔNG chạm vào dữ liệu.
    """
    app_env = (getattr(settings, "APP_ENV", "") or "").strip().lower()
    if app_env not in APP_ENV_CHO_PHEP:
        # ALLOWLIST, không phải blocklist. Bản trước chỉ cấm `production`/`prod`,
        # nên `staging`, chuỗi rỗng (biến chưa đặt) hay một tên gõ sai đều đi lọt
        # — với một script TẠO dữ liệu thật thì "không nhận ra là production"
        # không đủ, phải "chắc chắn là development".
        raise ChanLai(
            f"APP_ENV={app_env!r} không nằm trong allowlist {sorted(APP_ENV_CHO_PHEP)}"
        )

    ten = _ten_db()
    if ten not in DB_CHO_PHEP:
        raise ChanLai(
            f"database {ten!r} không nằm trong allowlist {sorted(DB_CHO_PHEP)}. "
            "Sửa allowlist là việc có chủ ý, không phải việc script tự đoán."
        )

    if can_ghi and os.environ.get("SMOKE_ALLOW_DESTRUCTIVE") != "1":
        raise ChanLai(
            "thiếu SMOKE_ALLOW_DESTRUCTIVE=1. Lệnh này TẠO dữ liệu thật; "
            "cờ phải do người chạy đặt tường minh cho từng lượt."
        )

    for ten_bien in ("SMOKE_WEB_BASE", "SMOKE_API_BASE"):
        gt = os.environ.get(ten_bien, "")
        if not gt:
            raise ChanLai(f"thiếu {ten_bien} — phải truyền rõ, không suy từ mặc định")
        if "localhost" not in gt and "127.0.0.1" not in gt:
            raise ChanLai(f"{ten_bien}={gt!r} không trỏ về máy cục bộ")

    print(f"  môi trường: APP_ENV={app_env or '(trống)'} · db={ten} · cờ phá huỷ ĐÃ bật")


def _so(thu_muc: Path, run_id: str) -> "registry.Registry":
    """Mở SỔ CÁI của lượt. Không tạo mới: `--baseline` phải chạy trước.

    Bản trước ghi một `created-ids.json` riêng dưới `/app/.smoke/<run_id>/`. Hai
    tệp cho một lượt nghĩa là có lúc chúng lệch nhau và không ai biết bên nào
    đúng — mà cleanup thì đọc registry. Nay chỉ còn MỘT sổ.
    """
    try:
        so = registry.Registry.doc(
            thu_muc, run_id,
            # Hằng lấy từ NGUỒN CHUẨN `smoke_lib.baseline`, không khai lại ở đây:
            # hai bản hằng là hai thứ sẽ lệch nhau.
            project_mong_doi=smoke_baseline._PROJECT_DUY_NHAT,
            database_mong_doi=smoke_baseline._DB_DUY_NHAT,
            # Tệp này CHỈ dựng fixture gói P1 — không có `F-REFUND-*` của P2. Khai
            # gói ra đây để một sổ mở cho gói khác bị chặn ngay, thay vì để fixture
            # P1 ghi vào sổ P2 rồi cleanup restore theo baseline của gói kia.
            pack_mong_doi=PACK,
        )
    except registry.LoiRegistry as e:
        raise ChanLai(
            f"không đọc được sổ của {run_id!r} tại {thu_muc}: {e}. "
            "Chạy `smoke_lib.cli --baseline` trước khi seed."
        )
    # `doc()` cho phép `baseline=None` — hợp lý cho việc đọc-để-xem, KHÔNG hợp lý
    # ở đây: seed tạo dữ liệu, và nếu baseline chưa được chụp thì cleanup không
    # còn mốc nào để phục hồi về. Đòi tường minh.
    if not so.du_lieu.get("baseline"):
        raise ChanLai(
            f"sổ của {run_id!r} chưa có baseline. Chạy `smoke_lib.cli --baseline` "
            "TRƯỚC khi seed — baseline phải chụp database lúc chưa có fixture nào."
        )
    return so


# Vai trò smoke ↔ persona. Bản trước khoá cứng `accountant01`/`manager01`/
# `kpahdrim` — ba tài khoản NỀN dùng chung: seed đổi dữ liệu của chúng là đổi nền
# cho mọi lượt sau, và `kpahdrim` còn là một tên người thật lọt vào mã.
#
# Nay mặc định trỏ sang persona `smoke_*` do `smoke_bootstrap_personas.py` dựng,
# và `--persona VAI=username` cho phép ghi đè tường minh khi cần.
PERSONA_MAC_DINH = {
    "ACC-A": "smoke_acc_a",
    "MGR-A": "smoke_mgr_a",
    "ACC-B": "smoke_acc_b",
    "OFF-A": "smoke_off_a",
}


# Vai trò mà mỗi persona BẮT BUỘC phải mang. `--persona` cho phép ghi đè tên tài
# khoản, nên nếu chỉ kiểm "tồn tại và active" thì `ACC-A=<một manager>` vẫn qua —
# và cả lượt smoke đo nhầm quyền.
VAI_BAT_BUOC = {
    "ACC-A": "accountant",
    "ACC-B": "accountant",
    "MGR-A": "manager",
    "OFF-A": "officer",
}


async def _actor(db, username: str, vai: Optional[str] = None) -> models.User:
    u = (
        await db.execute(select(models.User).where(models.User.username == username))
    ).scalars().first()
    if u is None:
        raise ChanLai(f"không tìm thấy tài khoản {username!r} trên DB này")
    if u.status != "active":
        raise ChanLai(f"tài khoản {username!r} có status={u.status!r}, phải là active")
    if u.unit_id is None:
        raise ChanLai(f"tài khoản {username!r} không thuộc đơn vị nào")
    if vai is not None and u.role != vai:
        raise ChanLai(
            f"tài khoản {username!r} có role={u.role!r}, chờ {vai!r}. `--persona` "
            "đổi được TÊN tài khoản chứ không đổi được vai mà ca smoke cần."
        )
    return u


async def _method_cash(db) -> PaymentMethod:
    m = (
        await db.execute(select(PaymentMethod).where(PaymentMethod.code == "cash"))
    ).scalars().first()
    if m is None or not m.is_active:
        raise ChanLai("thiếu PaymentMethod code='cash' đang active")
    return m


async def _ho_so(
    db,
    run_id: str,
    ma: str,
    unit_id: int,
    stt: int,
    *,
    officer_id: Optional[int] = None,
    applied_rules: Optional[dict] = None,
) -> models.AdmissionProfile:
    trang_thai = (
        await db.execute(select(models.ConsultationStatus).limit(1))
    ).scalars().first()
    if trang_thai is None:
        raise ChanLai("bảng consultation_status rỗng — DB chưa seed danh mục")

    lead = models.Lead(
        full_name=f"[SMOKE {run_id}] {ma}",
        phone=f"09{stt:08d}"[:11],
        source="smoke",
        unit_id=unit_id,
        consultation_status_id=trang_thai.id,
        # Officer bị chặn theo IDOR nếu lead không thuộc phạm vi họ — thiếu
        # dòng này thì ca dùng persona officer nhận 404 và trông như lỗi sản
        # phẩm, trong khi đó chỉ là fixture dựng thiếu.
        assigned_officer_id=officer_id,
    )
    db.add(lead)
    await db.flush()
    hs = models.AdmissionProfile(
        lead_id=lead.id,
        status="submitted",
        academic_year=2026,
        citizen_id=f"{stt:012d}",
        applied_rules=applied_rules or {},
    )
    db.add(hs)
    await db.flush()
    return hs


async def _fee_va_invoice(
    db, hs_id: int, ma: str, so_dot: int, tien_moi_dot: Decimal, loai=FeeTypeEnum.tuition
) -> Dict[str, Any]:
    tong = tien_moi_dot * so_dot
    fee = Fee(
        admission_profile_id=hs_id,
        fee_type=loai.value,
        academic_year=2026,
        # `chk_fee_nontuition_semester_no_null`: chỉ học phí mới có học kỳ. Lệ
        # phí hồ sơ mà mang semester_no là bị CHECK từ chối.
        semester_no=1 if loai is FeeTypeEnum.tuition else None,
        base_amount=tong,
        final_amount=tong,
        status="invoiced",
    )
    db.add(fee)
    await db.flush()

    ids = []
    for i in range(1, so_dot + 1):
        inv = Invoice(
            fee_id=fee.id,
            invoice_number=f"SMK-{ma}-{fee.id}-{i}",
            installment_no=i,
            amount=tien_moi_dot,
            status=InvoiceStatusEnum.issued.value,
            due_date=date.today() + timedelta(days=30 * i),
        )
        db.add(inv)
        await db.flush()
        ids.append(inv.id)
    return {"fee_id": fee.id, "invoice_ids": ids, "amount_moi_dot": str(tien_moi_dot)}


HOC_KY_TINH_PHI = 1


async def _gia_hoc_ky(db, ai) -> Any:
    """Hàng giá học kỳ — mắt xích THỨ HAI, và là cái đã chặn FIN-03 ở `BL20260818A`.

    Bản đầu của `_oac_cho_tinh_phi` chỉ dựng `OfferingAdmissionConfig` rồi coi
    `tuition_fee_per_year` là bằng chứng "tính được tiền". Sai, và sai im lặng:
    với `fee_type = tuition`, giá GỐC lấy **chỉ** từ `offering_semester_tuition`
    (`fee_calculation_service._semester_tuition_amount_for_ai`, gọi từ nhánh
    tuition của `calculate_fee`). `tuition_fee_per_year` chỉ dùng cho fee KHÔNG
    phải tuition.

    Đo trên `qlts_smoke` ở `BL20260818A`: ngành giải ra rồi (`academic_info_id=1`,
    `tuition_fee_per_year=5.500.000`) mà `preview_tuition` vẫn nổ
    `BadRequest: Chưa cấu hình học phí cho HK1 (academic_info_id=1)` vì bảng ấy
    có **0 hàng** (`qlts_dev` có 96). Kiến thức này đã nằm sẵn trong
    `tests/api/test_tuition_prepay_flow.py::_seed_hk1_tuition_for_config` —
    chỉ seeder là chưa biết.

    Hai luật của hàm này:

    * **KHÔNG ghi đè hàng catalog đã tồn tại.** Có hàng HK1 rồi thì dùng lại
      nguyên si, kể cả khi số của nó khác `tuition_fee_per_year`. Danh mục là dữ
      liệu của người khác; fixture không được sửa giá của nó để oracle tròn số.
    * **Fail-closed khi không suy ra được số.** Thiếu/không dương
      `tuition_fee_per_year` thì `ChanLai`, không dựng hàng `amount = 0` — một
      hàng giá 0 làm `calculate_fee` chạy được và cho ra hoá đơn 0 đồng, tức là
      biến một fixture hỏng thành một lượt smoke "xanh".

    Số tiền chọn bằng đúng `tuition_fee_per_year` là quyết định **cho fixture xác
    định**, không phải khẳng định về cách trường định giá học kỳ thật. Số thật
    được ghi vào sổ (`semester_amount`) nên oracle đọc, không đoán.
    """
    ost = (
        await db.execute(
            select(models.OfferingSemesterTuition).where(
                models.OfferingSemesterTuition.academic_info_id == ai.id,
                models.OfferingSemesterTuition.semester_no == HOC_KY_TINH_PHI,
            )
        )
    ).scalars().first()
    if ost is not None:
        return ost

    tien = ai.tuition_fee_per_year
    if tien is None or Decimal(str(tien)) <= 0:
        raise ChanLai(
            f"academic_info {ai.id} không có tuition_fee_per_year dương — không "
            f"suy ra được giá HK{HOC_KY_TINH_PHI}, và KHÔNG dựng hàng giá 0 "
            "(hoá đơn 0 đồng sẽ làm lượt smoke xanh trên một fixture hỏng)"
        )

    ost = models.OfferingSemesterTuition(
        academic_info_id=ai.id,
        semester_no=HOC_KY_TINH_PHI,
        amount=Decimal(str(tien)),
        notes="smoke fixture F-CALC — giá HK1 để FIN-03 tính phí được",
    )
    db.add(ost)
    await db.flush()
    return ost


async def _oac_cho_tinh_phi(db) -> Any:
    """Dựng `OfferingAdmissionConfig` **và** hàng giá HK1 — hai mắt xích FIN-03 cần.

    `resolve_fee_academic_info` với hồ sơ **legacy** (`uses_choice_engine=False`)
    giải ngành theo ba nhánh, đúng thứ tự::

        offering_admission_config.academic_info   (eager)
        → tra OAC theo offering_admission_config_id
        → applied_rules['academic_info_id']

    Đo trên `qlts_smoke` ở `BL20260817A`: `offering_academic_info` có **8 hàng**,
    nhưng `offering_admission_config` có **0 hàng** và 7/7 hồ sơ đều
    `offering_admission_config_id = NULL` + `applied_rules` không có
    `academic_info_id`. Cả ba nhánh cùng rỗng ⇒ `BadRequest`, trong khi
    `is_fee_eligible` vẫn trả `True` nên nút "Tính học phí" hiện ở trạng thái BẬT.

    Giải được ngành **chưa đủ**. Đo tiếp ở `BL20260818A`: OAC đã có, ngành giải
    ra, mà `preview_tuition` vẫn nổ vì thiếu hàng `offering_semester_tuition` —
    xem `_gia_hoc_ky`. Hàm này nay trả **ba** thứ và cả ba đều bắt buộc.

    Fixture này đóng khoảng trống *fixture*. Nó **KHÔNG** vá lỗi sản phẩm
    "cổng trạng thái nói được, bộ định giá nói không" — đó vẫn là nợ đang mở.

    Idempotent: có OAC / hàng giá hợp lệ rồi thì dùng lại, không đẻ thêm hàng mỗi
    lượt seed.
    """
    ai = (
        await db.execute(
            select(models.OfferingAcademicInfo)
            .where(
                models.OfferingAcademicInfo.academic_year == 2026,
                models.OfferingAcademicInfo.tuition_fee_per_year.isnot(None),
            )
            .order_by(models.OfferingAcademicInfo.id)
            .limit(1)
        )
    ).scalars().first()
    if ai is None:
        raise ChanLai(
            "không có OfferingAcademicInfo nào của năm 2026 kèm tuition_fee_per_year "
            "— danh mục nền chưa seed, không dựng được fixture tính phí"
        )

    oac = (
        await db.execute(
            select(models.OfferingAdmissionConfig)
            .where(
                models.OfferingAdmissionConfig.academic_info_id == ai.id,
                models.OfferingAdmissionConfig.is_active.is_(True),
            )
            .limit(1)
        )
    ).scalars().first()
    if oac is not None:
        return oac, ai, await _gia_hoc_ky(db, ai)

    crit = (
        await db.execute(
            select(models.AdmissionCriteria)
            .order_by(models.AdmissionCriteria.id)
            .limit(1)
        )
    ).scalars().first()
    if crit is None:
        raise ChanLai(
            "bảng admission_criteria rỗng — OfferingAdmissionConfig cần criteria_id "
            "NOT NULL, không dựng được fixture tính phí"
        )

    oac = models.OfferingAdmissionConfig(
        academic_info_id=ai.id,
        criteria_id=crit.id,
        is_active=True,
    )
    db.add(oac)
    await db.flush()
    return oac, ai, await _gia_hoc_ky(db, ai)


async def seed(
    run_id: str, thu_muc: Path, persona: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    kiem_moi_truong(can_ghi=True)
    pers = dict(PERSONA_MAC_DINH)
    pers.update(persona or {})
    thieu = [k for k in PERSONA_MAC_DINH if not pers.get(k)]
    if thieu:
        raise ChanLai(f"thiếu persona cho vai: {thieu}")

    so = _so(thu_muc, run_id)
    if so.du_lieu.get("fixtures"):
        raise ChanLai(
            f"sổ của {run_id!r} đã có fixture. Một RUN_ID chỉ seed MỘT lần; chạy "
            "lại sẽ tạo bản ghi mồ côi không ai cleanup. Dùng run-id mới hoặc "
            "cleanup trước."
        )

    async with AsyncSessionLocal() as db:
        acc_a = await _actor(db, pers["ACC-A"], VAI_BAT_BUOC["ACC-A"])
        mgr_a = await _actor(db, pers["MGR-A"], VAI_BAT_BUOC["MGR-A"])
        acc_b = await _actor(db, pers["ACC-B"], VAI_BAT_BUOC["ACC-B"])
        if acc_a.unit_id != mgr_a.unit_id:
            raise ChanLai(
                f"ACC-A(unit {acc_a.unit_id}) và MGR-A(unit {mgr_a.unit_id}) phải "
                "cùng đơn vị A"
            )
        if acc_b.unit_id == acc_a.unit_id:
            raise ChanLai("ACC-B phải thuộc đơn vị KHÁC để kiểm IDOR chéo")
        if acc_a.id == mgr_a.id:
            raise ChanLai("ACC-A và checker phải là hai tài khoản khác nhau")

        unit_a = acc_a.unit_id
        method = await _method_cash(db)
        base = abs(hash(run_id)) % 900000
        kq: Dict[str, Any] = {
            "run_id": run_id,
            "pack": PACK,
            "tao_luc": datetime.now(timezone.utc).isoformat(),
            "actor": {
                "ACC-A": {"id": acc_a.id, "username": acc_a.username,
                          "unit": unit_a, "role": acc_a.role},
                "MGR-A": {"id": mgr_a.id, "username": mgr_a.username,
                          "unit": mgr_a.unit_id, "role": mgr_a.role},
                "ACC-B": {"id": acc_b.id, "username": acc_b.username,
                          "unit": acc_b.unit_id, "role": acc_b.role},
            },
            "method_cash_id": method.id,
            "fixtures": {},
        }

        # F-APP — lệ phí hồ sơ, chưa thu.
        #
        # ⚠️ KHÔNG dựng sẵn Fee/Invoice `application`. Đường thu lệ phí TỰ tạo
        # sổ khi ghi tiền, và `_assert_paid_fee_fields` (admission_service)
        # đòi Fee đã có phải ở trạng thái `paid` khớp từng trường. Một Fee
        # `invoiced` dựng sẵn ⇒ 409 "Inconsistent application fee ledger: fee
        # status", và ca trông như lỗi sản phẩm. Đã vấp thật ở FIN-02.
        #
        # Panel lệ phí đọc `profile.applied_rules`, nên đó mới là chỗ phải seed.
        # Persona tường minh, KHÔNG quét "officer active bất kỳ ở đơn vị A": lượt
        # sau có thể bắt được một officer khác, nên hai lượt cùng run-id lại nói
        # về hai người — và không gì trong sổ cho biết điều đó đã xảy ra.
        officer = await _actor(db, pers["OFF-A"], VAI_BAT_BUOC["OFF-A"])
        if officer.unit_id != unit_a:
            raise ChanLai(
                f"OFF-A ({officer.username}) ở đơn vị {officer.unit_id}, "
                f"chờ đơn vị A ({unit_a})"
            )
        hs = await _ho_so(
            db,
            run_id,
            "FAPP",
            unit_a,
            base + 1,
            officer_id=officer.id,
            applied_rules={
                "requires_application_fee": True,
                "application_fee": int(TIEN_APP),
                "fee_status": "pending",
            },
        )
        kq["fixtures"]["F-APP"] = {
            "profile_id": hs.id,
            "officer_id": officer.id,
            "application_fee": str(TIEN_APP),
            "khong_co_fee_truoc": True,
        }
        kq["actor"]["OFF-A"] = {
            "id": officer.id,
            "username": officer.username,
            "unit": officer.unit_id,
            "role": officer.role,
        }

        # F-FULL — một khoản phí, một đợt.
        hs = await _ho_so(db, run_id, "FFULL", unit_a, base + 2)
        kq["fixtures"]["F-FULL"] = {
            "profile_id": hs.id,
            **await _fee_va_invoice(db, hs.id, "FFULL", 1, TIEN_FULL),
        }

        # F-FIFO — hai đợt còn nợ, tổng lớn hơn số sẽ thu.
        hs = await _ho_so(db, run_id, "FFIFO", unit_a, base + 3)
        kq["fixtures"]["F-FIFO"] = {
            "profile_id": hs.id,
            **await _fee_va_invoice(db, hs.id, "FFIFO", 2, TIEN_DOT),
        }

        # F-DUP — sẵn một phiếu chờ duyệt khớp luật dò trùng của dòng sắp ghi.
        hs = await _ho_so(db, run_id, "FDUP", unit_a, base + 4)
        f_dup = await _fee_va_invoice(db, hs.id, "FDUP", 1, TIEN_FULL)
        ngay_dup = datetime.now(timezone.utc).replace(hour=3, minute=0, second=0, microsecond=0)
        p = Payment(
            invoice_id=f_dup["invoice_ids"][0],
            method_id=method.id,
            amount=TIEN_DUP,
            reference_code=f"SMK-{run_id}-DUP-CU",
            status=PaymentStatusEnum.pending.value,
            payment_date=ngay_dup,
            created_by_id=acc_a.id,
        )
        db.add(p)
        await db.flush()
        kq["fixtures"]["F-DUP"] = {
            "profile_id": hs.id,
            **f_dup,
            "payment_ung_vien_id": p.id,
            "amount_ung_vien": str(TIEN_DUP),
            "payment_date": ngay_dup.isoformat(),
        }

        # F-REJECT — hoá đơn riêng để ghi rồi từ chối.
        hs = await _ho_so(db, run_id, "FREJ", unit_a, base + 5)
        kq["fixtures"]["F-REJECT"] = {
            "profile_id": hs.id,
            **await _fee_va_invoice(db, hs.id, "FREJ", 1, TIEN_FULL),
        }

        # F-IDOR-B — thuộc đơn vị B, dùng cho ca âm chéo đơn vị.
        hs_b = await _ho_so(db, run_id, "FIDORB", acc_b.unit_id, base + 6)
        kq["fixtures"]["F-IDOR-B"] = {
            "profile_id": hs_b.id,
            **await _fee_va_invoice(db, hs_b.id, "FIDORB", 1, TIEN_FULL),
        }

        # F-IMPORT — lô preview 6 dòng: hợp lệ · sai dữ liệu · không match ·
        # nghi trùng · hai dòng cùng Fee · dòng phân bổ FIFO.
        hs = await _ho_so(db, run_id, "FIMP", unit_a, base + 7)
        f_imp = await _fee_va_invoice(db, hs.id, "FIMP", 2, TIEN_DOT)
        lo = PaymentImportBatch(
            academic_year=2026,
            semester_no=1,
            file_name=f"smoke-{run_id}.xlsx",
            file_sha256=f"{base:064d}",
            status=PaymentImportBatchStatusEnum.preview.value,
            row_count=0,
            created_by_id=acc_a.id,
        )
        db.add(lo)
        await db.flush()
        kq["fixtures"]["F-IMPORT"] = {
            "profile_id": hs.id,
            "batch_id": lo.id,
            **f_imp,
        }

        # F-CALC — hồ sơ TÍNH PHÍ ĐƯỢC, mở khoá FIN-03.
        #
        # Khác mọi fixture trên ở đúng hai điểm, và cả hai đều bắt buộc:
        #   * `offering_admission_config_id` trỏ tới OAC thật ⇒ nhánh 2 của
        #     `resolve_fee_academic_info` giải được ngành;
        #   * KHÔNG dựng sẵn Fee tuition — FIN-03 là ca "tính phí mới". Dựng sẵn
        #     thì thao tác tính chỉ đi đường recalculate và ca mất hết ý nghĩa.
        oac, ai_calc, gia_hk = await _oac_cho_tinh_phi(db)
        hs = await _ho_so(db, run_id, "FCALC", unit_a, base + 8)
        hs.offering_admission_config_id = oac.id
        hs.uses_choice_engine = False
        await db.flush()
        kq["fixtures"]["F-CALC"] = {
            "profile_id": hs.id,
            "offering_admission_config_id": oac.id,
            "academic_info_id": ai_calc.id,
            "tuition_fee_per_year": str(ai_calc.tuition_fee_per_year),
            # Giá HK1 THẬT — đây mới là số `calculate_fee` dùng làm base cho
            # tuition. Ghi cả id lẫn số để oracle đọc thay vì suy từ
            # `tuition_fee_per_year` (hai số có thể khác nhau khi danh mục đã có
            # sẵn hàng giá và fixture KHÔNG được ghi đè nó).
            "semester_tuition_id": gia_hk.id,
            "semester_no": gia_hk.semester_no,
            "semester_amount": str(gia_hk.amount),
            # Cờ RIÊNG, không dùng `khong_co_fee_truoc` của F-APP: nhánh ấy còn
            # đòi `applied_rules.requires_application_fee` — luật của lệ phí hồ
            # sơ, không liên quan gì tới tính học phí.
            "tinh_phi_duoc": True,
            "khong_co_fee_tuition_truoc": True,
        }

        # F-CACHE — fixture RIÊNG cho FIN-07, không dùng chung với ca nào khác.
        #
        # Vì sao phải riêng: FIN-07 đo "UI dùng cache cũ trong lúc refetch". Nếu
        # mượn fixture đã bị FIN-04/05/06 làm đổi thì không phân biệt được
        # "cache cũ" với "dữ liệu đã đổi từ ca trước" — và một ca không phân biệt
        # được hai nguyên nhân thì không kết luận được gì.
        #
        # Hai persona KHÁC NHAU (`ACC-A` đọc, `ACC-B` ghi): hệ chỉ cho MỘT phiên
        # hoạt động mỗi người dùng nên kịch bản "hai phiên cùng ACC-A" của runbook
        # cũ không dựng được — đăng nhập lần hai thu hồi phiên trước.
        hs = await _ho_so(db, run_id, "FCACHE", unit_a, base + 9)
        f_cache = await _fee_va_invoice(db, hs.id, "FCACHE", 1, TIEN_FULL)
        kq["fixtures"]["F-CACHE"] = {
            "profile_id": hs.id,
            **f_cache,
            "persona_doc": "ACC-A",
            "persona_ghi": "ACC-B",
            "so_tien_se_ghi": str(TIEN_DUP),
            "khong_dung_chung": True,
        }

        # COMMIT trước, ghi registry sau: ghi trước mà commit hỏng thì tệp id
        # trỏ tới những bản ghi không tồn tại, và lượt cleanup sau sẽ đi tìm
        # chúng mãi. Ngược lại (commit xong, ghi hỏng) thì dữ liệu có thật và
        # lỗi nổ ra ngay tại đây, không âm thầm.
        await db.commit()
        # Ghi vào SỔ CÁI: hình dạng qua `ghi_fixture`, id qua `ghi_ids`/
        # `them_goc`. Cleanup và các pack sau đọc đúng một nguồn.
        # Actor phải vào SỔ, không chỉ nằm trong `kq` bộ nhớ: `--validate` chạy
        # ở một tiến trình KHÁC (và thường là lượt sau), nên thứ không được ghi
        # thì lượt ấy không có. Bản trước đọc `du["actor"]` trong khi sổ chỉ có
        # `fixtures` ⇒ KeyError chắc chắn.
        so.ghi_fixture("_ACTOR", kq["actor"])
        for ma, fx in kq["fixtures"].items():
            so.ghi_fixture(ma, fx)
        ho_so = sorted({
            fx["profile_id"] for fx in kq["fixtures"].values() if fx.get("profile_id")
        })
        if ho_so:
            so.them_goc(profile_ids=ho_so)
            so.ghi_ids("admission_profile", ho_so)

    print(f"\n  đã ghi sổ {so.duong}")
    return kq


def kiem_chu_so_huu(fapp: Mapping, off_a: Mapping, lead: Any) -> List[str]:
    """Chủ sở hữu THẬT của F-APP, đọc từ `lead`, không từ sổ.

    So `fapp["officer_id"]` với `off_a["id"]` là CHƯA ĐỦ: cả hai vế đều do chính
    seed ghi vào sổ, nên chúng luôn khớp nhau bất kể database về sau ra sao. Hồ sơ
    bị chuyển sang officer khác sau lúc seed thì chỉ `lead.assigned_officer_id`
    mới cho biết.

    Tách thành hàm thuần để kiểm được bằng stub — không cần database.
    """
    loi: List[str] = []
    if fapp.get("officer_id") != off_a.get("id"):
        loi.append("F-APP không thuộc OFF-A — hồ sơ và persona đang nói về hai người")
    if lead is None:
        loi.append("F-APP: không đọc được lead để kiểm chủ sở hữu")
        return loi
    if getattr(lead, "assigned_officer_id", None) != off_a.get("id"):
        loi.append(
            f"F-APP: lead đang thuộc officer "
            f"{getattr(lead, 'assigned_officer_id', None)}, chờ OFF-A "
            f"({off_a.get('id')}) — hồ sơ đã bị chuyển người"
        )
    if getattr(lead, "unit_id", None) != off_a.get("unit"):
        loi.append(
            f"F-APP: lead ở đơn vị {getattr(lead, 'unit_id', None)}, chờ đơn vị "
            f"của OFF-A ({off_a.get('unit')})"
        )
    return loi


def tach_so(du_lieu: Dict[str, Any], run_id: str) -> Dict[str, Any]:
    """Tách `fixtures` và `_ACTOR` khỏi sổ — và DỪNG khi thiếu.

    Tách thành hàm thuần để kiểm được mà không cần DB: bản trước đọc thẳng
    `du["actor"]` trong khi sổ chỉ có `fixtures`, và lỗi ấy chỉ lộ ra lúc chạy
    thật với một database.
    """
    tat_ca = dict(du_lieu.get("fixtures") or {})
    actor = tat_ca.pop("_ACTOR", None)
    if not tat_ca:
        raise ChanLai(f"sổ của {run_id!r} chưa có fixture nào — seed trước đã")
    if not actor:
        raise ChanLai(
            f"sổ của {run_id!r} không có `_ACTOR`. Không có danh tính persona thì "
            "mọi phép kiểm actor dưới đây không canh gì cả."
        )
    # Đòi ĐỦ bộ vai, không phải ba cái tiện tay: OFF-A là chủ sở hữu hồ sơ F-APP,
    # nên thiếu nó thì phép kiểm "hồ sơ thuộc đúng officer" không có gì để so.
    thieu_vai = sorted(set(VAI_BAT_BUOC) - set(actor))
    if thieu_vai:
        raise ChanLai(f"sổ của {run_id!r} thiếu actor {thieu_vai}")
    for vai, tt in sorted(actor.items()):
        if not tt.get("role"):
            raise ChanLai(
                f"sổ của {run_id!r}: actor {vai!r} không ghi role — validator "
                "không đối chiếu được vai hiện tại"
            )
    return {"fixtures": tat_ca, "actor": actor}


async def _kiem_duong_tinh_phi_that(db, profile_id: int) -> Optional[str]:
    """Gọi ĐÚNG hai bước mà nút "Tính học phí" gọi. Trả `None` nếu đạt.

    Hai bước, cùng thứ tự với `calculate_fee` nhánh tuition:

        FeeCalculationService._get_profile   (eager-load: không MissingGreenlet)
        → resolve_fee_academic_info          (giải ngành)
        → _semester_tuition_amount_for_ai    (giá HK — nguồn giá THẬT)

    Vì sao không kiểm hộ bằng `tuition_fee_per_year`: xem chú thích tại chỗ gọi.
    Vì sao không gọi thẳng `preview_tuition`: nó gộp thêm phần ưu đãi, nên khi đỏ
    thì không tách được "thiếu giá" với "chính sách ưu đãi hỏng" — mà một ca kiểm
    gộp hai nguyên nhân thì không kết luận được gì. Hai bước trên đã đủ để tái
    hiện đúng lỗi 400 đã chặn FIN-03.

    KHÔNG ghi gì: chỉ SELECT. Caller giữ session; không commit ở đây.
    """
    from app.services.fee_calculation_service import (  # noqa: PLC0415
        FeeCalculationService,
        resolve_fee_academic_info,
    )

    svc = FeeCalculationService(db)
    hs = await svc._get_profile(profile_id, unit_id=None)
    if hs is None:
        return f"hồ sơ {profile_id} không còn"

    try:
        ai = await resolve_fee_academic_info(db, hs)
    except Exception as e:  # BadRequest và mọi thứ khác đều là "không tính được"
        return f"resolve_fee_academic_info từ chối: {type(e).__name__}: {e}"
    if ai is None:
        return "resolve_fee_academic_info trả None — không giải được ngành"

    try:
        tien = await svc._semester_tuition_amount_for_ai(ai.id, HOC_KY_TINH_PHI)
    except Exception as e:
        return (
            f"giải được ngành (academic_info={ai.id}) nhưng KHÔNG ra giá "
            f"HK{HOC_KY_TINH_PHI}: {type(e).__name__}: {e}"
        )
    if tien is None or Decimal(str(tien)) <= 0:
        return (
            f"giá HK{HOC_KY_TINH_PHI} của academic_info {ai.id} là {tien!r} — "
            "không dương thì hoá đơn ra 0 đồng và lượt smoke xanh giả"
        )
    return None


async def _kiem_so_khop_gia_hoc_ky(db, fx: Mapping[str, Any]) -> Optional[str]:
    """Sổ ↔ DB cho hàng giá học kỳ. Trả `None` nếu khớp.

    Oracle đọc `semester_amount` trong sổ để khai delta. Sổ ghi một số mà DB giữ
    số khác thì bản khai sai từ trước khi bấm — và cái sai ấy sẽ hiện ra dưới
    dạng "lệch" của một ca hoàn toàn lành.
    """
    ma_gia = fx.get("semester_tuition_id")
    if not ma_gia:
        return (
            "sổ không có semester_tuition_id — seeder cũ chỉ ghi "
            "tuition_fee_per_year, đúng trường KHÔNG phải nguồn giá của tuition"
        )
    ost = await db.get(models.OfferingSemesterTuition, ma_gia)
    if ost is None:
        return f"hàng giá học kỳ {ma_gia} trong sổ không còn trong DB"
    if ost.semester_no != fx.get("semester_no"):
        return (
            f"hàng giá {ma_gia}: semester_no DB={ost.semester_no} ≠ "
            f"sổ={fx.get('semester_no')!r}"
        )
    if Decimal(str(ost.amount)) != Decimal(str(fx.get("semester_amount"))):
        return (
            f"hàng giá {ma_gia}: amount DB={ost.amount} ≠ "
            f"sổ={fx.get('semester_amount')!r}"
        )
    ai_id = fx.get("academic_info_id")
    if ai_id is not None and ost.academic_info_id != ai_id:
        return (
            f"hàng giá {ma_gia} thuộc academic_info {ost.academic_info_id}, "
            f"còn sổ khai ngành {ai_id} — giá của ngành KHÁC"
        )
    return None


async def validate(run_id: str, thu_muc: Path) -> int:
    """Kiểm HÌNH DẠNG, không kiểm sự tồn tại. Trả số lỗi."""
    kiem_moi_truong(can_ghi=False)
    so = _so(thu_muc, run_id)
    du = tach_so(so.du_lieu, run_id)

    loi: List[str] = []
    bang: List[tuple] = []

    async with AsyncSessionLocal() as db:
        for ma, fx in du["fixtures"].items():
            # F-CALC — hình dạng đúng là "giải được ngành, và CHƯA có Fee
            # tuition". Hai vế phải cùng đúng: thiếu vế đầu thì `Tính học phí`
            # nổ BadRequest; thiếu vế sau thì thao tác chỉ đi đường recalculate.
            if fx.get("tinh_phi_duoc"):
                hs = await db.get(models.AdmissionProfile, fx["profile_id"])
                if hs is None:
                    loi.append(f"{ma}: hồ sơ {fx['profile_id']} không còn")
                    continue
                if hs.uses_choice_engine:
                    loi.append(
                        f"{ma}: uses_choice_engine=True — nhánh legacy của "
                        "resolve_fee_academic_info sẽ không chạy"
                    )
                oac_id = hs.offering_admission_config_id
                if not oac_id:
                    loi.append(
                        f"{ma}: offering_admission_config_id rỗng — đúng cái NULL "
                        "đã chặn FIN-03 ở BL20260817A"
                    )
                else:
                    oac = await db.get(models.OfferingAdmissionConfig, oac_id)
                    if oac is None:
                        loi.append(f"{ma}: OAC {oac_id} không tồn tại")
                    elif not oac.is_active:
                        loi.append(f"{ma}: OAC {oac_id} is_active=False")
                    else:
                        ai = await db.get(
                            models.OfferingAcademicInfo, oac.academic_info_id
                        )
                        if ai is None:
                            loi.append(
                                f"{ma}: OAC {oac_id} trỏ tới academic_info "
                                f"{oac.academic_info_id} không tồn tại"
                            )
                # ĐI ĐÚNG ĐƯỜNG THẬT, không kiểm hộ bằng một trường gần đúng.
                #
                # Bản đầu kết luận "tính phí được" từ `ai.tuition_fee_per_year is
                # not None`. Trường đó KHÔNG phải nguồn giá của tuition, nên nó
                # chứng nhận nhầm nguyên một fixture: `BL20260818A` seed xanh,
                # validator xanh, mà `preview_tuition` trả 400.
                #
                # Bốn phép kiểm cấu trúc phía trên vẫn giữ vì chúng cho thông báo
                # cụ thể; phép kiểm dưới đây mới là trọng tài.
                ly_do = await _kiem_duong_tinh_phi_that(db, fx["profile_id"])
                if ly_do:
                    loi.append(f"{ma}: {ly_do}")
                # Sổ nói một đằng, DB một nẻo thì oracle đọc sổ sẽ khai sai delta.
                ly_do_so = await _kiem_so_khop_gia_hoc_ky(db, fx)
                if ly_do_so:
                    loi.append(f"{ma}: {ly_do_so}")
                fee_tt = (
                    await db.execute(
                        select(Fee).where(
                            Fee.admission_profile_id == fx["profile_id"],
                            Fee.fee_type == FeeTypeEnum.tuition.value,
                        )
                    )
                ).scalars().all()
                if fee_tt:
                    loi.append(
                        f"{ma}: đã có {len(fee_tt)} Fee tuition dựng sẵn — FIN-03 là "
                        "ca TÍNH MỚI, có sẵn thì chỉ còn đo đường recalculate"
                    )
                bang.append(
                    (ma, f"profile={fx['profile_id']}", "tính phí được",
                     f"oac={oac_id}")
                )
                continue

            # F-CACHE — phải là fixture RIÊNG. Nếu profile_id của nó trùng bất kỳ
            # fixture nào khác thì ca FIN-07 không phân biệt được "cache cũ" với
            # "dữ liệu đã đổi từ ca trước".
            if fx.get("khong_dung_chung"):
                trung = [
                    m for m, f2 in du["fixtures"].items()
                    if m != ma and f2.get("profile_id") == fx["profile_id"]
                ]
                if trung:
                    loi.append(
                        f"{ma}: dùng CHUNG hồ sơ {fx['profile_id']} với {trung} — "
                        "fixture cache phải riêng"
                    )
                if fx.get("persona_doc") == fx.get("persona_ghi"):
                    loi.append(
                        f"{ma}: persona đọc và ghi trùng nhau "
                        f"({fx.get('persona_doc')!r}) — hệ chỉ cho MỘT phiên hoạt "
                        "động mỗi người dùng, hai phiên cùng tài khoản không dựng được"
                    )
                for vai in ("persona_doc", "persona_ghi"):
                    if fx.get(vai) not in du["actor"]:
                        loi.append(
                            f"{ma}: {vai}={fx.get(vai)!r} không có trong _ACTOR"
                        )

            # F-APP cố ý KHÔNG có Fee/Invoice dựng sẵn — hình dạng đúng của nó
            # là "hồ sơ có luật đòi lệ phí, và CHƯA có sổ nào".
            if fx.get("khong_co_fee_truoc"):
                hs = await db.get(models.AdmissionProfile, fx["profile_id"])
                if hs is None:
                    loi.append(f"{ma}: hồ sơ {fx['profile_id']} không còn")
                    continue
                rules = hs.applied_rules or {}
                if rules.get("requires_application_fee") is not True:
                    loi.append(f"{ma}: applied_rules thiếu requires_application_fee=true")
                if str(rules.get("fee_status")) != "pending":
                    loi.append(
                        f"{ma}: fee_status={rules.get('fee_status')!r}, cần 'pending' "
                        "— hồ sơ đã thu rồi thì ca FIN-02 không chứng minh được gì"
                    )
                so_fee = (
                    await db.execute(
                        select(Fee).where(Fee.admission_profile_id == fx["profile_id"])
                    )
                ).scalars().all()
                if so_fee:
                    loi.append(
                        f"{ma}: đã có {len(so_fee)} Fee cho hồ sơ này — đường thu lệ "
                        "phí tự tạo sổ, có sẵn là 409 'Inconsistent application fee ledger'"
                    )
                bang.append(
                    (ma, f"profile={fx['profile_id']}", "chưa có sổ",
                     f"{Decimal(fx['application_fee']):,.0f}")
                )
                continue

            fee = await db.get(Fee, fx["fee_id"])
            if fee is None:
                loi.append(f"{ma}: fee {fx['fee_id']} không còn")
                continue

            invs = []
            for iid in fx["invoice_ids"]:
                inv = await db.get(Invoice, iid)
                if inv is None:
                    loi.append(f"{ma}: invoice {iid} không còn")
                    continue
                invs.append(inv)
                con_no = Decimal(str(inv.amount)) - Decimal(str(inv.paid_amount))
                bang.append(
                    (ma, f"fee={fee.id} inv={inv.id}", f"{fee.status}/{inv.status}",
                     f"{con_no:,.0f}")
                )
                if ma != "F-IDOR-B" and inv.status not in ("issued", "partial"):
                    loi.append(
                        f"{ma}: invoice {inv.id} status={inv.status!r}, cần payable"
                    )
                if con_no <= 0:
                    loi.append(f"{ma}: invoice {inv.id} không còn nợ ({con_no})")

            if ma == "F-FIFO":
                if len(invs) < 2:
                    loi.append("F-FIFO: cần ít nhất HAI đợt payable")
                tong_no = sum(
                    Decimal(str(i.amount)) - Decimal(str(i.paid_amount)) for i in invs
                )
                if tong_no <= TIEN_DOT:
                    loi.append(
                        f"F-FIFO: tổng còn nợ {tong_no} không lớn hơn số sẽ thu "
                        f"{TIEN_DOT} — ca phân bổ sẽ không tách được đợt"
                    )

            if ma == "F-DUP":
                p = await db.get(Payment, fx["payment_ung_vien_id"])
                if p is None:
                    loi.append("F-DUP: phiếu ứng viên không còn")
                elif p.status != PaymentStatusEnum.pending.value:
                    loi.append(f"F-DUP: phiếu ứng viên status={p.status!r}, cần pending")
                elif Decimal(str(p.amount)) != TIEN_DUP:
                    loi.append(f"F-DUP: số tiền ứng viên {p.amount} ≠ {TIEN_DUP}")

            if ma == "F-IMPORT":
                lo = await db.get(PaymentImportBatch, fx["batch_id"])
                if lo is None or lo.status != PaymentImportBatchStatusEnum.preview.value:
                    loi.append("F-IMPORT: lô phải tồn tại và ở trạng thái preview")

        # Actor: BỐN tài khoản, đúng vai, ACC-A ≠ checker, ACC-B khác đơn vị,
        # và OFF-A phải là chủ sở hữu THẬT của hồ sơ F-APP.
        a, m, b = du["actor"]["ACC-A"], du["actor"]["MGR-A"], du["actor"]["ACC-B"]
        if a["id"] == m["id"]:
            loi.append("ACC-A và MGR-A là cùng một tài khoản")
        if a["unit"] != m["unit"]:
            loi.append("ACC-A và MGR-A không cùng đơn vị A")
        if b["unit"] == a["unit"]:
            loi.append("ACC-B không thuộc đơn vị khác")
        # Kiểm VAI HIỆN TẠI trên DB, không chỉ "còn active". Chú thích cũ nói
        # "đúng vai" trong khi mã chỉ kiểm status — một actor bị đổi vai giữa
        # seed và validate vẫn qua, và cả lượt smoke đo nhầm quyền.
        for nhan, info in sorted(du["actor"].items()):
            u = await db.get(models.User, info["id"])
            if u is None or u.status != "active":
                loi.append(f"{nhan}: tài khoản không còn active")
                continue
            cho = VAI_BAT_BUOC.get(nhan)
            if cho and u.role != cho:
                loi.append(f"{nhan}: role hiện tại {u.role!r}, chờ {cho!r}")
            if u.role != info.get("role"):
                loi.append(
                    f"{nhan}: role đã đổi kể từ lúc seed "
                    f"({info.get('role')!r} → {u.role!r})"
                )
            if u.unit_id != info.get("unit"):
                loi.append(f"{nhan}: đơn vị đã đổi kể từ lúc seed")

        o = du["actor"].get("OFF-A") or {}
        if o.get("unit") != a["unit"]:
            loi.append("OFF-A không cùng đơn vị A với ACC-A")

        fapp = du["fixtures"].get("F-APP") or {}
        ld = None
        if fapp.get("profile_id"):
            hs = await db.get(models.AdmissionProfile, fapp["profile_id"])
            if hs is None:
                loi.append("F-APP: hồ sơ không còn để kiểm chủ sở hữu")
            else:
                ld = await db.get(models.Lead, hs.lead_id)
        loi.extend(kiem_chu_so_huu(fapp, o, ld))

    print("\n  fixture              IDs                         status          còn nợ")
    print("  " + "-" * 74)
    for r in bang:
        print(f"  {r[0]:<20} {r[1]:<27} {r[2]:<15} {r[3]:>10}")

    if loi:
        print("\n  LỖI HÌNH DẠNG:", file=sys.stderr)
        for e in loi:
            print(f"    - {e}", file=sys.stderr)
    return len(loi)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", required=True)
    ap.add_argument(
        "--thu-muc", type=Path, required=True,
        help="gốc registry (cùng giá trị đã truyền cho `smoke_lib.cli --baseline`)",
    )
    ap.add_argument(
        "--persona", action="append", default=[], metavar="VAI=USERNAME",
        help="ghi đè persona cho một vai, lặp lại được (mặc định: smoke_*)",
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--seed", action="store_true")
    g.add_argument("--validate", action="store_true")
    ns = ap.parse_args()

    pers: Dict[str, str] = {}
    for mo in ns.persona:
        if "=" not in mo:
            print(f"--persona sai dạng: {mo!r}, cần VAI=USERNAME", file=sys.stderr)
            return 2
        vai, _, ten = mo.partition("=")
        vai = vai.strip().upper()
        if vai not in PERSONA_MAC_DINH:
            print(
                f"vai {vai!r} không có; chọn trong {sorted(PERSONA_MAC_DINH)}",
                file=sys.stderr,
            )
            return 2
        pers[vai] = ten.strip()

    async def _chay() -> int:
        # MỘT vòng lặp cho cả hai pha: `asyncio.run` lần thứ hai dựng loop mới
        # trong khi engine còn giữ connection của loop cũ → "Event loop is
        # closed" ngay ở lượt ping đầu tiên.
        if ns.seed:
            await seed(ns.run_id, ns.thu_muc, pers)
        return await validate(ns.run_id, ns.thu_muc)

    so_loi = asyncio.run(_chay())

    if so_loi:
        print(f"\n[FAIL] {so_loi} lỗi hình dạng fixture — BLOCK cả lượt", file=sys.stderr)
        return 3
    print("\n[OK] fixture đúng hình dạng")
    return 0


if __name__ == "__main__":
    sys.exit(main())
