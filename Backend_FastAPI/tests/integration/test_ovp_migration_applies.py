"""Migration `ovp20260811` phải chạy được và tạo đúng hai hàng rào.

Cùng lý do với `test_mkchk_migration_applies.py`: một bộ test đọc *literal*
trong file migration vẫn xanh khi phần thi hành bị gỡ. Bộ này chạy
`alembic upgrade head` như deploy chạy, trên một CSDL trắng, rồi hỏi chính CSDL
đó.

Hai hàng rào được kiểm:

* ``uq_overpayment_payment`` — một phiếu thu chỉ sinh đúng một khoản thừa;
* ``chk_overpayment_source_type_valid`` + cột ``source_type``.

Và một hành vi quan trọng hơn cả hai: khi dữ liệu cũ ĐÃ có hai hàng cùng
``payment_id``, migration phải **dừng** chứ không xoá bớt. Đây là sổ nợ — mỗi
hàng là một khoản tiền của người học, không phải rác dọn được.
"""

import os
import subprocess
import uuid
from pathlib import Path

import asyncpg
import pytest

# Mỗi ca dựng CSDL trắng rồi chạy toàn bộ chuỗi migration — công việc phút.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.timeout(600),
]

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_TRUOC = "mrg20260811"


def _dsn(url: str, dbname: str) -> str:
    tho = url.split("://", 1)[1]
    return f"postgresql://{tho.rsplit('/', 1)[0]}/{dbname}"


def _alembic(url: str, dbname: str, rev: str) -> subprocess.CompletedProcess:
    moi_truong = dict(os.environ)
    moi_truong["DATABASE_URL"] = f"{url.rsplit('/', 1)[0]}/{dbname}"
    return subprocess.run(
        ["alembic", "upgrade", rev],
        cwd=_BACKEND_ROOT,
        env=moi_truong,
        capture_output=True,
        text=True,
        timeout=900,
    )


@pytest.fixture
def url_goc() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("Không có DATABASE_URL — bộ này cần một PostgreSQL thật")
    return url


@pytest.fixture
async def db_trang(url_goc: str):
    ten = f"qlts_ovp_{uuid.uuid4().hex[:8]}"
    qt = await asyncpg.connect(_dsn(url_goc, "postgres"))
    try:
        await qt.execute(f'CREATE DATABASE "{ten}"')
    finally:
        await qt.close()
    try:
        yield ten
    finally:
        qt = await asyncpg.connect(_dsn(url_goc, "postgres"))
        try:
            await qt.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
                ten,
            )
            await qt.execute(f'DROP DATABASE IF EXISTS "{ten}"')
        finally:
            await qt.close()


async def test_migration_tao_dung_hai_hang_rao(url_goc: str, db_trang: str):
    kq = _alembic(url_goc, db_trang, "head")
    assert kq.returncode == 0, (
        f"`alembic upgrade head` thất bại.\n{kq.stdout[-2000:]}\n{kq.stderr[-2000:]}"
    )

    conn = await asyncpg.connect(_dsn(url_goc, db_trang))
    try:
        ten_rb = [
            r["conname"]
            for r in await conn.fetch(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'overpayment_record'::regclass"
            )
        ]
        assert "uq_overpayment_payment" in ten_rb
        assert "chk_overpayment_source_type_valid" in ten_rb

        cot = await conn.fetchval(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'overpayment_record' AND column_name = 'source_type'"
        )
        assert cot == "source_type"

        # UNIQUE phải THẬT SỰ chặn, không chỉ tồn tại trong catalog.
        await conn.execute("SET session_replication_role = replica")
        await conn.execute(
            "INSERT INTO overpayment_record (payment_id, invoice_id, "
            "admission_profile_id, overpayment_amount, currency, status, "
            "created_at, updated_at) VALUES "
            "(1, 1, 1, 1000, 'VND', 'pending', now(), now())"
        )
        with pytest.raises(asyncpg.exceptions.UniqueViolationError):
            await conn.execute(
                "INSERT INTO overpayment_record (payment_id, invoice_id, "
                "admission_profile_id, overpayment_amount, currency, status, "
                "created_at, updated_at) VALUES "
                "(1, 1, 1, 2000, 'VND', 'pending', now(), now())"
            )

        # source_type lạ phải bị CHECK từ chối.
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await conn.execute(
                "INSERT INTO overpayment_record (payment_id, invoice_id, "
                "admission_profile_id, overpayment_amount, currency, status, "
                "source_type, created_at, updated_at) VALUES "
                "(2, 1, 1, 1000, 'VND', 'pending', 'bia_ra', now(), now())"
            )
    finally:
        await conn.close()


async def test_du_lieu_cu_trung_thi_migration_dung_lai(url_goc: str, db_trang: str):
    """Hai hàng cùng ``payment_id`` ⇒ DỪNG, và KHÔNG xoá hàng nào.

    Nếu migration tự dọn cho `ADD CONSTRAINT` chạy được, nó xoá mất một khoản
    nợ có thật mà không ai duyệt.
    """
    assert _alembic(url_goc, db_trang, _TRUOC).returncode == 0

    conn = await asyncpg.connect(_dsn(url_goc, db_trang))
    try:
        await conn.execute("SET session_replication_role = replica")
        await conn.execute(
            "INSERT INTO overpayment_record (payment_id, invoice_id, "
            "admission_profile_id, overpayment_amount, currency, status, "
            "created_at, updated_at) VALUES "
            "(99, 1, 1, 1000, 'VND', 'pending', now(), now()), "
            "(99, 1, 1, 2000, 'VND', 'pending', now(), now())"
        )
    finally:
        await conn.close()

    kq = _alembic(url_goc, db_trang, "head")
    assert kq.returncode != 0, "migration phải dừng khi dữ liệu cũ đã trùng"
    assert "payment_id" in (kq.stdout + kq.stderr)

    conn = await asyncpg.connect(_dsn(url_goc, db_trang))
    try:
        con_lai = await conn.fetchval(
            "SELECT count(*) FROM overpayment_record WHERE payment_id = 99"
        )
        assert con_lai == 2, "migration đã xoá bớt sổ nợ — tuyệt đối không được"
    finally:
        await conn.close()
