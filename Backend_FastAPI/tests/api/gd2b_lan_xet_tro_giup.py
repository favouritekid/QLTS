# tests/api/gd2b_lan_xet_tro_giup.py
"""Trợ giúp DÙNG CHUNG cho test API GĐ2-B đợt 2 (L3a + L4 — 9 route lần xét nháp). Không phải tệp test (không ``test_`` ⇒ pytest
không thu thập; cổng độ nhìn thấy chỉ theo dõi ``test_*.py``).

Dữ liệu GIẢ (tiền tố ``GIA``, mã hồ sơ do ``ma_gia`` sinh) — dựng trên danh mục GĐ1 ``tests.fixtures.hoi_dong_seed.danh_muc`` và
CÙNG phần cấu hình GĐ2-B mà ca BT35 của L3b dựng (``tests.integration.test_gd2b_bt35_toan_luot_db._nen``: trình độ + tiêu chí để
cổng NV qua, chỉ tiêu 500, bảng chỉ tiêu nháp năm 2026 + nhóm + thành viên, loại giấy cư trú, mức đối tượng), TRỪ lần xét / sàn
(test tạo qua API thật) và trừ các chỉnh mức KV riêng của BT35. Hằng hồ sơ (điểm, học phí, giấy, quy tắc giấy) lấy NGUYÊN từ BT35.

Học vụ ``d["ai"]["oto_lt"]`` (ô tô CĐ liên thông, chỉ tiêu trống, KHÔNG thuộc nhóm nào) là đích của các ca dời năm: dời năm một
thành viên nhóm vấp R4 ("gỡ khỏi nhóm trước") TRƯỚC phép kiểm sàn — ca kiểm sàn phải đứng riêng một bất biến.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Optional

from sqlalchemy import text

from app.database import AsyncSessionLocal
from tests.fixtures.hoi_dong_seed import chen, danh_muc, ho_so, kv, lich_su_thpt, ma_gia
from tests.integration.test_gd2b_bt35_toan_luot_db import DIEM, HP, KHAI_SINH, QUY_TAC_GIAY

NAM = 2026
NAM_KHAC = 2027
#: Đường dẫn của 9 route (hợp đồng §0) — gõ TAY theo hợp đồng, không lấy từ router (lấy từ mã thì đổi mã là đổi luôn ca kiểm).
P = "/api/admission-config/review-sessions"
PATCH_HOC_VU = "/api/admin/academic-info"


async def sql(cau: str, **ts):
    """Một câu SQL trên phiên RIÊNG, commit ngay (đọc / sửa dữ liệu kiểm, không qua dịch vụ)."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            return await s.execute(text(cau), ts)


async def _x(conn, cau, **ts):
    return await conn.execute(text(cau), ts)


async def nen_lan_xet(conn) -> dict:
    """Danh mục + cấu hình đủ để một hồ sơ "sạch" được máy xét xếp vào ô tô CĐ (chính quy) năm 2026. KHÔNG có lần xét / sàn."""
    d = await danh_muc(conn)
    dl = await chen(conn, "config_degree_level", code="cao_dang", name="Cao đẳng giả", display_order=2, is_active=True)
    d["ai"], d["duong"] = {}, {}
    for k in ("oto_cd", "duoc_cd"):
        await _x(conn, "UPDATE major_program SET degree_level_id = :dl WHERE id = :m", dl=dl, m=d["mp"][k])
        ap, _ = d["psg"][(k, "cq", "g1")]
        cr = await chen(conn, "admission_criteria", method_id=d["pt"], code="GIA-TC-" + k, name="Tiêu chí giả " + k,
                        is_active=True, subject_selection_mode="fixed", scoring_method="sum", policy_version="2025.1")
        await _x(conn, "UPDATE admission_path SET criteria_id = :c WHERE id = :a", c=cr, a=ap)
        d["duong"][k] = ap
        d["ai"][k] = (await _x(conn, "SELECT academic_info_id FROM admission_path WHERE id = :a", a=ap)).scalar_one()
        await _x(conn, "UPDATE offering_academic_info SET annual_admission_quota = 500 WHERE id = :i", i=d["ai"][k])
    ap_lt, _ = d["psg"][("oto_cd", "lt", "g1")]
    d["ai"]["oto_lt"] = (await _x(conn, "SELECT academic_info_id FROM admission_path WHERE id = :a", a=ap_lt)).scalar_one()
    await _x(conn, "INSERT INTO admission_quota_table (academic_year, status, version) VALUES (:y, 'draft', 1)", y=NAM)
    d["nhom"] = {}
    for k in ("oto_cd", "duoc_cd"):
        d["nhom"][k] = await chen(conn, "admission_quota_group", academic_year=NAM, code="GIA-N-" + k, name="Nhóm giả " + k,
                                  ceiling=1000)
        await chen(conn, "admission_quota_group_member", group_id=d["nhom"][k], offering_academic_info_id=d["ai"][k],
                   academic_year=NAM)
    d["giay"]["giay_xac_nhan_cu_tru"] = await chen(
        conn, "config_document_type", code="giay_xac_nhan_cu_tru", name="Giấy cư trú giả", display_order=99, is_active=True
    )
    for ma, diem in (("01", "2.00"), ("06", "1.00")):
        await chen(conn, "priority_object_config", academic_year=NAM, group_code="UT1", sub_code=ma,
                   description="Đối tượng giả " + ma, bonus_points=diem, effective_from=date(2026, 1, 1))
    return d


