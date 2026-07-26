"""MỤC 6 — Tính phí & hoá đơn · MỤC 7 — Maker–checker thanh toán."""
import asyncio
import json
from decimal import Decimal

from sqlalchemy import text

from app.database import AsyncSessionLocal
from smoke_lib import BASE, tao_client, ghi, tien, tong_ket

SEED = json.load(open("/app/smoke_ids.json", encoding="utf-8"))
U, P = SEED["users"], SEED["policies"]
AI_A = SEED["nganh_a"]["ai_id"]
PM = SEED["payment_methods"]


async def sql(q, **kw):
    """Chạy SQL; trả rows nếu là SELECT, [] nếu là UPDATE/INSERT."""
    async with AsyncSessionLocal() as s:
        res = await s.execute(text(q), kw)
        rows = res.mappings().all() if res.returns_rows else []
        await s.commit()
        return rows


async def _chuan_bi() -> int:
    """Hồ sơ ngành A sạch (chưa thu tiền), fee HK1 cũ bị huỷ."""
    async with AsyncSessionLocal() as s:
        pid = (await s.execute(text("""
            SELECT ap.id FROM admission_profile ap
            LEFT JOIN fee f ON f.admission_profile_id = ap.id
             AND f.fee_type='tuition' AND f.semester_no=1 AND f.status<>'cancelled'
            WHERE (ap.applied_rules->>'academic_info_id')::int = :ai
              AND ap.status IN ('submitted','resubmitted','approved')
              AND (f.id IS NULL OR COALESCE(f.paid_amount,0)=0)
              AND (SELECT count(*) FROM admission_profile_choice c
                   WHERE c.admission_profile_id = ap.id) <= 1
            ORDER BY ap.id DESC LIMIT 1
        """), {"ai": AI_A})).scalar()
        assert pid, "không còn hồ sơ sạch cho mục 6"
        await s.execute(text("""
            UPDATE invoice SET status='cancelled' WHERE fee_id IN (
                SELECT id FROM fee WHERE admission_profile_id=:p
                 AND fee_type='tuition' AND semester_no=1)
        """), {"p": pid})
        await s.execute(text("""
            UPDATE fee SET status='cancelled' WHERE admission_profile_id=:p
             AND fee_type='tuition' AND semester_no=1
        """), {"p": pid})
        await s.execute(text("""
            UPDATE lead SET assigned_officer_id=:o
             WHERE id=(SELECT lead_id FROM admission_profile WHERE id=:p)
        """), {"o": U["OFFICER_A"]["id"], "p": pid})
        await s.execute(text(
            "UPDATE offering_academic_info SET applied_discount_policy_ids=:v "
            "WHERE id=:ai"), {"v": json.dumps([P["P10"], P["P500"]]), "ai": AI_A})
        await s.execute(text(
            "UPDATE offering_semester_tuition SET amount=10000000 "
            "WHERE academic_info_id=:ai AND semester_no=1"), {"ai": AI_A})
        await s.commit()
    return pid


async def _bat_bien_fee(fee_id: int, nhan: str):
    rows = await sql("""
        SELECT f.base_amount, f.total_discount, f.final_amount, f.waived_amount,
               f.paid_amount,
               (SELECT COALESCE(SUM(d.discount_amount),0) FROM fee_applied_discount d
                 WHERE d.fee_id=f.id) AS tong_dong,
               (SELECT COALESCE(SUM(i.amount),0) FROM invoice i
                 WHERE i.fee_id=f.id AND i.status<>'cancelled') AS tong_hd
          FROM fee f WHERE f.id=:f
    """, f=fee_id)
    r = rows[0]
    ghi(nhan, "final = base − Σ dòng giảm",
        tien(r["final_amount"]) == tien(r["base_amount"]) - tien(r["tong_dong"]),
        f"base={r['base_amount']} Σdòng={r['tong_dong']} final={r['final_amount']}")
    ghi(nhan, "Σ hoá đơn active = final − waived",
        tien(r["tong_hd"]) == tien(r["final_amount"]) - tien(r["waived_amount"]),
        f"Σhđ={r['tong_hd']} final={r['final_amount']} waived={r['waived_amount']}")
    return r


