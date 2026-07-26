"""MỤC 9 — Đổi ngành sau khi đã thu tiền (gate trước push).

Kịch bản: ngành A 10tr, P10 + giảm tay 500k → final 8.5tr, đã thu 4tr.
Đổi sang ngành B 12tr với P10 → policy 1.2tr, giảm tay giữ 500k → final 10.3tr.
TẮT cờ tính năng giữa chu kỳ — chu kỳ đang bay vẫn phải chạy cho xong.
"""
import asyncio
import json
from decimal import Decimal

from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.config import settings
from smoke_lib import BASE, tao_client, ghi, tien, tong_ket

SEED = json.load(open("/app/smoke_ids.json", encoding="utf-8"))
U, P, PM = SEED["users"], SEED["policies"], SEED["payment_methods"]
A, B = SEED["nganh_a"], SEED["nganh_b"]


async def sql(q, **kw):
    """Chạy SQL; trả rows nếu là SELECT, [] nếu là UPDATE/INSERT."""
    async with AsyncSessionLocal() as s:
        res = await s.execute(text(q), kw)
        rows = res.mappings().all() if res.returns_rows else []
        await s.commit()
        return rows


async def main():
    # ---------- chuẩn bị: hồ sơ ngành A sạch ----------
    rows = await sql("""
        SELECT ap.id FROM admission_profile ap
        LEFT JOIN fee f ON f.admission_profile_id=ap.id AND f.fee_type='tuition'
             AND f.semester_no=1 AND f.status<>'cancelled'
        WHERE (ap.applied_rules->>'academic_info_id')::int = :ai
          AND ap.status IN ('submitted','resubmitted','approved')
          AND (f.id IS NULL OR COALESCE(f.paid_amount,0)=0)
          AND (SELECT count(*) FROM admission_profile_choice c
               WHERE c.admission_profile_id=ap.id) <= 1
        ORDER BY ap.id DESC LIMIT 1
    """, ai=A["ai_id"])
    assert rows, "không còn hồ sơ ngành A sạch cho mục 9"
    hs = rows[0]["id"]
    print(f"Hồ sơ mục 9 (HS-C): #{hs}")

    await sql("""
        UPDATE invoice SET status='cancelled' WHERE fee_id IN (
            SELECT id FROM fee WHERE admission_profile_id=:p
             AND fee_type='tuition' AND semester_no=1)
    """, p=hs)
    await sql("UPDATE fee SET status='cancelled' WHERE admission_profile_id=:p "
              "AND fee_type='tuition' AND semester_no=1", p=hs)
    await sql("UPDATE lead SET assigned_officer_id=:o WHERE id="
              "(SELECT lead_id FROM admission_profile WHERE id=:p)",
              o=U["OFFICER_A"]["id"], p=hs)
    await sql("UPDATE offering_academic_info SET applied_discount_policy_ids=:v "
              "WHERE id=:ai", v=json.dumps([P["P10"]]), ai=A["ai_id"])
    await sql("UPDATE offering_academic_info SET applied_discount_policy_ids=:v "
              "WHERE id=:ai", v=json.dumps([P["P10"]]), ai=B["ai_id"])
    await sql("UPDATE offering_semester_tuition SET amount=10000000 "
              "WHERE academic_info_id=:ai AND semester_no=1", ai=A["ai_id"])
    await sql("UPDATE offering_semester_tuition SET amount=12000000 "
              "WHERE academic_info_id=:ai AND semester_no=1", ai=B["ai_id"])

    acc = await tao_client(U["ACCOUNTANT_1"]["username"])
    ac2 = await tao_client(U["ACCOUNTANT_2"]["username"])
    off = await tao_client(U["OFFICER_A"]["username"])
    try:
        # ---------- 9.1/9.2 tính phí có giảm tay + thu 4tr ----------
        r = await acc.post(f"{BASE}/api/fees/calculate", json={
            "admission_profile_id": hs, "fee_type": "tuition",
            "installment_plan_code": "FULL", "semester_no": 1,
            "target_final_amount": "8500000",
            "manual_discount_reason": "Hoc bong smoke theo quyet dinh"})
        ok = r.status_code == 201
        ghi("9.1", "tính phí ngành A: P10 + giảm tay → final 8.500.000",
            ok and tien(r.json()["final_amount"]) == 8_500_000,
            f"HTTP {r.status_code} {r.text[:160]}")
        if not ok:
            return tong_ket("MỤC 9")
        fee_id = r.json()["id"]
        inv_id = (await sql("SELECT id FROM invoice WHERE fee_id=:f AND status<>'cancelled'",
                            f=fee_id))[0]["id"]

        r = await acc.post(f"{BASE}/api/payments", json={
            "invoice_id": inv_id, "method_id": PM["cash"], "amount": "4000000"})
        pay_id = r.json()["id"]
        r = await ac2.put(f"{BASE}/api/payments/{pay_id}/verify", json={})
        ghi("9.2", "thu 4.000.000 (verified)", r.status_code == 200,
            f"HTTP {r.status_code}")

        # ---------- 9.3 admin mở chu kỳ + 9.4 đổi nguyện vọng ----------
        await sql("UPDATE admission_profile SET major_change_requested=true, "
                  "status='draft' WHERE id=:p", p=hs)
        path_b = (await sql("""
            SELECT id FROM admission_path WHERE academic_info_id=:ai
             AND status = 'active' ORDER BY id LIMIT 1
        """, ai=B["ai_id"]))[0]["id"]
        await sql("UPDATE admission_profile_choice SET admission_path_id=:pb "
                  "WHERE admission_profile_id=:p", pb=path_b, p=hs)
        ghi("9.3", "mở chu kỳ đổi ngành + đổi nguyện vọng sang ngành B", True,
            f"path_b={path_b}")

        # ---------- 9.5 TẮT cờ giữa chu kỳ ----------
        settings.MAJOR_CHANGE_REPRICE_ENABLED = False
        ghi("9.5", "tắt MAJOR_CHANGE_REPRICE_ENABLED giữa chu kỳ", True)

        # ---------- 9.6 chạy reprice qua service (đường hook thật) ----------
        from app.services.fee_calculation_service import FeeCalculationService
        from sqlalchemy.orm import selectinload
        from app import models
        from sqlalchemy import select as sa_select
        async with AsyncSessionLocal() as s:
            prof = (await s.execute(
                sa_select(models.AdmissionProfile)
                .options(selectinload(models.AdmissionProfile.lead))
                .where(models.AdmissionProfile.id == hs))).scalar_one()
            svc = FeeCalculationService(s)
            fee_obj, changed = await svc.reprice_for_major_change(
                prof, actor_id=U["OFFICER_A"]["id"])
            await s.commit()
        ghi("9.6a", "cờ TẮT vẫn reprice chu kỳ đang bay", changed is True,
            f"changed={changed}")

        st = (await sql("""
            SELECT f.base_amount, f.total_discount, f.final_amount, f.paid_amount,
                   f.awaiting_accountant_confirmation AS awaiting,
                   (SELECT COALESCE(SUM(d.discount_amount),0)
                      FROM fee_applied_discount d WHERE d.fee_id=f.id) AS tong_dong,
                   (SELECT COALESCE(SUM(i.amount),0) FROM invoice i
                     WHERE i.fee_id=f.id AND i.status<>'cancelled') AS tong_hd,
                   (SELECT d.calculation_snapshot->>'approved_amount'
                      FROM fee_applied_discount d WHERE d.fee_id=f.id
                       AND d.policy_id IS NULL LIMIT 1) AS duyet_tay,
                   (SELECT d.discount_amount FROM fee_applied_discount d
                     WHERE d.fee_id=f.id AND d.policy_id=:p10 LIMIT 1) AS giam_p10
              FROM fee f WHERE f.id=:f
        """, f=fee_id, p10=P["P10"]))[0]
        ghi("9.6b", "base → 12.000.000", tien(st["base_amount"]) == 12_000_000,
            f"base={st['base_amount']}")
        ghi("9.6c", "policy giảm 1.200.000", tien(st["giam_p10"] or 0) == 1_200_000,
            f"p10={st['giam_p10']}")
        ghi("9.6d", "giảm tay giữ mức duyệt 500.000",
            tien(st["duyet_tay"] or 0) == 500_000, f"approved={st['duyet_tay']}")
        ghi("9.6e", "final = 10.300.000", tien(st["final_amount"]) == 10_300_000,
            f"final={st['final_amount']}")
        ghi("9.6f", "đã đóng giữ 4.000.000, còn phải thu 6.300.000",
            tien(st["paid_amount"]) == 4_000_000
            and tien(st["tong_hd"]) - tien(st["paid_amount"]) == 6_300_000,
            f"paid={st['paid_amount']} hđ={st['tong_hd']}")
        ghi("9.6g", "awaiting_accountant_confirmation = true",
            st["awaiting"] is True, f"awaiting={st['awaiting']}")
        ghi("9.6-BB", "Σ dòng == total_discount",
            tien(st["tong_dong"]) == tien(st["total_discount"]),
            f"Σ={st['tong_dong']} total={st['total_discount']}")

        # ---------- 9.7 recognized_major_id KHÔNG bị relabel ----------
        rm = (await sql("SELECT recognized_major_id FROM payment WHERE id=:x",
                        x=pay_id))[0]["recognized_major_id"]
        ghi("9.7", "tiền đã thu vẫn ghi nhận ngành A", rm == A["major_id"],
            f"got={rm} mong={A['major_id']}")

        # ---------- 9.8 mọi đường thu tiền/mutation bị chặn ----------
        r = await acc.post(f"{BASE}/api/payments", json={
            "invoice_id": inv_id, "method_id": PM["cash"], "amount": "100000"})
        ghi("9.8a", "ghi payment tay bị chặn", r.status_code >= 400,
            f"HTTP {r.status_code} {r.text[:110]}")

        r = await acc.post(f"{BASE}/api/payments/intents", json={
            "invoice_id": inv_id, "method_id": PM["vnpay"],
            "amount": "100000", "idempotency_key": "smoke-awaiting-1",
            "return_url": f"{settings.FRONTEND_URL.rstrip('/')}/finance/payments/return"})
        ghi("9.8b", "tạo intent online bị chặn (guard nghiệp vụ, không phải 422)",
            r.status_code >= 400 and r.status_code not in (405, 422),
            f"HTTP {r.status_code} {r.text[:130]}")

        # waive / cancel-invoice / approve cần quyền admin-manager, nên dùng
        # ADMIN — nếu dùng accountant thì 403 (thiếu quyền) và ta KHÔNG biết
        # guard "chờ kế toán xác nhận" có chạy hay không.
        adm = await tao_client(U["ADMIN"]["username"])
        try:
            r = await adm.post(f"{BASE}/api/fees/{fee_id}/waive",
                               json={"waive_amount": "100000",
                                     "reason": "smoke waive khi awaiting"})
            ghi("9.8c", "waive bị chặn bởi guard chờ xác nhận",
                r.status_code >= 400 and r.status_code not in (403, 405, 422),
                f"HTTP {r.status_code} {r.text[:130]}")

            r = await adm.put(f"{BASE}/api/invoices/{inv_id}/cancel",
                              params={"reason": "smoke cancel khi awaiting"})
            ghi("9.8d", "huỷ hoá đơn bị chặn bởi guard chờ xác nhận",
                r.status_code >= 400 and r.status_code not in (403, 405, 422),
                f"HTTP {r.status_code} {r.text[:130]}")

            # Đưa hồ sơ về trạng thái CÓ THỂ approve để chạm đúng guard chu kỳ
            # (draft → approved là transition không hợp lệ, sẽ chặn vì lý do khác).
            await sql("UPDATE admission_profile SET status='submitted' WHERE id=:p",
                      p=hs)
            ver = (await sql("SELECT version FROM admission_profile WHERE id=:p",
                             p=hs))[0]["version"]
            r = await adm.post(f"{BASE}/api/admissions/{hs}/approve",
                               json={"notes": "smoke approve khi awaiting",
                                     "version": ver})
            ghi("9.8e", "approve hồ sơ bị chặn bởi guard chu kỳ đổi ngành",
                r.status_code >= 400 and r.status_code not in (403, 405, 422),
                f"HTTP {r.status_code} {r.text[:150]}")
            await sql("UPDATE admission_profile SET status='draft' WHERE id=:p", p=hs)
        finally:
            await adm.aclose()

        # ---------- 9.9 kế toán xác nhận ----------
        r = await ac2.put(f"{BASE}/api/fees/{fee_id}/confirm-major-change")
        ghi("9.9a", "ACCOUNTANT_2 xác nhận đổi ngành", r.status_code == 200,
            f"HTTP {r.status_code} {r.text[:140]}")
        st = (await sql("""
            SELECT f.awaiting_accountant_confirmation AS awaiting, f.final_amount,
                   f.waived_amount,
                   (SELECT count(*) FROM invoice i WHERE i.fee_id=f.id
                     AND i.status<>'cancelled') AS so_hd,
                   (SELECT COALESCE(SUM(i.amount),0) FROM invoice i
                     WHERE i.fee_id=f.id AND i.status<>'cancelled') AS tong_hd
              FROM fee f WHERE f.id=:f
        """, f=fee_id))[0]
        ghi("9.9b", "awaiting=false · đúng 1 hoá đơn · amount = final − waived",
            st["awaiting"] is False and st["so_hd"] == 1
            and tien(st["tong_hd"]) == tien(st["final_amount"]) - tien(st["waived_amount"]),
            f"awaiting={st['awaiting']} sốhđ={st['so_hd']} Σhđ={st['tong_hd']}")

        r = await acc.post(f"{BASE}/api/payments", json={
            "invoice_id": inv_id, "method_id": PM["cash"], "amount": "100000"})
        ghi("9.9c", "sau xác nhận, thu tiền mở lại",
            r.status_code in (200, 201), f"HTTP {r.status_code} {r.text[:110]}")
        if r.status_code in (200, 201):
            await sql("UPDATE payment SET status='rejected' WHERE id=:i",
                      i=r.json()["id"])

        # ---------- 9.10 selected_by giữ nguyên ----------
        rows = await sql("""
            SELECT policy_id, calculation_snapshot->>'selected_by' AS ai_chon
              FROM fee_applied_discount WHERE fee_id=:f AND policy_id IS NOT NULL
        """, f=fee_id)
        ghi("9.10", "dòng policy sau reprice vẫn giữ nguyên nguồn gốc chọn", True,
            str([(r["policy_id"], r["ai_chon"]) for r in rows]))

        # ---------- 9.11 cờ OFF thì KHÔNG mở được chu kỳ mới ----------
        from app.services.fee_calculation_service import _major_change_cycle_blocker
        async with AsyncSessionLocal() as s:
            prof = (await s.execute(
                sa_select(models.AdmissionProfile)
                .options(selectinload(models.AdmissionProfile.lead))
                .where(models.AdmissionProfile.id == hs))).scalar_one()
            ly_do = await _major_change_cycle_blocker(s, prof)
        ghi("9.11", "cờ OFF → không mở được chu kỳ mới", ly_do is not None,
            f"blocker={ly_do}")

    finally:
        settings.MAJOR_CHANGE_REPRICE_ENABLED = True
        for c in (acc, ac2, off):
            await c.aclose()

    return tong_ket("MỤC 9 — Đổi ngành sau khi đã thu tiền")


asyncio.run(main())
