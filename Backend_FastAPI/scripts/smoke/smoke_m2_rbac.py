"""MỤC 2 — RBAC và IDOR (gate trước push).

Kiểm bằng API THẬT: token của từng vai, gọi thẳng endpoint, đối chiếu mã trả về.
UI ẩn nút chỉ là lớp trình bày; điều quyết định là server có chặn hay không.
"""
import os as _os
import sys as _sys

# Chạy được bằng `python scripts/smoke/<file>.py` từ bất kỳ thư mục nào: cần
# CẢ gốc dự án (để `import app`) LẪN thư mục này (để `import smoke_lib`).
_THU_MUC = _os.path.dirname(_os.path.abspath(__file__))
_GOC = _os.path.dirname(_os.path.dirname(_THU_MUC))
for _p in (_GOC, _THU_MUC):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import asyncio
import json

import httpx
from sqlalchemy import text

from app.database import AsyncSessionLocal
from smoke_lib import BASE, chay, doc_ids, ghi, tao_client, tong_ket

SEED = doc_ids()
U = SEED["users"]


async def _ho_so_cua_unit(unit_id: int) -> int:
    async with AsyncSessionLocal() as s:
        return (await s.execute(text("""
            SELECT ap.id FROM admission_profile ap
            JOIN lead l ON l.id = ap.lead_id
            WHERE l.unit_id = :u AND ap.status IN ('submitted','resubmitted','approved')
            ORDER BY ap.id DESC LIMIT 1
        """), {"u": unit_id})).scalar()


async def main():
    hs_a = await _ho_so_cua_unit(SEED["unit_a"]["id"])
    assert hs_a, "không tìm được hồ sơ ở đơn vị A"
    # Quyền của officer là 3 TẦNG: admin > manager (phạm vi đơn vị) > officer
    # (hồ sơ ĐƯỢC GIAO + trong đơn vị). Nên phải giao hồ sơ cho OFFICER_A đúng
    # như kịch bản mô tả ("Manager tạo lead, gán OFFICER_A") — nếu không, 404 mà
    # OFFICER_A nhận là ĐÚNG chứ không phải lỗi.
    async with AsyncSessionLocal() as s:
        await s.execute(text("""
            UPDATE lead SET assigned_officer_id = :off
             WHERE id = (SELECT lead_id FROM admission_profile WHERE id = :p)
        """), {"off": U["OFFICER_A"]["id"], "p": hs_a})
        await s.commit()
    print(f"Hồ sơ đơn vị A dùng để kiểm: #{hs_a} (đã giao OFFICER_A)")

    cl = {}
    try:
        for nhan in ("ADMIN", "MANAGER_A", "OFFICER_A", "OFFICER_B",
                     "ACCOUNTANT_1", "ACCOUNTANT_2", "CANDIDATE"):
            try:
                cl[nhan] = await tao_client(U[nhan]["username"])
                ghi("2.1", f"đăng nhập {nhan}", True)
            except Exception as e:
                ghi("2.1", f"đăng nhập {nhan}", False, repr(e)[:200])
        if len(cl) < 7:
            return tong_ket("MỤC 2 — RBAC/IDOR")

        # 2.2 OFFICER_A mở hồ sơ đơn vị mình
        r = await cl["OFFICER_A"].get(f"{BASE}/api/admissions/{hs_a}")
        ghi("2.2", "OFFICER_A xem hồ sơ đơn vị A", r.status_code == 200,
            f"HTTP {r.status_code}")

        # 2.3 OFFICER_B gọi thẳng API — phải 404, KHÔNG lộ tồn tại
        r = await cl["OFFICER_B"].get(f"{BASE}/api/admissions/{hs_a}")
        ghi("2.3", "OFFICER_B bị chặn (404, không lộ tồn tại)",
            r.status_code == 404, f"HTTP {r.status_code} :: {r.text[:120]}")

        # 2.4 Accountant không được duyệt hồ sơ / sửa nguyện vọng
        r = await cl["ACCOUNTANT_1"].post(f"{BASE}/api/admissions/{hs_a}/approve",
                         json={"reason": "smoke"})
        ghi("2.4a", "ACCOUNTANT không duyệt được hồ sơ",
            r.status_code in (401, 403, 404), f"HTTP {r.status_code}")
        r = await cl["ACCOUNTANT_1"].post(
            f"{BASE}/api/v2/admissions/{hs_a}/choices",
            json={"admission_path_id": 1, "display_order": 9})
        ghi("2.4b", "ACCOUNTANT không sửa được nguyện vọng",
            r.status_code in (401, 403, 404, 422), f"HTTP {r.status_code}")

        # 2.5 Officer không được xác nhận đổi ngành (việc của kế toán)
        async with AsyncSessionLocal() as s:
            fee_id = (await s.execute(text(
                "SELECT id FROM fee WHERE fee_type='tuition' AND semester_no=1 "
                "AND status <> 'cancelled' ORDER BY id DESC LIMIT 1"))).scalar()
        r = await cl["OFFICER_A"].put(f"{BASE}/api/fees/{fee_id}/confirm-major-change")
        ghi("2.5", "OFFICER không xác nhận đổi ngành được",
            r.status_code in (401, 403, 404), f"HTTP {r.status_code}")

        # 2.6 Candidate (role user) không vào được quản trị/tài chính
        r = await cl["CANDIDATE"].get(f"{BASE}/api/admin/tuition-discount-policies")
        ghi("2.6a", "CANDIDATE không xem được cấu hình ưu đãi",
            r.status_code in (401, 403), f"HTTP {r.status_code}")
        r = await cl["CANDIDATE"].get(f"{BASE}/api/fees")
        ghi("2.6b", "CANDIDATE không xem được danh sách phí",
            r.status_code in (401, 403), f"HTTP {r.status_code}")

        # 2.7 Admin xem được cả hai đơn vị
        hs_b = await _ho_so_cua_unit(SEED["unit_b"]["id"])
        r = await cl["ADMIN"].get(f"{BASE}/api/admissions/{hs_a}")
        ok_a = r.status_code == 200
        ok_b = True
        if hs_b:
            r2 = await cl["ADMIN"].get(f"{BASE}/api/admissions/{hs_b}")
            ok_b = r2.status_code == 200
        ghi("2.7", "ADMIN xem được hồ sơ mọi đơn vị", ok_a and ok_b,
            f"unitA={ok_a} unitB={ok_b if hs_b else 'không có hồ sơ ở B'}")

        # Không token → 401
        async with httpx.AsyncClient(timeout=60) as anon:
            r = await anon.get(f"{BASE}/api/admissions/{hs_a}")
        ghi("2.8", "không token → 401", r.status_code == 401,
            f"HTTP {r.status_code}")

    finally:
        for c in cl.values():
            await c.aclose()

    return tong_ket("MỤC 2 — RBAC/IDOR")


chay(main)
