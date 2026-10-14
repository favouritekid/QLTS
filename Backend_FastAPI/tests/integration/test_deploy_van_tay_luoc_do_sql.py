"""Chạy THẬT các câu SQL mà Step 4c của `scripts/deploy.sh` gửi vào PostgreSQL.

Vì sao tệp này tồn tại
----------------------
Bộ `test_deploy_*` chạy deploy.sh với stub `docker` ⇒ không một câu SQL nào của
4c thật sự tới PostgreSQL. Diễn tập LOCAL vòng 2 (12-10-2026) đã bắt được đúng
lỗ ấy: câu vân tay lược đồ đầu tiên đổ trên PG16 thật với
`operator is not unique: text || "char"` (cột `relkind`/`contype`… kiểu "char")
— mọi ca stub vẫn xanh. Lỗi đó ở prod nghĩa là MỌI lượt deploy dừng ở 4c.

Tệp này nạp CHÍNH chuỗi SQL từ deploy.sh (không chép tay) và chạy trên CSDL test:
  * vân tay chạy được, ổn định giữa hai lần đọc, không dòng nào chứa xuống dòng;
  * vân tay ĐỔI khi có bảng mới / cột mới (đúng ca F35: migration hỏng để lại
    object) và trở về y nguyên sau ROLLBACK;
  * ba câu đo còn lại (phiên lạ, bộ đếm bảng, pg_stat_database) chạy được và
    trả đúng hình dạng mà deploy.sh kiểm.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import text

from app.database import AsyncSessionLocal

pytestmark = pytest.mark.asyncio


def _tim_deploy_sh() -> Path:
    for thu_muc in Path(__file__).resolve().parents:
        p = thu_muc / "scripts" / "deploy.sh"
        if p.is_file() and (thu_muc / "docker-compose.yml").is_file():
            return p
    pytest.skip("không thấy scripts/deploy.sh (cần gốc repo)", allow_module_level=True)


_DEPLOY = _tim_deploy_sh().read_text(encoding="utf-8")


def _bien_bash(ten: str) -> str:
    """Lấy giá trị `ten="..."` (một chuỗi nháy kép, có thể nhiều dòng) từ deploy.sh.

    Chuỗi này cố ý KHÔNG chứa `"`, `$`, backtick, `\\` trước ký tự đặc biệt của
    bash ⇒ nội dung giữa hai dấu nháy CHÍNH LÀ câu SQL bash gửi đi. Kiểm lại điều
    đó ở đây để một bản sửa sau này không âm thầm đổi ngữ nghĩa.
    """
    m = re.search(rf'^{ten}="(.*?)"$', _DEPLOY, re.S | re.M)
    assert m, f"không tìm thấy {ten} trong deploy.sh"
    sql = m.group(1)
    for cam in ('"', "$", "`"):
        assert cam not in sql, f"{ten} chứa {cam!r} — bash sẽ diễn giải, SQL thật khác chuỗi này"
    return sql


SQL_VAN_TAY = _bien_bash("_DCG_SQL_VAN_TAY")
SQL_PHIEN = _bien_bash("_DCG_SQL_PHIEN")
SQL_DEM = _bien_bash("_DCG_SQL_DEM")
SQL_CSDL = _bien_bash("_DCG_SQL_CSDL")


async def _van_tay(s) -> list[str]:
    return [r[0] for r in (await s.execute(text(SQL_VAN_TAY))).all()]


async def test_van_tay_chay_duoc_on_dinh_va_moi_dong_mot_object(setup_test_database) -> None:
    async with AsyncSessionLocal() as s:
        lan1 = await _van_tay(s)
        lan2 = await _van_tay(s)
    assert any(d.startswith("rel|") for d in lan1), "vân tay không có dòng bảng nào"
    assert any(d.startswith("col|") for d in lan1)
    assert lan1 == lan2, "vân tay KHÔNG ổn định giữa hai lần đọc — so khớp sẽ luôn lệch"
    assert all("\n" not in d and "\r" not in d for d in lan1)
    assert len(lan1) == len(set(lan1)), "vân tay có dòng trùng — phép so tập sẽ che khác biệt"


async def test_van_tay_bat_bang_moi_va_cot_moi_roi_tro_ve_sau_rollback(setup_test_database) -> None:
    async with AsyncSessionLocal() as s:
        goc = await _van_tay(s)
        await s.execute(text("CREATE TABLE _vt_kiem_thu (id int PRIMARY KEY, ten text NOT NULL DEFAULT 'x')"))
        co_bang = await _van_tay(s)
        await s.rollback()
        sau = await _van_tay(s)
    them = set(co_bang) - set(goc)
    assert "rel|public._vt_kiem_thu|r" in them, sorted(them)
    assert any(d.startswith("col|public._vt_kiem_thu|ten|text|true|") for d in them), sorted(them)
    assert any(d.startswith("con|public._vt_kiem_thu|_vt_kiem_thu_pkey|p|") for d in them), sorted(them)
    assert any(d.startswith("idx|public._vt_kiem_thu|_vt_kiem_thu_pkey|") for d in them), sorted(them)
    assert sau == goc, "sau ROLLBACK vân tay phải về Y NGUYÊN"


async def test_van_tay_bat_cot_moi_tren_bang_san_co(setup_test_database) -> None:
    async with AsyncSessionLocal() as s:
        goc = await _van_tay(s)
        ten_bang = next(d.split("|")[1] for d in goc if d.startswith("rel|public.") and d.endswith("|r"))
        await s.execute(text(f"ALTER TABLE {ten_bang} ADD COLUMN _vt_cot_thu int"))
        co_cot = await _van_tay(s)
        await s.rollback()
    them = set(co_cot) - set(goc)
    assert them == {f"col|{ten_bang}|_vt_cot_thu|integer|false|"}, sorted(them)


async def test_ba_cau_do_con_lai_chay_duoc_va_dung_hinh_dang(setup_test_database) -> None:
    async with AsyncSessionLocal() as s:
        phien = (await s.execute(text(SQL_PHIEN))).scalar_one()
        dem = [r[0] for r in (await s.execute(text(SQL_DEM))).all()]
        csdl = (await s.execute(text(SQL_CSDL))).scalar_one()
    assert isinstance(phien, int) and phien >= 0
    assert dem and all(re.fullmatch(r"[^|]+\|[0-9]+", d) for d in dem), dem[:5]
    assert re.fullmatch(r"[0-9]+(\|[0-9]+){4}", csdl), csdl
