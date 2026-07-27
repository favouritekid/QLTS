"""MỤC 5 — Preview ưu đãi (gate trước push).

Bảy ca theo kịch bản + bất biến "Σ số tiền từng dòng == total_discount".
"""
import asyncio
import json
from decimal import Decimal

from sqlalchemy import text

from app.database import AsyncSessionLocal
from smoke_lib import BASE, chay, ghi, tao_client, tien, tong_ket

SEED = json.load(open("/app/smoke_ids.json", encoding="utf-8"))
U, P = SEED["users"], SEED["policies"]
AI_A = SEED["nganh_a"]["ai_id"]


async def _gan_policy(ai_id: int, ids: list):
    async with AsyncSessionLocal() as s:
        await s.execute(text(
            "UPDATE offering_academic_info SET applied_discount_policy_ids = :v "
            "WHERE id = :ai"), {"v": json.dumps(ids), "ai": ai_id})
        await s.commit()


async def _doi_hk1(ai_id: int, amount: str):
    async with AsyncSessionLocal() as s:
        await s.execute(text(
            "UPDATE offering_semester_tuition SET amount = :a "
            "WHERE academic_info_id = :ai AND semester_no = 1"),
            {"a": Decimal(amount), "ai": ai_id})
        await s.commit()


async def _bat_tat_policy(pid: int, active: bool):
    async with AsyncSessionLocal() as s:
        await s.execute(text(
            "UPDATE tuition_discount_policy SET is_active = :a WHERE id = :p"),
            {"a": active, "p": pid})
        await s.commit()


async def _ho_so_tinh_phi_duoc() -> int:
    """Hồ sơ ngành A, đủ điều kiện tính phí, CHƯA có học phí HK1."""
    async with AsyncSessionLocal() as s:
        pid = (await s.execute(text("""
            SELECT ap.id FROM admission_profile ap
            JOIN lead l ON l.id = ap.lead_id
            WHERE (ap.applied_rules->>'academic_info_id')::int = :ai
              AND ap.status IN ('submitted','resubmitted','approved')
              AND NOT EXISTS (SELECT 1 FROM fee f WHERE f.admission_profile_id=ap.id
                              AND f.fee_type='tuition' AND f.semester_no=1
                              AND f.status <> 'cancelled')
              AND (SELECT count(*) FROM admission_profile_choice c
                   WHERE c.admission_profile_id = ap.id) <= 1
            ORDER BY ap.id DESC LIMIT 1
        """), {"ai": AI_A})).scalar()
        if not pid:
            # Dev-DB: mọi hồ sơ ngành A đã có học phí HK1. Chọn một hồ sơ CHƯA
            # THU ĐỒNG NÀO rồi huỷ khoản phí cũ để có điểm xuất phát sạch —
            # thao tác trên BẢN SAO dev, không đụng dữ liệu gốc.
            pid = (await s.execute(text("""
                SELECT ap.id FROM admission_profile ap
                JOIN fee f ON f.admission_profile_id = ap.id
                 AND f.fee_type='tuition' AND f.semester_no=1 AND f.status<>'cancelled'
                WHERE (ap.applied_rules->>'academic_info_id')::int = :ai
                  AND ap.status IN ('submitted','resubmitted','approved')
                  AND COALESCE(f.paid_amount,0) = 0
                  AND (SELECT count(*) FROM admission_profile_choice c
                       WHERE c.admission_profile_id = ap.id) <= 1
                ORDER BY ap.id DESC LIMIT 1
            """), {"ai": AI_A})).scalar()
            if pid:
                await s.execute(text("""
                    UPDATE invoice SET status='cancelled'
                     WHERE fee_id IN (SELECT id FROM fee
                                       WHERE admission_profile_id=:p
                                         AND fee_type='tuition' AND semester_no=1)
                """), {"p": pid})
                await s.execute(text("""
                    UPDATE fee SET status='cancelled'
                     WHERE admission_profile_id=:p AND fee_type='tuition'
                       AND semester_no=1
                """), {"p": pid})
        if pid:
            await s.execute(text("""
                UPDATE lead SET assigned_officer_id = :o
                 WHERE id = (SELECT lead_id FROM admission_profile WHERE id = :p)
            """), {"o": U["OFFICER_A"]["id"], "p": pid})
            await s.commit()
        return pid


