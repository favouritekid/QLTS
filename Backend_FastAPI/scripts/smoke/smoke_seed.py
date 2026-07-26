"""Seed dữ liệu cho kịch bản smoke Admission–Finance.

Chạy TRONG container backend của stack smoke:
    docker compose -p qlts-mc -f docker-compose.yml -f docker-compose.smoke.yml \
        run --rm --no-deps --entrypoint python backend /app/../smoke_seed.py

In ra JSON các id cần cho các bước sau.
"""
import asyncio
import json
from decimal import Decimal

from sqlalchemy import select, text

from app.database import AsyncSessionLocal
from app import models
from app.models.finance import InstallmentPlan, PaymentMethod
from app.models.tuition_discount_policy import TuitionDiscountPolicy
from app.security import get_password_hash

PW = "Test@12345"


async def _user(s, username, role, unit_id, full_name):
    u = (await s.execute(
        select(models.User).where(models.User.username == username)
    )).scalar_one_or_none()
    if u is None:
        u = models.User(username=username, email=f"{username}@smoke.test")
        s.add(u)
    u.password_hash = get_password_hash(PW)
    u.role = role
    u.status = "active"
    u.full_name = full_name
    u.unit_id = unit_id
    u.mfa_enabled = False
    u.totp_secret_encrypted = None
    await s.flush()
    return u


async def _policy(s, code, name, dtype, value, stackable, priority, **kw):
    p = (await s.execute(
        select(TuitionDiscountPolicy).where(TuitionDiscountPolicy.code == code)
    )).scalar_one_or_none()
    if p is None:
        p = TuitionDiscountPolicy(code=code)
        s.add(p)
    p.name = name
    p.discount_type = dtype
    p.discount_value = Decimal(value)
    p.is_stackable = stackable
    p.priority = priority
    p.is_active = kw.get("is_active", True)
    p.valid_from = kw.get("valid_from")
    p.valid_to = kw.get("valid_to")
    p.applicable_scope = {"all_programs": True, "is_heavy_only": False}
    p.target_criteria = {}
    p.max_usage = None
    p.current_usage = 0
    await s.flush()
    return p


