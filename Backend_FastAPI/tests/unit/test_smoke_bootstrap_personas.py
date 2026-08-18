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


# =============================================================================
# MFA onboarding cho persona đặc quyền
#
# BL20260817A ghi FIN-09 là BLOCKED_MFA: `MFA_ENFORCE_ROLES = ['admin','manager']`
# và `deps.py:368` trả 403 ở mọi endpoint qua `get_current_active_user` khi role
# đặc quyền chưa bật MFA. Đo được 195 phản hồi 403 "MFA is required" cho phiên
# `smoke_mgr_a`; `/api/users/me` cũng 403 nên giao diện không tải nổi.
#
# Blocker thuộc HARNESS, không phải sản phẩm — nên vá ở bootstrap.
# =============================================================================
_MA_BOOTSTRAP = _TEP.read_text(encoding="utf-8")


def test_ca_kiem_nay_co_du_manh_khong_mfa():
    """Vô nghĩa nếu script chưa hề nhắc tới MFA."""
    assert "PERSONA_CAN_MFA" in _MA_BOOTSTRAP, "script chưa khai persona nào cần MFA"
    assert "async def bat_mfa" in _MA_BOOTSTRAP, "script chưa có bước bật MFA"


def test_dung_ba_persona_dac_quyen_khong_hon_khong_kem():
    """Chỉ `admin`/`manager` thuộc `MFA_ENFORCE_ROLES`.

    Bật thừa cho officer/accountant là tự thêm một bước đăng nhập mà sản phẩm
    không đòi; bật thiếu thì FIN-09 vẫn kẹt.
    """
    mod = _nap()
    assert set(mod.PERSONA_CAN_MFA) == {"smoke_mgr_a", "smoke_mgr_b", "smoke_admin"}

    vai_theo_ten = {p["username"]: p["role"] for p in mod.PERSONA}
    for ten in mod.PERSONA_CAN_MFA:
        assert vai_theo_ten[ten] in ("admin", "manager"), (
            f"{ten} có role {vai_theo_ten[ten]!r} — không thuộc MFA_ENFORCE_ROLES"
        )
    for ten, vai in vai_theo_ten.items():
        if vai in ("admin", "manager"):
            assert ten in mod.PERSONA_CAN_MFA, f"{ten} là {vai} mà không được onboard"
        else:
            assert ten not in mod.PERSONA_CAN_MFA, (
                f"{ten} là {vai} — bootstrap không được bật MFA cho nó"
            )


def test_bat_mfa_di_qua_hop_dong_that_khong_gan_thang_co():
    """Phải gọi `setup_mfa` + `enable_mfa`, không đặt `mfa_enabled = True`.

    Gán thẳng cờ thì `totp_secret_encrypted` rỗng ⇒ persona không sinh nổi mã ⇒
    "đã bật MFA" mà không đăng nhập được, tệ hơn chưa bật vì nó trông như xong.
    """
    khoi = _MA_BOOTSTRAP.split("async def bat_mfa", 1)[1].split("\nasync def ", 1)[0]
    assert "mfa_service.setup_mfa(" in khoi, "không gọi setup_mfa"
    assert "mfa_service.enable_mfa(" in khoi, "không gọi enable_mfa"
    assert "pyotp.TOTP(" in khoi, "không sinh mã TOTP thật để enable_mfa verify"

    import re
    # Bắt đúng dạng GÁN trên một đối tượng (`u.mfa_enabled = True`), không bắt
    # mọi lần chuỗi ấy xuất hiện: thông báo lỗi trong `kiem_hoi_tu` có chứa
    # `mfa_enabled=True` như một mẩu văn bản, và một biểu thức quét cả tệp sẽ
    # bắt nhầm chính lời giải thích. (Đã vấp: bản đầu của ca này đỏ vì lý do đó.)
    gan_tay = re.findall(r"^\s*\w+\.mfa_enabled\s*=", _MA_BOOTSTRAP, re.M)
    assert not gan_tay, (
        f"script gán thẳng mfa_enabled ({gan_tay}) — phải đi qua enable_mfa để "
        "secret được mã hoá vào DB"
    )
    # và tuyệt đối không sửa DB bằng SQL tay
    for cam in (r'UPDATE\s+"?user"?\s+SET', r"update\s+.*\bmfa_enabled\s*="):
        assert not re.search(cam, _MA_BOOTSTRAP, re.I), f"script chạy SQL tay: {cam!r}"


