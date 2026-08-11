"""Migration `mkchk20260811` phải CHẠY ĐƯỢC và tạo ra đúng trạng thái.

Vì sao cần bộ này bên cạnh bộ AST ở `tests/unit`: bộ kia chỉ đọc *literal*
trong file migration. Nó vẫn xanh nếu ai đó xoá sạch vòng `INSERT` trong
`upgrade()` mà giữ lại hằng `_POLICIES`, và nó không biết migration có nằm trên
đường tới `head` hay không. Nói cách khác nó đo "có khai báo", không đo "có
hiệu lực".

Bộ này đo hiệu lực, theo đúng cách deploy làm: dựng một CSDL trắng, chạy
`alembic upgrade head` như một tiến trình thật, rồi hỏi chính CSDL đó ba câu:

1. hai dòng policy manager có tồn tại với ``v3='allow'`` không;
2. CHECK constraint có tồn tại ở dạng NOT VALID (``convalidated = false``) —
   NOT VALID là chủ ý: dữ liệu lịch sử có thể đã bẩn, và chặn deploy vì hàng cũ
   nghĩa là để ngỏ lỗ hổng cho hàng mới;
3. một bản ghi MỚI có ``rejected_by_id = created_by_id`` có bị CSDL từ chối
   không — NOT VALID vẫn kiểm mọi hàng mới, và đây là thứ duy nhất chứng minh
   hàng rào tầng CSDL thật sự đứng đó.

Câu 3 chèn thẳng vào ``payment`` với ``session_replication_role = replica`` để
tắt kiểm khoá ngoại: ta đang đo CHECK constraint, không đo FK, và dựng đủ chuỗi
lead → profile → fee → invoice chỉ để chạm vào nó sẽ làm bộ test vỡ mỗi lần một
bảng không liên quan đổi cột NOT NULL.
"""

import os
import subprocess
import uuid
from pathlib import Path

import asyncpg
import pytest

#  của CI là mức cho ca thường. Mỗi ca ở đây dựng một CSDL trắng
# rồi chạy TOÀN BỘ chuỗi migration (~290 revision) — công việc phút, không phải
# giây. Nới hạn ngay tại đây thay vì hạ  toàn shard, để mọi ca khác
# vẫn bị giữ ở mức nghiêm.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.timeout(600),
]

_MARKER = "mkchk20260811"

# 🔴 KHÔNG hard-code "/app". Đó là đường dẫn bên trong container dev; CI chạy
# pytest trực tiếp với , nên  không
# tồn tại và cả ba helper alembic đổ — shard đỏ đúng ở chỗ bộ test này lẽ ra
# phải bảo vệ.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_ROUTES = ("/api/payments/{id}/verify", "/api/payments/{id}/reject")


def _dsn_asyncpg(url: str, dbname: str) -> str:
    """`postgresql+asyncpg://u:p@host:port/<db>` → DSN thuần cho asyncpg."""
    tho = url.split("://", 1)[1]
    phan_dau = tho.rsplit("/", 1)[0]
    return f"postgresql://{phan_dau}/{dbname}"


@pytest.fixture
def url_goc() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("Không có DATABASE_URL — bộ này cần một PostgreSQL thật")
    return url


@pytest.fixture
async def db_trang(url_goc: str):
    """Một CSDL trắng, tự xoá sau khi xong. KHÔNG đụng dev/test DB."""
    ten = f"qlts_mkchk_{uuid.uuid4().hex[:8]}"
    quan_tri = await asyncpg.connect(_dsn_asyncpg(url_goc, "postgres"))
    try:
        await quan_tri.execute(f'CREATE DATABASE "{ten}"')
    finally:
        await quan_tri.close()

    try:
        yield ten
    finally:
        quan_tri = await asyncpg.connect(_dsn_asyncpg(url_goc, "postgres"))
        try:
            # Ngắt mọi kết nối còn sót, nếu không DROP sẽ treo.
            await quan_tri.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
                ten,
            )
            await quan_tri.execute(f'DROP DATABASE IF EXISTS "{ten}"')
        finally:
            await quan_tri.close()


def _chay_alembic(url_goc: str, dbname: str) -> subprocess.CompletedProcess:
    """Chạy đúng câu lệnh mà deploy chạy — tiến trình thật, không import lén."""
    moi_truong = dict(os.environ)
    phan_dau = url_goc.rsplit("/", 1)[0]
    moi_truong["DATABASE_URL"] = f"{phan_dau}/{dbname}"
    return subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=_BACKEND_ROOT,
        env=moi_truong,
        capture_output=True,
        text=True,
        timeout=900,
    )


