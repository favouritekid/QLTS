# -*- coding: utf-8 -*-
"""GĐ1b — migration ``gd1b20261117`` trên PostgreSQL THẬT (CSDL dùng một lần), nâng / hạ qua ĐÚNG ``alembic`` (tiến trình
con ⇒ đúng ``env.py`` AUTOCOMMIT). Khuôn ``test_council_decision_migration.py``.

CSDL trước nâng cấp = ``create_all()`` của model HIỆN TẠI rồi gỡ ĐÚNG phần GĐ1b (5 bảng, 4 cột, I1 / I2, trigger) ⇒ mọi
cột khác của ``profile_document`` / ``document_audit_log`` y như thật. Sau nâng cấp, so lược đồ phần GĐ1b với một CSDL dựng
thẳng từ model: đó là phép khoá "migration = model" (thay cho so chuỗi).

Đặc tả bản 3.6 §4.4 (khôi phục người tải), §4.3 (dấu tải), §4.6b (bằng chứng), §10.
"""
import asyncio
import hashlib
import itertools
import os
import secrets
import sys
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy.engine import make_url

from app.config import settings
from app.models.base import Base
from tests.fixtures.database import kiem_url_csdl_test

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

GOC = Path(__file__).resolve().parents[2]  # Backend_FastAPI (có alembic.ini)
#: Mỗi giấy mẫu một loại giấy riêng (``uq_profile_document_path`` = một giấy / loại / hồ sơ).
_LOAI_GIAY = itertools.count(1)
TRUOC = "hdts20261113"
SAU = "gd1b20261117"
BANG_MOI = (
    "document_bulk_batch_item",
    "document_bulk_batch",
    "document_cross_review_grant",
    "document_evidence_file",
    "document_download_log",
)
GO_GD1B = (
    "DROP TABLE document_bulk_batch_item, document_bulk_batch, document_cross_review_grant, "
    "document_evidence_file, document_download_log",
    "DROP TRIGGER trg_profile_document_row_version ON profile_document",
    "DROP FUNCTION profile_document_bump_row_version()",
    "ALTER TABLE profile_document DROP CONSTRAINT ck_profile_document_uploader_known, "
    "DROP CONSTRAINT ck_profile_document_receiver_known, DROP COLUMN uploaded_by, DROP COLUMN uploaded_by_unknown, "
    "DROP COLUMN paper_submitted_by_unknown, DROP COLUMN row_version",
)


def _url(ten_db, driver):
    return make_url(settings.DATABASE_URL).set(drivername=driver, database=ten_db).render_as_string(hide_password=False)


async def _tao_db():
    ten = "qlts_test_gd1b_%s" % secrets.token_hex(4)
    assert kiem_url_csdl_test(_url(ten, "postgresql+asyncpg")) is None
    q = await asyncpg.connect(_url(make_url(settings.DATABASE_URL).database, "postgresql"))
    try:
        await q.execute('CREATE DATABASE "%s"' % ten)
    finally:
        await q.close()
    return ten