def test_bat_mfa_thu_hoi_phien_cu():
    """`enable_mfa` KHÔNG tự thu hồi khi `current_session_id=None`.

    `mfa_service.py:241` bọc nhánh thu hồi trong `if current_session_id:`. Bootstrap
    không có phiên của mình nên truyền `None` ⇒ nhánh ấy không chạy ⇒ phiên đăng
    nhập TRƯỚC khi bật MFA vẫn hợp lệ, và `get_current_active_user` chỉ kiểm CỜ
    `mfa_enabled` nên nó đi lọt mà chưa hề trả lời challenge TOTP nào.

    Ca này canh phần khai báo; hiệu lực thật do
    `tests/integration/test_smoke_mfa_bootstrap_thuc.py` đo trên DB.
    """
    khoi = _MA_BOOTSTRAP.split("async def bat_mfa", 1)[1].split("\nasync def ", 1)[0]
    assert "revoke_all_other_sessions(" in khoi, (
        "bat_mfa không thu hồi phiên cũ — enable_mfa(current_session_id=None) bỏ "
        "qua nhánh thu hồi, nên phiên trước-MFA vẫn dùng được"
    )
    assert "except_session_id=None" in khoi, (
        "phải thu hồi TẤT CẢ: bootstrap không có phiên nào cần giữ"
    )


def test_guard_chan_ca_placeholder_cua_chinh_kho_nay():
    """Guard phải bắt placeholder mà chính `.example` của kho này viết ra.

    Bản đầu chỉ chặn `CHANGE_ME_IN_PRODUCTION` (mặc định của `config.py`), nên
    `THAY_BANG_CHUOI_NGAU_NHIEN_CUA_BAN` trong `.env.smoke.app.example` đi lọt:
    đổi khoá Fernet nhưng quên đổi muối vẫn qua cửa.
    """
    mod = _nap()
    from cryptography.fernet import Fernet
    khoa_that = Fernet.generate_key().decode()

    goc = _TEP.parent.parent.parent
    vidu = goc / ".env.smoke.app.example"
    assert vidu.is_file(), f"thiếu {vidu}"
    noi_dung = vidu.read_text(encoding="utf-8")

    import re
    for bien in ("MFA_ENCRYPTION_KEY", "DEVICE_FINGERPRINT_SALT"):
        m = re.search(rf"^{bien}=(.*)$", noi_dung, re.M)
        assert m, f"`.env.smoke.app.example` thiếu {bien}"
        gia_tri = m.group(1).strip()
        assert gia_tri, f"{bien} trong .example để rỗng — guard sẽ bắt vì rỗng, "            "không phải vì là placeholder; ca này mất ý nghĩa"

        import pytest as _pt
        monkey = _pt.MonkeyPatch()
        try:
            monkey.setenv("MFA_ENCRYPTION_KEY", khoa_that)
            monkey.setenv("DEVICE_FINGERPRINT_SALT", "muoi-that-du-dai-16")
            monkey.setenv(bien, gia_tri)
            with _pt.raises(mod.ChanLai) as e:
                mod.kiem_moi_truong_mfa()
            assert "placeholder" in str(e.value).lower(), (
                f"guard chặn {bien} nhưng không nói vì là placeholder: {e.value}"
            )
        finally:
            monkey.undo()


def test_guard_chan_salt_qua_ngan():
    """Muối 6 ký tự không phải muối."""
    mod = _nap()
    from cryptography.fernet import Fernet
    import pytest as _pt
    monkey = _pt.MonkeyPatch()
    try:
        monkey.setenv("MFA_ENCRYPTION_KEY", Fernet.generate_key().decode())
        monkey.setenv("DEVICE_FINGERPRINT_SALT", "abc123")
        with _pt.raises(mod.ChanLai) as e:
            mod.kiem_moi_truong_mfa()
        assert "ngắn" in str(e.value)
    finally:
        monkey.undo()


