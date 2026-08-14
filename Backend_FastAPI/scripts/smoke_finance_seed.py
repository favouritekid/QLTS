"""Seed + validator fixture cho Chrome smoke Finance (gói P1 — core collection).

Chạy TRONG container backend. Đây là công cụ PHÁ HOẠI dữ liệu: nó tạo hồ sơ,
khoản phí, hoá đơn và phiếu thu thật trong cơ sở dữ liệu được trỏ tới. Vì vậy
mọi hàng rào ở đây là fail-closed — thiếu một điều kiện thì thoát với mã khác 0
và KHÔNG chạm vào dữ liệu:

* ``APP_ENV`` không được là production;
* tên database phải khớp allowlist dev/test — không suy từ biến môi trường nào
  khác, không có giá trị mặc định;
* ``SMOKE_ALLOW_DESTRUCTIVE=1`` phải do người chạy đặt tường minh;
* URL/mật khẩu không có giá trị mặc định trong mã.

Hai chế độ:

  python scripts/smoke_finance_seed.py --run-id R1 --seed
  python scripts/smoke_finance_seed.py --run-id R1 --validate

``--validate`` đọc ``created-ids.json`` rồi kiểm lại HÌNH DẠNG của từng fixture
trên cơ sở dữ liệu và in bảng ``fixture -> IDs -> status -> amount``. Nó phải
thoát khác 0 khi bất kỳ điều kiện nào của §A05 sai — một validator luôn xanh
thì không khác gì không có validator.

Không tra cứu bản ghi theo TÊN học sinh: mọi id được ghi vào ``created-ids.json``
ngay lúc tạo, và mọi phép kiểm sau đó đi theo id.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, "/app")

from sqlalchemy import select, text  # noqa: E402

from app import models  # noqa: E402
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

#: Chỉ ba tên này. Không so khớp lỏng ("chứa chữ dev"), vì `qlts_production_dev_copy`
#: cũng chứa nó.
DB_CHO_PHEP = {"qlts_dev", "qlts_test", "qlts_smoke"}

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
    url = str(settings.DATABASE_URL)
    return url.rsplit("/", 1)[-1].split("?", 1)[0]


def kiem_moi_truong(can_ghi: bool) -> None:
    """Hai tầng: môi trường phải là dev/test, VÀ người chạy phải nói rõ ý định."""
    app_env = (getattr(settings, "APP_ENV", "") or "").lower()
    if app_env in {"production", "prod"}:
        raise ChanLai(f"APP_ENV={app_env!r} — tuyệt đối không chạy trên production")

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


def _duong_dan(run_id: str) -> Path:
    thu_muc = Path("/app/.smoke") / run_id
    thu_muc.mkdir(parents=True, exist_ok=True)
    return thu_muc / "created-ids.json"


def _ghi_atomic(duong: Path, du_lieu: Dict[str, Any]) -> None:
    """Ghi tạm rồi thay — nửa tệp id là thứ không cleanup được."""
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=duong.parent, delete=False, suffix=".tmp"
    ) as f:
        json.dump(du_lieu, f, ensure_ascii=False, indent=2, default=str)
        tam = Path(f.name)
    os.replace(tam, duong)


async def _actor(db, username: str) -> models.User:
    u = (
        await db.execute(select(models.User).where(models.User.username == username))
    ).scalars().first()
    if u is None:
        raise ChanLai(f"không tìm thấy tài khoản {username!r} trên DB này")
    if u.status != "active":
        raise ChanLai(f"tài khoản {username!r} có status={u.status!r}, phải là active")
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


async def seed(run_id: str) -> Dict[str, Any]:
    kiem_moi_truong(can_ghi=True)
    duong = _duong_dan(run_id)
    if duong.exists():
        raise ChanLai(
            f"{duong} đã tồn tại. Một RUN_ID chỉ seed MỘT lần; chạy lại sẽ tạo "
            "bản ghi mồ côi không ai cleanup. Dùng run-id mới hoặc cleanup trước."
        )

    async with AsyncSessionLocal() as db:
        acc_a = await _actor(db, "accountant01")
        mgr_a = await _actor(db, "manager01")
        acc_b = await _actor(db, "kpahdrim")
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
            "pack": "P1",
            "tao_luc": datetime.now(timezone.utc).isoformat(),
            "actor": {
                "ACC-A": {"id": acc_a.id, "username": acc_a.username, "unit": unit_a},
                "MGR-A": {"id": mgr_a.id, "username": mgr_a.username, "unit": mgr_a.unit_id},
                "ACC-B": {"id": acc_b.id, "username": acc_b.username, "unit": acc_b.unit_id},
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
        officer = (
            await db.execute(
                select(models.User).where(
                    models.User.role == "officer",
                    models.User.status == "active",
                    models.User.unit_id == unit_a,
                )
            )
        ).scalars().first()
        if officer is None:
            raise ChanLai(f"không có officer active nào ở đơn vị {unit_a}")
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

        # COMMIT trước, ghi registry sau: ghi trước mà commit hỏng thì tệp id
        # trỏ tới những bản ghi không tồn tại, và lượt cleanup sau sẽ đi tìm
        # chúng mãi. Ngược lại (commit xong, ghi hỏng) thì dữ liệu có thật và
        # lỗi nổ ra ngay tại đây, không âm thầm.
        await db.commit()
        _ghi_atomic(duong, kq)

    print(f"\n  đã ghi {duong}")
    return kq


async def validate(run_id: str) -> int:
    """Kiểm HÌNH DẠNG, không kiểm sự tồn tại. Trả số lỗi."""
    kiem_moi_truong(can_ghi=False)
    duong = _duong_dan(run_id)
    if not duong.exists():
        raise ChanLai(f"chưa có {duong} — seed trước đã")
    du = json.loads(duong.read_text(encoding="utf-8"))

    loi: List[str] = []
    bang: List[tuple] = []

    async with AsyncSessionLocal() as db:
        for ma, fx in du["fixtures"].items():
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

        # Actor: ba tài khoản, đúng vai, ACC-A ≠ checker, ACC-B khác đơn vị.
        a, m, b = du["actor"]["ACC-A"], du["actor"]["MGR-A"], du["actor"]["ACC-B"]
        if a["id"] == m["id"]:
            loi.append("ACC-A và MGR-A là cùng một tài khoản")
        if a["unit"] != m["unit"]:
            loi.append("ACC-A và MGR-A không cùng đơn vị A")
        if b["unit"] == a["unit"]:
            loi.append("ACC-B không thuộc đơn vị khác")
        for nhan, info in (("ACC-A", a), ("MGR-A", m), ("ACC-B", b)):
            u = await db.get(models.User, info["id"])
            if u is None or u.status != "active":
                loi.append(f"{nhan}: tài khoản không còn active")

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
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--seed", action="store_true")
    g.add_argument("--validate", action="store_true")
    ns = ap.parse_args()

    async def _chay() -> int:
        # MỘT vòng lặp cho cả hai pha: `asyncio.run` lần thứ hai dựng loop mới
        # trong khi engine còn giữ connection của loop cũ → "Event loop is
        # closed" ngay ở lượt ping đầu tiên.
        if ns.seed:
            await seed(ns.run_id)
        return await validate(ns.run_id)

    so_loi = asyncio.run(_chay())

    if so_loi:
        print(f"\n[FAIL] {so_loi} lỗi hình dạng fixture — BLOCK cả lượt", file=sys.stderr)
        return 3
    print("\n[OK] fixture đúng hình dạng")
    return 0


if __name__ == "__main__":
    sys.exit(main())
