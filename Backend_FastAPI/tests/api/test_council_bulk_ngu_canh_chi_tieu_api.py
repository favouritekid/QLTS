# -*- coding: utf-8 -*-
"""F263 (Codex lần 16; đặc tả vòng giao diện bản 2 mục 2.1 + bản 3 mục 2.1.4) — Phê duyệt hàng loạt KHÔNG khoá dòng
chỉ tiêu ngoài tập đã khoá ở đầu lô, kể cả khi phiên sửa cấu hình đổi năm học của dòng học vụ giữa bước dò và bước
khoá.

Hồ sơ "cũ" = ``applied_rules`` không có ``academic_info_id`` ⇒ ngữ cảnh chỉ tiêu dò theo ``lead.offering_id`` +
năm học (``_resolve_quota_context``). Lô dò KHÔNG khoá, rồi khoá tập đã dò; mỗi mục phải dùng ĐÚNG ngữ cảnh đã dò
(so trước mọi khoá mới) — lệch ⇒ mục ấy trả câu "thử lại", không khoá dòng mới.

Điểm đồng bộ (bọc hàm bằng ``monkeypatch`` — chỉ có trong test):

* P0 — sau khi dò lần đầu, TRƯỚC khi khoá tập (bọc ``qos.khoa_o_chi_tieu``, lần gọi đầu);
* P1 — sau khi khoá tập, trước mục đầu tiên (bọc ``asv._khoa_truoc_lo_duyet``);
* P2 — trong mục của hồ sơ đích, ngay sau quyết định của ``_resolve_quota_context`` có ánh xạ (trả về HOẶC ném),
  TRƯỚC khi SAVEPOINT của mục kết thúc (khoá lấy trong SAVEPOINT bị nhả khi SAVEPOINT lùi ⇒ đo sau đó vô nghĩa).

Phép đo khoá hàng (F270 — ``pg_locks`` không hiện khoá hàng thường): phiên thứ ba ``FOR UPDATE NOWAIT`` có
``lock_timeout`` rồi ROLLBACK ngay; "bi_giu" = SQLSTATE 55P03. Mỗi ca có ĐỐI CHỨNG DƯƠNG: một dòng chắc chắn lô đang
giữ phải đo ra "bi_giu" (chứng minh phép đo phân biệt được hai trạng thái)."""
import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

import app.database as csdl
from app import models
from app.database import AsyncSessionLocal
from app.repositories.council_decision_repository import ma_loi_csdl
from app.services import admission_service as asv
from app.services import quota_occupancy_service as qos
from app.utils.exceptions import ServiceError
from tests.api import test_council_decisions_api as qd
from tests.api.test_council_decision_hai_phien_api import (  # noqa: F401
    _ban,
    _dam_bao_sts09,
    _Diem,
    _nop,
    _o_chi_tieu,
)
from tests.api.test_council_decision_khoa_cheo_api import (
    _duyet_hang_loat,
    _gan_nganh,
    _lead,
    _theo_doi_hoa_hong,
)
from tests.api.test_council_decision_profile_gates_api import (  # noqa: F401 — fixture
    SACH,
    ad,
    hs,
    tk,
)

pytestmark = pytest.mark.integration


# ── công cụ ─────────────────────────────────────────────────────────────────────────────────────────────────────
async def _thu_khoa(bang, id_):
    """Phiên thứ ba: thử khoá ĐÚNG một dòng, không chờ. Luôn ROLLBACK ngay (không giữ khoá của chính mình)."""
    async with csdl.engine.connect() as k:
        gd = await k.begin()
        try:
            await k.execute(text("SET LOCAL lock_timeout = '200ms'"))
            await k.execute(text("SELECT id FROM %s WHERE id = :i FOR UPDATE NOWAIT" % bang), {"i": id_})
            return "trong"
        except DBAPIError as e:
            if ma_loi_csdl(e)[0] == "55P03":
                return "bi_giu"
            raise
        finally:
            await gd.rollback()