async def test_migration_tao_dung_trang_thai(url_goc: str, db_trang: str):
    kq = _chay_alembic(url_goc, db_trang)
    assert kq.returncode == 0, (
        f"`alembic upgrade head` THẤT BẠI trên CSDL trắng.\n"
        f"stdout:\n{kq.stdout[-3000:]}\n\nstderr:\n{kq.stderr[-3000:]}"
    )

    conn = await asyncpg.connect(_dsn_asyncpg(url_goc, db_trang))
    try:
        # (1) hai dòng policy manager, đúng effect, có dấu vết chủ sở hữu
        for route in _ROUTES:
            row = await conn.fetchrow(
                """
                SELECT v3, template_id FROM casbin_rule
                WHERE ptype = 'p' AND v0 = 'role:manager'
                  AND v1 = $1 AND v2 = 'PUT'
                """,
                route,
            )
            assert row is not None, (
                f"KHÔNG có policy cho (role:manager, {route}, PUT) sau khi "
                "migration chạy — enforcer sẽ DENY và manager 403."
            )
            assert row["v3"] == "allow", (
                f"policy ({route}) có v3={row['v3']!r}, không phải 'allow' — "
                "hàng lệch effect không mở được quyền."
            )
            assert row["template_id"] == _MARKER

        # (2) constraint tồn tại và ở dạng NOT VALID
        rec = await conn.fetchrow(
            """
            SELECT convalidated FROM pg_constraint
            WHERE conname = 'chk_payment_no_self_reject'
              AND conrelid = 'payment'::regclass
            """
        )
        assert rec is not None, "thiếu constraint chk_payment_no_self_reject"
        assert rec["convalidated"] is False, (
            "constraint phải ở dạng NOT VALID: dữ liệu lịch sử có thể đã có vi "
            "phạm, và VALIDATE ngay sẽ làm migration đổ ở chính môi trường cần "
            "vá nhất."
        )

        # (3) hàng MỚI vi phạm phải bị CSDL từ chối
        await conn.execute("SET session_replication_role = replica")
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await conn.execute(
                """
                INSERT INTO payment
                    (invoice_id, method_id, amount, status,
                     created_by_id, rejected_by_id, created_at, updated_at)
                VALUES (1, 1, 1000, 'rejected', 42, 42, now(), now())
                """
            )

        # …và cùng bản ghi ấy với checker KHÁC người ghi thì phải vào được:
        # nếu không, constraint đang chặn nhầm cả đường hợp lệ.
        await conn.execute(
            """
            INSERT INTO payment
                (invoice_id, method_id, amount, status,
                 created_by_id, rejected_by_id, created_at, updated_at)
            VALUES (1, 1, 1000, 'rejected', 42, 43, now(), now())
            """
        )
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Hình dạng hàng có sẵn — ba ca mà bản migration đầu tiên làm sai
# ---------------------------------------------------------------------------

_TRUOC = "dbte20260803002"  # revision ngay trước mkchk


def _chay_alembic_toi(url_goc: str, dbname: str, rev: str):
    moi_truong = dict(os.environ)
    phan_dau = url_goc.rsplit("/", 1)[0]
    moi_truong["DATABASE_URL"] = f"{phan_dau}/{dbname}"
    return subprocess.run(
        ["alembic", "upgrade", rev],
        cwd=_BACKEND_ROOT,
        env=moi_truong,
        capture_output=True,
        text=True,
        timeout=900,
    )


def _downgrade(url_goc: str, dbname: str, rev: str):
    moi_truong = dict(os.environ)
    phan_dau = url_goc.rsplit("/", 1)[0]
    moi_truong["DATABASE_URL"] = f"{phan_dau}/{dbname}"
    return subprocess.run(
        ["alembic", "downgrade", rev],
        cwd=_BACKEND_ROOT,
        env=moi_truong,
        capture_output=True,
        text=True,
        timeout=900,
    )


async def test_hang_v3_null_lam_migration_dung_lai(url_goc: str, db_trang: str):
    """v3 IS NULL phải làm migration DỪNG, không phải "thêm allow bên cạnh".

    Adapter tuần tự hoá hàng NULL thành policy BA trường; enforcer nạp nó vào
    model bốn trường rồi enforce() ném invalid policy size — toàn bộ
    authorization 500. Thêm một dòng allow đúng hình dạng KHÔNG chữa được, vì
    dòng hỏng vẫn nằm đó.

    Bản trước của bộ này chỉ đếm so_allow == 1 nên xanh trong khi runtime
    sẽ đổ — đúng loại "xanh vì đo nhầm thứ".
    """
    assert _chay_alembic_toi(url_goc, db_trang, _TRUOC).returncode == 0

    conn = await asyncpg.connect(_dsn_asyncpg(url_goc, db_trang))
    try:
        await conn.execute(
            "INSERT INTO casbin_rule (ptype, v0, v1, v2, v3) "
            "VALUES ('p', 'role:manager', $1, 'PUT', NULL)",
            _ROUTES[0],
        )
    finally:
        await conn.close()

    kq = _chay_alembic_toi(url_goc, db_trang, "head")
    assert kq.returncode != 0, (
        "migration phải DỪNG khi gặp hàng v3 IS NULL — thêm allow bên cạnh chỉ "
        "để lại một policy ba trường làm enforce() ném invalid policy size"
    )
    assert "invalid policy size" in (kq.stdout + kq.stderr).lower()


