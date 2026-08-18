"""Seed Finance: persona tường minh, và MỘT sổ cái duy nhất.

Hai thứ tệp này canh, cả hai đều từng sai theo cách không ai thấy:

* seed khoá cứng `accountant01`/`manager01`/`kpahdrim` — ba tài khoản NỀN dùng
  chung. Seed đổi dữ liệu của chúng là đổi nền cho mọi lượt sau, và `kpahdrim`
  còn là tên một người thật nằm trong mã;
* seed ghi `created-ids.json` riêng trong khi cleanup đọc `registry.json`. Hai
  tệp cho một lượt nghĩa là có lúc chúng lệch nhau, và không ai biết bên nào đúng.

Phần chạm DB không kiểm ở đây (cần `qlts_smoke` thật). Phần kiểm được mà không
cần DB là: bản đồ persona, hàng rào môi trường, và giao ước ghi sổ.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest


def _goc_backend() -> Path:
    for goc in Path(__file__).resolve().parents:
        if (goc / "scripts").is_dir() and (goc / "tests").is_dir():
            return goc
    pytest.fail("không xác định được gốc Backend_FastAPI")


_GOC = _goc_backend()
_SEED = _GOC / "scripts" / "smoke_finance_seed.py"

if str(_GOC) not in sys.path:
    sys.path.insert(0, str(_GOC))

from scripts.smoke_lib import registry  # noqa: E402

assert _SEED.is_file(), f"thiếu {_SEED} — mọi ca dưới đây sẽ không canh gì cả"
_MA = _SEED.read_text(encoding="utf-8")


# =============================================================================
# Persona — không còn tài khoản nền, không còn tên người thật
# =============================================================================
def test_khong_con_khoa_cung_tai_khoan_nen():
    """`accountant01`/`manager01` là dữ liệu nền; `kpahdrim` là tên một người.

    Chỉ soi dòng LỆNH: các tên này vẫn được phép xuất hiện trong chú thích giải
    thích vì sao chúng bị bỏ — một biểu thức khớp cả chú thích sẽ bắt nhầm chính
    lời giải thích ấy.
    """
    dong_lenh = [
        d for d in _MA.splitlines()
        if d.strip() and not d.lstrip().startswith("#")
    ]
    ma_lenh = "\n".join(dong_lenh)
    for ten in ("accountant01", "manager01", "kpahdrim"):
        assert f'"{ten}"' not in ma_lenh and f"'{ten}'" not in ma_lenh, (
            f"seed còn khoá cứng tài khoản {ten!r}"
        )


def test_persona_mac_dinh_deu_la_smoke():
    from scripts import smoke_finance_seed as sd  # noqa: WPS433

    assert set(sd.PERSONA_MAC_DINH) == {"ACC-A", "MGR-A", "ACC-B", "OFF-A"}
    for vai, ten in sd.PERSONA_MAC_DINH.items():
        assert ten.startswith("smoke_"), f"{vai} trỏ {ten!r}, không phải persona smoke"


def test_off_a_lay_theo_persona_khong_quet_theo_vai_tro():
    """Quét "officer active bất kỳ ở đơn vị A" làm hai lượt nói về hai người.

    Và không gì trong sổ cho biết điều đó đã xảy ra.
    """
    assert 'models.User.role == "officer"' not in _MA, (
        "seed còn quét officer theo vai trò thay vì lấy theo persona"
    )
    assert 'pers["OFF-A"]' in _MA


# =============================================================================
# Một sổ cái duy nhất
# =============================================================================
def test_khong_con_ghi_created_ids_json():
    """Neo vào LITERAL có dấu nháy, không vào chuỗi trần.

    Lọc bỏ dòng `#` là chưa đủ: tên tệp cũ vẫn còn trong DOCSTRING giải thích vì
    sao nó bị bỏ, và một phép kiểm khớp cả prose sẽ bắt nhầm chính lời giải thích
    ấy. Chỉ dạng `"created-ids.json"` / `'created-ids.json'` mới là mã thật sự
    dùng tên tệp.
    """
    con = re.findall(r"""['"]created-ids\.json['"]""", _MA)
    assert not con, (
        "seed còn ghi tệp id riêng — cleanup đọc registry.json, hai nguồn sẽ lệch"
    )