def _bat_bien_tong_dong(body: dict) -> tuple:
    tong_dong = sum(tien(o["amount"]) for o in body["discount_policies"])
    return tong_dong == tien(body["total_discount"]), tong_dong


async def main():
    hs = await _ho_so_tinh_phi_duoc()
    assert hs, "không tìm được hồ sơ ngành A đủ điều kiện tính phí"
    print(f"Hồ sơ dùng cho mục 5: #{hs} (ngành A, ai={AI_A})")

    off = await tao_client(U["OFFICER_A"]["username"])
    adm = await tao_client(U["ADMIN"]["username"])
    try:
        async def preview(ids=None, tuong_minh=False):
            params = {"admission_profile_id": hs, "semester_no": 1}
            if tuong_minh:
                params["explicit_discount_selection"] = "true"
                if ids:
                    params["discount_policy_ids"] = ids
            r = await off.get(f"{BASE}/api/fees/tuition-preview", params=params)
            assert r.status_code == 200, f"preview {r.status_code}: {r.text[:200]}"
            return r.json()

        # ---- 5.1 mặc định P10 + P500 trên base 10tr ----
        await _gan_policy(AI_A, [P["P10"], P["P500"]])
        await _doi_hk1(AI_A, "10000000")
        b = await preview()
        ok = (tien(b["base_amount"]) == 10_000_000
              and tien(b["total_discount"]) == 1_500_000
              and tien(b["final_amount"]) == 8_500_000)
        ghi("5.1", "mặc định P10+P500 → giảm 1.500.000, final 8.500.000", ok,
            f"base={b['base_amount']} giam={b['total_discount']} final={b['final_amount']}")
        bb, tong = _bat_bien_tong_dong(b)
        ghi("5.1-BB", "Σ dòng == total_discount", bb, f"Σ={tong}")

        # ---- 5.2 lựa chọn tường minh rỗng ----
        b = await preview(ids=None, tuong_minh=True)
        ok = (tien(b["total_discount"]) == 0
              and tien(b["final_amount"]) == 10_000_000)
        ghi("5.2", "chọn tường minh [] → giảm 0, final 10.000.000", ok,
            f"giam={b['total_discount']} final={b['final_amount']}")

        # ---- 5.3 N-HIGH + P10 → chỉ N-HIGH ----
        await _gan_policy(AI_A, [P["N_HIGH"], P["P10"]])
        b = await preview(ids=[P["N_HIGH"], P["P10"]], tuong_minh=True)
        opts = {o["id"]: o for o in b["discount_policies"]}
        ok = (tien(b["total_discount"]) == 2_000_000
              and tien(b["final_amount"]) == 8_000_000
              and opts[P["N_HIGH"]]["applied"] is True
              and opts[P["P10"]]["applied"] is False
              and opts[P["P10"]]["reason_text"])
        ghi("5.3", "N-HIGH + P10 → chỉ N-HIGH, P10 có lý do bị chặn", ok,
            f"final={b['final_amount']} P10_reason={opts[P['P10']].get('reason')}")
        bb, tong = _bat_bien_tong_dong(b)
        ghi("5.3-BB", "Σ dòng == total_discount", bb, f"Σ={tong}")

        # ---- 5.4 P10 + N-LOW → chỉ P10 ----
        await _gan_policy(AI_A, [P["P10"], P["N_LOW"]])
        b = await preview(ids=[P["P10"], P["N_LOW"]], tuong_minh=True)
        opts = {o["id"]: o for o in b["discount_policies"]}
        ok = (tien(b["total_discount"]) == 1_000_000
              and tien(b["final_amount"]) == 9_000_000
              and opts[P["P10"]]["applied"] is True
              and opts[P["N_LOW"]]["applied"] is False)
        ghi("5.4", "P10 + N-LOW → chỉ P10 (final 9.000.000)", ok,
            f"final={b['final_amount']} NLOW_reason={opts[P['N_LOW']].get('reason')}")
        bb, tong = _bat_bien_tong_dong(b)
        ghi("5.4-BB", "Σ dòng == total_discount", bb, f"Σ={tong}")

        # ---- 5.5 base 1tr, ưu đãi 800k + 500k → 800k + 200k ----
        async with AsyncSessionLocal() as s:
            await s.execute(text(
                "UPDATE tuition_discount_policy SET discount_type='amount', "
                "discount_value=800000, is_stackable=true, priority=10 WHERE id=:p"),
                {"p": P["N_HIGH"]})
            await s.execute(text(
                "UPDATE tuition_discount_policy SET discount_type='amount', "
                "discount_value=500000, is_stackable=true, priority=1 WHERE id=:p"),
                {"p": P["N_LOW"]})
            await s.commit()
        await _gan_policy(AI_A, [P["N_HIGH"], P["N_LOW"]])
        await _doi_hk1(AI_A, "1000000")
        b = await preview()
        opts = {o["id"]: o for o in b["discount_policies"]}
        ok = (tien(opts[P["N_HIGH"]]["amount"]) == 800_000
              and tien(opts[P["N_LOW"]]["amount"]) == 200_000
              and tien(b["total_discount"]) == 1_000_000)
        ghi("5.5", "base 1tr + 800k/500k → dòng 800.000 và 200.000", ok,
            f"lon={opts[P['N_HIGH']]['amount']} nho={opts[P['N_LOW']]['amount']} "
            f"tong={b['total_discount']}")
        bb, tong = _bat_bien_tong_dong(b)
        ghi("5.5-BB", "Σ dòng == total_discount", bb, f"Σ={tong}")

        # ---- 5.6 preview cũ + admin tắt policy → tính phí phải 400 ----
        await _doi_hk1(AI_A, "10000000")
        await _gan_policy(AI_A, [P["P10"], P["P500"]])
        b = await preview()  # người dùng "đang xem" preview
        await _bat_tat_policy(P["P10"], False)  # admin tắt giữa chừng
        r = await off.post(f"{BASE}/api/fees/calculate", json={
            "admission_profile_id": hs, "fee_type": "tuition",
            "installment_plan_code": "FULL", "semester_no": 1,
            "discount_policy_ids": [P["P10"], P["P500"]],
        })
        detail = (r.json() or {}).get("detail", "") if r.headers.get(
            "content-type", "").startswith("application/json") else r.text
        ok = (r.status_code == 400 and "ngừng hoạt động" in str(detail)
              and "tải lại" in str(detail))
        ghi("5.6", "policy vừa bị tắt → 400 kèm lý do tiếng Việt + yêu cầu tải lại",
            ok, f"HTTP {r.status_code} :: {str(detail)[:160]}")
        await _bat_tat_policy(P["P10"], True)

        # ---- 5.7 bỏ tích toàn bộ rồi tính → khớp preview không giảm ----
        b_rong = await preview(ids=None, tuong_minh=True)
        r = await off.post(f"{BASE}/api/fees/calculate", json={
            "admission_profile_id": hs, "fee_type": "tuition",
            "installment_plan_code": "FULL", "semester_no": 1,
            "discount_policy_ids": [],
        })
        ok = r.status_code == 201
        if ok:
            fee = r.json()
            ok = (tien(fee["total_discount"]) == tien(b_rong["total_discount"]) == 0
                  and tien(fee["final_amount"]) == tien(b_rong["final_amount"]))
        ghi("5.7", "bỏ tích toàn bộ → phí tạo ra khớp preview không giảm", ok,
            f"HTTP {r.status_code} :: {r.text[:160] if not ok else ''}")

        # dọn: huỷ fee vừa tạo để mục 6 bắt đầu sạch
        if r.status_code == 201:
            async with AsyncSessionLocal() as s:
                await s.execute(text(
                    "UPDATE invoice SET status='cancelled' WHERE fee_id=:f"),
                    {"f": r.json()["id"]})
                await s.execute(text(
                    "UPDATE fee SET status='cancelled' WHERE id=:f"),
                    {"f": r.json()["id"]})
                await s.commit()

    finally:
        await off.aclose()
        await adm.aclose()

    return tong_ket("MỤC 5 — Preview ưu đãi")


chay(main)
