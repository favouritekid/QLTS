"""GĐ2-A — bảng chỉ tiêu năm / nhóm ngành qua REQUEST THẬT (router → deps → dịch vụ → CSDL thật) + hai phiên CSDL thật cho
khoá năm và cho khoá dòng bảng ``FOR SHARE`` của trigger (sửa chỉ tiêu ↔ khoá bảng, hai chiều). Đặc tả GĐ2 bản 3 §3, §10, §11; ca biên B14–B17, B20, D13, D14. Không dữ liệu thật. Mỗi ca kiểm một bất biến.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app import models
from app.config import settings
from app.database import AsyncSessionLocal
from tests.api.test_admission_doc_mutations_response_parity import _login

pytestmark = pytest.mark.asyncio

P = "/api/admission-config/quota-tables"
NAM = 2026


async def _sql(cau: str, **ts):
    async with AsyncSessionLocal() as s:
        async with s.begin():
            return await s.execute(text(cau), ts)


@pytest.fixture
async def hoc_vu(seed_lead_dependencies):
    """Bốn học vụ năm 2026 (bốn hình thức của một ngành) + một học vụ năm 2025."""
    mpid = seed_lead_dependencies["major_program_id"]
    ts = int(datetime.now().timestamp() * 1000)
    ra = {"2026": [], "2025": None}
    async with AsyncSessionLocal() as s:
        async with s.begin():
            for i in range(5):
                ot = models.ConfigOfferingType(code=f"gd2a_{ts}_{i}", name=f"GD2A {ts} {i}", display_order=i + 1)
                s.add(ot)
                await s.flush()
                po = models.ProgramOffering(
                    offering_type=f"GD2A_{ts}_{i}", program_id=mpid, offering_type_id=ot.id,
                    is_active=True, duration_semesters=6,
                )
                s.add(po)
                await s.flush()
                ai = models.OfferingAcademicInfo(
                    offering_id=po.id, academic_year=NAM if i < 4 else NAM - 1, is_published=True,
                    annual_admission_quota=None,
                )
                s.add(ai)
                await s.flush()
                if i < 4:
                    ra["2026"].append(ai.id)
                else:
                    ra["2025"] = ai.id
    return ra


def _than(version, hoc_vu, *, nhom=None):
    a, b, c, d = hoc_vu["2026"]
    return {
        "version": version,
        "groups": nhom
        if nhom is not None
        else [
            {"code": "N1", "name": "Nhóm Kỹ thuật", "ceiling": 120,
             "members": [{"offering_academic_info_id": a, "annual_admission_quota": 50},
                         {"offering_academic_info_id": b, "annual_admission_quota": 60}]},
            {"code": "N2", "name": "Nhóm Sức khoẻ", "ceiling": 40,
             "members": [{"offering_academic_info_id": c, "annual_admission_quota": 40}]},
        ],
    }


async def _chi_tieu(ai_id):
    return (await _sql("SELECT annual_admission_quota FROM offering_academic_info WHERE id = :i", i=ai_id)).scalar_one()


async def _bang():
    return (await _sql("SELECT status, version FROM admission_quota_table WHERE academic_year = :y", y=NAM)).one_or_none()


# ── tạo / đọc / sửa ─────────────────────────────────────────────────────────────────────────────────────────────────
async def test_admin_tao_bang_moi_ghi_chi_tieu_nganh_va_doc_lai(client: AsyncClient, admin_token_headers, hoc_vu):
    r = await client.put(f"{P}/{NAM}", headers=admin_token_headers, json=_than(0, hoc_vu))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["status"], body["version"]) == ("draft", 1)
    assert [(g["code"], g["ceiling"], len(g["members"])) for g in body["groups"]] == [("N1", 120, 2), ("N2", 40, 1)]
    assert all(g["usage"] == {"publish_count": 0, "approved_count": 0, "used": 0} for g in body["groups"])
    a, b, c, d = hoc_vu["2026"]
    assert [await _chi_tieu(x) for x in (a, b, c, d)] == [50, 60, 40, None]
    r = await client.get(f"{P}/{NAM}", headers=admin_token_headers)
    assert r.status_code == 200 and r.json() == body, r.text
    vet = (
        await _sql(
            "SELECT action FROM entity_audit_log WHERE entity_type = 'admission_quota_table' AND entity_id = :y", y=NAM
        )
    ).scalars().all()
    assert vet == ["created"]


async def test_doc_nam_chua_co_bang_404(client: AsyncClient, admin_token_headers):
    r = await client.get(f"{P}/{NAM}", headers=admin_token_headers)
    assert r.status_code == 404, r.text


async def test_put_sai_phien_ban_409_khong_ghi_gi(client: AsyncClient, admin_token_headers, hoc_vu):
    assert (await client.put(f"{P}/{NAM}", headers=admin_token_headers, json=_than(0, hoc_vu))).status_code == 200
    than = _than(0, hoc_vu)
    than["groups"][0]["ceiling"] = 999
    r = await client.put(f"{P}/{NAM}", headers=admin_token_headers, json=than)
    assert r.status_code == 409 and r.json()["error_code"] == "QUOTA_TABLE_STALE", r.text
    assert tuple(await _bang()) == ("draft", 1)
    assert (await _sql("SELECT ceiling FROM admission_quota_group WHERE code = 'N1'")).scalar_one() == 120


async def test_put_lan_hai_giu_id_nhom_theo_ma_thay_thanh_vien(client: AsyncClient, admin_token_headers, hoc_vu):
    r = await client.put(f"{P}/{NAM}", headers=admin_token_headers, json=_than(0, hoc_vu))
    id_n1 = next(g["id"] for g in r.json()["groups"] if g["code"] == "N1")
    a, b, c, d = hoc_vu["2026"]
    than = _than(1, hoc_vu, nhom=[
        {"code": "N1", "name": "Nhóm Kỹ thuật (đổi tên)", "ceiling": 100,
         "members": [{"offering_academic_info_id": a, "annual_admission_quota": 55}]},
        {"code": "N3", "name": "Nhóm mới", "ceiling": 10,
         "members": [{"offering_academic_info_id": d, "annual_admission_quota": 10}]},
    ])
    r = await client.put(f"{P}/{NAM}", headers=admin_token_headers, json=than)
    assert r.status_code == 200, r.text
    g = {x["code"]: x for x in r.json()["groups"]}
    assert set(g) == {"N1", "N3"} and g["N1"]["id"] == id_n1 and g["N1"]["ceiling"] == 100
    assert [m["offering_academic_info_id"] for m in g["N1"]["members"]] == [a]
    # Ngành rời bảng giữ chỉ tiêu đã có (bảng chỉ ghi chỉ tiêu của thành viên).
    assert [await _chi_tieu(x) for x in (a, b, c, d)] == [55, 60, 40, 10]


async def test_put_nganh_khac_nam_400(client: AsyncClient, admin_token_headers, hoc_vu):
    than = _than(0, hoc_vu)
    than["groups"][1]["members"].append({"offering_academic_info_id": hoc_vu["2025"], "annual_admission_quota": 5})
    r = await client.put(f"{P}/{NAM}", headers=admin_token_headers, json=than)
    assert r.status_code == 400, r.text
    assert r.json()["offering_academic_info_ids"] == [hoc_vu["2025"]]
    assert await _bang() is None


async def test_put_mot_nganh_hai_nhom_400(client: AsyncClient, admin_token_headers, hoc_vu):
    than = _than(0, hoc_vu)
    a = hoc_vu["2026"][0]
    than["groups"][1]["members"].append({"offering_academic_info_id": a, "annual_admission_quota": 5})
    r = await client.put(f"{P}/{NAM}", headers=admin_token_headers, json=than)
    assert r.status_code == 400, r.text
    assert r.json()["duplicate_offering_academic_info_ids"] == [a]
    assert await _bang() is None


async def test_put_ma_nhom_trung_400(client: AsyncClient, admin_token_headers, hoc_vu):
    than = _than(0, hoc_vu)
    than["groups"][1]["code"] = "N1"
    r = await client.put(f"{P}/{NAM}", headers=admin_token_headers, json=than)
    assert r.status_code == 400, r.text
    assert r.json()["duplicate_group_codes"] == ["N1"]


async def test_put_tran_am_422(client: AsyncClient, admin_token_headers, hoc_vu):
    than = _than(0, hoc_vu)
    than["groups"][0]["ceiling"] = -1
    r = await client.put(f"{P}/{NAM}", headers=admin_token_headers, json=than)
    assert r.status_code == 422, r.text


# ── khoá / mở khoá ──────────────────────────────────────────────────────────────────────────────────────────────────
async def _tao_va_khoa(client, h, hoc_vu):
    assert (await client.put(f"{P}/{NAM}", headers=h, json=_than(0, hoc_vu))).status_code == 200
    r = await client.post(f"{P}/{NAM}/lock", headers=h, json={"version": 1})
    assert r.status_code == 200, r.text
    return r.json()


async def test_khoa_bang_roi_put_bi_chan_409(client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu):
    body = await _tao_va_khoa(client, admin_token_headers, hoc_vu)
    assert (body["status"], body["version"], body["locked_by_user_id"]) == ("locked", 2, admin_user_in_db["id"])
    r = await client.put(f"{P}/{NAM}", headers=admin_token_headers, json=_than(2, hoc_vu))
    assert r.status_code == 409 and r.json()["error_code"] == "QUOTA_TABLE_LOCKED", r.text


async def test_bang_khoa_thi_api_sua_hoc_vu_co_san_bi_csdl_chan_409(client: AsyncClient, admin_token_headers, hoc_vu):
    await _tao_va_khoa(client, admin_token_headers, hoc_vu)
    a = hoc_vu["2026"][0]
    r = await client.patch(
        f"/api/admin/academic-info/{a}", headers=admin_token_headers, json={"annual_admission_quota": 51}
    )
    assert r.status_code == 409, r.text
    assert r.json()["error_code"] == "QUOTA_TABLE_LOCKED", r.text
    assert await _chi_tieu(a) == 50
    # Sửa trường KHÁC chỉ tiêu vẫn được (trigger chỉ canh annual_admission_quota).
    r = await client.patch(
        f"/api/admin/academic-info/{a}", headers=admin_token_headers, json={"target_audience": "Học sinh THPT"}
    )
    assert r.status_code == 200, r.text


@pytest.mark.parametrize(
    "cau",
    [
        "UPDATE admission_quota_group SET ceiling = ceiling + 1 WHERE code = 'N1'",
        "DELETE FROM admission_quota_group_member WHERE academic_year = 2026",
        "INSERT INTO admission_quota_group (academic_year, code, name, ceiling) VALUES (2026, 'NX', 'X', 1)",
        "DELETE FROM admission_quota_table WHERE academic_year = 2026",
    ],
)
async def test_bang_khoa_thi_csdl_chan_moi_cau_ghi_nhom_thanh_vien(client: AsyncClient, admin_token_headers, hoc_vu, cau):
    await _tao_va_khoa(client, admin_token_headers, hoc_vu)
    from sqlalchemy.exc import DBAPIError

    from app.repositories.council_decision_repository import db_error_codes

    with pytest.raises(DBAPIError) as e:
        await _sql(cau)
    assert db_error_codes(e.value)[0] == "QLC01", cau


async def test_khoa_hai_lan_va_sai_phien_ban(client: AsyncClient, admin_token_headers, hoc_vu):
    await _tao_va_khoa(client, admin_token_headers, hoc_vu)
    r = await client.post(f"{P}/{NAM}/lock", headers=admin_token_headers, json={"version": 2})
    assert r.status_code == 409 and r.json()["error_code"] == "QUOTA_TABLE_ALREADY_LOCKED", r.text
    r = await client.post(f"{P}/{NAM}/lock", headers=admin_token_headers, json={"version": 1})
    assert r.status_code == 409 and r.json()["error_code"] == "QUOTA_TABLE_STALE", r.text


async def test_khoa_khi_nganh_thanh_vien_thieu_chi_tieu_409(client: AsyncClient, admin_token_headers, hoc_vu):
    assert (await client.put(f"{P}/{NAM}", headers=admin_token_headers, json=_than(0, hoc_vu))).status_code == 200
    c = hoc_vu["2026"][2]
    await _sql("UPDATE offering_academic_info SET annual_admission_quota = NULL WHERE id = :i", i=c)
    r = await client.post(f"{P}/{NAM}/lock", headers=admin_token_headers, json={"version": 1})
    assert r.status_code == 409, r.text
    assert r.json()["offering_academic_info_ids"] == [c]
    assert tuple(await _bang()) == ("draft", 1)


async def test_khoa_duoc_khi_chi_tieu_bang_0_nhap_ro(client: AsyncClient, admin_token_headers, hoc_vu):
    """Câu 4 owner 19-11: chỉ tiêu 0 nhập RÕ RÀNG là một con số (không phải "thiếu") ⇒ khoá được; chỉ NULL mới chặn."""
    than = _than(0, hoc_vu)
    than["groups"][1]["members"][0]["annual_admission_quota"] = 0
    assert (await client.put(f"{P}/{NAM}", headers=admin_token_headers, json=than)).status_code == 200
    c = hoc_vu["2026"][2]
    assert await _chi_tieu(c) == 0
    r = await client.post(f"{P}/{NAM}/lock", headers=admin_token_headers, json={"version": 1})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "locked"


async def test_mo_khoa_bat_buoc_ly_do_va_luu_vet(client: AsyncClient, admin_token_headers, hoc_vu):
    await _tao_va_khoa(client, admin_token_headers, hoc_vu)
    r = await client.post(f"{P}/{NAM}/unlock", headers=admin_token_headers, json={"version": 2, "reason": "   "})
    assert r.status_code == 422, r.text
    assert tuple(await _bang()) == ("locked", 2)
    r = await client.post(
        f"{P}/{NAM}/unlock", headers=admin_token_headers,
        json={"version": 2, "reason": "Có văn bản điều chỉnh chỉ tiêu ngành"},
    )
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["version"], r.json()["locked_by_user_id"]) == ("draft", 3, None)
    vet = (
        await _sql(
            "SELECT action, reason FROM entity_audit_log WHERE entity_type = 'admission_quota_table' "
            "AND entity_id = :y ORDER BY id", y=NAM,
        )
    ).all()
    assert [tuple(x) for x in vet] == [
        ("created", None), ("locked", None), ("unlocked", "Có văn bản điều chỉnh chỉ tiêu ngành"),
    ]
    # Mở khoá xong sửa được.
    r = await client.put(f"{P}/{NAM}", headers=admin_token_headers, json=_than(3, hoc_vu))
    assert r.status_code == 200, r.text


async def test_mo_khoa_bang_chua_khoa_409(client: AsyncClient, admin_token_headers, hoc_vu):
    assert (await client.put(f"{P}/{NAM}", headers=admin_token_headers, json=_than(0, hoc_vu))).status_code == 200
    r = await client.post(f"{P}/{NAM}/unlock", headers=admin_token_headers, json={"version": 1, "reason": "thử"})
    assert r.status_code == 409 and r.json()["error_code"] == "QUOTA_TABLE_NOT_LOCKED", r.text


# ── quyền ───────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("vai", ["quan_ly", "can_bo"])
async def test_chi_admin_403_cho_vai_khac(
    client: AsyncClient, admin_token_headers, manager_user_in_db, officer_user_in_db, hoc_vu, vai
):
    assert (await client.put(f"{P}/{NAM}", headers=admin_token_headers, json=_than(0, hoc_vu))).status_code == 200
    u = manager_user_in_db if vai == "quan_ly" else officer_user_in_db
    h = await _login(client, u["username"], u["password"])
    client.cookies.clear()  # cookie đăng nhập đè tiêu đề — request đi đúng vai của ``h``
    for m, duong, than in (
        ("GET", f"{P}/{NAM}", None),
        ("PUT", f"{P}/{NAM}", _than(1, hoc_vu)),
        ("POST", f"{P}/{NAM}/lock", {"version": 1}),
        ("POST", f"{P}/{NAM}/unlock", {"version": 1, "reason": "x"}),
    ):
        r = await client.request(m, duong, headers=h, json=than)
        assert r.status_code == 403, (vai, m, duong, r.text)
    assert tuple(await _bang()) == ("draft", 1)


async def test_lop_phu_chi_admin_tu_choi_vai_khac_du_lot_casbin():
    """Lớp phụ ``deps.require_quota_table_admin`` (Casbin là tầng chủ sở hữu vai): gọi THẲNG dependency với người không
    phải admin ⇒ 403 — một cấu hình Casbin sai không mở được bảng chỉ tiêu cho vai khác."""
    from types import SimpleNamespace

    from app.core import deps
    from app.utils.exceptions import PermissionDeniedError

    for vai in ("manager", "officer", "accountant"):
        with pytest.raises(PermissionDeniedError):
            await deps.require_quota_table_admin(SimpleNamespace(id=1, role=vai))
    u = SimpleNamespace(id=1, role="admin")
    assert await deps.require_quota_table_admin(u) is u


# ── đóng băng (request thật 503 ↔ 200) ─────────────────────────────────────────────────────────────────────────────
async def test_dong_bang_chan_route_ghi_bang_chi_tieu_503_doc_van_duoc(
    client: AsyncClient, admin_token_headers, hoc_vu, monkeypatch
):
    assert (await client.put(f"{P}/{NAM}", headers=admin_token_headers, json=_than(0, hoc_vu))).status_code == 200
    monkeypatch.setattr(settings, "ADMISSION_FROZEN", True)
    for m, duong, than in (
        ("PUT", f"{P}/{NAM}", _than(1, hoc_vu)),
        ("POST", f"{P}/{NAM}/lock", {"version": 1}),
        ("POST", f"{P}/{NAM}/unlock", {"version": 1, "reason": "x"}),
    ):
        r = await client.request(m, duong, headers=admin_token_headers, json=than)
        assert r.status_code == 503 and r.json()["code"] == "ADMISSION_FROZEN", (m, duong, r.text)
    assert (await client.get(f"{P}/{NAM}", headers=admin_token_headers)).status_code == 200
    assert tuple(await _bang()) == ("draft", 1)
    monkeypatch.setattr(settings, "ADMISSION_FROZEN", False)
    r = await client.post(f"{P}/{NAM}/lock", headers=admin_token_headers, json={"version": 1})
    assert r.status_code == 200, r.text


# ── khoá năm: hai phiên CSDL thật ──────────────────────────────────────────────────────────────────────────────────
async def test_khoa_nam_tuan_tu_hai_lan_tao_bang_cung_nam(admin_user_in_db, hoc_vu):
    """Hai giao dịch cùng tạo bảng năm 2026 (``version = 0``), thành viên RỜI nhau (không chung dòng học vụ nào để khoá).
    Giao dịch thứ hai phải CHỜ khoá năm (advisory) rồi thấy bảng đã có ⇒ 409 ``quota_table_stale`` — không phải lỗi
    trùng khoá chính (500)."""
    from app.schemas.admission_quota_table import QuotaTablePut
    from app.services import admission_quota_table_service as svc

    a, b, c, d = hoc_vu["2026"]
    than_1 = QuotaTablePut(version=0, groups=[{"code": "N1", "name": "Một", "ceiling": 9,
                                                "members": [{"offering_academic_info_id": a, "annual_admission_quota": 1}]}])
    than_2 = QuotaTablePut(version=0, groups=[{"code": "N2", "name": "Hai", "ceiling": 9,
                                                "members": [{"offering_academic_info_id": b, "annual_admission_quota": 2}]}])
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    try:
        await svc.replace_quota_table(s1, NAM, than_1, actor_id=admin_user_in_db["id"])  # giữ khoá năm, CHƯA commit
        pid2 = (await s2.execute(text("SELECT pg_backend_pid()"))).scalar_one()
        viec = asyncio.ensure_future(svc.replace_quota_table(s2, NAM, than_2, actor_id=admin_user_in_db["id"]))
        cho = None
        for _ in range(100):
            await asyncio.sleep(0.05)
            async with AsyncSessionLocal() as s3:
                cho = (
                    await s3.execute(
                        text(
                            "SELECT l.locktype FROM pg_locks l WHERE l.pid = :p AND NOT l.granted"
                        ),
                        {"p": pid2},
                    )
                ).scalars().all()
            if cho:
                break
        assert cho == ["advisory"], cho  # chờ ĐÚNG khoá năm
        assert not viec.done()
        await s1.commit()
        from app.services.admission_quota_table_service import QuotaTableConflict

        with pytest.raises(QuotaTableConflict) as e:
            await viec
        assert e.value.reason_code == "quota_table_stale"
        await s2.rollback()
    finally:
        await s1.close()
        await s2.close()
    assert (await _sql("SELECT string_agg(code, ',') FROM admission_quota_group")).scalar_one() == "N1"


# ── khoá dòng bảng ``FOR SHARE`` trong trigger ↔ lệnh khoá bảng: hai phiên CSDL thật ────────────────────────────────────
# Guard: ``admission_quota_assert_table_unlocked`` (``app/models/admission_quota_ddl.py``) khoá dòng ``admission_quota_table``
# của năm ``FOR SHARE``. Hai đường ghi dưới đây KHÔNG lấy khoá năm (advisory) — đường sửa học vụ có sẵn / SQL tay — nên
# chỉ khoá dòng ấy đứng giữa chúng và lệnh khoá bảng. Mỗi đường đi qua một loại trigger gọi CÙNG hàm kiểm.
GHI_KHI_KHOA = {
    "chi_tieu_nganh": (
        "UPDATE offering_academic_info SET annual_admission_quota = 55 WHERE id = :a",
        "SELECT annual_admission_quota FROM offering_academic_info WHERE id = :a",
        50,
        55,
    ),
    "tran_nhom": (
        "UPDATE admission_quota_group SET ceiling = 121 WHERE academic_year = :y AND code = 'N1'",
        "SELECT ceiling FROM admission_quota_group WHERE academic_year = :y AND code = 'N1'",
        120,
        121,
    ),
}


def _tham_so_ghi(duong: str, hoc_vu) -> dict:
    return {"a": hoc_vu["2026"][0]} if duong == "chi_tieu_nganh" else {"y": NAM}


async def _tao_bang_nhap(admin_user_in_db, hoc_vu) -> None:
    """Bảng 2026 ``draft`` version 1 (ngành a = 50 thuộc nhóm N1 trần 120), đã commit."""
    from app.schemas.admission_quota_table import QuotaTablePut
    from app.services import admission_quota_table_service as svc

    async with AsyncSessionLocal() as s:
        await svc.replace_quota_table(s, NAM, QuotaTablePut(**_than(0, hoc_vu)), actor_id=admin_user_in_db["id"])
        await s.commit()
    assert tuple(await _bang()) == ("draft", 1)


async def _pid(s) -> int:
    return (await s.execute(text("SELECT pg_backend_pid()"))).scalar_one()


def _mo_ta(viec) -> str:
    if not viec.done():
        return "việc chưa xong"
    if viec.cancelled():
        return "việc bị huỷ"
    e = viec.exception()
    if e is None:
        return "việc ĐÃ XONG không chờ ai"
    from app.repositories.council_decision_repository import db_error_codes

    return "việc đã lỗi %s %s" % (type(e).__name__, db_error_codes(e))


async def _bi_chan_boi(pid_cho: int, pid_giu: int, viec) -> bool:
    """Hỏi CSDL từ phiên THỨ BA (``pg_blocking_pids``, không hỏi spy): phiên ``pid_cho`` có đang chờ khoá do phiên
    ``pid_giu`` giữ không. Việc đã xong (không chờ gì) ⇒ False ngay."""
    for _ in range(100):
        await asyncio.sleep(0.05)
        if viec.done():
            return False
        async with AsyncSessionLocal() as s3:
            chan = (await s3.execute(text("SELECT pg_blocking_pids(:p)"), {"p": pid_cho})).scalar_one()
        if pid_giu in (chan or []):
            return True
    return False


async def _dong(giu, cho, viec) -> None:
    """Dọn hai phiên kể cả khi ca đỏ giữa chừng: nhả phiên GIỮ khoá trước để việc đang chờ chạy xong, rồi đóng phiên chờ."""
    await giu.rollback()
    await giu.close()
    if viec is not None:
        try:
            await asyncio.wait_for(viec, 10)
        except (Exception, asyncio.CancelledError):  # kết quả đã được ca kiểm đọc, hoặc ca đã đỏ ở bước trước
            pass
    await cho.rollback()
    await cho.close()


@pytest.mark.parametrize("duong", list(GHI_KHI_KHOA))
async def test_hai_phien_ghi_chi_tieu_truoc_thi_khoa_bang_phai_cho(admin_user_in_db, hoc_vu, duong):
    """Phiên 1 sửa chỉ tiêu / trần (trigger giữ ``FOR SHARE`` dòng bảng), CHƯA commit. Phiên 2 gọi dịch vụ khoá bảng THẬT ⇒
    phải CHỜ đúng phiên 1; phiên 1 commit xong thì khoá mới chạy, và bảng khoá mang giá trị MỚI — không có ca "khoá xong
    rồi chỉ tiêu mới đổi"."""
    from app.services import admission_quota_table_service as svc

    ghi, doc, cu, moi = GHI_KHI_KHOA[duong]
    ts = _tham_so_ghi(duong, hoc_vu)
    await _tao_bang_nhap(admin_user_in_db, hoc_vu)
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid1 = await _pid(s1)
        await s1.execute(text(ghi), ts)  # giữ khoá, CHƯA commit
        pid2 = await _pid(s2)
        viec = asyncio.ensure_future(
            svc.lock_quota_table(s2, NAM, expected_version=1, actor_id=admin_user_in_db["id"])
        )
        assert await _bi_chan_boi(pid2, pid1, viec), (
            "khoá bảng KHÔNG chờ giao dịch đang sửa (%s) — %s" % (duong, _mo_ta(viec))
        )
        await s1.commit()
        await viec
        await s2.commit()
    finally:
        await _dong(s1, s2, viec)
    assert tuple(await _bang()) == ("locked", 2)
    assert (await _sql(doc, **ts)).scalar_one() == moi


