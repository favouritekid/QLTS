"""MỤC 3 — hồ sơ đơn giản · MỤC 4 — revision/resubmit/reject · MỤC 8 — online & import lô."""
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
from decimal import Decimal

from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.config import settings
from smoke_lib import BASE, chay, doc_ids, ghi, tao_client, tien, tong_ket

RETURN_URL = f"{settings.FRONTEND_URL.rstrip(chr(47))}/finance/payments/return"

SEED = doc_ids()
U, P, PM = SEED["users"], SEED["policies"], SEED["payment_methods"]


async def sql(q, **kw):
    async with AsyncSessionLocal() as s:
        res = await s.execute(text(q), kw)
        rows = res.mappings().all() if res.returns_rows else []
        await s.commit()
        return rows


async def main():
    import time
    hau_to = str(int(time.time()))[-6:]
    adm = await tao_client(U["ADMIN"]["username"])
    mgr = await tao_client(U["MANAGER_A"]["username"])
    off = await tao_client(U["OFFICER_A"]["username"])
    ac1 = await tao_client(U["ACCOUNTANT_1"]["username"])
    ac2 = await tao_client(U["ACCOUNTANT_2"]["username"])
    try:
        # ================= MỤC 3 — hồ sơ đơn giản =================
        r = await off.post(f"{BASE}/api/leads", json={
            "full_name": f"Smoke Thi Sinh M3 {hau_to}",
            "phone": f"09{hau_to}88",
            "source": "smoke",
            "unit_id": SEED["unit_a"]["id"],
        })
        ok = r.status_code in (200, 201)
        ghi("3.1", "OFFICER tạo lead mới", ok, f"HTTP {r.status_code} {r.text[:140]}")
        lead_id = r.json().get("id") if ok else None

        if lead_id:
            await sql("UPDATE lead SET assigned_officer_id=:o WHERE id=:l",
                      o=U["OFFICER_A"]["id"], l=lead_id)
            # Lấy method + round từ một admission_path đang mở để chắc chắn hợp lệ.
            # Hồ sơ đòi lead ĐÃ chọn chương trình (offering) — gán offering của
            # chính ngành đang dùng cho smoke, rồi lấy method/round từ path đó.
            pth = (await sql("""
                SELECT ap.admission_method_id AS m, ap.admission_round_id AS r,
                       oai.offering_id AS off_id
                  FROM admission_path ap
                  JOIN offering_academic_info oai ON oai.id = ap.academic_info_id
                 WHERE ap.status='active' AND oai.id = :ai
                 ORDER BY ap.id DESC LIMIT 1
            """, ai=SEED["nganh_a"]["ai_id"]))[0]
            await sql("UPDATE lead SET offering_id=:o WHERE id=:l",
                      o=pth["off_id"], l=lead_id)
            # Quy tắc nghiệp vụ: lead phải có ít nhất một lần tư vấn trước khi
            # lập hồ sơ. Ghi thẳng một buổi tư vấn đã diễn ra cho lead smoke.
            await sql("""
                INSERT INTO consultation
                    (lead_id, consultation_date, method, notes, officer_id,
                     consultation_status_id, created_at)
                VALUES (:l, now(), 'phone', 'Smoke tu van lan 1', :o, 'sts06', now())
            """, l=lead_id, o=U["OFFICER_A"]["id"])
            r = await off.post(f"{BASE}/api/admissions", json={
                "lead_id": lead_id, "academic_year": 2026,
                "admission_method_id": pth["m"], "admission_round_id": pth["r"]})
            ok2 = r.status_code in (200, 201)
            ghi("3.2", "tạo hồ sơ draft từ lead", ok2,
                f"HTTP {r.status_code} {r.text[:150]}")
            hs_moi = r.json().get("id") if ok2 else None

            if hs_moi:
                # 3.4 submit khi thiếu giấy → phải chặn và NÊU giấy thiếu
                ver = (await sql("SELECT version FROM admission_profile WHERE id=:p",
                                 p=hs_moi))[0]["version"]
                r = await off.post(f"{BASE}/api/admissions/{hs_moi}/submit",
                                   json={"version": ver})
                noi_dung = r.text.lower()
                ghi("3.4", "submit thiếu điều kiện → bị chặn kèm lý do cụ thể",
                    r.status_code >= 400 and len(r.text) > 20,
                    f"HTTP {r.status_code} {r.text[:180]}")

                # 3.7 refresh: dữ liệu không mất
                r = await off.get(f"{BASE}/api/admissions/{hs_moi}")
                ghi("3.7", "đọc lại hồ sơ sau khi tạo → dữ liệu còn nguyên",
                    r.status_code == 200 and r.json()["lead_id"] == lead_id,
                    f"HTTP {r.status_code}")

        # ================= MỤC 4 — revision / resubmit / reject =================
        rows = await sql("""
            SELECT ap.id, ap.version FROM admission_profile ap
             JOIN lead l ON l.id=ap.lead_id
            WHERE ap.status='submitted' AND l.unit_id=:u
            ORDER BY ap.id DESC LIMIT 1
        """, u=SEED["unit_a"]["id"])
        if rows:
            hs4, ver4 = rows[0]["id"], rows[0]["version"]
            await sql("UPDATE lead SET assigned_officer_id=:o WHERE id="
                      "(SELECT lead_id FROM admission_profile WHERE id=:p)",
                      o=U["OFFICER_A"]["id"], p=hs4)
            r = await adm.post(f"{BASE}/api/admissions/{hs4}/request-revision",
                               json={"reason": "Smoke yeu cau sua ho so",
                                     "version": ver4})
            ok = r.status_code == 200
            ghi("4.1", "người có quyền yêu cầu sửa hồ sơ (có lý do)", ok,
                f"HTTP {r.status_code} {r.text[:150]}")

            if ok:
                # 4.3 history có actor + trạng thái cũ/mới + lý do
                h = await sql("""
                    SELECT from_status, to_status, transitioned_by_user_id AS actor,
                           actor_actual_role, transition_reason AS ly_do
                      FROM admission_profile_status_history
                     WHERE profile_id=:p ORDER BY id DESC LIMIT 1
                """, p=hs4)
                ghi("4.3", "history ghi đủ actor · trạng thái cũ/mới · lý do",
                    bool(h) and h[0]["actor"] and h[0]["from_status"]
                    and h[0]["to_status"] and h[0]["ly_do"],
                    str(dict(h[0])) if h else "không có history")

                # 4.4 resubmit bằng version CŨ → 409
                r = await off.post(f"{BASE}/api/admissions/{hs4}/resubmit",
                                   json={"version": ver4})
                ghi("4.4", "resubmit bằng version cũ → 409",
                    r.status_code == 409, f"HTTP {r.status_code} {r.text[:130]}")

        # 4.5 hồ sơ rejected: mọi đường thu tiền bị chặn
        rows = await sql("""
            SELECT f.id AS fee_id, i.id AS inv_id, ap.id AS hs
              FROM fee f JOIN invoice i ON i.fee_id=f.id
              JOIN admission_profile ap ON ap.id=f.admission_profile_id
             WHERE i.status IN ('issued','partial') AND f.status<>'cancelled'
               AND ap.status IN ('submitted','approved')
               AND f.awaiting_accountant_confirmation IS NOT TRUE
               AND (i.amount - COALESCE(i.paid_amount,0)) > 200000
             ORDER BY f.id DESC LIMIT 1
        """)
        if rows:
            hs5, inv5 = rows[0]["hs"], rows[0]["inv_id"]
            truoc = (await sql("SELECT status FROM admission_profile WHERE id=:p",
                               p=hs5))[0]["status"]
            await sql("UPDATE admission_profile SET status='rejected' WHERE id=:p",
                      p=hs5)
            r = await ac1.post(f"{BASE}/api/payments", json={
                "invoice_id": inv5, "method_id": PM["cash"], "amount": "100000"})
            ghi("4.5", "hồ sơ rejected → chặn thu tiền (đúng lý do hồ sơ, "
                        "không phải trạng thái hoá đơn)",
                r.status_code >= 400 and "rút/từ chối" in r.text,
                f"HTTP {r.status_code} {r.text[:150]}")
            await sql("UPDATE admission_profile SET status=:s WHERE id=:p",
                      s=truoc, p=hs5)

        # ================= MỤC 8 — online & import lô =================
        rows = await sql("""
            SELECT i.id AS inv_id, i.amount, i.paid_amount, f.id AS fee_id
              FROM invoice i JOIN fee f ON f.id=i.fee_id
              JOIN admission_profile ap ON ap.id=f.admission_profile_id
             WHERE i.status IN ('issued','partial') AND f.status<>'cancelled'
               AND f.awaiting_accountant_confirmation IS NOT TRUE
               AND ap.status NOT IN ('withdrawn','rejected','withdrawal_pending')
               AND (i.amount - COALESCE(i.paid_amount,0)) > 200000
             ORDER BY i.id DESC LIMIT 1
        """)
        if not rows:
            ghi("8.0", "tìm hoá đơn còn nợ để test online", False, "không có")
        else:
            inv8 = rows[0]["inv_id"]
            r = await ac1.post(f"{BASE}/api/payments/intents", json={
                "invoice_id": inv8, "method_id": PM["vnpay"], "amount": "100000",
                "idempotency_key": f"smoke-intent-{hau_to}",
                "return_url": RETURN_URL})
            ok = r.status_code in (200, 201)
            ghi("8.1a", "tạo payment intent hợp lệ", ok,
                f"HTTP {r.status_code} {r.text[:150]}")

            # 8.1b idempotency: cùng key → không tạo intent thứ hai
            r2 = await ac1.post(f"{BASE}/api/payments/intents", json={
                "invoice_id": inv8, "method_id": PM["vnpay"], "amount": "100000",
                "idempotency_key": f"smoke-intent-{hau_to}",
                "return_url": RETURN_URL})
            n = (await sql("SELECT count(*) c FROM payment_intent "
                           "WHERE idempotency_key=:k",
                           k=f"smoke-intent-{hau_to}"))[0]["c"]
            ghi("8.1b", "gửi lại cùng idempotency_key → KHÔNG tạo intent thứ hai",
                n == 1, f"số intent={n} HTTP2={r2.status_code}")

            # 8.3 callback sai chữ ký → từ chối, số dư không đổi
            truoc = (await sql("SELECT paid_amount FROM invoice WHERE id=:i",
                               i=inv8))[0]["paid_amount"]
            import httpx
            async with httpx.AsyncClient(timeout=60) as anon:
                rc = await anon.post(f"{BASE}/api/payments/callback/vnpay",
                                     json={"vnp_TxnRef": "SMOKE-FAKE",
                                           "vnp_Amount": "10000000",
                                           "vnp_ResponseCode": "00",
                                           "vnp_SecureHash": "sai-chu-ky"})
            sau = (await sql("SELECT paid_amount FROM invoice WHERE id=:i",
                             i=inv8))[0]["paid_amount"]
            ghi("8.3", "callback sai chữ ký → từ chối, số dư KHÔNG đổi",
                rc.status_code >= 400 and tien(truoc) == tien(sau),
                f"HTTP {rc.status_code} paid {truoc}→{sau}")

    finally:
        for c in (adm, mgr, off, ac1, ac2):
            await c.aclose()

    return tong_ket("MỤC 3 + 4 + 8")


chay(main)