def test_bat_mfa_idempotent():
    """Chạy lại không được bật lại — `enable_mfa` ném 400 khi đã bật."""
    khoi = _MA_BOOTSTRAP.split("async def bat_mfa", 1)[1].split("\nasync def ", 1)[0]
    assert "if u.mfa_enabled:" in khoi, "thiếu nhánh bỏ qua khi đã bật"


def test_thieu_key_hoac_salt_bi_chan_TRUOC_moi_mutation(monkeypatch):
    """Fail-closed, và phải chặn TRƯỚC khi tạo tài khoản nào.

    `config.py:811-815` TỰ SINH giá trị thay thế khi thiếu và chỉ in WARNING ⇒
    lượt sau sinh khoá khác ⇒ `decrypt_secret` ném "Key may have changed" trên
    chính secret mình vừa ghi. Nên "thiếu" phải là DỪNG, không phải "tự lo".
    """
    mod = _nap()
    from cryptography.fernet import Fernet
    khoa_hop_le = Fernet.generate_key().decode()

    # đủ cả hai → qua
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", khoa_hop_le)
    monkeypatch.setenv("DEVICE_FINGERPRINT_SALT", "muoi-du-dai-cho-smoke")
    mod.kiem_moi_truong_mfa()

    for thieu, gia_tri in (
        ("MFA_ENCRYPTION_KEY", ""),
        ("DEVICE_FINGERPRINT_SALT", ""),
        ("DEVICE_FINGERPRINT_SALT", "CHANGE_ME_IN_PRODUCTION"),
        ("MFA_ENCRYPTION_KEY", "khong-phai-fernet"),
    ):
        monkeypatch.setenv("MFA_ENCRYPTION_KEY", khoa_hop_le)
        monkeypatch.setenv("DEVICE_FINGERPRINT_SALT", "muoi-du-dai-cho-smoke")
        monkeypatch.setenv(thieu, gia_tri)
        with pytest.raises(mod.ChanLai) as e:
            mod.kiem_moi_truong_mfa()
        assert thieu in str(e.value), f"thông báo không nêu {thieu}"

    # Guard phải nằm trên ĐƯỜNG GHI, không phải chỉ "có mặt đâu đó trong _chay".
    #
    # `_chay` có ba nhánh: --in-mat-khau, --in-ma-totp, và đường ghi. Nhánh
    # --in-ma-totp cũng gọi guard, và nó nằm TRƯỚC provision trong văn bản. Nên
    # một phép kiểm kiểu `chay.find(guard) < chay.find(provision)` vẫn xanh sau
    # khi guard đã bị gỡ khỏi đường ghi — đúng lớp "phép kiểm gộp che nhánh phía
    # sau". (Đã vấp: đột biến gỡ guard khỏi đường ghi KHÔNG bị bắt.)
    #
    # Neo vào đoạn TỪ `kiem_moi_truong(can_ghi=True)` — mốc duy nhất chỉ có ở
    # đường ghi — cho tới `provision_personas(`.
    chay = _MA_BOOTSTRAP.split("async def _chay", 1)[1]
    moc_ghi = chay.find("kiem_moi_truong(can_ghi=True)")
    assert moc_ghi != -1, "_chay không còn nhánh ghi"
    vi_provision = chay.find("provision_personas(", moc_ghi)
    assert vi_provision != -1, "đường ghi không gọi provision_personas"

    doan_truoc_provision = chay[moc_ghi:vi_provision]
    assert "kiem_moi_truong_mfa()" in doan_truoc_provision, (
        "guard MFA KHÔNG nằm giữa `kiem_moi_truong(can_ghi=True)` và "
        "`provision_personas` — hỏng giữa chừng thì còn lại vài persona đã tạo và "
        "vài persona chưa, không cái nào nói ra điều đó"
    )