async def main():
    out = {}
    async with AsyncSessionLocal() as s:
        # ---------- Đơn vị A / B ----------
        # Đơn vị A = nơi lead/hồ sơ thật nằm (IDOR xét theo ``lead.unit_id``),
        # đơn vị B = một đơn vị khác để kiểm chặn chéo.
        units = (await s.execute(
            select(models.OrganizationUnit).order_by(models.OrganizationUnit.id)
        )).scalars().all()
        by_id = {u.id: u for u in units}
        unit_a = by_id.get(14) or units[0]
        unit_b = by_id.get(15) or next(u for u in units if u.id != unit_a.id)
        out["unit_a"] = {"id": unit_a.id, "name": unit_a.name}
        out["unit_b"] = {"id": unit_b.id, "name": unit_b.name}

        # ---------- Tài khoản ----------
        accounts = {
            "ADMIN": ("smoke_admin", "admin", unit_a.id, "Smoke Admin"),
            "MANAGER_A": ("smoke_manager_a", "manager", unit_a.id, "Smoke Manager A"),
            "OFFICER_A": ("smoke_officer_a", "officer", unit_a.id, "Smoke Officer A"),
            "OFFICER_B": ("smoke_officer_b", "officer", unit_b.id, "Smoke Officer B"),
            "ACCOUNTANT_1": ("smoke_acc_1", "accountant", unit_a.id, "Smoke Accountant 1"),
            "ACCOUNTANT_2": ("smoke_acc_2", "accountant", unit_a.id, "Smoke Accountant 2"),
            "CANDIDATE": ("smoke_candidate", "user", unit_a.id, "Smoke Candidate"),
        }
        out["users"] = {}
        for label, (username, role, unit_id, full_name) in accounts.items():
            u = await _user(s, username, role, unit_id, full_name)
            out["users"][label] = {"id": u.id, "username": username, "role": role,
                                   "unit_id": unit_id}

        # ---------- Ngành A / B (dùng academic_info sẵn có của unit A) ----------
        # Ngành KHÔNG cần cùng đơn vị với hồ sơ — quyền xem hồ sơ xét theo
        # ``lead.unit_id``, còn ngành thuộc khoa chuyên môn.
        # Chọn ngành có SẴN hồ sơ CHƯA THU ĐỒNG NÀO — kịch bản cần tính phí từ
        # đầu, mà dev-DB hầu hết hồ sơ đã thu một phần. Ưu tiên ngành nhiều hồ
        # sơ sạch nhất để các mục sau còn hồ sơ mà dùng.
        rows = (await s.execute(text("""
            SELECT oai.id AS ai_id, mp.id AS major_id, mp.name AS nganh,
                   po.id AS offering_id,
                   count(*) FILTER (
                       WHERE f.id IS NULL OR COALESCE(f.paid_amount, 0) = 0
                   ) AS ho_so_sach
            FROM offering_academic_info oai
            JOIN program_offering po ON po.id = oai.offering_id
            JOIN major_program mp ON mp.id = po.program_id
            JOIN admission_profile ap
              ON (ap.applied_rules->>'academic_info_id')::int = oai.id
             AND ap.status IN ('submitted', 'resubmitted', 'approved')
             AND (SELECT count(*) FROM admission_profile_choice c
                  WHERE c.admission_profile_id = ap.id) <= 1
            LEFT JOIN fee f ON f.admission_profile_id = ap.id
             AND f.fee_type = 'tuition' AND f.semester_no = 1
             AND f.status <> 'cancelled'
            WHERE EXISTS (SELECT 1 FROM admission_path pth
                          WHERE pth.academic_info_id = oai.id)
              AND EXISTS (SELECT 1 FROM offering_semester_tuition ost
                          WHERE ost.academic_info_id = oai.id AND ost.semester_no = 1)
            GROUP BY oai.id, mp.id, mp.name, po.id
            HAVING count(*) FILTER (
                       WHERE f.id IS NULL OR COALESCE(f.paid_amount, 0) = 0
                   ) >= 2
            ORDER BY ho_so_sach DESC
            LIMIT 2
        """))).mappings().all()
        assert len(rows) >= 2, f"Cần >=2 ngành có hồ sơ sạch, có {len(rows)}"
        ai_a, ai_b = rows[0], rows[1]

        for ai, amount in ((ai_a, "10000000"), (ai_b, "12000000")):
            await s.execute(text("""
                UPDATE offering_semester_tuition SET amount = :amt
                 WHERE academic_info_id = :ai AND semester_no = 1
            """), {"amt": Decimal(amount), "ai": ai["ai_id"]})
            n = (await s.execute(text("""
                SELECT count(*) FROM offering_semester_tuition
                 WHERE academic_info_id = :ai AND semester_no = 1
            """), {"ai": ai["ai_id"]})).scalar()
            if not n:
                await s.execute(text("""
                    INSERT INTO offering_semester_tuition
                        (academic_info_id, semester_no, amount, created_at, updated_at)
                    VALUES (:ai, 1, :amt, now(), now())
                """), {"ai": ai["ai_id"], "amt": Decimal(amount)})

        out["nganh_a"] = {"ai_id": ai_a["ai_id"], "major_id": ai_a["major_id"],
                          "ten": ai_a["nganh"], "hk1": 10000000}
        out["nganh_b"] = {"ai_id": ai_b["ai_id"], "major_id": ai_b["major_id"],
                          "ten": ai_b["nganh"], "hk1": 12000000}

        # ---------- Chính sách ----------
        from datetime import date
        p10 = await _policy(s, "SMK_P10", "P10 giam 10%", "percentage", "10", True, 5)
        p500 = await _policy(s, "SMK_P500", "P500 giam 500k", "amount", "500000", True, 4)
        nhigh = await _policy(s, "SMK_NHIGH", "N-HIGH 2tr khong cong don",
                              "amount", "2000000", False, 90)
        nlow = await _policy(s, "SMK_NLOW", "N-LOW 2tr khong cong don",
                             "amount", "2000000", False, 1)
        expired = await _policy(s, "SMK_EXPIRED", "EXPIRED het han",
                                "amount", "300000", True, 3,
                                valid_to=date(2026, 6, 30))
        out["policies"] = {"P10": p10.id, "P500": p500.id, "N_HIGH": nhigh.id,
                           "N_LOW": nlow.id, "EXPIRED": expired.id}

        # Gắn P10 + P500 cho ngành A (mặc định kịch bản mục 5.1)
        await s.execute(text("""
            UPDATE offering_academic_info
               SET applied_discount_policy_ids = :ids
             WHERE id = :ai
        """), {"ids": json.dumps([p10.id, p500.id]), "ai": ai_a["ai_id"]})
        # Ngành B: P10 (để mục 9 có policy 1.200.000 trên base 12tr)
        await s.execute(text("""
            UPDATE offering_academic_info
               SET applied_discount_policy_ids = :ids
             WHERE id = :ai
        """), {"ids": json.dumps([p10.id]), "ai": ai_b["ai_id"]})

        # ---------- Phương thức thanh toán ----------
        out["payment_methods"] = {}
        for code, name, online in (("cash", "Tien mat", False),
                                   ("vnpay", "VNPay online", True)):
            m = (await s.execute(
                select(PaymentMethod).where(PaymentMethod.code == code)
            )).scalar_one_or_none()
            if m is None:
                m = PaymentMethod(code=code)
                s.add(m)
            m.name = name
            m.is_online = online
            m.is_active = True
            m.requires_verification = not online
            await s.flush()
            out["payment_methods"][code] = m.id

        # ---------- Kế hoạch trả góp 2 đợt ----------
        plan = (await s.execute(
            select(InstallmentPlan).where(InstallmentPlan.code == "SMK_TWO")
        )).scalar_one_or_none()
        if plan is None:
            plan = InstallmentPlan(code="SMK_TWO")
            s.add(plan)
        plan.name = "Smoke 2 dot"
        plan.installment_count = 2
        plan.schedule = [
            {"installment_no": 1, "percent": 50.0, "due_days_offset": 0},
            {"installment_no": 2, "percent": 50.0, "due_days_offset": 30},
        ]
        plan.is_active = True
        await s.flush()
        out["installment_plan"] = {"id": plan.id, "code": "SMK_TWO"}

        await s.commit()

    print("SEED_JSON_START")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("SEED_JSON_END")


asyncio.run(main())