def test_seed_ghi_vao_so_bang_dung_ba_loi_goi():
    for goi in ("ghi_fixture(", "them_goc(", 'ghi_ids("admission_profile"'):
        assert goi in _MA, f"seed không gọi {goi}"
    # `_ACTOR` phải được GHI, không chỉ được ĐỌC: `--validate` chạy ở tiến trình
    # khác, nên danh tính persona không nằm trong sổ thì lượt ấy không có.
    assert 'ghi_fixture("_ACTOR"' in _MA, (
        "seed không ghi actor vào sổ — validator sẽ không có danh tính persona"
    )


def test_seed_va_validate_deu_doi_thu_muc_so():
    assert "--thu-muc" in _MA, "CLI chưa nhận gốc registry"
    assert re.search(r"def seed\([^)]*thu_muc", _MA, re.S), "seed() chưa nhận thu_muc"
    assert re.search(r"def validate\([^)]*thu_muc", _MA, re.S), (
        "validate() chưa nhận thu_muc"
    )


# =============================================================================
# Hàng rào môi trường — allowlist, không phải blocklist
# =============================================================================
def test_seed_dung_allowlist_moi_truong():
    assert "APP_ENV_CHO_PHEP" in _MA, "seed chưa có allowlist môi trường"
    assert 'app_env in {"production", "prod"}' not in _MA, (
        "seed còn dùng blocklist — chuỗi rỗng, `staging` và mọi tên gõ sai đi lọt"
    )


# =============================================================================
# `Registry.ghi_fixture` — giao ước của sổ
# =============================================================================
def _mo(tmp_path, run_id="SMK1"):
    return registry.Registry.mo(
        tmp_path, run_id=run_id, git_sha="0" * 40, pack="P1",
        project="qltssmoke", database="qlts_smoke",
    )


def test_ghi_fixture_luu_duoc_va_doc_lai_duoc(tmp_path):
    reg = _mo(tmp_path)
    reg.ghi_fixture("F-APP", {"profile_id": 7, "khong_co_fee_truoc": True})
    lai = registry.Registry.doc(tmp_path, "SMK1")
    assert lai.du_lieu["fixtures"]["F-APP"]["profile_id"] == 7


def test_ghi_fixture_hai_lan_cung_ma_bi_chan(tmp_path):
    """Ghi đè là xoá dấu vết bản trước — sổ cái mất nghĩa ngay lúc đó."""
    reg = _mo(tmp_path)
    reg.ghi_fixture("F-APP", {"profile_id": 7})
    with pytest.raises(registry.LoiRegistry, match="đã ghi"):
        reg.ghi_fixture("F-APP", {"profile_id": 8})


def test_ghi_fixture_rong_bi_chan(tmp_path):
    """"Không quan sát được gì" không được đọc thành "không có gì sai"."""
    with pytest.raises(registry.LoiRegistry, match="rỗng"):
        _mo(tmp_path).ghi_fixture("F-APP", {})


@pytest.mark.parametrize("ma", ["", "  ", "F APP", "F/APP", "x" * 33])
def test_ma_fixture_sai_dang_bi_chan(tmp_path, ma):
    with pytest.raises(registry.LoiRegistry, match="mã fixture"):
        _mo(tmp_path).ghi_fixture(ma, {"profile_id": 1})


def test_so_moi_co_san_khoa_fixtures(tmp_path):
    """Thiếu khoá này thì `seed` phải tự tạo, và một sổ cũ đọc lên sẽ khác hình dạng."""
    reg = _mo(tmp_path)
    assert reg.du_lieu["fixtures"] == {}