async def test_co_deny_thi_migration_dung_lai(url_goc: str, db_trang: str):
    """DENY cố ý phải làm migration DỪNG, không âm thầm thêm allow bên cạnh."""
    assert _chay_alembic_toi(url_goc, db_trang, _TRUOC).returncode == 0

    conn = await asyncpg.connect(_dsn_asyncpg(url_goc, db_trang))
    try:
        await conn.execute(
            "INSERT INTO casbin_rule (ptype, v0, v1, v2, v3) "
            "VALUES ('p', 'role:manager', $1, 'PUT', 'deny')",
            _ROUTES[1],
        )
    finally:
        await conn.close()

    kq = _chay_alembic_toi(url_goc, db_trang, "head")
    assert kq.returncode != 0, (
        "migration phải DỪNG khi gặp deny cố ý, không được ghi allow bên cạnh"
    )
    assert "deny" in (kq.stdout + kq.stderr).lower()


async def test_downgrade_khong_xoa_policy_cua_nguoi_khac(
    url_goc: str, db_trang: str
):
    """Downgrade chỉ gỡ dòng do CHÍNH migration này đặt vào.

    Bản đầu xoá theo (v0, v1, v2) nên cuốn theo cả allow đã tồn tại từ trước —
    downgrade lấy đi quyền mà nó chưa bao giờ cấp.
    """
    assert _chay_alembic_toi(url_goc, db_trang, _TRUOC).returncode == 0

    conn = await asyncpg.connect(_dsn_asyncpg(url_goc, db_trang))
    try:
        # Ai đó đã sync tay từ trước — không mang marker của migration này.
        await conn.execute(
            "INSERT INTO casbin_rule (ptype, v0, v1, v2, v3) "
            "VALUES ('p', 'role:manager', $1, 'PUT', 'allow')",
            _ROUTES[0],
        )
    finally:
        await conn.close()

    assert _chay_alembic_toi(url_goc, db_trang, "head").returncode == 0
    assert _downgrade(url_goc, db_trang, _TRUOC).returncode == 0

    conn = await asyncpg.connect(_dsn_asyncpg(url_goc, db_trang))
    try:
        con_lai = await conn.fetchval(
            "SELECT count(*) FROM casbin_rule WHERE ptype='p' "
            "AND v0='role:manager' AND v1=$1 AND v2='PUT' AND v3='allow'",
            _ROUTES[0],
        )
        assert con_lai == 1, (
            "downgrade đã xoá cả dòng allow có sẵn từ trước — nó chỉ được gỡ "
            "đúng dòng mang template_id của mình"
        )
    finally:
        await conn.close()


async def test_enforcer_that_cho_manager_qua(url_goc: str, db_trang: str):
    """Policy migration tạo ra phải ENFORCE được, không chỉ tồn tại trong SQL.

    Đếm dòng trong `casbin_rule` không chứng minh authorization chạy: hàng sai
    hình dạng vẫn "có mặt" trong bảng mà làm `enforce()` ném. Ca này nạp bằng
    chính `AsyncEnforcer` + adapter mà ứng dụng dùng, rồi hỏi đúng câu ứng dụng
    hỏi.
    """
    import casbin
    from casbin_async_sqlalchemy_adapter import Adapter as AsyncCasbinAdapter
    from sqlalchemy.ext.asyncio import create_async_engine

    assert _chay_alembic(url_goc, db_trang).returncode == 0

    phan_dau = url_goc.rsplit("/", 1)[0]
    engine = create_async_engine(f"{phan_dau}/{db_trang}")
    try:
        adapter = AsyncCasbinAdapter(engine)
        model_path = _BACKEND_ROOT / "auth_model.conf"
        assert model_path.exists(), f"không thấy {model_path}"

        enforcer = casbin.AsyncEnforcer(str(model_path), adapter)
        await enforcer.load_policy()

        for route in _ROUTES:
            assert enforcer.enforce("role:manager", route, "PUT") is True, (
                f"enforcer TỪ CHỐI (role:manager, {route}, PUT) dù policy đã "
                "nằm trong bảng — hàng có mặt không đồng nghĩa với enforce được"
            )
    finally:
        await engine.dispose()
