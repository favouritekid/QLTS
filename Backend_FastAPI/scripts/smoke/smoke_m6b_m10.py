"""MỤC 6 (phần còn lại) · MỤC 10 — Refund & withdrawal.

6.6 tính lại khi hoá đơn đã phát hành (bằng ADMIN để chạm ĐÚNG guard)
6.7 fee draft: tính lại base → fee total và từng dòng cùng đổi
6.8 giảm tay qua nhiều vòng đổi base: approved bất biến, applied bị cap, cap về 0
    vẫn còn dòng audit, base tăng lại thì phục hồi
10  refund maker-checker + withdraw hồ sơ đang có tiền
"""
import asyncio
import json
from decimal import Decimal

from sqlalchemy import text

from app.database import AsyncSessionLocal
from smoke_lib import BASE, chay, ghi, tao_client, tien, tong_ket

SEED = json.load(open("/app/smoke_ids.json", encoding="utf-8"))
U, P, PM = SEED["users"], SEED["policies"], SEED["payment_methods"]
A = SEED["nganh_a"]


async def sql(q, **kw):
    async with AsyncSessionLocal() as s:
        res = await s.execute(text(q), kw)
        rows = res.mappings().all() if res.returns_rows else []
        await s.commit()
        return rows


async def _ho_so_sach(policy_ids=None, base="10000000"):
    """Hồ sơ CHƯA thu tiền ở BẤT KỲ ngành nào (ngành A đã cạn sau mục 5/6/9),
    rồi đặt giá + chính sách cho chính ngành của hồ sơ đó."""
    rows = await sql("""
        SELECT ap.id, (ap.applied_rules->>'academic_info_id')::int AS ai
        FROM admission_profile ap
        LEFT JOIN fee f ON f.admission_profile_id=ap.id AND f.fee_type='tuition'
             AND f.semester_no=1 AND f.status<>'cancelled'
        WHERE ap.status IN ('submitted','resubmitted','approved')
          AND (f.id IS NULL OR COALESCE(f.paid_amount,0)=0)
          AND ap.major_change_requested IS NOT TRUE
          AND (SELECT count(*) FROM admission_profile_choice c
               WHERE c.admission_profile_id=ap.id) <= 1
          AND EXISTS (SELECT 1 FROM offering_semester_tuition ost
                      WHERE ost.academic_info_id=(ap.applied_rules->>'academic_info_id')::int
                        AND ost.semester_no=1)
        ORDER BY ap.id DESC LIMIT 1
    """)
    assert rows, "hết hồ sơ sạch trên toàn bộ dữ liệu"
    hs, ai = rows[0]["id"], rows[0]["ai"]
    await sql("UPDATE invoice SET status='cancelled' WHERE fee_id IN "
              "(SELECT id FROM fee WHERE admission_profile_id=:p "
              " AND fee_type='tuition' AND semester_no=1)", p=hs)
    await sql("UPDATE fee SET status='cancelled' WHERE admission_profile_id=:p "
              "AND fee_type='tuition' AND semester_no=1", p=hs)
    await sql("UPDATE lead SET assigned_officer_id=:o WHERE id="
              "(SELECT lead_id FROM admission_profile WHERE id=:p)",
              o=U["OFFICER_A"]["id"], p=hs)
    await sql("UPDATE offering_academic_info SET applied_discount_policy_ids=:v "
              "WHERE id=:ai", v=json.dumps(policy_ids or []), ai=ai)
    await sql("UPDATE offering_semester_tuition SET amount=:b "
              "WHERE academic_info_id=:ai AND semester_no=1",
              b=Decimal(base), ai=ai)
    return hs


async def _dong(fee_id: int):
    return await sql("""
        SELECT policy_id,
               discount_amount,
               calculation_snapshot->>'approved_amount' AS duyet,
               calculation_snapshot->>'applied_amount' AS ap_dung,
               calculation_snapshot->>'capped_from' AS bi_cat
          FROM fee_applied_discount WHERE fee_id=:f
         ORDER BY application_order
    """, f=fee_id)