def test_khong_bao_gio_in_secret():
    """Người trực cần mã 6 số, không cần secret.

    Đưa secret ra là đưa vĩnh viễn: nó vào log, vào lịch sử shell, vào ảnh chụp.
    Mã TOTP sống 30 giây và vô dụng ngay sau đó.
    """
    assert "--in-ma-totp" in _MA_BOOTSTRAP, "thiếu đường lấy mã đăng nhập"
    khoi = _MA_BOOTSTRAP.split("async def ma_totp", 1)[1].split("\nasync def ", 1)[0]
    assert "pyotp.TOTP(" in khoi and ".now()" in khoi, "không sinh mã 6 số"
    import re
    assert not re.search(r"print\(\s*secret", _MA_BOOTSTRAP), "script in secret ra stdout"
    assert not re.search(r"print\([^)]*totp_secret", _MA_BOOTSTRAP), (
        "script in totp_secret ra stdout"
    )


def test_khong_noi_tay_MFA_ENFORCE_ROLES():
    """Sửa danh sách role bắt buộc MFA là đổi hành vi sản phẩm để né hàng rào.

    Chỉ cấm GÁN/ghi đè, không cấm NHẮC TỚI: script phải được phép giải thích vì
    sao ba persona kia cần MFA, và lời giải thích ấy tất nhiên nêu tên hằng số.
    """
    import re
    ghi = re.findall(
        r"(?:^\s*(?:settings\.)?MFA_ENFORCE_ROLES\s*=|"
        r"setattr\s*\(\s*settings\s*,\s*[\"']MFA_ENFORCE_ROLES|"
        r"monkeypatch\.setattr\([^)]*MFA_ENFORCE_ROLES)",
        _MA_BOOTSTRAP,
        re.M,
    )
    assert not ghi, f"script ghi đè MFA_ENFORCE_ROLES ({ghi}) — đó là nới hàng rào"


def test_kiem_hoi_tu_canh_ca_hai_chieu():
    """Đặc quyền phải bật; officer/accountant phải KHÔNG bị bật."""
    khoi = _MA_BOOTSTRAP.split("async def kiem_hoi_tu", 1)[1].split("\nasync def ", 1)[0]
    assert "PERSONA_CAN_MFA" in khoi, "kiem_hoi_tu không phân biệt persona đặc quyền"
    assert "totp_secret_encrypted" in khoi, (
        "chỉ kiểm cờ mà không kiểm secret — cờ bật + secret rỗng vẫn qua cửa"
    )
    assert "decrypt_secret" in khoi, (
        "không giải mã thử — khoá đổi giữa hai lượt sẽ chỉ lộ ra lúc đăng nhập"
    )
    assert "elif u.mfa_enabled:" in khoi, (
        "không canh chiều ngược: officer/accountant bị bật MFA vẫn lọt"
    )


def test_bat_mfa_KHONG_tu_goi_post_commit_callback():
    """Callback phát `USER_FORCE_LOGOUT` và chỉ hợp lệ SAU commit.

    `session_service.py:623` ghi rõ "Sau khi đã commit". `bat_mfa` chạy bên trong
    một giao dịch còn dở — `_chay` chỉ commit sau khi xong cả ba persona. Gọi sớm
    nghĩa là persona thứ hai/thứ ba hỏng, hoặc chính `commit` hỏng, thì DB rollback
    trong khi client đã bị đá ra: phiên vẫn hiệu lực mà người dùng đã mất phiên.
    """
    khoi = _MA_BOOTSTRAP.split("async def bat_mfa", 1)[1].split("\nasync def ", 1)[0]
    import re
    goi_som = re.findall(r"await\s+(?:callback|cb)\s*\(\s*\)", khoi)
    assert not goi_som, (
        f"bat_mfa tự gọi post-commit callback ({goi_som}) trong khi giao dịch chưa "
        "commit — phải TRẢ nó về cho người gọi"
    )
    assert "return f\"vua_bat(thu_hoi=" in khoi and "callback" in khoi, (
        "bat_mfa không trả callback về — người gọi không có gì để chạy sau commit"
    )