# =============================================================================
# BỐN LỖI CHỈ LỘ RA KHI CHẠY — soi chuỗi nguồn không bắt được cái nào
# =============================================================================
# Bộ ca ở trên phần lớn khẳng định về NỘI DUNG TỆP. Chúng không thi hành đường
# hậu-commit của `seed()` lẫn `validate()`, nên đã để lọt bốn lỗi: một `NameError`
# sau khi DB đã ghi xong, một `KeyError` trong validator, một sổ chưa baseline vẫn
# seed được, và `--persona` nhận nhầm vai. Bốn ca dưới đây THI HÀNH mã thật bằng
# stub — không cần database.
def _sd():
    from scripts import smoke_finance_seed as sd  # noqa: WPS433
    return sd


def _chan(capsys, ham, *a, **k) -> str:
    """Gọi `ham` và trả về LÝ DO đã in ra stderr.

    ⚠️ `ChanLai` của seed kế thừa `SystemExit` và in lý do ra stderr rồi thoát mã
    2 — nên `str(exc)` là `"2"`, và `pytest.raises(..., match=...)` khớp vào con
    số ấy chứ không vào câu giải thích. Một ca dùng `match` ở đây sẽ đỏ vì lý do
    chẳng liên quan, hoặc xanh vì `"2"` tình cờ khớp.
    """
    sd = _sd()
    with pytest.raises(sd.ChanLai):
        ham(*a, **k)
    return capsys.readouterr().err


def test_khong_co_ten_CHUA_DINH_NGHIA(tmp_path):
    """Bắt cả họ `NameError`, không riêng biến `duong` đã bị xoá.

    Lỗi ấy nằm ở dòng chạy SAU khi DB và sổ đã ghi xong: người trực thấy exit 1
    và tưởng lượt seed hỏng, trong khi dữ liệu đã nằm trong database.
    """
    pyflakes = pytest.importorskip("pyflakes.api", reason="cần pyflakes")
    from pyflakes.reporter import Reporter  # noqa: WPS433
    import io as _io

    ra, loi = _io.StringIO(), _io.StringIO()
    for ten in ("smoke_finance_seed.py", "smoke_bootstrap_personas.py"):
        pyflakes.checkPath(str(_GOC / "scripts" / ten), Reporter(ra, loi))
    xau = [d for d in ra.getvalue().splitlines() if "undefined name" in d]
    assert not xau, "tên chưa định nghĩa:\n" + "\n".join(xau)


@pytest.mark.parametrize(
    "so,khop",
    [
        ({"fixtures": {}}, "chưa có fixture"),
        ({"fixtures": {"F-APP": {"profile_id": 1}}}, "_ACTOR"),
        (
            {"fixtures": {"F-APP": {"profile_id": 1},
                          "_ACTOR": {"ACC-A": {}, "MGR-A": {}}}},
            "ACC-B",
        ),
    ],
)
def test_tach_so_thieu_gi_cung_DUNG(capsys, so, khop):
    """Validator đọc `du["actor"]` trong khi sổ chỉ có `fixtures` ⇒ KeyError.

    Một `KeyError` giữa validator không nói được điều gì cho người đọc log; phải
    là một câu nêu rõ sổ thiếu gì.
    """
    ly_do = _chan(capsys, _sd().tach_so, so, "SMK1")
    assert khop in ly_do, f"lý do không nêu {khop!r}: {ly_do!r}"


def test_tach_so_du_thi_tra_ve_ca_hai():
    sd = _sd()
    du = sd.tach_so(
        {"fixtures": {"F-APP": {"profile_id": 1},
                      "_ACTOR": {
                          "ACC-A": {"id": 1, "role": "accountant"},
                          "MGR-A": {"id": 2, "role": "manager"},
                          "ACC-B": {"id": 3, "role": "accountant"},
                          "OFF-A": {"id": 4, "role": "officer"},
                      }}},
        "SMK1",
    )
    assert du["actor"]["ACC-A"]["id"] == 1
    assert "_ACTOR" not in du["fixtures"], "_ACTOR không được lẫn vào danh sách fixture"