async def main():
    adm = await tao_client(U["ADMIN"]["username"])
    ac1 = await tao_client(U["ACCOUNTANT_1"]["username"])
    ac2 = await tao_client(U["ACCOUNTANT_2"]["username"])
    try:
        # ================= MỤC 6 phần còn lại =================
        hs = await _ho_so_sach(policy_ids=[P["P10"]], base="10000000")
        print(f"Hồ sơ mục 6b: #{hs}")

        r = await adm.post(f"{BASE}/api/fees/calculate", json={
            "admission_profile_id": hs, "fee_type": "tuition",
            "installment_plan_code": "FULL", "semester_no": 1})
        assert r.status_code == 201, r.text[:200]
        fee_id = r.json()["id"]

        # 6.6 — ADMIN tính lại khi hoá đơn ĐÃ phát hành
        r = await adm.post(f"{BASE}/api/fees/{fee_id}/recalculate",
                           params={"new_base_amount": "9000000", "reason": "smoke"})
        ghi("6.6", "ADMIN tính lại khi hoá đơn đã phát hành → chặn bởi guard "
                   "nghiệp vụ (không phải thiếu quyền)",
            r.status_code == 400 and "hủy hóa đơn" in r.text.lower(),
            f"HTTP {r.status_code} {r.text[:150]}")

        # 6.7 — đưa hoá đơn về draft rồi tính lại: dòng phải đổi theo
        await sql("UPDATE invoice SET status='draft' WHERE fee_id=:f", f=fee_id)
        r = await adm.post(f"{BASE}/api/fees/{fee_id}/recalculate",
                           params={"new_base_amount": "20000000",
                                   "reason": "smoke doi base"})
        st = (await sql("SELECT base_amount, total_discount, final_amount "
                        "FROM fee WHERE id=:f", f=fee_id))[0]
        dong = await _dong(fee_id)
        p10 = next((d for d in dong if d["policy_id"] == P["P10"]), None)
        ghi("6.7", "fee draft tính lại base 20tr → dòng P10 thành 2.000.000",
            r.status_code == 200 and tien(st["base_amount"]) == 20_000_000
            and p10 and tien(p10["discount_amount"]) == 2_000_000
            and tien(st["total_discount"]) == 2_000_000,
            f"HTTP {r.status_code} base={st['base_amount']} p10={p10 and p10['discount_amount']}")

        # 6.8 — giảm tay qua nhiều vòng
        hs2 = await _ho_so_sach(policy_ids=[], base="10000000")
        r = await adm.post(f"{BASE}/api/fees/calculate", json={
            "admission_profile_id": hs2, "fee_type": "tuition",
            "installment_plan_code": "FULL", "semester_no": 1,
            "discount_policy_ids": [],
            "target_final_amount": "9500000",
            "manual_discount_reason": "Giam tay smoke 500k theo quyet dinh"})
        assert r.status_code == 201, r.text[:200]
        fee2 = r.json()["id"]
        await sql("UPDATE invoice SET status='draft' WHERE fee_id=:f", f=fee2)
        d = (await _dong(fee2))[0]
        ghi("6.8a", "giảm tay ban đầu: duyệt 500.000",
            tien(d["duyet"] or d["discount_amount"]) == 500_000,
            f"duyệt={d['duyet']} áp={d['discount_amount']}")

        # base xuống dưới mức duyệt → phải CHẶN có chữ, KHÔNG được 500
        await sql("UPDATE invoice SET status='draft' WHERE fee_id=:f", f=fee2)
        r = await adm.post(f"{BASE}/api/fees/{fee2}/recalculate",
                           params={"new_base_amount": "300000", "reason": "ha base"})
        ghi("6.8b", "hạ base khiến phải thu = 0 → chặn 400 có chữ (KHÔNG 500)",
            r.status_code == 400 and "bằng 0" in r.text,
            f"HTTP {r.status_code} {r.text[:150]}")

        # base tăng lại 20tr → giảm tay vẫn đúng 500k (không bị bào mòn)
        await sql("UPDATE invoice SET status='draft' WHERE fee_id=:f", f=fee2)
        r = await adm.post(f"{BASE}/api/fees/{fee2}/recalculate",
                           params={"new_base_amount": "20000000", "reason": "tang base"})
        d = (await _dong(fee2))[0]
        ghi("6.8c", "base tăng lại → giảm tay giữ đúng 500.000",
            r.status_code == 200 and tien(d["duyet"]) == 500_000
            and tien(d["discount_amount"]) == 500_000 and not d["bi_cat"],
            f"HTTP {r.status_code} duyệt={d['duyet']} áp={d['discount_amount']}")

        # 6.8d — cap về 0 xảy ra ở luồng ĐỔI GIÁ HỌC KỲ (không qua recalculate):
        # dòng audit phải còn nguyên với mức duyệt.
        ai_fee2 = (await sql("""
            SELECT (ap.applied_rules->>'academic_info_id')::int AS ai
              FROM fee f JOIN admission_profile ap ON ap.id=f.admission_profile_id
             WHERE f.id=:f
        """, f=fee2))[0]["ai"]
        await sql("UPDATE invoice SET status='draft' WHERE fee_id=:f", f=fee2)
        await sql("UPDATE offering_semester_tuition SET amount=400000 "
                  "WHERE academic_info_id=:ai AND semester_no=1", ai=ai_fee2)
        from app.services.fee_calculation_service import (
            recalculate_fees_for_semester_tuition_change)
        async with AsyncSessionLocal() as s:
            n = await recalculate_fees_for_semester_tuition_change(s, ai_fee2)
            await s.commit()
        dong = await _dong(fee2)
        tay = [d for d in dong if d["policy_id"] is None]
        ghi("6.8d", "đổi giá học kỳ khiến phải-thu = 0 → BỎ QUA fee đó (có log), "
                    "KHÔNG vỡ 500 và KHÔNG mất dòng audit",
            n == 0 and len(tay) == 1 and tien(tay[0]["duyet"]) == 500_000,
            f"số fee đổi={n} số dòng tay={len(tay)} "
            + (f"duyệt={tay[0]['duyet']} áp={tay[0]['discount_amount']}" if tay else ""))

        # Đổi giá học kỳ xuống mức VẪN còn phải thu → dòng phải cập nhật đúng
        await sql("UPDATE offering_semester_tuition SET amount=3000000 "
                  "WHERE academic_info_id=:ai AND semester_no=1", ai=ai_fee2)
        async with AsyncSessionLocal() as s:
            n2 = await recalculate_fees_for_semester_tuition_change(s, ai_fee2)
            await s.commit()
        st2 = (await sql("SELECT base_amount, final_amount FROM fee WHERE id=:f",
                         f=fee2))[0]
        tay2 = [d for d in (await _dong(fee2)) if d["policy_id"] is None]
        ghi("6.8e", "đổi giá học kỳ xuống 3.000.000 → base đổi, giảm tay giữ 500.000",
            n2 == 1 and tien(st2["base_amount"]) == 3_000_000
            and tien(st2["final_amount"]) == 2_500_000
            and tien(tay2[0]["discount_amount"]) == 500_000,
            f"n={n2} base={st2['base_amount']} final={st2['final_amount']} "
            f"tay={tay2[0]['discount_amount'] if tay2 else None}")

        # ================= MỤC 10 — refund & withdrawal =================
        hs3 = await _ho_so_sach(policy_ids=[], base="10000000")
        r = await adm.post(f"{BASE}/api/fees/calculate", json={
            "admission_profile_id": hs3, "fee_type": "tuition",
            "installment_plan_code": "FULL", "semester_no": 1})
        assert r.status_code == 201, r.text[:200]
        fee3 = r.json()["id"]
        inv3 = (await sql("SELECT id FROM invoice WHERE fee_id=:f "
                          "AND status<>'cancelled'", f=fee3))[0]["id"]
        r = await ac1.post(f"{BASE}/api/payments", json={
            "invoice_id": inv3, "method_id": PM["cash"], "amount": "3000000"})
        pay3 = r.json()["id"]
        await ac2.put(f"{BASE}/api/payments/{pay3}/verify", json={})

        r = await ac1.post(f"{BASE}/api/refunds", json={
            "payment_id": pay3, "amount": "1000000",
            "reason": "Smoke hoan tien theo yeu cau thi sinh"})
        ok = r.status_code in (200, 201)
        ghi("10.1", "ACCOUNTANT_1 tạo yêu cầu hoàn 1.000.000", ok,
            f"HTTP {r.status_code} {r.text[:150]}")
        if ok:
            ref_id = r.json()["id"]
            r = await ac1.post(f"{BASE}/api/refunds/{ref_id}/approve", json={})
            ghi("10.2", "maker KHÔNG tự duyệt hoàn tiền được",
                r.status_code >= 400, f"HTTP {r.status_code} {r.text[:130]}")
            # Duyệt hoàn tiền là quyền QUẢN LÝ (kế toán chỉ tạo yêu cầu) —
            # dùng ADMIN, vẫn khác người tạo nên maker-checker được giữ.
            r = await adm.post(f"{BASE}/api/refunds/{ref_id}/approve", json={})
            ghi("10.3a", "người duyệt (khác maker) duyệt được hoàn tiền",
                r.status_code == 200,
                f"HTTP {r.status_code} {r.text[:130]}")

        # 10.5 withdraw hồ sơ đang có tiền
        ver = (await sql("SELECT version FROM admission_profile WHERE id=:p",
                         p=hs3))[0]["version"]
        r = await adm.post(f"{BASE}/api/admissions/{hs3}/withdraw",
                           json={"reason": "Smoke rut ho so co tien",
                                 "version": ver})
        st = (await sql("SELECT status FROM admission_profile WHERE id=:p",
                        p=hs3))[0]["status"]
        ghi("10.5a", "rút hồ sơ đang có tiền → vào luồng chờ hoàn",
            r.status_code in (200, 201) and st in
            ("withdrawal_pending", "withdrawn"),
            f"HTTP {r.status_code} status={st} {r.text[:120]}")

        r = await ac1.post(f"{BASE}/api/payments", json={
            "invoice_id": inv3, "method_id": PM["cash"], "amount": "100000"})
        ghi("10.5b", "không thu thêm được tiền vào hồ sơ đã rút",
            r.status_code >= 400, f"HTTP {r.status_code} {r.text[:130]}")

        con = (await sql("SELECT count(*) c FROM payment WHERE invoice_id=:i", i=inv3))[0]["c"]
        ghi("10.5c", "lịch sử payment/invoice KHÔNG bị xoá", con >= 1,
            f"số payment còn={con}")

    finally:
        for c in (adm, ac1, ac2):
            await c.aclose()

    return tong_ket("MỤC 6 (phần còn lại) + MỤC 10")


chay(main)