def test_chay_goi_callback_SAU_commit():
    """Và người gọi phải chạy nó ĐÚNG THỨ TỰ: gom → commit → chạy.

    Neo vào đoạn của ĐƯỜNG GHI (`kiem_moi_truong(can_ghi=True)`) để không bắt
    nhầm nhánh `--in-mat-khau`/`--in-ma-totp` nằm trước — cùng lớp bẫy "phép kiểm
    gộp che nhánh phía sau" đã vấp một lần ở guard MFA.
    """
    chay = _MA_BOOTSTRAP.split("async def _chay", 1)[1]
    moc_ghi = chay.find("kiem_moi_truong(can_ghi=True)")
    assert moc_ghi != -1, "_chay không còn nhánh ghi"
    duong_ghi = chay[moc_ghi:]

    import re

    vi_commit = duong_ghi.find("await db.commit()")
    assert vi_commit != -1, "đường ghi không commit"

    truoc_commit = duong_ghi[:vi_commit]
    sau_commit = duong_ghi[vi_commit:]

    # Bắt MỌI lời gọi callback, không neo vào đúng một tên biến.
    #
    # Bản đầu của ca này so `find("await cb()")` với vị trí commit — và một đột
    # biến chèn `await _c()` TRƯỚC commit vẫn xanh, vì `await cb()` sau commit vẫn
    # còn đó. Đo được: 36 passed trên bản đã hỏng. Phép kiểm theo vị trí của MỘT
    # chuỗi không bao giờ chứng minh được "không có lời gọi nào ở phía trước".
    MAU_GOI = r"await\s+\w*(?:cb|callback|_c)\w*\s*\(\s*\)"

    som = re.findall(MAU_GOI, truoc_commit)
    assert not som, (
        f"có lời gọi callback TRƯỚC commit ({som}) — sự kiện force-logout phát trên "
        "trạng thái chưa commit; persona sau hỏng là DB rollback trong khi client "
        "đã bị đá ra"
    )
    muon = re.findall(MAU_GOI, sau_commit)
    assert muon, (
        "đường ghi không chạy callback nào SAU commit — sự kiện force-logout không "
        "bao giờ phát, client cũ giữ phiên cho tới lần gọi API kế tiếp"
    )
    assert "cho_sau_commit" in duong_ghi, (
        "không gom callback: gọi rải rác giữa vòng lặp thì persona sau hỏng vẫn đã "
        "phát force-logout cho persona trước"
    )



# =============================================================================
# Đường lấy mật khẩu / TOTP phải FAIL-CLOSED
#
# Bản runbook trước dùng `docker compose … | tail -1`. Hai đường hỏng:
#   * PowerShell (shell của máy smoke) KHÔNG có `tail`; `bash.exe` trỏ sang WSL mà
#     WSL không có `/bin/bash` ⇒ lệnh không chạy được;
#   * trong Bash, mã thoát của pipeline là của `tail` ⇒ `docker` đổ mà pipeline
#     vẫn trả 0 kèm chuỗi RỖNG. Lỗi biến thành "thành công với giá trị rỗng".
#
# Ca `test_output_CLI_…` không bắt được: nó gọi `ma_totp` qua một driver Python,
# không đi qua `main()`, argparse, Docker Compose hay pipeline của runbook.
# =============================================================================
_RUNBOOK = _GOC.parent / "Documents" / "FINANCE_CHROME_SMOKE_RUNBOOK.md"


def _khoi_buoc4() -> str:
    assert _RUNBOOK.is_file(), f"thiếu {_RUNBOOK}"
    noi_dung = _RUNBOOK.read_text(encoding="utf-8")
    dau = noi_dung.find("**Bước 4")
    assert dau != -1, "runbook không còn Bước 4 của §A04.1"
    cuoi = noi_dung.find("### A05.", dau)
    return noi_dung[dau: cuoi if cuoi != -1 else len(noi_dung)]


def test_ca_kiem_nay_co_du_manh_khong_runbook():
    """Vô nghĩa nếu không định vị được khối lệnh cần canh."""
    khoi = _khoi_buoc4()
    assert "--in-ma-totp" in khoi and "--in-mat-khau" in khoi, (
        "không tìm thấy hai lệnh lấy mật khẩu/mã trong Bước 4"
    )


