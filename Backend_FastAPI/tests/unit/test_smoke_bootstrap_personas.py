"""Bootstrap persona: hàng rào, dẫn xuất mật khẩu, và hình dạng bộ persona.

Phần chạm DB (`verify_foundation`/`provision_personas`/`kiem_hoi_tu`) không kiểm
được ở đây vì nó cần một `qlts_smoke` thật — nó thuộc cổng destructive. Tệp này
kiểm những thứ SAI được mà không cần DB, và đó đúng là chỗ một script bootstrap
hay hỏng: hàng rào nới tay và mật khẩu dùng chung.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _goc_backend() -> Path:
    for goc in Path(__file__).resolve().parents:
        if (goc / "scripts").is_dir() and (goc / "tests").is_dir():
            return goc
    pytest.fail("không xác định được gốc Backend_FastAPI")


_GOC = _goc_backend()
_TEP = _GOC / "scripts" / "smoke_bootstrap_personas.py"

if str(_GOC) not in sys.path:
    sys.path.insert(0, str(_GOC))


def _nap():
    """Nạp module theo ĐƯỜNG DẪN, không qua `import scripts.…`.

    Script này `sys.path.insert(0, "/app")` rồi import `app.*`; nạp theo đường dẫn
    cho phép ca test chạy ở cả nơi có `/app` (container) lẫn nơi không có, miễn là
    gói `app` nhập được.
    """
    assert _TEP.is_file(), f"thiếu {_TEP} — mọi ca dưới đây sẽ không canh gì cả"
    spec = importlib.util.spec_from_file_location("smoke_bootstrap_personas", _TEP)
    mod = importlib.util.module_from_spec(spec)
    # KHÔNG bắt Exception rồi `skip`. Bản đầu làm thế "cho an toàn ở mọi môi
    # trường", nhưng hệ quả là một hồi quy import — đổi tên hàm, xoá dependency,
    # lỗi cú pháp — biến CẢ MODULE thành skip và required check vẫn xanh. Ở Tier 5
    # môi trường luôn có `app`, nên import hỏng phải là ĐỎ.
    spec.loader.exec_module(mod)
    return mod


bp = _nap()


# =============================================================================
# Hình dạng bộ persona
# =============================================================================
def test_dung_sau_persona_va_ten_khong_trung():
    ten = [p["username"] for p in bp.PERSONA]
    assert len(ten) == 6, f"chờ 6 persona, có {len(ten)}"
    assert len(set(ten)) == 6, f"tên persona trùng nhau: {ten}"


def test_moi_persona_deu_mang_tien_to_smoke():
    """Tiền tố `smoke_` là thứ phân biệt tài khoản của lượt thử với dữ liệu nền.

    Một persona tên `accountant01` sẽ ghi đè mật khẩu của tài khoản nền dùng chung
    — đúng lý do bộ này tồn tại.
    """
    for p in bp.PERSONA:
        assert p["username"].startswith("smoke_"), p["username"]


def test_co_ca_don_vi_A_va_B():
    """Thiếu persona ở đơn vị B thì không kiểm được IDOR chéo đơn vị."""
    dv = {p["unit"] for p in bp.PERSONA}
    assert dv == {"A", "B"}, dv


# =============================================================================
# Dẫn xuất mật khẩu
# =============================================================================
_MASTER = b"mot-master-secret-du-dai-de-test"


def test_moi_persona_MOT_mat_khau_khac_nhau():
    """Dùng chung một chuỗi cho sáu tài khoản là lộ một cái mất cả sáu."""
    mk = {p["username"]: bp.mat_khau(p["username"], _MASTER) for p in bp.PERSONA}
    assert len(set(mk.values())) == 6, f"có mật khẩu trùng nhau: {mk}"


def test_dan_xuat_TAT_DINH():
    """Chạy lại phải ra đúng mật khẩu cũ — đó là điều kiện để lượt hai HỘI TỤ."""
    a = bp.mat_khau("smoke_acc_a", _MASTER)
    b = bp.mat_khau("smoke_acc_a", _MASTER)
    assert a == b


def test_doi_master_thi_doi_TOAN_BO():
    khac = bp.mat_khau("smoke_acc_a", b"mot-master-secret-hoan-toan-khac")
    assert khac != bp.mat_khau("smoke_acc_a", _MASTER)


def test_mat_khau_khong_chua_master_nguyen_van():
    mk = bp.mat_khau("smoke_acc_a", _MASTER)
    assert _MASTER.decode() not in mk


def test_mat_khau_du_hang_ky_tu():
    """Qua được mọi chính sách độ phức tạp mà không phải đọc chính sách ấy."""
    mk = bp.mat_khau("smoke_acc_a", _MASTER)
    assert any(c.isupper() for c in mk)
    assert any(c.islower() for c in mk)
    assert any(c.isdigit() for c in mk)
    assert any(not c.isalnum() for c in mk)
    assert len(mk) >= 20


# =============================================================================
# Định dạng Casbin — phải khớp ỨNG DỤNG, không phải khớp chính nó
# =============================================================================
def test_chu_the_va_vai_dung_dinh_dang():
    assert bp._chu_the(7) == "user:7"
    assert bp._vai("manager") == "role:manager"


def test_dinh_dang_casbin_khop_MIGRATION_va_SERVICE():
    """Đối chiếu CHÉO NGUỒN, không tự khẳng định.

    Bản đầu của script ghi `v0=<username>`, `v1=<role>` trần — và hàm hậu kiểm
    của nó kiểm ĐÚNG định dạng sai ấy, nên cả hai nhất quán với nhau mà enforcer
    không thấy persona nào có vai trò. Ca này đọc hai nguồn ĐỘC LẬP:

      * migration `zq6w7x8y9z0a1` — `('g', 'user:1', 'role:admin')`
      * `user_service.py` — `f"user:{db_user.id}"` / `f"role:{db_user.role}"`
    """
    mig = next(
        (_GOC / "alembic" / "versions").glob("zq6w7x8y9z0a1*seed_operational_baseline.py")
    ).read_text(encoding="utf-8")
    assert "'user:1', 'role:admin'" in mig, (
        "migration không còn dùng định dạng `user:<id>`/`role:<role>` — đọc lại "
        "trước khi tin ca này"
    )

    svc = (_GOC / "app" / "services" / "user_service.py").read_text(encoding="utf-8")
    assert 'f"user:{db_user.id}"' in svc and 'f"role:{db_user.role}"' in svc, (
        "user_service không còn dựng chủ thể Casbin theo định dạng ấy"
    )

    # Và script phải sinh ra ĐÚNG hình dạng đó.
    assert bp._chu_the(1) == "user:1"
    assert bp._vai("admin") == "role:admin"


def test_khong_con_ghi_casbin_bang_username_tran():
    """Kiểm ngược ở mức mã: không câu SQL nào truyền username vào `v0`."""
    ma = _TEP.read_text(encoding="utf-8")
    assert '{"u": ten' not in ma and '"u": username' not in ma, (
        "còn chỗ truyền username trần làm chủ thể Casbin"
    )
    assert '_chu_the(u.id)' in ma, "không thấy chỗ nào dựng chủ thể đúng định dạng"


# =============================================================================
# Hàng rào
# =============================================================================
def test_thieu_master_secret_thi_BLOCK(monkeypatch):
    monkeypatch.delenv("SMOKE_PERSONA_MASTER_SECRET", raising=False)
    with pytest.raises(bp.ChanLai, match="SMOKE_PERSONA_MASTER_SECRET"):
        bp._master()


def test_master_secret_qua_NGAN_thi_BLOCK(monkeypatch):
    monkeypatch.setenv("SMOKE_PERSONA_MASTER_SECRET", "ngan")
    with pytest.raises(bp.ChanLai, match="SMOKE_PERSONA_MASTER_SECRET"):
        bp._master()


def test_app_env_dung_ALLOWLIST_khong_phai_blocklist(monkeypatch):
    """`staging`, rỗng hay một tên gõ sai đều phải DỪNG.

    Blocklist (chỉ cấm `production`/`prod`) để lọt chuỗi rỗng, `staging` và mọi
    tên gõ sai — với một script tạo tài khoản thì "không nhận ra là production"
    không đủ, phải "chắc chắn là development".
    """
    assert bp.APP_ENV_CHO_PHEP == {"development"}
    for gt in ("staging", "", "Production", "dev", "test"):
        monkeypatch.setattr(bp.settings, "APP_ENV", gt, raising=False)
        with pytest.raises(bp.ChanLai, match="APP_ENV"):
            bp.kiem_moi_truong(can_ghi=False)


def test_database_khac_qlts_smoke_thi_BLOCK(monkeypatch):
    monkeypatch.setattr(bp.settings, "APP_ENV", "development", raising=False)
    monkeypatch.setattr(
        bp.settings, "DATABASE_URL",
        "postgresql+asyncpg://q:x@postgres:5432/qlts_dev", raising=False,
    )
    with pytest.raises(bp.ChanLai, match="qlts_smoke"):
        bp.kiem_moi_truong(can_ghi=False)


def test_ghi_ma_thieu_co_destructive_thi_BLOCK(monkeypatch):
    monkeypatch.setattr(bp.settings, "APP_ENV", "development", raising=False)
    monkeypatch.setattr(
        bp.settings, "DATABASE_URL",
        "postgresql+asyncpg://q:x@postgres:5432/qlts_smoke", raising=False,
    )
    monkeypatch.delenv("SMOKE_ALLOW_DESTRUCTIVE", raising=False)
    with pytest.raises(bp.ChanLai, match="SMOKE_ALLOW_DESTRUCTIVE"):
        bp.kiem_moi_truong(can_ghi=True)
    # Chiều ngược: ĐỌC thì không cần cờ, nếu không thì lệnh in mật khẩu cũng bị
    # chặn và người trực sẽ đặt cờ phá huỷ chỉ để đọc một chuỗi.
    bp.kiem_moi_truong(can_ghi=False)


# =============================================================================
# Không rò mật khẩu ra log
# =============================================================================
def test_khong_co_lenh_print_nao_in_mat_khau():
    """Chỉ nhánh `--in-mat-khau` được phép in, và nó in ĐÚNG một dòng.

    Kiểm bằng cách đọc mã: mọi `print` khác không được nhận giá trị của
    `mat_khau(...)`. Một mật khẩu lọt vào log là lọt vào cả bản lưu log lẫn ảnh
    chụp màn hình của lượt smoke.
    """
    ma = _TEP.read_text(encoding="utf-8")
    in_mat_khau = [
        d.strip() for d in ma.splitlines()
        if d.strip().startswith("print(") and "mat_khau(" in d
    ]
    assert in_mat_khau == ["print(mat_khau(in_mat_khau))"], in_mat_khau