def test_so_CHUA_baseline_thi_khong_duoc_seed(capsys, tmp_path):
    """Baseline phải chụp database lúc CHƯA có fixture nào.

    `Registry.doc()` cho phép `baseline=None` — hợp lý cho việc đọc-để-xem, nhưng
    seed mà chạy trước baseline thì cleanup không còn mốc nào để phục hồi về.
    """
    _mo(tmp_path)  # mở sổ nhưng KHÔNG ghi baseline
    ly_do = _chan(capsys, _sd()._so, tmp_path, "SMK1")
    assert "baseline" in ly_do, ly_do


def test_so_cua_project_KHAC_bi_chan(capsys, tmp_path):
    """Một sổ chép từ project/database khác không được dùng cho lượt này."""
    registry.Registry.mo(
        tmp_path, run_id="SMK2", git_sha="0" * 40, pack="P1",
        project="qltskhac", database="qlts_smoke",
    )
    ly_do = _chan(capsys, _sd()._so, tmp_path, "SMK2")
    assert "qltskhac" in ly_do or "project" in ly_do, ly_do


class _KetQua:
    def __init__(self, u):
        self._u = u

    def scalars(self):
        return self

    def first(self):
        return self._u


class _DBGia:
    """Đủ để `_actor` chạy: nó chỉ `await db.execute(...)` rồi `.scalars().first()`."""

    def __init__(self, u):
        self._u = u

    async def execute(self, *a, **k):
        return _KetQua(self._u)


class _UserGia:
    def __init__(self, **kw):
        self.username = kw.get("username", "smoke_acc_a")
        self.status = kw.get("status", "active")
        self.role = kw.get("role", "accountant")
        self.unit_id = kw.get("unit_id", 4)
        self.id = kw.get("id", 1)


def test_persona_SAI_VAI_bi_chan(capsys):
    """`--persona ACC-A=<một manager>` từng đi lọt.

    `_actor` chỉ kiểm tồn tại + active, nên đổi được TÊN tài khoản là đổi được cả
    quyền mà ca smoke đo — và không có gì báo.
    """
    import asyncio  # noqa: WPS433
    db = _DBGia(_UserGia(role="manager"))
    ly_do = _chan(capsys, lambda: asyncio.run(
        _sd()._actor(db, "smoke_acc_a", "accountant")))
    assert "role" in ly_do, ly_do


def test_persona_dung_vai_thi_qua():
    """Chiều ngược: đúng vai KHÔNG được chặn, nếu không guard chỉ là 'cấm hết'."""
    import asyncio  # noqa: WPS433
    sd = _sd()
    u = asyncio.run(_sd()._actor(_DBGia(_UserGia(role="accountant")),
                                 "smoke_acc_a", "accountant"))
    assert u.role == "accountant"


@pytest.mark.parametrize(
    "kw,khop",
    [
        ({"status": "inactive"}, "status"),
        ({"unit_id": None}, "đơn vị"),
    ],
)
def test_actor_thieu_dieu_kien_khac_cung_chan(capsys, kw, khop):
    import asyncio  # noqa: WPS433
    ly_do = _chan(capsys, lambda: asyncio.run(
        _sd()._actor(_DBGia(_UserGia(**kw)), "smoke_acc_a", "accountant")))
    assert khop in ly_do, ly_do