async def _xoa_db(ten):
    q = await asyncpg.connect(_url(make_url(settings.DATABASE_URL).database, "postgresql"))
    try:
        await q.execute('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % ten)
    finally:
        await q.close()


async def _create_all(ten):
    """Đúng hàm dựng lược đồ của bộ test (tạo ENUM trước ``create_all``), trỏ vào CSDL dùng một lần ``ten``."""
    from types import SimpleNamespace

    from tests.fixtures.database import init_schema_once

    await init_schema_once(SimpleNamespace(DATABASE_URL=_url(ten, "postgresql+asyncpg")), Base)


@pytest_asyncio.fixture
async def csdl_truoc():
    """CSDL ở phiên bản ``hdts20261113``: lược đồ model hiện tại trừ phần GĐ1b."""
    ten = await _tao_db()
    try:
        await _create_all(ten)
        k = await asyncpg.connect(_url(ten, "postgresql"))
        try:
            for s in GO_GD1B:
                await k.execute(s)
            await k.execute(
                "CREATE TABLE alembic_version (version_num varchar(32) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
            await k.execute("INSERT INTO alembic_version VALUES ($1)", TRUOC)
        finally:
            await k.close()
        yield ten
    finally:
        await _xoa_db(ten)


async def _alembic(ten_db, lenh, dich, co=None):
    env = dict(os.environ)
    env["DATABASE_URL"] = _url(ten_db, "postgresql+asyncpg")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("GD1B_DOWNGRADE_DROP_DATA_ENABLED", None)
    if co is not None:
        env[co[0]] = co[1]
    p = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "alembic", lenh, dich, cwd=str(GOC), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await asyncio.wait_for(p.communicate(), 120)
    return p.returncode, out.decode("utf-8", "replace")


async def _phien_ban(k):
    return await k.fetchval("SELECT version_num FROM alembic_version")


# --------------------------------------------------------------------------------------------------------------------
# Dữ liệu mẫu — chèn ở chế độ replica (bỏ khoá ngoại / trigger) để khỏi dựng cả chuỗi lead → hồ sơ.
# --------------------------------------------------------------------------------------------------------------------
async def _user(k, ten):
    return await k.fetchval(
        'INSERT INTO "user" (username, email, password_hash, role, total_lead_score) '
        "VALUES ($1, $2, 'x', 'officer', 0) RETURNING id",
        ten,
        ten + "@example.com",
    )


async def _giay(k, profile_id, *, file_path=None, status="uploaded", paper_by=None, category="path"):
    return await k.fetchval(
        "INSERT INTO profile_document (profile_id, document_type_id, category, priority_sub_code, status, file_path, "
        "paper_submitted_by, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, now(), now()) RETURNING id",
        profile_id,
        None if category != "path" else next(_LOAI_GIAY),
        category,
        "04" if category != "path" else None,
        status,
        file_path,
        paper_by,
    )


async def _nhat_ky(k, doc_id, action, actor, *, new_file_path=None, giay_truoc=0):
    return await k.fetchval(
        "INSERT INTO document_audit_log (profile_document_id, action, actor_user_id, new_file_path, created_at) "
        "VALUES ($1, $2, $3, $4, now() - make_interval(secs => $5)) RETURNING id",
        doc_id, action, actor, new_file_path, float(giay_truoc),
    )


async def _cot(k, doc_id):
    return await k.fetchrow(
        "SELECT uploaded_by, uploaded_by_unknown, paper_submitted_by_unknown, row_version FROM profile_document "
        "WHERE id = $1",
        doc_id,
    )


async def _luoc_do(k):
    """Phần lược đồ GĐ1b: cột, ràng buộc, chỉ mục, trigger, thân hàm."""
    bang = list(BANG_MOI) + ["profile_document"]
    cot = await k.fetch(
        "SELECT table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = ANY($1) ORDER BY 1, 2",
        bang,
    )
    rb = await k.fetch(
        "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid::regclass::text = ANY($1) ORDER BY 1, 2",
        bang,
    )
    cm = await k.fetch(
        "SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename = ANY($1) "
        "ORDER BY 1, 2",
        bang,
    )
    tg = await k.fetch(
        "SELECT tgname, pg_get_triggerdef(oid) FROM pg_trigger WHERE tgrelid = 'profile_document'::regclass "
        "AND NOT tgisinternal ORDER BY 1"
    )
    ham = await k.fetchval("SELECT prosrc FROM pg_proc WHERE proname = 'profile_document_bump_row_version'")
    return (
        [tuple(r) for r in cot],
        [tuple(r) for r in rb],
        [tuple(r) for r in cm],
        [tuple(r) for r in tg],
        " ".join((ham or "").split()),
    )


async def test_nang_cap_khoi_phuc_nguoi_tai_dau_tai_bang_chung_va_luoc_do_khop_model(csdl_truoc):
    ten = csdl_truoc
    k = await asyncpg.connect(_url(ten, "postgresql"))
    thu_muc = GOC / "uploads" / "admissions" / "990001"
    tep_co = thu_muc / "da-duyet.pdf"
    try:
        await k.execute("SET session_replication_role = replica")
        a = await _user(k, "gd1b_mig_a")
        b = await _user(k, "gd1b_mig_b")
        # (1) tải đúng tệp, sau đó chỉ có tải xuống / duyệt ⇒ khôi phục được (lọc theo hành động ĐỔI TỆP).
        d1 = await _giay(k, 990001, file_path="uploads/admissions/990001/a.pdf")
        await _nhat_ky(k, d1, "uploaded", a, new_file_path="uploads/admissions/990001/a.pdf", giay_truoc=30)
        await _nhat_ky(k, d1, "downloaded", b, giay_truoc=20)
        # (2) bản ghi tải trỏ tệp khác ⇒ không rõ.
        d2 = await _giay(k, 990001, file_path="uploads/admissions/990001/b.pdf")
        await _nhat_ky(k, d2, "uploaded", a, new_file_path="uploads/admissions/990001/khac.pdf", giay_truoc=30)
        # (3) sự kiện đổi tệp mới nhất là reset ⇒ không rõ.
        d3 = await _giay(k, 990001, file_path="uploads/admissions/990001/c.pdf")
        await _nhat_ky(k, d3, "uploaded", a, new_file_path="uploads/admissions/990001/c.pdf", giay_truoc=30)
        await _nhat_ky(k, d3, "reset", b, giay_truoc=10)
        # (4) không nhật ký ⇒ không rõ.
        d4 = await _giay(k, 990001, file_path="uploads/admissions/990001/d.pdf")
        # (5) actor NULL ⇒ không rõ.
        d5 = await _giay(k, 990001, file_path="uploads/admissions/990001/e.pdf")
        await _nhat_ky(k, d5, "uploaded", None, new_file_path="uploads/admissions/990001/e.pdf", giay_truoc=30)
        # (6) bản giấy đã nhận mất người nhận ⇒ cờ; (7) còn người nhận ⇒ không cờ.
        d6 = await _giay(k, 990001, status="paper_submitted")
        d7 = await _giay(k, 990001, status="paper_submitted", paper_by=b)
        # (8) minh chứng ưu tiên có tệp, không người tải ⇒ KHÔNG đụng (I1 chỉ giấy thường).
        d8 = await _giay(k, 990001, file_path="uploads/admissions/990001/ut.pdf", category="priority_evidence")
        # (9) giấy đã duyệt có tệp TRÊN ĐĨA + nhật ký verified ⇒ dòng bằng chứng có sha256.
        thu_muc.mkdir(parents=True, exist_ok=True)
        noi_dung = b"gd1b-bang-chung-" + secrets.token_bytes(8)
        tep_co.write_bytes(noi_dung)
        d9 = await _giay(k, 990001, file_path="uploads/admissions/990001/da-duyet.pdf", status="verified")
        await _nhat_ky(k, d9, "uploaded", a, new_file_path="uploads/admissions/990001/da-duyet.pdf", giay_truoc=30)
        v9 = await _nhat_ky(k, d9, "verified", b, giay_truoc=5)
        # (10) giấy đã duyệt có tệp KHÔNG còn trên đĩa ⇒ bằng chứng file_missing.
        d10 = await _giay(k, 990001, file_path="uploads/admissions/990001/mat.pdf", status="verified")
        await _nhat_ky(k, d10, "uploaded", a, new_file_path="uploads/admissions/990001/mat.pdf", giay_truoc=30)
        v10 = await _nhat_ky(k, d10, "verified", b, giay_truoc=5)
        # Tải xuống: 2 dòng có actor (d1 ở trên + d4), 1 dòng không actor.
        await _nhat_ky(k, d4, "downloaded", a, giay_truoc=3)
        await _nhat_ky(k, d4, "downloaded", None, giay_truoc=2)
        await k.execute("SET session_replication_role = origin")

        rc, out = await _alembic(ten, "upgrade", SAU)
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == SAU

        assert tuple(await _cot(k, d1)) == (a, False, False, 1)
        for d in (d2, d3, d4, d5):
            assert tuple(await _cot(k, d))[:3] == (None, True, False), d
        assert tuple(await _cot(k, d6))[:3] == (None, False, True)
        assert tuple(await _cot(k, d7))[:3] == (None, False, False)
        assert tuple(await _cot(k, d8))[:3] == (None, False, False)
        assert tuple(await _cot(k, d9))[:3] == (a, False, False)

        tai = await k.fetch(
            "SELECT actor_user_id, document_row_id FROM document_download_log ORDER BY document_row_id"
        )
        assert [tuple(r) for r in tai] == [(b, d1), (a, d4)]

        bc = {
            r["profile_document_id"]: r
            for r in await k.fetch(
                "SELECT profile_document_id, verification_audit_id, sha256, file_missing FROM document_evidence_file"
            )
        }
        assert set(bc) == {d9, d10}
        assert (bc[d9]["verification_audit_id"], bc[d9]["sha256"], bc[d9]["file_missing"]) == (
            v9, hashlib.sha256(noi_dung).hexdigest(), False,
        )
        assert (bc[d10]["verification_audit_id"], bc[d10]["sha256"], bc[d10]["file_missing"]) == (v10, None, True)

        # Trigger row_version sống sau nâng cấp.
        await k.execute("UPDATE profile_document SET rejection_reason = 'x' WHERE id = $1", d1)
        assert (await _cot(k, d1))["row_version"] == 2

        # Lược đồ GĐ1b sau nâng cấp == lược đồ dựng thẳng từ model.
        ten_mau = await _tao_db()
        try:
            await _create_all(ten_mau)
            km = await asyncpg.connect(_url(ten_mau, "postgresql"))
            try:
                mau = await _luoc_do(km)
            finally:
                await km.close()
        finally:
            await _xoa_db(ten_mau)
        that = await _luoc_do(k)
        for i, ten_phan in enumerate(("cột", "ràng buộc", "chỉ mục", "trigger", "thân hàm")):
            assert that[i] == mau[i], ten_phan
    finally:
        await k.close()
        if tep_co.exists():
            tep_co.unlink()
        if thu_muc.exists():
            thu_muc.rmdir()


async def test_i1_tu_choi_giay_duyet_co_tep_khong_nguoi_tai_hoi_tu_phien_rieng(csdl_truoc):
    ten = csdl_truoc
    rc, out = await _alembic(ten, "upgrade", SAU)
    assert rc == 0, out[-3000:]
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        await k.execute("SET session_replication_role = replica")  # bỏ khoá ngoại; CHECK vẫn chạy
        with pytest.raises(asyncpg.CheckViolationError) as e:
            await _giay(k, 990002, file_path="uploads/admissions/990002/x.pdf", status="verified")
        assert e.value.constraint_name == "ck_profile_document_uploader_known"
        # Minh chứng ưu tiên: I1 không áp (F356).
        await _giay(k, 990002, file_path="uploads/admissions/990002/ut.pdf", category="priority_evidence")
    finally:
        await k.close()


async def test_giay_duyet_co_tep_khong_nhat_ky_verified_thi_dung_va_khong_con_gi_do_dang(csdl_truoc):
    ten = csdl_truoc
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        await k.execute("SET session_replication_role = replica")
        await _giay(k, 990003, file_path="uploads/admissions/990003/khong-nk.pdf", status="verified")
        await k.execute("SET session_replication_role = origin")
        rc, out = await _alembic(ten, "upgrade", SAU)
        assert rc != 0
        assert "QLB05" in out, out[-3000:]  # SQLSTATE riêng: giấy đã duyệt có tệp mà không có nhật ký verified
        # Câu DO rollback TRỌN: phiên bản giữ nguyên, không bảng / cột nào của GĐ1b còn lại.
        assert await _phien_ban(k) == TRUOC
        for bang in BANG_MOI:
            assert await k.fetchval("SELECT to_regclass($1)", bang) is None, bang
        assert await k.fetchval(
            "SELECT count(*) FROM information_schema.columns WHERE table_name = 'profile_document' "
            "AND column_name IN ('uploaded_by','uploaded_by_unknown','paper_submitted_by_unknown','row_version')"
        ) == 0
    finally:
        await k.close()


async def test_ha_cap_con_du_lieu_thi_dung_khong_xoa_gi(csdl_truoc):
    ten = csdl_truoc
    rc, out = await _alembic(ten, "upgrade", SAU)
    assert rc == 0, out[-3000:]
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        a = await _user(k, "gd1b_mig_ha")
        await k.execute(
            "INSERT INTO document_download_log (actor_user_id, profile_id, document_row_id) VALUES ($1, 1, 1)", a
        )
        rc, out = await _alembic(ten, "downgrade", TRUOC)
        assert rc != 0
        assert "GD1BDataPresent" in out, out[-3000:]
        assert await _phien_ban(k) == SAU
        assert await k.fetchval("SELECT count(*) FROM document_download_log") == 1
        # Rỗng ⇒ hạ được.
        await k.execute("DELETE FROM document_download_log")
        rc, out = await _alembic(ten, "downgrade", TRUOC)
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == TRUOC
        for bang in BANG_MOI:
            assert await k.fetchval("SELECT to_regclass($1)", bang) is None, bang
    finally:
        await k.close()
