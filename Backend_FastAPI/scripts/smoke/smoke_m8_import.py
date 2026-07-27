"""MỤC 8 (phần còn lại) — NHẬP LÔ thu học phí từ file Excel.

5 loại dòng trong CÙNG một file: khớp · sai số tiền · CCCD không tồn tại ·
trùng trong file · ngày sai định dạng. Sau đó commit và ĐẢO LÔ (void), đối
chiếu số dư trước/sau bằng SQL — không tin trả lời API suông.
"""

import asyncio
import io
import json
import uuid
from decimal import Decimal

import pandas as pd
from sqlalchemy import text

from app.database import AsyncSessionLocal
from smoke_lib import BASE, chay, ghi, tao_client, tien, tong_ket

NAM = 2026
KY = 1
NHAN = "SMK8-IMPORT"
# Mã tham chiếu phải DUY NHẤT mỗi lần chạy: hệ thống cảnh báo "nghi trùng giao dịch"
# khi (hồ sơ, mã tham chiếu, số tiền) đã ghi nhận — dùng lại mã cũ sẽ tự gây cảnh báo.
LAN = uuid.uuid4().hex[:6].upper()


async def sql(q, **kw):
    async with AsyncSessionLocal() as s:
        res = await s.execute(text(q), kw)
        rows = [dict(r) for r in res.mappings().all()] if res.returns_rows else []
        await s.commit()
        return rows


def dung_file(rows) -> bytes:
    """Dựng .xlsx đúng bộ cột template."""
    df = pd.DataFrame(
        rows,
        columns=[
            "Số CCCD",
            "Họ và tên học sinh",
            "Số tiền thu (VNĐ)",
            "Ngày thu",
            "Hình thức",
            "Mã tham chiếu",
            "Ghi chú",
        ],
    )
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