def test_dich_chi_duoc_la_qlts_smoke(capsys, monkeypatch):
    """Seed ghi vào `qlts_dev` trong khi sổ nói `qlts_smoke` là mất dấu vết.

    Allowlist cũ mở cho `qlts_dev`/`qlts_test`, nên seed có thể ghi dữ liệu thử
    vào database dev, còn cleanup thì restore `qlts_smoke` — đống dữ liệu ấy nằm
    lại, không ai dọn, và không gì trong sổ cho biết.

    Phải dừng ở HÀNG RÀO, tức trước khi mở session.
    """
    sd = _sd()
    monkeypatch.setattr(sd.settings, "APP_ENV", "development", raising=False)
    monkeypatch.setenv("SMOKE_ALLOW_DESTRUCTIVE", "1")
    for ten in ("qlts_dev", "qlts_test", "qlts_production"):
        monkeypatch.setattr(
            sd.settings, "DATABASE_URL",
            f"postgresql+asyncpg://q:x@postgres:5432/{ten}", raising=False,
        )
        ly_do = _chan(capsys, sd.kiem_moi_truong, can_ghi=True)
        assert ten in ly_do, ly_do


def test_dich_dung_thi_qua(monkeypatch):
    """Chiều ngược — nếu không, hàng rào chỉ là 'cấm hết'."""
    sd = _sd()
    monkeypatch.setattr(sd.settings, "APP_ENV", "development", raising=False)
    monkeypatch.setattr(
        sd.settings, "DATABASE_URL",
        "postgresql+asyncpg://q:x@postgres:5432/qlts_smoke", raising=False,
    )
    monkeypatch.setenv("SMOKE_ALLOW_DESTRUCTIVE", "1")
    # Guard còn đòi hai đường cơ sở phải trỏ máy cục bộ — cấp đủ, nếu không ca
    # "chiều ngược" sẽ đỏ vì một điều kiện KHÁC và không chứng minh được gì về
    # allowlist database.
    monkeypatch.setenv("SMOKE_WEB_BASE", "http://127.0.0.1:3100")
    monkeypatch.setenv("SMOKE_API_BASE", "http://127.0.0.1:8100")
    sd.kiem_moi_truong(can_ghi=True)


def test_tach_so_thieu_OFF_A_thi_DUNG(capsys):
    """OFF-A là chủ sở hữu hồ sơ F-APP — thiếu nó thì không so được chủ sở hữu."""
    so = {"fixtures": {"F-APP": {"profile_id": 1}, "_ACTOR": {
        "ACC-A": {"id": 1, "role": "accountant"},
        "MGR-A": {"id": 2, "role": "manager"},
        "ACC-B": {"id": 3, "role": "accountant"},
    }}}
    ly_do = _chan(capsys, _sd().tach_so, so, "SMK1")
    assert "OFF-A" in ly_do, ly_do


def test_tach_so_actor_thieu_role_thi_DUNG(capsys):
    """Không có role trong sổ thì validator không đối chiếu được vai hiện tại."""
    so = {"fixtures": {"F-APP": {"profile_id": 1}, "_ACTOR": {
        "ACC-A": {"id": 1, "role": "accountant"},
        "MGR-A": {"id": 2, "role": "manager"},
        "ACC-B": {"id": 3, "role": "accountant"},
        "OFF-A": {"id": 4},          # thiếu role
    }}}
    ly_do = _chan(capsys, _sd().tach_so, so, "SMK1")
    assert "role" in ly_do, ly_do


@pytest.mark.parametrize(
    "url,dich_that",
    [
        # Tham số truy vấn chứa dấu gạch chéo: `rsplit("/")` trả về `qlts_smoke`
        # trong khi kết nối THẬT đi tới `qlts_dev`. Đã tái hiện.
        ("postgresql+asyncpg://q:x@postgres:5432/qlts_dev?application_name=/qlts_smoke",
         "qlts_dev"),
        ("postgresql+asyncpg://q:x@postgres:5432/qlts_production?opt=/qlts_smoke",
         "qlts_production"),
    ],
)
def test_url_lach_bang_tham_so_truy_van_bi_CHAN(capsys, monkeypatch, url, dich_that):
    """Định danh của ĐÍCH PHÁ HUỶ không được tự tách chuỗi lỏng tay."""
    sd = _sd()
    monkeypatch.setattr(sd.settings, "APP_ENV", "development", raising=False)
    monkeypatch.setattr(sd.settings, "DATABASE_URL", url, raising=False)
    monkeypatch.setenv("SMOKE_ALLOW_DESTRUCTIVE", "1")
    monkeypatch.setenv("SMOKE_WEB_BASE", "http://127.0.0.1:3100")
    monkeypatch.setenv("SMOKE_API_BASE", "http://127.0.0.1:8100")
    ly_do = _chan(capsys, sd.kiem_moi_truong, can_ghi=True)
    assert dich_that in ly_do, (
        f"hàng rào đọc ra đích khác {dich_that!r} — parser đang bị lách: {ly_do!r}"
    )