async def _ho_so_cu(pid):
    """Bỏ ``academic_info_id`` khỏi ảnh chụp luật ⇒ ngữ cảnh chỉ tiêu dò theo lead → ngành + năm học."""
    await qd._sql("UPDATE admission_profile SET applied_rules = applied_rules - 'academic_info_id' WHERE id = :p", p=pid)
    assert await qd._q1("SELECT applied_rules ? 'academic_info_id' FROM admission_profile WHERE id = :p", p=pid) is False


async def _nhan_ban_hoc_vu(goc_id, *, offering_id, nam):
    """Thêm một dòng ``offering_academic_info`` chép mọi cột của ``goc_id`` (trừ id), đổi ngành + năm. Trả id."""
    cot = [
        r[0]
        for r in await qd._q(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'offering_academic_info' "
            "AND column_name NOT IN ('id', 'offering_id', 'academic_year') ORDER BY ordinal_position"
        )
    ]
    ds = ", ".join(cot)
    async with csdl.engine.begin() as c:
        return (
            await c.execute(
                text(
                    "INSERT INTO offering_academic_info (offering_id, academic_year, %s) "
                    "SELECT :o, :n, %s FROM offering_academic_info WHERE id = :g RETURNING id" % (ds, ds)
                ),
                {"o": offering_id, "n": nam, "g": goc_id},
            )
        ).scalar_one()


async def _dong_nam(off, nam):
    return await qd._q1(
        "SELECT count(*) FROM offering_academic_info WHERE offering_id = :o AND academic_year = :n", o=off, n=nam
    )


async def _doi_nam(ai_id, nam):
    await qd._sql("UPDATE offering_academic_info SET academic_year = :n WHERE id = :a", n=nam, a=ai_id)


async def _nganh_khac(off):
    """Một ngành khác ``off`` có dòng học vụ (lấy dòng đầu). Trả (offering_id, ai_id)."""
    r = await qd._q(
        "SELECT offering_id, id FROM offering_academic_info WHERE offering_id <> :o ORDER BY id LIMIT 1", o=off
    )
    assert r, "seed thiếu ngành thứ hai"
    return r[0][0], r[0][1]


def _boc_p0(monkeypatch, diem, viec_chen):
    """P0: lần gọi đầu ``qos.khoa_o_chi_tieu`` (từ ``_khoa_truoc_lo_duyet``) — chạy ``viec_chen`` ở phiên khác
    (commit) TRƯỚC khi lô khoá tập."""
    goc = qos.khoa_o_chi_tieu

    async def boc(*a, **kw):
        if diem.so_lan == 0:
            diem.so_lan += 1
            await viec_chen()
        return await goc(*a, **kw)

    monkeypatch.setattr(qos, "khoa_o_chi_tieu", boc)


def _boc_p1(monkeypatch, diem, viec_chen):
    """P1: sau khi ``_khoa_truoc_lo_duyet`` khoá xong tập — chạy ``viec_chen`` ở phiên khác (commit)."""
    goc = asv._khoa_truoc_lo_duyet

    async def boc(*a, **kw):
        kq = await goc(*a, **kw)
        if diem.so_lan == 0:
            diem.so_lan += 1
            await viec_chen()
        return kq

    monkeypatch.setattr(asv, "_khoa_truoc_lo_duyet", boc)


def _boc_p2(monkeypatch, pid_dich, do):
    """P2: trong mục của ``pid_dich``, ngay sau lần gọi ``_resolve_quota_context(lock=True)`` ĐẦU TIÊN (trả về hoặc
    ném) — chạy ``do()`` (phép đo của phiên thứ ba) TRƯỚC khi SAVEPOINT của mục kết thúc. Ghi kết quả vào ``ket``.
    Điều kiện kích hoạt KHÔNG dựa vào tham số mới ``ngu_canh_da_do`` ⇒ cùng phép đo chạy được trên mã cũ (đỏ do
    hành vi — khoá dòng ngoài tập — không phải do thiếu ký hiệu). Bước dò của ``_khoa_truoc_lo_duyet`` và lần dò
    không khoá bên trong đều gọi ``lock=False`` ⇒ không kích hoạt."""
    goc = asv._resolve_quota_context
    ket = {}

    async def boc(db, profile, *a, **kw):
        if kw.get("lock") is not True or profile.id != pid_dich or ket:
            return await goc(db, profile, *a, **kw)
        try:
            return await goc(db, profile, *a, **kw)
        finally:
            ket.update(await do())

    monkeypatch.setattr(asv, "_resolve_quota_context", boc)
    return ket


