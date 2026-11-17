"""GĐ1b lô — sổ khoá tư vấn + kết nối L + đường dẫn route, trên CSDL / ứng dụng THẬT (đặc tả bản 3.6 §5.3, F374; hợp đồng
bản 4 §2.1 "khác 815074 và khác hai hashtext(...) đang có").
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text
from starlette.routing import Match

import app.database as csdl
from app.core import advisory_lock_keys as keys
from tests.api.test_gd1b_lo_tro_giup import khoa_vung_lo, lo_routers  # noqa: F401

pytestmark = pytest.mark.asyncio


async def test_vung_khoa_moi_khac_hashtext_cua_cac_vung_dang_co(setup_test_database):
    async with csdl.engine.connect() as k:
        cu = {
            (await k.execute(text("SELECT hashtext(:t)"), {"t": t})).scalar() for t in keys.EXISTING_HASHTEXT_NAMESPACES
        }
    assert len(cu) == len(keys.EXISTING_HASHTEXT_NAMESPACES)
    assert not cu & set(keys.REGISTERED_NAMESPACES), cu


async def test_ket_noi_L_autocommit_khong_treo_giao_dich_va_nha_het_khoa(setup_test_database):
    from app.repositories import document_bulk_repository as repo

    k = keys.batch_lock_key(uuid.uuid4())
    lock = await repo.try_lock_batch(keys.BULK_VERIFY_BATCH_NS, k)
    assert lock is not None
    try:
        assert await repo.batch_lock_alive(lock) is True
        assert await repo.try_lock_batch(keys.BULK_VERIFY_BATCH_NS, k) is None, "phiên khác không lấy được khoá đang giữ"
        async with csdl.engine.connect() as c:
            st = (await c.execute(text("SELECT state FROM pg_stat_activity WHERE pid = :p"), {"p": lock.pid})).scalar()
        assert st == "idle", f"L phải AUTOCOMMIT (không 'idle in transaction'): {st}"
    finally:
        await repo.release_batch_lock(lock)
    assert [x for x in await khoa_vung_lo() if x["k"] == k] == []
    # NullPool: ``close()`` là ngắt vật lý — tiến trình phục vụ của L phải biến mất (chờ tối đa 2 s cho việc thoát).
    con = None
    for _ in range(40):
        async with csdl.engine.connect() as c:
            con = (await c.execute(text("SELECT count(*) FROM pg_stat_activity WHERE pid = :p"), {"p": lock.pid})).scalar()
        if con == 0:
            break
        await asyncio.sleep(0.05)
    assert con == 0


async def test_duong_dan_moi_khong_bi_route_cu_chan(client, lo_routers):
    """Router mới gắn SAU các router cũ (như Claude sẽ đăng ký): route đầu tiên khớp đầy đủ mỗi đường mới phải là route mới
    (tham số kiểu ``int`` của route cũ không được nuốt ``documents`` / ``cross-review``)."""
    from app.routers import document_bulk_verify, document_cross_review

    moi = {document_bulk_verify.__name__, document_cross_review.__name__}
    ma = str(uuid.uuid4())
    duong = [
        ("POST", "/api/admissions/documents/bulk-verify/preview"),
        ("POST", f"/api/admissions/documents/bulk-verify/{ma}/execute"),
        ("GET", f"/api/admissions/documents/bulk-verify/{ma}"),
        ("POST", f"/api/admissions/documents/bulk-verify/{ma}/finalize"),
        ("GET", "/api/admissions/documents/bulk-verify"),
        ("POST", "/api/admissions/cross-review/grants"),
        ("GET", "/api/admissions/cross-review/grants"),
        ("POST", "/api/admissions/cross-review/grants/7/revoke"),
        ("GET", "/api/admissions/cross-review/eligibility"),
        ("GET", "/api/admissions/cross-review/queue"),
        ("POST", "/api/admissions/cross-review/verify"),
        ("POST", "/api/admissions/cross-review/reject"),
        ("POST", "/api/admissions/cross-review/bulk-verify/preview"),
        ("POST", f"/api/admissions/cross-review/bulk-verify/{ma}/execute"),
        ("GET", f"/api/admissions/cross-review/bulk-verify/{ma}"),
        ("POST", f"/api/admissions/cross-review/bulk-verify/{ma}/finalize"),
        ("GET", "/api/admissions/cross-review/bulk-verify"),
    ]
    for method, path in duong:
        scope = {"type": "http", "method": method, "path": path, "root_path": "", "query_string": b"", "headers": []}
        dau = None
        for route in lo_routers.router.routes:
            m, _ = route.matches(scope)
            if m == Match.FULL:
                dau = route
                break
        assert dau is not None, (method, path)
        assert getattr(dau.endpoint, "__module__", None) in moi, (method, path, getattr(dau, "path", None))
