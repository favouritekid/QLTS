"""MỤC 3 (phần còn lại) — THÍ SINH TỰ PHỤC VỤ qua magic-link.

Kiểm tra đúng chỗ dễ mất tiền/mất dữ liệu: link phải xác thực bằng 4 số cuối
CCCD, dùng MỘT lần, không dùng chéo hành động, và không tiết lộ token có thật
hay không khi sai.
"""

import asyncio
import json
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.database import AsyncSessionLocal
from smoke_lib import BASE, chay, ghi, tao_client, tong_ket

NHAN = "SMK3-MAGICLINK"


async def sql(q, **kw):
    async with AsyncSessionLocal() as s:
        res = await s.execute(text(q), kw)
        rows = [dict(r) for r in res.mappings().all()] if res.returns_rows else []
        await s.commit()
        return rows


async def lay_hoac_duyet(manager, so_luong: int) -> list:
    """Lấy hồ sơ đã duyệt; nếu chưa có thì DUYỆT qua API thật (không sửa DB tay)."""
    hs = await sql(
        """
        SELECT p.id AS pid, p.citizen_id AS cccd, p.status
        FROM admission_profile p
        JOIN lead l ON l.id = p.lead_id
        WHERE p.status = 'approved' AND p.citizen_id IS NOT NULL
          AND l.deleted_at IS NULL AND l.unit_id = 14
        ORDER BY p.id DESC LIMIT :n
        """,
        n=so_luong,
    )
    if len(hs) >= so_luong:
        return hs

    ung_vien = await sql(
        """
        SELECT p.id AS pid, p.citizen_id AS cccd, p.version
        FROM admission_profile p
        JOIN lead l ON l.id = p.lead_id
        WHERE p.status IN ('submitted','resubmitted') AND p.citizen_id IS NOT NULL
          AND l.deleted_at IS NULL AND l.unit_id = 14
        ORDER BY p.id DESC LIMIT :n
        """,
        n=so_luong * 6,
    )
    ly_do = []
    for uv in ung_vien:
        if len(hs) >= so_luong:
            break
        r = await manager.post(
            f"{BASE}/api/admissions/{uv['pid']}/approve",
            json={"notes": "smoke: duyệt để phát hành link xác nhận",
                  "version": uv["version"]},
        )
        if r.status_code in (200, 201):
            hs.append({"pid": uv["pid"], "cccd": uv["cccd"], "status": "approved"})
        else:
            ly_do.append(f"#{uv['pid']} HTTP {r.status_code} {r.text[:120]}")
    if len(hs) < so_luong and ly_do:
        print("  (không duyệt được: " + " | ".join(ly_do[:3]) + ")")
    return hs


