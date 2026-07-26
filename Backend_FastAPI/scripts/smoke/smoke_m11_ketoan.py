"""MỤC 11 — Accounting & báo cáo (gate trước push).

Trong CÙNG một kỳ: payment +5.000.000, reversal −2.000.000, refund −1.000.000.
Kỳ vọng: Tổng thu 3.000.000 · Tổng hoàn 1.000.000 · Net 2.000.000.
Điểm mấu chốt: reversal KHÔNG được xuất hiện dưới nhãn "Tổng hoàn".
"""
import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import text

from app.database import AsyncSessionLocal
from smoke_lib import ghi, tien, tong_ket

SEED = json.load(open("/app/smoke_ids.json", encoding="utf-8"))
A = SEED["nganh_a"]
NHAN = "SMK11"


async def sql(q, **kw):
    async with AsyncSessionLocal() as s:
        res = await s.execute(text(q), kw)
        rows = res.mappings().all() if res.returns_rows else []
        await s.commit()
        return rows


async def main():
    now = datetime.now(timezone.utc)
    nam, thang = now.year, now.month

    # ---------- dọn giao dịch smoke cũ trong kỳ ----------
    await sql("DELETE FROM payment_transaction WHERE notes LIKE :n", n=f"{NHAN}%")

    # Cần một invoice/payment thật để gắn transaction (FK).
    row = (await sql("""
        SELECT p.id AS pay_id, i.fee_id
          FROM payment p JOIN invoice i ON i.id = p.invoice_id
         WHERE p.status='verified' ORDER BY p.id DESC LIMIT 1
    """))[0]

    # ---------- dựng 3 giao dịch trong kỳ ----------
    for loai, so_tien in (("payment", "5000000"),
                          ("reversal", "-2000000"),
                          ("refund", "-1000000")):
        await sql("""
            INSERT INTO payment_transaction
                (payment_id, fee_id, transaction_type, amount,
                 balance_before, balance_after, notes, created_at)
            VALUES (:pay, :fee, :t, :a, 0, 0, :n, now())
        """, pay=row["pay_id"], fee=row["fee_id"], t=loai,
             a=Decimal(so_tien), n=f"{NHAN} {loai}")
    ghi("11.0", "dựng payment +5tr, reversal −2tr, refund −1tr trong kỳ", True)

    # ---------- gọi ĐÚNG hàm mà sổ kế toán dùng ----------
    from app.services.accounting_service import AccountingPeriodService
    async with AsyncSessionLocal() as s:
        svc = AccountingPeriodService(s)
        tong = await svc._calculate_period_totals(thang, nam)  # (month, year)

    # Chỉ so phần smoke vừa thêm (kỳ có thể đã có dữ liệu dev khác).
    truoc = (await sql("""
        SELECT
          COALESCE(SUM(amount) FILTER (WHERE transaction_type='payment'
                       AND notes NOT LIKE :n), 0) AS pay_cu,
          COALESCE(SUM(amount) FILTER (WHERE transaction_type='reversal'
                       AND notes NOT LIKE :n), 0) AS rev_cu,
          COALESCE(SUM(amount) FILTER (WHERE transaction_type='refund'
                       AND notes NOT LIKE :n), 0) AS ref_cu
        FROM payment_transaction
        WHERE date_trunc('month', created_at) = date_trunc('month', now())
    """, n=f"{NHAN}%"))[0]

    thu_smoke = tien(tong["payments"]) - (tien(truoc["pay_cu"]) + tien(truoc["rev_cu"]))
    hoan_smoke = tien(tong["refunds"]) - abs(tien(truoc["ref_cu"]))

    ghi("11.1", "Tổng thu phần smoke = 3.000.000 (5tr − 2tr reversal)",
        thu_smoke == 3_000_000,
        f"thu_smoke={thu_smoke} (tổng kỳ={tong['payments']}, cũ={truoc['pay_cu']}+{truoc['rev_cu']})")
    ghi("11.2", "Tổng hoàn phần smoke = 1.000.000 (CHỈ refund)",
        hoan_smoke == 1_000_000,
        f"hoàn_smoke={hoan_smoke} (tổng kỳ={tong['refunds']}, cũ={truoc['ref_cu']})")
    ghi("11.3", "Net phần smoke = 2.000.000", thu_smoke - hoan_smoke == 2_000_000,
        f"net={thu_smoke - hoan_smoke}")
    ghi("11.4", "reversal KHÔNG nằm trong nhãn 'Tổng hoàn'",
        hoan_smoke == 1_000_000 and hoan_smoke != 3_000_000,
        f"nếu gộp reversal thì hoàn sẽ là 3.000.000, thực tế {hoan_smoke}")

    # ---------- 11.5 doanh thu theo ngành dựa trên recognized_major_id ----------
    rows = await sql("""
        SELECT p.recognized_major_id AS major, COUNT(*) AS n, SUM(p.amount) AS tien
          FROM payment p
         WHERE p.status='verified' AND p.recognized_major_id IS NOT NULL
         GROUP BY 1 ORDER BY 3 DESC LIMIT 5
    """)
    ghi("11.5", "doanh thu theo ngành dựa trên Payment.recognized_major_id",
        len(rows) > 0, str([(r["major"], str(r["tien"])) for r in rows]))

    # ---------- 11.6 tiền thu TRƯỚC đổi ngành vẫn thuộc ngành A ----------
    rows = await sql("""
        SELECT p.id, p.amount, p.recognized_major_id AS ghi_nhan,
               f.resolved_major_id AS nganh_hien_tai
          FROM payment p
          JOIN invoice i ON i.id = p.invoice_id
          JOIN fee f ON f.id = i.fee_id
         WHERE p.status='verified'
           AND p.recognized_major_id IS NOT NULL
           AND f.resolved_major_id IS NOT NULL
           AND p.recognized_major_id <> f.resolved_major_id
         LIMIT 5
    """)
    ghi("11.6", "có khoản thu giữ ngành LÚC THU dù fee đã đổi sang ngành khác",
        len(rows) > 0,
        str([(r["id"], r["ghi_nhan"], r["nganh_hien_tai"]) for r in rows])
        or "không có ca đổi ngành nào trong dữ liệu")

    # ---------- dọn ----------
    await sql("DELETE FROM payment_transaction WHERE notes LIKE :n", n=f"{NHAN}%")
    ghi("11.7", "dọn giao dịch smoke khỏi kỳ", True)

    return tong_ket("MỤC 11 — Accounting & báo cáo")


asyncio.run(main())