class _LeadGia:
    def __init__(self, officer=4, unit=1):
        self.assigned_officer_id = officer
        self.unit_id = unit


_OFF_A = {"id": 4, "unit": 1, "role": "officer"}
_FAPP = {"profile_id": 9, "officer_id": 4}


def test_chu_so_huu_dung_thi_khong_bao_loi():
    assert _sd().kiem_chu_so_huu(_FAPP, _OFF_A, _LeadGia()) == []


@pytest.mark.parametrize(
    "lead,khop",
    [
        (_LeadGia(officer=99), "đã bị chuyển người"),
        (_LeadGia(unit=7), "đơn vị"),
        (None, "không đọc được lead"),
    ],
)
def test_ho_so_bi_CHUYEN_NGUOI_sau_seed_thi_bat_duoc(lead, khop):
    """So `fapp.officer_id` với `off_a.id` là so hai giá trị CÙNG do seed ghi.

    Chúng luôn khớp nhau bất kể database về sau ra sao. Chủ sở hữu thật nằm ở
    `lead.assigned_officer_id`.
    """
    loi = _sd().kiem_chu_so_huu(_FAPP, _OFF_A, lead)
    assert any(khop in d for d in loi), loi


def test_vai_bat_buoc_phu_du_bon_vai():
    sd = _sd()
    assert set(sd.VAI_BAT_BUOC) == set(sd.PERSONA_MAC_DINH), (
        "mỗi vai persona phải có một vai trò bắt buộc tương ứng"
    )


# =============================================================================
# Settings SAU khi nạp env smoke — thứ `docker compose config` không nhìn thấy
# =============================================================================
# Bốn nhóm dưới đây có MẶC ĐỊNH GỌI RA NGOÀI trong `app/config.py`. Chúng là
# default của Pydantic, không phải giá trị trong env file, nên phép kiểm model
# Compose không thấy chúng: model chỉ chứa những gì được khai. Phải dựng Settings
# thật với env của stack smoke rồi đọc giá trị HIỆU LỰC.
def _env_mau() -> dict:
    tep = _GOC.parent / ".env.smoke.app.example"
    assert tep.is_file(), f"thiếu {tep}"
    ra = {}
    for d in tep.read_text(encoding="utf-8").splitlines():
        d = d.strip()
        if not d or d.startswith("#") or "=" not in d:
            continue
        k, _, v = d.partition("=")
        ra[k.strip()] = v.strip()
    return ra


@pytest.mark.parametrize(
    "khoa,mac_dinh_nguy_hiem",
    [
        ("HIBP_CHECK_ENABLED", "True → gọi api.pwnedpasswords.com"),
        ("SMS_PUBLIC_BASE_URL", "https://qlts.tnpc.edu.vn"),
        ("VNPAY_PAYMENT_URL", "https://sandbox.vnpayment.vn/..."),
        ("VNPAY_API_URL", "https://sandbox.vnpayment.vn/..."),
        ("MOMO_ENDPOINT", "https://test-payment.momo.vn/..."),
        ("ZALO_ENABLED", "công tắc tích hợp"),
        ("ZALO_BOT_ENABLED", "công tắc tích hợp"),
    ],
)
def test_env_mau_dat_lai_moi_mac_dinh_goi_ra_ngoai(khoa, mac_dinh_nguy_hiem):
    env = _env_mau()
    assert khoa in env, (
        f"`.env.smoke.app.example` không đặt {khoa} — mặc định trong config.py là "
        f"{mac_dinh_nguy_hiem}, và `docker compose config` KHÔNG thấy mặc định ấy"
    )