async def main():
    hs = await _chuan_bi()
    print(f"Hồ sơ mục 6/7: #{hs}")
    off = await tao_client(U["OFFICER_A"]["username"])
    ac1 = await tao_client(U["ACCOUNTANT_1"]["username"])
    ac2 = await tao_client(U["ACCOUNTANT_2"]["username"])
    try:
        # ---------- 6.1 tính phí ----------
        r = await off.post(f"{BASE}/api/fees/calculate", json={
            "admission_profile_id": hs, "fee_type": "tuition",
            "installment_plan_code": "FULL", "semester_no": 1})
        ok = r.status_code == 201
        ghi("6.1", "OFFICER tính phí HK1", ok, f"HTTP {r.status_code} {r.text[:140]}")
        if not ok:
            return tong_ket("MỤC 6/7")
        fee = r.json()
        fee_id = fee["id"]
        ghi("6.1b", "final = 8.500.000 (10tr − 10% − 500k)",
            tien(fee["final_amount"]) == 8_500_000, f"final={fee['final_amount']}")

        # ---------- 6.2 bất biến ----------
        await _bat_bien_fee(fee_id, "6.2")

        # ---------- 6.3 selected_by ----------
        rows = await sql("""
            SELECT policy_id, calculation_snapshot->>'selected_by' AS ai_chon
              FROM fee_applied_discount WHERE fee_id=:f ORDER BY application_order
        """, f=fee_id)
        # Không truyền discount_policy_ids ⇒ áp mặc định ⇒ KHÔNG có selected_by.
        ghi("6.3a", "áp mặc định thì KHÔNG đóng dấu selected_by",
            all(r["ai_chon"] is None for r in rows),
            str([(r["policy_id"], r["ai_chon"]) for r in rows]))

        # ---------- 6.4 duplicate ----------
        r = await off.post(f"{BASE}/api/fees/calculate", json={
            "admission_profile_id": hs, "fee_type": "tuition",
            "installment_plan_code": "FULL", "semester_no": 1})
        n = (await sql("SELECT count(*) c FROM fee WHERE admission_profile_id=:p "
                       "AND fee_type='tuition' AND semester_no=1 AND status<>'cancelled'",
                       p=hs))[0]["c"]
        ghi("6.4", "tính phí lần hai bị chặn, không tạo fee thứ hai",
            r.status_code == 400 and n == 1, f"HTTP {r.status_code} sốfee={n}")

        # ---------- 6.6 tính lại khi hoá đơn đã phát hành ----------
        inv = (await sql("SELECT id, status FROM invoice WHERE fee_id=:f "
                         "AND status<>'cancelled' ORDER BY id", f=fee_id))
        ghi("6.5", "hoá đơn được phát hành cùng lúc tính phí (tuition auto-issue)",
            len(inv) == 1 and inv[0]["status"] in ("issued", "partial", "paid"),
            str([(i["id"], i["status"]) for i in inv]))
        r = await off.post(f"{BASE}/api/fees/{fee_id}/recalculate",
                           params={"new_base_amount": "9000000", "reason": "smoke"})
        ghi("6.6", "tính lại khi hoá đơn đã phát hành → bị chặn",
            r.status_code in (400, 403), f"HTTP {r.status_code} {r.text[:120]}")

        # ---------- 7. maker–checker ----------
        r = await ac1.post(f"{BASE}/api/payments", json={
            "invoice_id": inv[0]["id"], "method_id": PM["cash"],
            "amount": "4000000", "notes": "smoke maker"})
        ok = r.status_code in (200, 201)
        pay = r.json() if ok else {}
        ghi("7.1", "ACCOUNTANT_1 ghi nhận 4.000.000 → pending",
            ok and pay.get("status") == "pending",
            f"HTTP {r.status_code} status={pay.get('status')} {r.text[:120] if not ok else ''}")
        if not ok:
            return tong_ket("MỤC 6/7")
        pay_id = pay["id"]

        r = await ac1.put(f"{BASE}/api/payments/{pay_id}/verify", json={})
        ghi("7.2", "maker KHÔNG tự verify được (self-approval)",
            r.status_code in (400, 403), f"HTTP {r.status_code} {r.text[:120]}")

        r = await ac2.put(f"{BASE}/api/payments/{pay_id}/verify", json={})
        ghi("7.3", "ACCOUNTANT_2 verify thành công", r.status_code == 200,
            f"HTTP {r.status_code} {r.text[:140]}")

        st = (await sql("""
            SELECT p.status AS pay, p.recognized_major_id, i.status AS inv,
                   i.paid_amount AS inv_paid, f.paid_amount AS fee_paid, f.status AS fee
              FROM payment p JOIN invoice i ON i.id=p.invoice_id
              JOIN fee f ON f.id=i.fee_id WHERE p.id=:x
        """, x=pay_id))[0]
        ghi("7.3b", "payment verified · invoice partial · fee paid=4.000.000",
            st["pay"] == "verified" and st["inv"] == "partial"
            and tien(st["fee_paid"]) == 4_000_000,
            f"pay={st['pay']} inv={st['inv']} fee_paid={st['fee_paid']}")
        ghi("7.3c", "recognized_major_id = ngành A",
            st["recognized_major_id"] == SEED["nganh_a"]["major_id"],
            f"got={st['recognized_major_id']} mong={SEED['nganh_a']['major_id']}")

        r = await ac2.put(f"{BASE}/api/payments/{pay_id}/verify", json={})
        ghi("7.4", "verify lần hai bị chặn (idempotent)",
            r.status_code in (400, 409), f"HTTP {r.status_code}")

        # 7.6 trả vượt remaining
        con_lai = 8_500_000 - 4_000_000
        r = await ac1.post(f"{BASE}/api/payments", json={
            "invoice_id": inv[0]["id"], "method_id": PM["cash"],
            "amount": str(con_lai + 1_000_000), "notes": "smoke vuot"})
        vuot_bi_chan = r.status_code >= 400
        if not vuot_bi_chan:  # nếu cho ghi thì phải chặn ở verify
            rid = r.json()["id"]
            rv = await ac2.put(f"{BASE}/api/payments/{rid}/verify", json={})
            vuot_bi_chan = rv.status_code >= 400
            await sql("UPDATE payment SET status='rejected' WHERE id=:i", i=rid)
        ghi("7.6", "trả vượt số còn lại bị chặn", vuot_bi_chan,
            f"HTTP {r.status_code} {r.text[:120]}")

        # 7.5 trả đủ phần còn lại
        r = await ac1.post(f"{BASE}/api/payments", json={
            "invoice_id": inv[0]["id"], "method_id": PM["cash"],
            "amount": str(con_lai), "notes": "smoke tra du"})
        ok = r.status_code in (200, 201)
        if ok:
            rid = r.json()["id"]
            rv = await ac2.put(f"{BASE}/api/payments/{rid}/verify", json={})
            ok = rv.status_code == 200
        st = (await sql("""
            SELECT i.status AS inv, f.status AS fee, f.paid_amount, f.final_amount
              FROM invoice i JOIN fee f ON f.id=i.fee_id WHERE i.id=:i
        """, i=inv[0]["id"]))[0]
        ghi("7.5", "trả đủ → invoice paid, fee settled, paid = final",
            ok and st["inv"] == "paid" and tien(st["paid_amount"]) == tien(st["final_amount"]),
            f"inv={st['inv']} fee={st['fee']} paid={st['paid_amount']}/{st['final_amount']}")

        await _bat_bien_fee(fee_id, "7.7")

    finally:
        for c in (off, ac1, ac2):
            await c.aclose()

    return tong_ket("MỤC 6/7 — Tính phí & Maker-checker")


asyncio.run(main())