async def _chuan_bi(hs):
    """Hai hồ sơ cũ "Đã nộp": p (``SACH[0]``) < q (``SACH[2]``), cùng ô K (lead → ngành của K, chỉ tiêu năm 10)."""
    await _dam_bao_sts09()
    o = await _o_chi_tieu(hs, SACH[0], chi_tieu=10)
    p, q = hs[SACH[0]][1], hs[SACH[2]][1]
    assert p < q
    for x in (p, q):
        await _nop(x)
        await _gan_nganh(x, o["off"])
        await _ho_so_cu(x)
    return o, p, q


# ── ca 1: đổi năm của hai dòng học vụ giữa DÒ và KHOÁ ───────────────────────────────────────────────────────────
async def test_f263_doi_nam_truoc_khi_khoa(client, hs, ad, monkeypatch):  # noqa: F811
    o, p, _ = await _chuan_bi(hs)
    x = o["ai"]
    assert await qd._q1("SELECT academic_year FROM offering_academic_info WHERE id = :a", a=x) == 2026
    y = await _nhan_ban_hoc_vu(x, offering_id=o["off"], nam=2019)  # cùng ngành, năm chưa dùng
    vp = (await _ban(p))[1]
    hoa_hong = _theo_doi_hoa_hong(monkeypatch)

    async def doi_cho():  # phiên B: X 2026 → 2031, Y 2019 → 2026 (commit) — lô đã dò ra X, chưa khoá
        await _doi_nam(x, 2031)
        await _doi_nam(y, 2026)

    _boc_p0(monkeypatch, _Diem(), doi_cho)
    do = _boc_p2(
        monkeypatch,
        p,
        lambda: _hai_phep_do(("offering_academic_info", y, "y"), ("offering_academic_info", x, "x")),
    )
    r = await _duyet_hang_loat(client, ad, (p, vp))
    assert r.status_code == 200, r.text
    kq = r.json()
    assert do == {"y": "trong", "x": "bi_giu"}, do  # x: đối chứng dương (lô giữ X từ đầu lô)
    assert (kq["success_count"], kq["failed_ids"]) == (0, [p]), kq
    assert kq["errors"][str(p)] == qos.THONG_DIEP_XUNG_DOT, kq
    assert (await _ban(p))[0] == "submitted"  # đọc SAU commit, từ kết nối khác
    assert hoa_hong == []


async def _hai_phep_do(*muc):
    return {nhan: await _thu_khoa(bang, id_) for bang, id_, nhan in muc}


# ── ca 2: dò ra None, dòng khớp XUẤT HIỆN sau khi khoá tập (chỉ guard từng mục bắt được) ────────────────────────
async def test_f263_dong_moi_sau_khi_khoa_tap(client, hs, ad, monkeypatch):  # noqa: F811
    o, p, q = await _chuan_bi(hs)
    off2, z = await _nganh_khac(o["off"])
    await _gan_nganh(p, off2)
    nam_z = await qd._q1("SELECT academic_year FROM offering_academic_info WHERE id = :a", a=z)
    await _doi_nam(z, 2030)
    assert await _dong_nam(off2, 2026) == 0, "tiền điều kiện: ngành 2 còn dòng năm 2026"  # p dò ra None (ngành 2 không có dòng năm 2026)
    vp, vq = (await _ban(p))[1], (await _ban(q))[1]
    hoa_hong = _theo_doi_hoa_hong(monkeypatch)

    async def hien_z():  # phiên B: dòng ngành 2 trở về năm 2026 (commit) — SAU khi lô khoá tập {X}
        await _doi_nam(z, 2026)

    _boc_p1(monkeypatch, _Diem(), hien_z)
    do = _boc_p2(
        monkeypatch,
        p,
        lambda: _hai_phep_do(("offering_academic_info", z, "z"), ("offering_academic_info", o["ai"], "x")),
    )
    try:
        r = await _duyet_hang_loat(client, ad, (p, vp), (q, vq))
    finally:
        await _doi_nam(z, nam_z)
    assert r.status_code == 200, r.text
    kq = r.json()
    assert do == {"z": "trong", "x": "bi_giu"}, do
    assert (kq["success_count"], kq["failed_ids"]) == (1, [p]), kq
    assert kq["errors"][str(p)] == qos.THONG_DIEP_XUNG_DOT, kq
    assert ((await _ban(p))[0], (await _ban(q))[0]) == ("submitted", "approved")
    assert hoa_hong == [await _lead(q)]  # callback CHỈ cho mục đã commit