def test_settings_hieu_luc_khong_goi_ra_ngoai(monkeypatch):
    """Dựng Settings THẬT với env smoke rồi đọc giá trị hiệu lực.

    Đây là tầng duy nhất bắt được ca "env file không khai khoá X nên Pydantic lấy
    default trỏ ra Internet" — model Compose không có khoá ấy để mà kiểm.
    """
    from app.config import Settings  # noqa: WPS433

    for k, v in _env_mau().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://q:x@postgres:5432/qlts_smoke"
    )
    s = Settings()

    assert s.HIBP_CHECK_ENABLED is False, "HIBP còn bật ⇒ gọi api.pwnedpasswords.com"
    assert s.ZALO_ENABLED is False
    assert s.ZALO_BOT_ENABLED is False
    for khoa in ("SMS_PUBLIC_BASE_URL", "VNPAY_PAYMENT_URL", "VNPAY_API_URL",
                 "MOMO_ENDPOINT", "FRONTEND_URL", "CORS_ORIGINS"):
        gt = str(getattr(s, khoa, "") or "")
        assert "127.0.0.1" in gt or ".invalid" in gt or "localhost" in gt, (
            f"{khoa}={gt!r} không trỏ đích nội bộ"
        )


# =============================================================================
# F-CALC và F-CACHE — hai fixture mở khoá FIN-03 và FIN-07
#
# BL20260817A ghi cả hai ca là BLOCKED_FIXTURE:
#   FIN-03  7/7 hồ sơ có offering_admission_config_id = NULL, applied_rules
#           không có academic_info_id, bảng offering_admission_config 0 hàng
#           ⇒ resolve_fee_academic_info rơi hết ba nhánh legacy ⇒ BadRequest
#   FIN-07  registry không có F-CACHE, và runbook đòi hai phiên cùng ACC-A —
#           không dựng được vì hệ chỉ cho MỘT phiên hoạt động mỗi người dùng
# =============================================================================
def test_ca_kiem_nay_co_du_manh_khong_fcalc():
    """Ca dưới đây vô nghĩa nếu seeder không thật sự khai hai fixture ấy."""
    assert '"F-CALC"' in _MA, "seeder chưa khai F-CALC"
    assert '"F-CACHE"' in _MA, "seeder chưa khai F-CACHE"


def test_fcalc_dung_oac_that_khong_phai_applied_rules():
    """FIN-03 phải đi qua OAC thật, không lách bằng `applied_rules`.

    `resolve_fee_academic_info` chấp nhận `applied_rules['academic_info_id']` ở
    nhánh CUỐI. Nhét thẳng khoá vào đó thì ca xanh mà không chứng minh được
    đường OAC — vốn là đường sản phẩm thật dùng.
    """
    assert "_oac_cho_tinh_phi" in _MA, "thiếu helper dựng OfferingAdmissionConfig"
    assert "models.OfferingAdmissionConfig(" in _MA, (
        "seeder không tạo hàng OfferingAdmissionConfig nào — FIN-03 vẫn kẹt ở "
        "đúng chỗ cũ"
    )
    assert "offering_admission_config_id = oac.id" in _MA, (
        "hồ sơ F-CALC không được gắn OAC"
    )
    # Không được lách bằng `applied_rules`.
    #
    # Phép kiểm phải trỏ ĐÚNG vào `applied_rules`, không quét cả tệp: seeder ghi
    # `"academic_info_id"` vào SỔ như một mẩu ghi chép — hợp lệ, và một biểu thức
    # quét toàn tệp sẽ bắt nhầm chính mẩu ấy. (Đã vấp: bản đầu của ca này đỏ vì
    # lý do đó.)
    for khoi in re.findall(r"applied_rules\s*=\s*\{(.*?)\}", _MA, re.S):
        assert "academic_info_id" not in khoi, (
            "seeder nhét academic_info_id vào applied_rules — đó là nhánh CUỐI của "
            "resolve_fee_academic_info, không phải đường OAC mà FIN-03 cần chứng minh"
        )