def test_khong_dung_pipeline_nuot_ma_thoat():
    """`docker … | tail` biến lỗi thành thành công-với-giá-trị-rỗng."""
    import re
    khoi = _khoi_buoc4()
    # Chỉ soi DÒNG LỆNH, không soi câu văn giải thích vì sao không dùng nó.
    dong_lenh = [
        d for d in khoi.splitlines()
        if ("docker compose" in d or "smoke_bootstrap_personas.py" in d)
        and not d.lstrip().startswith(("*", "#", ">", "🔴"))
    ]
    # ⚠️ Biểu thức PHẢI là raw string thật.
    #
    # Bản đầu của ca này được sinh ra từ một chuỗi KHÔNG raw, nên `\b` (word
    # boundary) bị Python dịch thành ký tự BACKSPACE `\x08` ngay lúc ghi tệp. Biểu
    # thức thành `(tail|head|Select-Object)\x08` — không bao giờ khớp. Đo được:
    # đột biến đổi cả khối về `docker … | tail -1` vẫn cho 41 passed.
    #
    # Một biểu thức không khớp gì cả trông y hệt một biểu thức không tìm thấy gì.
    xau = [d for d in dong_lenh
           if re.search(r"\|\s*(?:tail|head|Select-Object|findstr)\b", d)]
    assert not xau, (
        "dòng lệnh còn nối pipeline làm mất mã thoát của docker:\n  "
        + "\n  ".join(x.strip() for x in xau)
    )


def test_co_du_BA_phep_kiem_fail_closed():
    """Mã thoát · định dạng · rỗng — thiếu cái nào là một đường lỗi im lặng."""
    khoi = _khoi_buoc4()
    # Kiểm THEO TỪNG LỆNH, không kiểm "có mặt đâu đó".
    #
    # Runbook có hai lệnh (`--in-ma-totp`, `--in-mat-khau`) và mỗi lệnh cần một
    # phép kiểm riêng. Bản đầu chỉ hỏi `"$LASTEXITCODE" in khoi` — nên gỡ phép
    # kiểm của lệnh TOTP vẫn xanh, vì phép kiểm của lệnh mật khẩu còn đó. Đo được:
    # 41 passed trên bản đã hỏng.
    dong = khoi.splitlines()
    for co in ("--in-ma-totp", "--in-mat-khau"):
        vi = [i for i, d in enumerate(dong) if co in d and "docker compose" in d]
        assert vi, f"không tìm thấy lệnh {co} trong Bước 4"
        for i in vi:
            ke_tiep = "\n".join(dong[i + 1: i + 4])
            assert "$LASTEXITCODE" in ke_tiep, (
                f"lệnh {co} không kiểm mã thoát ngay sau đó — docker đổ mà script "
                f"vẫn đi tiếp với giá trị rỗng. Ba dòng kế tiếp:\n{ke_tiep}"
            )
    assert "'^\\d{6}$'" in khoi or "^\\d{6}$" in khoi, (
        "không kiểm định dạng TOTP — một dòng rỗng cũng là 'một dòng'"
    )
    assert "IsNullOrWhiteSpace" in khoi, "không kiểm mật khẩu rỗng"
    assert "throw" in khoi, "không dừng khi kiểm hỏng"


def test_script_khong_bat_nguoi_goi_phai_loc():
    """Log của `app.config` phải sang stderr, để stdout chỉ còn giá trị.

    Đây mới là gốc: bắt người gọi lọc thì sớm muộn có người lọc bằng cách nuốt
    mất mã thoát.
    """
    assert "contextlib.redirect_stdout(sys.stderr)" in _MA_BOOTSTRAP, (
        "script không đổi hướng log lúc import — stdout vẫn lẫn INFO của app.config"
    )
    import re
    m = re.search(
        r"with contextlib\.redirect_stdout\(sys\.stderr\):(.*?)\n\n",
        _MA_BOOTSTRAP, re.S,
    )
    assert m, "không đọc được khối import đã đổi hướng"
    assert "from app.config import settings" in m.group(1), (
        "`app.config` nằm NGOÀI khối đổi hướng — nó vẫn in ra stdout"
    )


def test_annotation_cua_bat_mfa_khop_gia_tri_tra_ve():
    """Hàm trả tuple thì khai báo phải nói tuple."""
    import re
    m = re.search(r"async def bat_mfa\([^)]*\)\s*->\s*([^:]+):", _MA_BOOTSTRAP)
    assert m, "không đọc được khai báo bat_mfa"
    khai = m.group(1).strip()
    assert "Tuple" in khai, (
        f"bat_mfa khai báo trả {khai!r} nhưng thực tế trả (nhãn, callback|None)"
    )