async def main():
    officer = await tao_client("smoke_officer_a")
    manager = await tao_client("smoke_manager_a")

    # ---- 3.8 hồ sơ approved (có CCCD) để phát hành link xác nhận -----------
    hs = await lay_hoac_duyet(manager, 3)
    if not hs:
        ghi("3.8", "tìm/duyệt hồ sơ để phát hành link", False, "không duyệt được hồ sơ nào")
        return tong_ket(NHAN)
    pid = hs[0]["pid"]
    cccd = hs[0]["cccd"]
    bon_so_cuoi = cccd[-4:]

    # Officer chỉ thấy hồ sơ ĐƯỢC PHÂN CÔNG — hồ sơ này không của họ nên phải 404
    # (không phải 403: không tiết lộ hồ sơ có tồn tại).
    r_off = await officer.post(f"{BASE}/api/admissions/{pid}/send-confirmation")
    ghi(
        "3.8a",
        "cán bộ KHÔNG được phân công hồ sơ → không phát hành được link (404, không lộ sự tồn tại)",
        r_off.status_code == 404,
        f"HTTP {r_off.status_code} {r_off.text[:140]}",
    )

    r = await manager.post(f"{BASE}/api/admissions/{pid}/send-confirmation")
    ghi(
        "3.8a2",
        "quản lý phụ trách đơn vị phát hành link xác nhận cho hồ sơ đã duyệt",
        r.status_code in (200, 201),
        f"HTTP {r.status_code} {r.text[:160]}",
    )

    tok = await sql(
        """
        SELECT token, action_type, expires_at, confirmed_at
        FROM admission_confirmation_token
        WHERE profile_id = :p AND confirmed_at IS NULL
        ORDER BY id DESC LIMIT 1
        """,
        p=pid,
    )
    if not tok:
        ghi("3.8b", "token được lưu lại để đối chiếu", False, "không thấy token")
        return tong_ket(NHAN)
    token = tok[0]["token"]
    hanh_dong = tok[0]["action_type"] or "confirm"
    ghi(
        "3.8b",
        "token có hạn dùng và chưa sử dụng",
        tok[0]["expires_at"] is not None and tok[0]["confirmed_at"] is None,
        f"hết hạn {tok[0]['expires_at']} · action {hanh_dong}",
    )

    # Thí sinh KHÔNG đăng nhập — dùng client trắng.
    import httpx

    khach = httpx.AsyncClient(timeout=60)

    # ---- 3.9 sai 4 số cuối CCCD → từ chối, KHÔNG đổi trạng thái -----------
    r = await khach.post(
        f"{BASE}/api/v2/admissions/magic-link/{hanh_dong}/{token}",
        json={"cccd": "0000"},
    )
    tt = await sql("SELECT status, confirmed_at FROM admission_profile WHERE id = :p", p=pid)
    ghi(
        "3.9a",
        "nhập SAI 4 số cuối CCCD → từ chối và hồ sơ giữ nguyên trạng thái",
        r.status_code in (400, 401, 403, 404) and tt[0]["status"] == "approved",
        f"HTTP {r.status_code} · trạng thái {tt[0]['status']}",
    )

    # ---- 3.10 token bịa → 404, không phân biệt được với token thật sai CCCD
    token_bia = secrets.token_urlsafe(32)
    r_bia = await khach.post(
        f"{BASE}/api/v2/admissions/magic-link/{hanh_dong}/{token_bia}",
        json={"cccd": bon_so_cuoi},
    )
    ghi(
        "3.10",
        "token BỊA → 404, không tiết lộ token có tồn tại hay không",
        r_bia.status_code == 404,
        f"HTTP {r_bia.status_code} {r_bia.text[:140]}",
    )

    # ---- 3.11 dùng token confirm cho hành động KHÁC → 404 -----------------
    hd_khac = "withdraw" if hanh_dong == "confirm" else "confirm"
    r_cheo = await khach.post(
        f"{BASE}/api/v2/admissions/magic-link/{hd_khac}/{token}",
        json={"cccd": bon_so_cuoi},
    )
    tt = await sql("SELECT status FROM admission_profile WHERE id = :p", p=pid)
    ghi(
        "3.11",
        f"dùng token '{hanh_dong}' cho hành động '{hd_khac}' → chặn, hồ sơ không đổi",
        r_cheo.status_code in (400, 404, 501) and tt[0]["status"] == "approved",
        f"HTTP {r_cheo.status_code} · trạng thái {tt[0]['status']}",
    )

    # ---- 3.9b nhập sai liên tiếp → KHOÁ tạm thời (chống dò 4 số cuối) ------
    # Mỗi lần sai ở trên đã cộng dồn; nhập sai thêm cho tới khi hệ thống khoá.
    ma_khoa = None
    for _ in range(6):
        rs = await khach.post(
            f"{BASE}/api/v2/admissions/magic-link/{hanh_dong}/{token}",
            json={"cccd": "1111"},
        )
        if "Quá nhiều lần" in rs.text:
            ma_khoa = rs.text
            break
    ghi(
        "3.9b",
        "nhập sai liên tiếp → KHOÁ tạm thời (không thể dò 4 số cuối CCCD)",
        ma_khoa is not None,
        (ma_khoa or "không thấy khoá sau 6 lần sai")[:160],
    )
    kb = await sql(
        "SELECT attempt_count, lock_until FROM admission_confirmation_token WHERE token = :t",
        t=token,
    )
    ghi(
        "3.9c",
        "số lần sai và mốc mở khoá được lưu lại để truy vết",
        bool(kb) and kb[0]["attempt_count"] >= 1 and kb[0]["lock_until"] is not None,
        f"sai {kb[0]['attempt_count'] if kb else '?'} lần · mở khoá {kb[0]['lock_until'] if kb else '?'}",
    )

    # ---- 3.12 đúng CCCD → xác nhận thành công (token SẠCH của hồ sơ khác) --
    # Token trên đã bị khoá do thử sai; dùng hồ sơ thứ hai để kiểm tra luồng thuận.
    pid = hs[1]["pid"]
    bon_so_cuoi = hs[1]["cccd"][-4:]
    r_ph = await manager.post(f"{BASE}/api/admissions/{pid}/send-confirmation")
    tok2 = await sql(
        """
        SELECT token, action_type FROM admission_confirmation_token
        WHERE profile_id = :p AND confirmed_at IS NULL
        ORDER BY id DESC LIMIT 1
        """,
        p=pid,
    )
    if not tok2:
        ghi("3.12a", "phát hành link cho hồ sơ thứ hai", False, f"HTTP {r_ph.status_code}")
        return tong_ket(NHAN)
    token = tok2[0]["token"]
    hanh_dong = tok2[0]["action_type"] or "confirm"

    r_ok = await khach.post(
        f"{BASE}/api/v2/admissions/magic-link/{hanh_dong}/{token}",
        json={"cccd": bon_so_cuoi},
    )
    tt = await sql(
        "SELECT status, confirmed_at FROM admission_profile WHERE id = :p", p=pid
    )
    ghi(
        "3.12a",
        "nhập ĐÚNG 4 số cuối CCCD → xác nhận thành công",
        r_ok.status_code == 200,
        f"HTTP {r_ok.status_code} {r_ok.text[:200]}",
    )
    ghi(
        "3.12b",
        "hồ sơ chuyển sang confirmed và có mốc thời gian xác nhận",
        tt[0]["status"] == "confirmed" and tt[0]["confirmed_at"] is not None,
        f"{tt[0]['status']} · {tt[0]['confirmed_at']}",
    )
    dau_vet = await sql(
        """
        SELECT to_status, transitioned_by_role, transitioned_by_user_id,
               transitioned_by_lead_id, metadata
        FROM admission_profile_status_history
        WHERE profile_id = :p AND to_status = 'confirmed'
        ORDER BY id DESC LIMIT 1
        """,
        p=pid,
    )
    ghi(
        "3.12c",
        "có dòng lịch sử ghi lại việc xác nhận, ghi rõ là do THÍ SINH tự làm "
        "(không quy nhầm cho cán bộ)",
        bool(dau_vet)
        and (
            dau_vet[0]["transitioned_by_user_id"] is None
            or "magic_link" in json.dumps(dau_vet[0]["metadata"] or {}, ensure_ascii=False)
        ),
        f"vai trò {dau_vet[0]['transitioned_by_role'] if dau_vet else '?'} · "
        f"user {dau_vet[0]['transitioned_by_user_id'] if dau_vet else '?'} · "
        f"{json.dumps((dau_vet[0]['metadata'] if dau_vet else {}) or {}, ensure_ascii=False)[:120]}",
    )

    # ---- 3.13 dùng LẠI đúng token đó → chặn (một lần duy nhất) ------------
    r_lai = await khach.post(
        f"{BASE}/api/v2/admissions/magic-link/{hanh_dong}/{token}",
        json={"cccd": bon_so_cuoi},
    )
    ghi(
        "3.13",
        "dùng LẠI cùng token → chặn (link chỉ có tác dụng một lần)",
        r_lai.status_code in (400, 404, 409, 410),
        f"HTTP {r_lai.status_code} {r_lai.text[:140]}",
    )

    # ---- 3.14 token HẾT HẠN → chặn ---------------------------------------
    hs2 = hs[2:3]
    if hs2:
        pid2, cccd2 = hs2[0]["pid"], hs2[0]["cccd"]
        r2 = await manager.post(f"{BASE}/api/admissions/{pid2}/send-confirmation")
        t2 = await sql(
            """
            SELECT token FROM admission_confirmation_token
            WHERE profile_id = :p AND confirmed_at IS NULL
            ORDER BY id DESC LIMIT 1
            """,
            p=pid2,
        )
        if r2.status_code in (200, 201) and t2:
            await sql(
                """
                UPDATE admission_confirmation_token SET expires_at = :e
                WHERE token = :t
                """,
                e=datetime.now(timezone.utc) - timedelta(days=1),
                t=t2[0]["token"],
            )
            r_het = await khach.post(
                f"{BASE}/api/v2/admissions/magic-link/{hanh_dong}/{t2[0]['token']}",
                json={"cccd": cccd2[-4:]},
            )
            tt2 = await sql(
                "SELECT status FROM admission_profile WHERE id = :p", p=pid2
            )
            ghi(
                "3.14",
                "token HẾT HẠN → chặn, hồ sơ không bị xác nhận",
                r_het.status_code in (400, 404, 410) and tt2[0]["status"] == "approved",
                f"HTTP {r_het.status_code} · trạng thái {tt2[0]['status']}",
            )
        else:
            ghi("3.14", "dựng token hết hạn", False, f"HTTP {r2.status_code}")

    # ---- 3.15 officer đơn vị KHÁC không phát hành link được ---------------
    try:
        officer_b = await tao_client("smoke_officer_b")
        r_b = await officer_b.post(f"{BASE}/api/admissions/{pid}/send-confirmation")
        ghi(
            "3.15",
            "cán bộ đơn vị KHÁC không phát hành được link cho hồ sơ ngoài phạm vi",
            r_b.status_code in (403, 404),
            f"HTTP {r_b.status_code}",
        )
        await officer_b.aclose()
    except Exception as e:  # noqa: BLE001
        ghi("3.15", "cán bộ đơn vị KHÁC bị chặn", False, str(e)[:140])

    await khach.aclose()
    await officer.aclose()
    await manager.aclose()
    return tong_ket(NHAN)
chay(main)