def test_fcalc_khong_dung_san_fee_tuition():
    """FIN-03 là ca TÍNH MỚI. Có Fee tuition sẵn thì chỉ còn đo recalculate."""
    assert '"khong_co_fee_tuition_truoc": True' in _MA, (
        "F-CALC chưa khai bất biến 'chưa có Fee tuition'"
    )
    assert "FeeTypeEnum.tuition.value" in _MA, (
        "validator không lọc theo fee_type — nó sẽ bắt nhầm cả lệ phí hồ sơ"
    )


def test_fcalc_khong_muon_co_cua_fapp():
    """`khong_co_fee_truoc` là cờ của F-APP và kéo theo luật lệ phí hồ sơ.

    Dùng lại cờ ấy cho F-CALC thì validator đòi
    `applied_rules.requires_application_fee` — một trường F-CALC không có, và ca
    sẽ đỏ vì lý do chẳng liên quan gì tới tính học phí.
    """
    khoi = _MA.split('kq["fixtures"]["F-CALC"]', 1)
    assert len(khoi) == 2, "không tìm thấy khối khai F-CALC"
    than = khoi[1].split("}", 1)[0]
    assert '"khong_co_fee_truoc"' not in than, (
        "F-CALC đang mượn cờ của F-APP — hai bất biến khác nhau phải hai cờ khác nhau"
    )


def test_fcache_la_fixture_rieng_va_hai_persona_khac_nhau():
    """Tái dùng dữ liệu bẩn thì không phân biệt được cache cũ với dữ liệu mới."""
    assert '"khong_dung_chung": True' in _MA, "F-CACHE chưa khai bất biến 'riêng'"
    assert '"persona_doc"' in _MA and '"persona_ghi"' in _MA, (
        "F-CACHE chưa khai hai persona"
    )
    khoi = _MA.split('kq["fixtures"]["F-CACHE"]', 1)
    assert len(khoi) == 2, "không tìm thấy khối khai F-CACHE"
    than = khoi[1].split("}", 1)[0]
    doc = re.search(r'"persona_doc":\s*"([^"]+)"', than)
    ghi = re.search(r'"persona_ghi":\s*"([^"]+)"', than)
    assert doc and ghi, "không đọc được persona của F-CACHE"
    assert doc.group(1) != ghi.group(1), (
        f"persona đọc và ghi trùng nhau ({doc.group(1)!r}) — hệ chỉ cho MỘT phiên "
        "hoạt động mỗi người dùng, hai phiên cùng tài khoản không dựng được"
    )


def test_validator_co_canh_ca_hai_fixture_moi():
    """Seed mà validator không canh thì fixture hỏng vẫn qua cửa."""
    assert 'fx.get("tinh_phi_duoc")' in _MA, "validator không canh F-CALC"
    assert 'fx.get("khong_dung_chung")' in _MA, "validator không canh F-CACHE"
    # và phải canh ĐÚNG THỨ: OAC tồn tại + active + academic_info có học phí
    for moc in ("is_active", "tuition_fee_per_year", "offering_admission_config_id"):
        assert moc in _MA, f"validator F-CALC không kiểm {moc}"


def test_helper_oac_idempotent():
    """Seed lại cùng run-id không được đẻ thêm OAC mỗi lượt."""
    khoi = _MA.split("async def _oac_cho_tinh_phi", 1)[1].split("\nasync def ", 1)[0]
    assert "if oac is not None:" in khoi, (
        "helper không tái dùng OAC sẵn có — mỗi lượt seed sẽ thêm một hàng"
    )
    assert "ChanLai" in khoi, (
        "helper không fail-closed khi thiếu danh mục nền — nó sẽ trả None và lỗi "
        "nổ ở chỗ khác, xa nguyên nhân"
    )