# ── ca 3: tập khoá RỖNG (mọi hồ sơ dò ra None) vẫn là ràng buộc ─────────────────────────────────────────────────
async def test_f263_tap_khoa_rong(client, hs, ad, monkeypatch):  # noqa: F811
    o, p, _ = await _chuan_bi(hs)
    off2, z = await _nganh_khac(o["off"])
    await _gan_nganh(p, off2)
    nam_z = await qd._q1("SELECT academic_year FROM offering_academic_info WHERE id = :a", a=z)
    await _doi_nam(z, 2030)
    assert await _dong_nam(off2, 2026) == 0, "tiền điều kiện: ngành 2 còn dòng năm 2026"
    vp = (await _ban(p))[1]
    hoa_hong = _theo_doi_hoa_hong(monkeypatch)

    async def hien_z():
        await _doi_nam(z, 2026)

    _boc_p1(monkeypatch, _Diem(), hien_z)
    # đối chứng dương ca này: dòng HỒ SƠ p — lô khoá mọi hồ sơ FOR UPDATE từ đầu (tập học vụ thì rỗng)
    do = _boc_p2(
        monkeypatch, p, lambda: _hai_phep_do(("offering_academic_info", z, "z"), ("admission_profile", p, "p"))
    )
    try:
        r = await _duyet_hang_loat(client, ad, (p, vp))
    finally:
        await _doi_nam(z, nam_z)
    assert r.status_code == 200, r.text
    kq = r.json()
    assert do == {"z": "trong", "p": "bi_giu"}, do
    assert (kq["success_count"], kq["failed_ids"]) == (0, [p]), kq
    assert kq["errors"][str(p)] == qos.THONG_DIEP_XUNG_DOT, kq
    assert (await _ban(p))[0] == "submitted"
    assert hoa_hong == []


# ── ca 4: đối chứng — không phiên chen ⇒ lô qua như cũ ─────────────────────────────────────────────────────────
async def test_f263_khong_chen_van_qua(client, hs, ad, monkeypatch):  # noqa: F811
    o, p, q = await _chuan_bi(hs)
    vp, vq = (await _ban(p))[1], (await _ban(q))[1]
    hoa_hong = _theo_doi_hoa_hong(monkeypatch)
    r = await _duyet_hang_loat(client, ad, (p, vp), (q, vq))
    assert r.status_code == 200, r.text
    assert (r.json()["success_count"], r.json()["failed_ids"]) == (2, []), r.text
    assert sorted(hoa_hong) == sorted([await _lead(p), await _lead(q)])


# ── ca 5: ánh xạ THIẾU hồ sơ ≠ "dò ra None" ⇒ lỗi, không coi như khớp ──────────────────────────────────────────
async def test_f263_anh_xa_thieu(hs):  # noqa: F811
    o, p, _ = await _chuan_bi(hs)
    off2, z = await _nganh_khac(o["off"])
    await _gan_nganh(p, off2)
    nam_z = await qd._q1("SELECT academic_year FROM offering_academic_info WHERE id = :a", a=z)
    await _doi_nam(z, 2030)
    assert await _dong_nam(off2, 2026) == 0, "tiền điều kiện: ngành 2 còn dòng năm 2026"  # p dò ra None — nếu "thiếu" bị coi như None thì sẽ lọt
    try:
        async with AsyncSessionLocal() as db:
            ho_so = await db.get(models.AdmissionProfile, p)
            await db.refresh(ho_so, ["lead"])
            with pytest.raises(ServiceError):
                await asv._resolve_quota_context(db, ho_so, lock=True, ngu_canh_da_do={})
            await db.rollback()
    finally:
        await _doi_nam(z, nam_z)