async def ho_so_xet(
    conn,
    d,
    so: int,
    *,
    nv=(("oto_cd", "cq", "g1"),),
    nganh_hoc_phi: str = "oto_cd",
    du_giay_hoc_phi: bool = True,
    full_name: str = "Họ Giả Lần Xét",
) -> int:
    """Một hồ sơ ``submitted`` năm 2026 (Kinh, KV1, đủ giấy bắt buộc + học phí HK1 đã đóng). ``nv`` = các (ngành, loại hình, tổ hợp)
    theo ``display_order`` 1, 2, …; ``du_giay_hoc_phi=False`` ⇒ không giấy, không học phí (``ineligible``)."""
    pid = await ho_so(
        conn, d, cccd=ma_gia(so), full_name=full_name, dob=date(2008, 1, 1), gender="Nam", ethnicity="01",
        permanent_commune_code="GX1", cultural_education_level="graduated_thpt", vocational_qualification="none",
        priority_resolution_snapshot=kv("KV1"), academic_history=lich_su_thpt(d, "KV1"),
        nv=[(i + 1, *x) for i, x in enumerate(nv)], diem={i: DIEM for i in range(len(nv))},
        hoc_phi=[dict(HP, resolved_major=nganh_hoc_phi)] if du_giay_hoc_phi else [],
        giay=[KHAI_SINH] if du_giay_hoc_phi else [], status="submitted",
    )
    await _x(conn, "UPDATE admission_profile SET applied_rules = CAST(:a AS jsonb) WHERE id = :p",
             a=json.dumps(QUY_TAC_GIAY), p=pid)
    return pid


async def so_san(session_id: int) -> int:
    return (await sql("SELECT count(*) FROM admission_review_floor WHERE session_id = :s", s=session_id)).scalar_one()


async def san(session_id: int) -> list:
    """Sàn trong CSDL: [(id học vụ, mức dạng chuỗi)] tăng dần."""
    return [
        (int(a), "%.2f" % b)
        for a, b in (
            await sql(
                "SELECT offering_academic_info_id, floor_score FROM admission_review_floor WHERE session_id = :s "
                "ORDER BY offering_academic_info_id",
                s=session_id,
            )
        ).all()
    ]


async def lan_xet(session_id: int):
    """(trạng thái, version, seq_no) trong CSDL."""
    return tuple(
        (await sql("SELECT status, version, seq_no FROM admission_review_session WHERE id = :s", s=session_id)).one()
    )


async def nam_hoc_vu(ai_id: int) -> int:
    return (await sql("SELECT academic_year FROM offering_academic_info WHERE id = :i", i=ai_id)).scalar_one()


async def so_run(session_id: Optional[int] = None) -> int:
    if session_id is None:
        return (await sql("SELECT count(*) FROM admission_review_run")).scalar_one()
    return (await sql("SELECT count(*) FROM admission_review_run WHERE session_id = :s", s=session_id)).scalar_one()


async def pid_cua(s) -> int:
    return (await s.execute(text("SELECT pg_backend_pid()"))).scalar_one()


async def bi_chan_boi(pid_giu: int, viec, *, lan: int = 100) -> Optional[str]:
    """Hỏi CSDL từ phiên THỨ BA (``pg_blocking_pids`` — không hỏi spy): có backend nào đang CHỜ khoá do phiên ``pid_giu`` giữ, trong
    khi ``viec`` (request / lệnh của phía chờ) chưa xong. Trả ``locktype`` của khoá đang chờ (vd ``advisory`` = khoá năm), hoặc
    ``None`` nếu ``viec`` đã xong (không chờ ai) / hết lượt hỏi."""
    for _ in range(lan):
        await asyncio.sleep(0.05)
        if viec.done():
            return None
        async with AsyncSessionLocal() as s3:
            loai = (
                await s3.execute(
                    text(
                        "SELECT l.locktype FROM pg_locks l WHERE NOT l.granted AND l.pid <> pg_backend_pid() "
                        "AND CAST(:g AS integer) = ANY(pg_blocking_pids(l.pid))"
                    ),
                    {"g": pid_giu},
                )
            ).scalars().all()
        if loai:
            return loai[0]
    return None


def mo_ta(viec) -> str:
    if not viec.done():
        return "việc chưa xong"
    if viec.cancelled():
        return "việc bị huỷ"
    e = viec.exception()
    if e is None:
        return "việc ĐÃ XONG không chờ ai"
    from app.repositories.council_decision_repository import db_error_codes

    return "việc đã lỗi %s %s" % (type(e).__name__, db_error_codes(e))


async def dong(giu, viec) -> None:
    """Dọn phiên GIỮ khoá kể cả khi ca đỏ giữa chừng: nhả trước để việc đang chờ chạy xong, rồi chờ việc."""
    await giu.rollback()
    await giu.close()
    if viec is not None:
        try:
            await asyncio.wait_for(viec, 10)
        except (Exception, asyncio.CancelledError):  # kết quả đã được ca kiểm đọc, hoặc ca đã đỏ ở bước trước
            pass


def khong_du_lieu_ca_nhan(obj) -> bool:
    """Không khoá nào của phản hồi (ở mọi tầng) là CCCD / điện thoại / ngày sinh / địa chỉ / dân tộc (hợp đồng §3.5, HĐ8)."""
    cam = {"citizen_id", "cccd", "phone", "dob", "date_of_birth", "address", "ethnicity", "ethnicity_name"}
    if isinstance(obj, dict):
        return all(k not in cam and khong_du_lieu_ca_nhan(v) for k, v in obj.items())
    if isinstance(obj, list):
        return all(khong_du_lieu_ca_nhan(v) for v in obj)
    return True