@pytest.mark.parametrize("duong", list(GHI_KHI_KHOA))
async def test_hai_phien_khoa_bang_truoc_thi_ghi_chi_tieu_cho_roi_bi_chan(admin_user_in_db, hoc_vu, duong):
    """Phiên 2 khoá bảng qua dịch vụ THẬT (giữ ``FOR UPDATE`` dòng bảng), CHƯA commit. Phiên 1 sửa chỉ tiêu / trần ⇒ trigger
    phải CHỜ đúng phiên 2; phiên 2 commit xong thì phiên 1 đọc lại dòng, thấy ``locked`` ⇒ SQLSTATE ``QLC01``; giá trị cũ
    giữ nguyên."""
    from sqlalchemy.exc import DBAPIError

    from app.models.admission_quota_ddl import SQLSTATE_QUOTA_TABLE_LOCKED
    from app.repositories.council_decision_repository import db_error_codes
    from app.services import admission_quota_table_service as svc

    ghi, doc, cu, moi = GHI_KHI_KHOA[duong]
    ts = _tham_so_ghi(duong, hoc_vu)
    await _tao_bang_nhap(admin_user_in_db, hoc_vu)
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid2 = await _pid(s2)
        await svc.lock_quota_table(s2, NAM, expected_version=1, actor_id=admin_user_in_db["id"])  # CHƯA commit
        pid1 = await _pid(s1)
        viec = asyncio.ensure_future(s1.execute(text(ghi), ts))
        assert await _bi_chan_boi(pid1, pid2, viec), (
            "sửa (%s) KHÔNG chờ lệnh khoá bảng đang dở — %s" % (duong, _mo_ta(viec))
        )
        await s2.commit()
        with pytest.raises(DBAPIError) as e:
            await viec
        assert db_error_codes(e.value)[0] == SQLSTATE_QUOTA_TABLE_LOCKED
    finally:
        await _dong(s2, s1, viec)
    assert tuple(await _bang()) == ("locked", 2)
    assert (await _sql(doc, **ts)).scalar_one() == cu