async def main():
    ketoan = await tao_client("smoke_acc_1")
    manager = await tao_client("smoke_manager_a")

    # ---- chọn 3 hồ sơ CÒN NỢ, mỗi hồ sơ 1 hoá đơn payable -------------------
    hs = await sql(
        """
        SELECT p.id AS pid, p.citizen_id AS cccd, l.full_name AS ten,
               f.id AS fee_id, f.final_amount - f.paid_amount AS con_no
        FROM admission_profile p
        JOIN lead l ON l.id = p.lead_id
        JOIN fee f ON f.admission_profile_id = p.id
                  AND f.fee_type = 'tuition' AND f.semester_no = :k
                  AND f.status NOT IN ('cancelled','waived')
        WHERE p.citizen_id IS NOT NULL AND l.deleted_at IS NULL
          AND p.academic_year = :y AND l.unit_id = 14
          AND p.status NOT IN ('withdrawn','rejected','withdrawal_pending')
          AND f.final_amount - f.paid_amount > 2000000
          AND EXISTS (SELECT 1 FROM invoice i
                      WHERE i.fee_id = f.id AND i.status IN ('issued','partial','overdue'))
        ORDER BY p.id DESC LIMIT 4
        """,
        k=KY,
        y=NAM,
    )
    if len(hs) < 4:
        ghi("8.4", "chuẩn bị dữ liệu import", False, f"chỉ tìm được {len(hs)} hồ sơ")
        return tong_ket(NHAN)
    a, b, c, d = hs

    # Hồ sơ ở trạng thái KHÔNG thu được (đang chờ rút / đã rút / bị từ chối): preview
    # có thể vẫn khớp CCCD, nhưng pha GHI TIỀN phải chặn.
    e_rows = await sql(
        """
        SELECT p.id AS pid, p.citizen_id AS cccd, p.status AS trang_thai,
               l.full_name AS ten, f.final_amount - f.paid_amount AS con_no
        FROM admission_profile p
        JOIN lead l ON l.id = p.lead_id
        JOIN fee f ON f.admission_profile_id = p.id
                  AND f.fee_type = 'tuition' AND f.semester_no = :k
                  AND f.status NOT IN ('cancelled','waived')
        WHERE p.citizen_id IS NOT NULL AND l.deleted_at IS NULL
          AND p.academic_year = :y AND l.unit_id = 14
          AND p.status IN ('withdrawn','rejected','withdrawal_pending')
          AND f.final_amount - f.paid_amount > 1000000
          AND EXISTS (SELECT 1 FROM invoice i
                      WHERE i.fee_id = f.id AND i.status IN ('issued','partial','overdue'))
        ORDER BY p.id DESC LIMIT 1
        """,
        k=KY,
        y=NAM,
    )
    e = e_rows[0] if e_rows else None

    truoc = {r["pid"]: Decimal(str(r["con_no"])) for r in hs}
    if e:
        truoc[e["pid"]] = Decimal(str(e["con_no"]))

    # ---- 5 loại dòng --------------------------------------------------------
    # Ref có tiền tố cố định + pid để không đụng dữ liệu cũ.
    rows = [
        # (1) KHỚP
        [a["cccd"], a["ten"], "1.000.000", "10/07/2026", "Tiền mặt", f"SMK8A{LAN}{a['pid']}", ""],
        # (2) SAI SỐ TIỀN — vượt tổng còn nợ
        [b["cccd"], b["ten"], "999.000.000", "10/07/2026", "Chuyển khoản", f"SMK8B{LAN}{b['pid']}", ""],
        # (3) CCCD KHÔNG TỒN TẠI
        ["099999999999", "Người Không Có Thật", "500.000", "10/07/2026", "Tiền mặt", f"SMK8X{LAN}", ""],
        # (4) TRÙNG trong file — cùng CCCD + CÙNG số tiền với dòng (1)
        [a["cccd"], a["ten"], "1.000.000", "11/07/2026", "Tiền mặt", f"SMK8A2{LAN}{a['pid']}", ""],
        # (5) NGÀY SAI định dạng
        [c["cccd"], c["ten"], "500.000", "32/13/2026", "Tiền mặt", f"SMK8C{LAN}{c['pid']}", ""],
        # (6) KHỚP THUẦN — không cảnh báo nào (mốc đối chiếu cho nhóm warned)
        [d["cccd"], d["ten"], "1.500.000", "10/07/2026", "Chuyển khoản", f"SMK8D{LAN}{d['pid']}", ""],
    ]
    if e:
        # (7) hồ sơ ở trạng thái KHÔNG thu được
        rows.append(
            [e["cccd"], e["ten"], "1.000.000", "10/07/2026", "Tiền mặt", f"SMK8E{LAN}{e['pid']}", ""]
        )
    noi_dung = dung_file(rows)

    # ---- 8.4 preview: phân loại đúng từng dòng, KHÔNG ghi tiền --------------
    r = await ketoan.post(
        f"{BASE}/api/payments/import/preview",
        files={"file": ("smoke8.xlsx", noi_dung,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"academic_year": str(NAM), "semester_no": str(KY)},
    )
    ok = r.status_code == 200
    ghi("8.4a", "kế toán preview file 5 dòng → 200", ok, f"HTTP {r.status_code} {r.text[:200]}")
    if not ok:
        return tong_ket(NHAN)
    pv = r.json()
    batch_id = pv["batch_id"]
    by_no = {row["row_no"]: row for row in pv["rows"]}

    ghi(
        "8.4b",
        "dòng KHỚP (đúng CCCD, tiền trong hạn mức) → matched/warned + phân bổ FIFO",
        by_no.get(2, {}).get("status") in ("matched", "warned")
        and len(by_no.get(2, {}).get("allocations") or []) >= 1,
        f"{by_no.get(2, {}).get('status')} · {by_no.get(2, {}).get('message')}",
    )
    ghi(
        "8.4c",
        "dòng SAI SỐ TIỀN (vượt còn nợ) → error, nêu rõ số còn nợ",
        by_no.get(3, {}).get("status") == "error"
        and "vượt tổng còn nợ" in (by_no.get(3, {}).get("message") or ""),
        f"{by_no.get(3, {}).get('status')} · {by_no.get(3, {}).get('message')}",
    )
    ghi(
        "8.4d",
        "dòng CCCD KHÔNG TỒN TẠI → error, không âm thầm bỏ qua",
        by_no.get(4, {}).get("status") == "error"
        and by_no.get(4, {}).get("message"),
        f"{by_no.get(4, {}).get('status')} · {by_no.get(4, {}).get('message')}",
    )
    ghi(
        "8.4e",
        "dòng TRÙNG trong file (cùng CCCD + cùng số tiền) → cảnh báo nghi copy nhầm",
        by_no.get(5, {}).get("status") == "warned"
        and "copy nh" in (by_no.get(5, {}).get("message") or ""),
        f"{by_no.get(5, {}).get('status')} · {by_no.get(5, {}).get('message')}",
    )
    ghi(
        "8.4f",
        "dòng NGÀY SAI định dạng → error ngay ở khâu đọc file",
        by_no.get(6, {}).get("status") == "error"
        and ("ngày" in (by_no.get(6, {}).get("message") or "").lower()),
        f"{by_no.get(6, {}).get('status')} · {by_no.get(6, {}).get('message')}",
    )
    ghi(
        "8.4h",
        "dòng SẠCH (tên khớp, tiền trong hạn mức, không trùng) → matched, không cảnh báo thừa",
        by_no.get(7, {}).get("status") == "matched"
        and not by_no.get(7, {}).get("message"),
        f"{by_no.get(7, {}).get('status')} · {by_no.get(7, {}).get('message')}",
    )

    # preview PHẢI read-only
    sau_pv = {
        r_["pid"]: Decimal(str(r_["con_no"]))
        for r_ in await sql(
            """
            SELECT p.id AS pid, f.final_amount - f.paid_amount AS con_no
            FROM admission_profile p
            JOIN fee f ON f.admission_profile_id = p.id
                      AND f.fee_type='tuition' AND f.semester_no=:k
                      AND f.status NOT IN ('cancelled','waived')
            WHERE p.id = ANY(:ids)
            """,
            k=KY,
            ids=list(truoc.keys()),
        )
    }
    ghi(
        "8.4g",
        "preview KHÔNG ghi tiền (số còn nợ y nguyên)",
        sau_pv == truoc,
        f"trước {truoc} · sau {sau_pv}",
    )

    # ---- 8.5 xem lại cùng file (chưa commit) → THAY THẾ lô preview cũ -------
    # Xem trước là read-only nên phải xem lại được nhiều lần; điều KHÔNG được phép
    # là để lại 2 lô cùng-hiệu-lực cho một file (nguy cơ commit đúp).
    r2 = await ketoan.post(
        f"{BASE}/api/payments/import/preview",
        files={"file": ("smoke8.xlsx", noi_dung,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"academic_year": str(NAM), "semester_no": str(KY)},
    )
    ok = r2.status_code == 200
    if ok:
        batch_moi = r2.json()["batch_id"]
        con_lai = await sql(
            """
            SELECT id, status FROM payment_import_batch
            WHERE file_sha256 = (SELECT file_sha256 FROM payment_import_batch WHERE id = :b)
              AND status <> 'void'
            """,
            b=batch_moi,
        )
        ghi(
            "8.5a",
            "xem lại CÙNG file khi chưa commit → thay thế lô cũ, chỉ còn ĐÚNG 1 lô hiệu lực",
            len(con_lai) == 1 and con_lai[0]["id"] == batch_moi,
            f"lô cũ #{batch_id} → lô mới #{batch_moi}; còn hiệu lực: {con_lai}",
        )
        rc_cu = await ketoan.post(f"{BASE}/api/payments/import/{batch_id}/commit")
        ghi(
            "8.5b",
            "commit theo id lô CŨ đã bị thay thế → 404 (không ghi tiền theo bản xem lỗi thời)",
            rc_cu.status_code == 404,
            f"HTTP {rc_cu.status_code} {rc_cu.text[:140]}",
        )
        batch_id = batch_moi
    else:
        ghi("8.5a", "xem lại cùng file → 200", False, f"HTTP {r2.status_code} {r2.text[:160]}")

    # ---- 8.6 commit: chỉ ghi dòng hợp lệ ------------------------------------
    rc = await ketoan.post(f"{BASE}/api/payments/import/{batch_id}/commit")
    ok = rc.status_code == 200
    ghi("8.6a", "kế toán commit lô → 200", ok, f"HTTP {rc.status_code} {rc.text[:200]}")
    if not ok:
        return tong_ket(NHAN)
    cm = rc.json()

    sau_cm = {
        r_["pid"]: Decimal(str(r_["con_no"]))
        for r_ in await sql(
            """
            SELECT p.id AS pid, f.final_amount - f.paid_amount AS con_no
            FROM admission_profile p
            JOIN fee f ON f.admission_profile_id = p.id
                      AND f.fee_type='tuition' AND f.semester_no=:k
                      AND f.status NOT IN ('cancelled','waived')
            WHERE p.id = ANY(:ids)
            """,
            k=KY,
            ids=list(truoc.keys()),
        )
    }
    # Hồ sơ A có 2 dòng hợp lệ (1tr + 1tr) → giảm nợ 2tr. B và C là dòng lỗi → y nguyên.
    ghi(
        "8.6b",
        "chỉ dòng HỢP LỆ được ghi tiền — hồ sơ A giảm nợ đúng 2.000.000",
        truoc[a["pid"]] - sau_cm[a["pid"]] == Decimal("2000000"),
        f"giảm {tien(truoc[a['pid']] - sau_cm[a['pid']])}",
    )
    ghi(
        "8.6c",
        "hồ sơ của dòng LỖI không bị đụng tới",
        sau_cm[b["pid"]] == truoc[b["pid"]] and sau_cm[c["pid"]] == truoc[c["pid"]],
        f"B {tien(sau_cm[b['pid']])} · C {tien(sau_cm[c['pid']])}",
    )
    ghi(
        "8.6c2",
        "dòng SẠCH cũng được ghi đúng số tiền (1.500.000)",
        truoc[d["pid"]] - sau_cm[d["pid"]] == Decimal("1500000"),
        f"giảm {tien(truoc[d['pid']] - sau_cm[d['pid']])}",
    )
    # Lọc theo ĐÚNG lô này (không dùng tiền tố mã tham chiếu — lần chạy trước để lại
    # payment cùng tiền tố đã bị đảo, sẽ lẫn vào kết quả).
    pm = await sql(
        """
        SELECT pay.status, count(*) AS n
        FROM (SELECT * FROM payment_import_row WHERE jsonb_typeof(payment_ids) = 'array') r
        JOIN LATERAL jsonb_array_elements_text(r.payment_ids) AS pid ON TRUE
        JOIN payment pay ON pay.id = pid::int
        WHERE r.batch_id = :b
        GROUP BY pay.status
        """,
        b=batch_id,
    )
    ghi(
        "8.6d",
        "payment sinh ra ở trạng thái verified (auto-verify: kế toán=maker, hệ thống=checker)",
        bool(pm) and all(x["status"] == "verified" for x in pm) and sum(x["n"] for x in pm) == 3,
        str(pm),
    )
    if e:
        dong_e = next(
            (x for x in cm["rows"] if str(e["cccd"]) in json.dumps(x, ensure_ascii=False)), None
        )
        ghi(
            "8.6e",
            f"hồ sơ {e['trang_thai']} → pha GHI TIỀN chặn dù preview đã khớp "
            "(kiểm tra lại trạng thái dưới khoá, không tin bản xem trước)",
            sau_cm.get(e["pid"]) == truoc[e["pid"]],
            f"còn nợ {tien(sau_cm.get(e['pid']))} · dòng: {(dong_e or {}).get('message')}",
        )

    # ---- 8.7 commit lại → 409 ----------------------------------------------
    rc2 = await ketoan.post(f"{BASE}/api/payments/import/{batch_id}/commit")
    ghi(
        "8.7a",
        "commit LẠI lô đã ghi → 409, không nhân đôi tiền",
        rc2.status_code == 409,
        f"HTTP {rc2.status_code} {rc2.text[:160]}",
    )

    r3 = await ketoan.post(
        f"{BASE}/api/payments/import/preview",
        files={"file": ("smoke8.xlsx", noi_dung,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"academic_year": str(NAM), "semester_no": str(KY)},
    )
    ghi(
        "8.7b",
        "upload lại file ĐÃ ghi tiền → 409 kèm hướng dẫn phải đảo lô trước",
        r3.status_code == 409 and "void" in r3.text.lower(),
        f"HTTP {r3.status_code} {r3.text[:200]}",
    )

    # ---- 8.7c chống thu khống: gõ lại ĐÚNG mã tham chiếu + số tiền đã ghi ---
    file_lap = dung_file(
        [[d["cccd"], d["ten"], "1.500.000", "12/07/2026", "Chuyển khoản",
          f"SMK8D{LAN}{d['pid']}", "gõ lại đơn lẻ"]]
    )
    r4 = await ketoan.post(
        f"{BASE}/api/payments/import/preview",
        files={"file": ("smoke8_lap.xlsx", file_lap,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"academic_year": str(NAM), "semester_no": str(KY)},
    )
    dong_lap = (r4.json()["rows"][0] if r4.status_code == 200 and r4.json()["rows"] else {})
    ghi(
        "8.7c",
        "file KHÁC nhưng cùng (hồ sơ · mã tham chiếu · số tiền) đã ghi → cảnh báo nghi trùng giao dịch",
        dong_lap.get("status") == "warned"
        and "nghi trùng giao dịch" in (dong_lap.get("message") or ""),
        f"HTTP {r4.status_code} · {dong_lap.get('status')} · {dong_lap.get('message')}",
    )

    # ---- 8.8 kế toán KHÔNG được void; manager thì được ----------------------
    rv0 = await ketoan.post(
        f"{BASE}/api/payments/import/{batch_id}/void", json={"reason": "smoke thử quyền"}
    )
    ghi(
        "8.8a",
        "kế toán KHÔNG được đảo lô (gate cao hơn: manager/admin)",
        rv0.status_code == 403,
        f"HTTP {rv0.status_code} {rv0.text[:160]}",
    )

    rv = await manager.post(
        f"{BASE}/api/payments/import/{batch_id}/void",
        json={"reason": "smoke: đảo lô kiểm tra hoàn nguyên số dư"},
    )
    ok = rv.status_code == 200
    ghi("8.8b", "manager đảo lô → 200", ok, f"HTTP {rv.status_code} {rv.text[:200]}")

    if ok:
        sau_vd = {
            r_["pid"]: Decimal(str(r_["con_no"]))
            for r_ in await sql(
                """
                SELECT p.id AS pid, f.final_amount - f.paid_amount AS con_no
                FROM admission_profile p
                JOIN fee f ON f.admission_profile_id = p.id
                          AND f.fee_type='tuition' AND f.semester_no=:k
                          AND f.status NOT IN ('cancelled','waived')
                WHERE p.id = ANY(:ids)
                """,
                k=KY,
                ids=list(truoc.keys()),
            )
        }
        ghi(
            "8.8c",
            "sau khi đảo lô, số còn nợ TRỞ LẠI đúng như trước import",
            sau_vd == truoc,
            f"trước {truoc} · sau đảo {sau_vd}",
        )
        pm2 = await sql(
            """
            SELECT pay.status, count(*) AS n
            FROM (SELECT * FROM payment_import_row WHERE jsonb_typeof(payment_ids) = 'array') r
            JOIN LATERAL jsonb_array_elements_text(r.payment_ids) AS pid ON TRUE
            JOIN payment pay ON pay.id = pid::int
            WHERE r.batch_id = :b
            GROUP BY pay.status
            """,
            b=batch_id,
        )
        ghi(
            "8.8d",
            "payment của lô chuyển sang refunded (giữ dấu vết, không xoá)",
            bool(pm2) and all(x["status"] == "refunded" for x in pm2),
            str(pm2),
        )
        rev = await sql(
            """
            SELECT count(*) AS n
            FROM (SELECT * FROM payment_import_row WHERE jsonb_typeof(payment_ids) = 'array') r
            JOIN LATERAL jsonb_array_elements_text(r.payment_ids) AS pid ON TRUE
            JOIN payment_transaction pt ON pt.payment_id = pid::int
                                       AND pt.transaction_type = 'reversal'
            WHERE r.batch_id = :b
            """,
            b=batch_id,
        )
        ghi(
            "8.8e",
            "có bút toán reversal đối ứng cho từng payment bị đảo",
            rev[0]["n"] == 3,
            f"{rev[0]['n']} bút toán reversal",
        )

    # ---- 8.9 lô sau khi đảo vẫn tra cứu được + phân quyền -------------------
    rd = await ketoan.get(f"{BASE}/api/payments/import/batches/{batch_id}")
    ghi(
        "8.9a",
        "tra cứu chi tiết lô sau khi đảo → còn nguyên vết (status void)",
        rd.status_code == 200 and rd.json().get("status") == "void",
        f"HTTP {rd.status_code} · {rd.json().get('status') if rd.status_code == 200 else rd.text[:120]}",
    )
    try:
        officer = await tao_client("smoke_officer_a")
        ro = await officer.get(f"{BASE}/api/payments/import/batches/{batch_id}")
        ghi(
            "8.9b",
            "officer KHÔNG xem được lô import (không phải nhân sự tài chính)",
            ro.status_code in (403, 404),
            f"HTTP {ro.status_code}",
        )
        await officer.aclose()
    except Exception as e:  # noqa: BLE001
        ghi("8.9b", "officer KHÔNG xem được lô import", False, str(e)[:160])

    await ketoan.aclose()
    await manager.aclose()
    return tong_ket(NHAN)
chay(main)
