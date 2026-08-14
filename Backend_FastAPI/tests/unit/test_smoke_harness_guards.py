"""Hàng rào của harness smoke Finance — mỗi ca là một cách hỏng đã lường trước.

Hai module trong `scripts/smoke_lib/` là công cụ PHÁ HOẠI: một cái ghi sổ những
bản ghi thật đã bị đụng, cái kia DROP nguyên một database. Nên tệp này không
kiểm "hàm chạy đúng khi mọi thứ đúng" — nó kiểm **hàm có chặn được khi có gì đó
sai** hay không, và ở những chỗ dễ tự lừa nhất còn kiểm nó **không chặn nhầm**
đường lành: một guard luôn đỏ vô dụng y như một guard luôn xanh.

Cố ý KHÔNG `pytest.skip` ở mức module khi thiếu `smoke_lib`: thiếu thư viện
nghĩa là harness không tồn tại, và một tệp test im lặng bỏ qua sẽ báo xanh cho
đúng lúc chẳng có gì được canh.
"""

from __future__ import annotations

import json
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
if not (_GOC / "scripts" / "smoke_lib").is_dir():
    pytest.fail(
        f"thiếu {_GOC / 'scripts' / 'smoke_lib'} — harness smoke không tồn tại. "
        "Đây là lỗi, không phải lý do để bỏ qua tệp test."
    )
if str(_GOC) not in sys.path:
    sys.path.insert(0, str(_GOC))

from scripts.smoke_lib import baseline, registry  # noqa: E402

_ENV_DU = {"SMOKE_ALLOW_DESTRUCTIVE": "1"}
_DANH_TINH = {
    "project": "qltssmoke",
    "container_id": "a1b2c3d4e5f6",
    "nhan_container": {
        "com.docker.compose.project": "qltssmoke",
        "com.docker.compose.service": "postgres",
    },
    "system_identifier": "7412598630145236",
}


# =============================================================================
# baseline — hàng rào 1: môi trường
# =============================================================================
def test_moi_truong_hop_le_thi_di_qua():
    baseline.kiem_moi_truong(app_env="development", ten_db="qlts_smoke", moi_truong=_ENV_DU)


@pytest.mark.parametrize("app_env", ["production", "PRODUCTION", "prod", "Production"])
def test_production_bi_chan(app_env):
    """Nay chặn bằng allowlist nên thông điệp nói 'allowlist', không nói 'production'."""
    with pytest.raises(baseline.ChanLai, match="allowlist"):
        baseline.kiem_moi_truong(app_env=app_env, ten_db="qlts_smoke", moi_truong=_ENV_DU)


@pytest.mark.parametrize("ten_db", ["qlts_dev", "qlts_test", "qlts_production", "qlts_smoke_g2", ""])
def test_dich_khac_qlts_smoke_bi_chan(ten_db):
    with pytest.raises(baseline.ChanLai, match="qlts_smoke"):
        baseline.kiem_moi_truong(app_env="development", ten_db=ten_db, moi_truong=_ENV_DU)


@pytest.mark.parametrize("gia_tri", [None, "", "0", "true", "yes", " 1"])
def test_thieu_co_destructive_bi_chan(gia_tri):
    env = {} if gia_tri is None else {"SMOKE_ALLOW_DESTRUCTIVE": gia_tri}
    with pytest.raises(baseline.ChanLai, match="SMOKE_ALLOW_DESTRUCTIVE"):
        baseline.kiem_moi_truong(app_env="development", ten_db="qlts_smoke", moi_truong=env)


@pytest.mark.parametrize(
    "ham,kwargs",
    [
        ("lenh_dump", {"user": "qlts", "duong_trong_container": "/tmp/x.dump"}),
        ("lenh_restore", {"user": "qlts", "duong_trong_container": "/tmp/x.dump"}),
        ("lenh_drop_tao", {"user": "qlts"}),
        ("lenh_dem_session", {"user": "qlts"}),
    ],
)
def test_moi_ham_dung_lenh_deu_tu_kiem_dich(ham, kwargs):
    """Guard đặt ở một chỗ duy nhất là guard bỏ trống cửa."""
    with pytest.raises(baseline.ChanLai, match="qlts_smoke"):
        getattr(baseline, ham)(ten_db="qlts_dev", **kwargs)


@pytest.mark.parametrize("user", ["postgres", "qlts; DROP DATABASE qlts_dev", "admin"])
def test_user_ngoai_allowlist_bi_chan(user):
    """`shell=False` chặn shell injection, KHÔNG chặn SQL injection."""
    with pytest.raises(baseline.ChanLai, match="allowlist"):
        baseline.lenh_dump(ten_db="qlts_smoke", user=user, duong_trong_container="/t.dump")


@pytest.mark.parametrize("bang", ["fee; DROP TABLE x", "Fee", "1fee", "a" * 70, ""])
def test_ten_bang_khong_hop_le_bi_chan(bang):
    with pytest.raises(baseline.ChanLai, match="tên bảng"):
        baseline.cau_lenh_van_tay([bang])


def test_lenh_drop_tao_khong_dung_force():
    cac = baseline.lenh_drop_tao(ten_db="qlts_smoke", user="qlts")
    ghep = " ".join(" ".join(x) for x in cac)
    assert "pg_terminate_backend" in ghep
    assert "FORCE" not in ghep.upper()
    assert "ON_ERROR_STOP=1" in ghep


# =============================================================================
# baseline — hàng rào 2: danh tính đích
# =============================================================================
def test_danh_tinh_dung_thi_di_qua():
    assert baseline.kiem_danh_tinh(**_DANH_TINH)["project"] == "qltssmoke"


def test_project_sai_bi_chan():
    d = dict(_DANH_TINH, project="qlts")
    with pytest.raises(baseline.ChanLai, match="compose project"):
        baseline.kiem_danh_tinh(**d)


def test_container_mang_nhan_project_khac_bi_chan():
    """Ca cốt lõi: một container khác vẫn có thể chứa database trùng tên."""
    d = dict(_DANH_TINH, nhan_container={"com.docker.compose.project": "qlts"})
    with pytest.raises(baseline.ChanLai, match="trùng tên"):
        baseline.kiem_danh_tinh(**d)


@pytest.mark.parametrize("cid", ["", "xyz", "ABC123", "a1b2"])
def test_container_id_khong_hop_le_bi_chan(cid):
    with pytest.raises(baseline.ChanLai, match="container id"):
        baseline.kiem_danh_tinh(**dict(_DANH_TINH, container_id=cid))


@pytest.mark.parametrize("sid", ["", "abc", "123"])
def test_system_identifier_khong_hop_le_bi_chan(sid):
    with pytest.raises(baseline.ChanLai, match="system_identifier"):
        baseline.kiem_danh_tinh(**dict(_DANH_TINH, system_identifier=sid))


@pytest.mark.parametrize("khoa", ["container_id", "system_identifier", "project"])
def test_danh_tinh_doi_giua_chung_bi_chan(khoa):
    """Đổi container giữa lượt — thứ mà 'cùng tên database' không thấy."""
    nen = baseline.kiem_danh_tinh(**_DANH_TINH)
    doi = dict(nen)
    doi[khoa] = "qltssmoke2" if khoa == "project" else ("f" * 12 if khoa == "container_id" else "9" * 16)
    with pytest.raises(baseline.ChanLai, match="ĐÃ ĐỔI|compose project"):
        baseline.kiem_danh_tinh(
            project=doi["project"],
            container_id=doi["container_id"],
            nhan_container={
                "com.docker.compose.project": doi["project"],
                "com.docker.compose.service": "postgres",
            },
            system_identifier=doi["system_identifier"],
            danh_tinh_baseline=nen,
        )


# =============================================================================
# baseline — hàng rào 3: archive phải dùng được
# =============================================================================
_TOC_DU = "\n".join(
    f"34{i:02d}; 0 164{i:02d} TABLE DATA public {t} qlts"
    for i, t in enumerate(baseline.BANG_TRONG_YEU)
)


def _dump_gia(tmp_path: Path) -> Path:
    d = tmp_path / "b.dump"
    d.write_bytes(b"PGDMP" + b"\x00" * 64)
    return d


def test_archive_du_dieu_kien_thi_qua(tmp_path):
    d = _dump_gia(tmp_path)
    sha = baseline.kiem_archive(
        duong=d, dau_ra_pg_restore_list=_TOC_DU, ma_thoat_pg_restore_list=0
    )
    assert len(sha) == 64


def test_header_dung_nhung_pg_restore_khong_doc_duoc_thi_chan(tmp_path):
    """Đây chính là chỗ bản đầu tự lừa: blob PGDMP + zero được coi là hợp lệ."""
    d = _dump_gia(tmp_path)
    baseline.kiem_header(d)  # phép kiểm rẻ vẫn qua...
    with pytest.raises(baseline.ChanLai, match="pg_restore --list"):  # ...nhưng đầy đủ thì không
        baseline.kiem_archive(
            duong=d, dau_ra_pg_restore_list="", ma_thoat_pg_restore_list=1
        )


def test_toc_rong_bi_chan(tmp_path):
    with pytest.raises(baseline.ChanLai, match="rỗng nội dung"):
        baseline.kiem_archive(
            duong=_dump_gia(tmp_path), dau_ra_pg_restore_list="   ",
            ma_thoat_pg_restore_list=0,
        )


@pytest.mark.parametrize("bo", list(baseline.BANG_TRONG_YEU))
def test_toc_thieu_bang_trong_yeu_bi_chan(tmp_path, bo):
    toc = "\n".join(l for l in _TOC_DU.splitlines() if not l.endswith(f" {bo} qlts"))
    with pytest.raises(baseline.ChanLai, match="thiếu bảng trọng yếu"):
        baseline.kiem_archive(
            duong=_dump_gia(tmp_path), dau_ra_pg_restore_list=toc,
            ma_thoat_pg_restore_list=0,
        )


def test_dump_thieu_bi_chan(tmp_path):
    with pytest.raises(baseline.ChanLai, match="không thấy"):
        baseline.kiem_header(tmp_path / "khong-co.dump")


def test_dump_rong_bi_chan(tmp_path):
    d = tmp_path / "r.dump"; d.write_bytes(b"")
    with pytest.raises(baseline.ChanLai, match="RỖNG"):
        baseline.kiem_header(d)


def test_dump_la_thong_bao_loi_bi_chan(tmp_path):
    d = tmp_path / "l.dump"
    d.write_bytes(b"pg_dump: error: connection to server failed\n")
    with pytest.raises(baseline.ChanLai, match="PGDMP"):
        baseline.kiem_header(d)


def test_checksum_lech_bi_chan(tmp_path):
    with pytest.raises(baseline.ChanLai, match="checksum"):
        baseline.kiem_header(_dump_gia(tmp_path), sha_mong_doi="0" * 64)


# =============================================================================
# baseline — hàng rào 4: vân tay hậu restore fail-closed
# =============================================================================
_BANG_VT = ("fee", "invoice", "payment")


def test_van_tay_doc_duoc_thi_tra_ve_dict():
    assert baseline.phan_tich_van_tay(
        "fee|12\ninvoice|7\npayment|3\n", bang_bat_buoc=_BANG_VT
    ) == {"fee": 12, "invoice": 7, "payment": 3}


def test_van_tay_rong_KHONG_duoc_tinh_la_pass():
    """`{} == {}` là cách cleanup xanh giả trong khi database rỗng."""
    with pytest.raises(baseline.ChanLai, match="RỖNG"):
        baseline.phan_tich_van_tay("", bang_bat_buoc=_BANG_VT)


def test_dong_rac_khong_duoc_bo_qua_im_lang():
    with pytest.raises(baseline.ChanLai, match="không đọc được"):
        baseline.phan_tich_van_tay(
            "fee|12\nERROR: relation does not exist\n", bang_bat_buoc=_BANG_VT
        )


def test_so_hang_khong_phai_so_bi_chan():
    with pytest.raises(baseline.ChanLai, match="số hàng"):
        baseline.phan_tich_van_tay("fee|nhiều\n", bang_bat_buoc=_BANG_VT)


def test_bang_trung_bi_chan():
    with pytest.raises(baseline.ChanLai, match="hai lần"):
        baseline.phan_tich_van_tay(
            "fee|1\nfee|2\ninvoice|0\npayment|0\n", bang_bat_buoc=_BANG_VT
        )


def test_van_tay_thieu_bang_bi_chan():
    with pytest.raises(baseline.ChanLai, match="thiếu bảng"):
        baseline.phan_tich_van_tay("fee|1\ninvoice|2\n", bang_bat_buoc=_BANG_VT)


def test_van_tay_thua_bang_bi_chan():
    with pytest.raises(baseline.ChanLai, match="ngoài danh sách"):
        baseline.phan_tich_van_tay(
            "fee|1\ninvoice|2\npayment|3\nlead|9\n", bang_bat_buoc=_BANG_VT
        )


def test_sau_restore_khop_thi_qua():
    baseline.kiem_sau_restore(
        van_tay_baseline="a" * 64, van_tay_hien_tai="a" * 64,
        alembic_baseline="ovp20260811", alembic_hien_tai="ovp20260811",
    )


def test_alembic_lech_sau_restore_bi_chan():
    with pytest.raises(baseline.ChanLai, match="alembic head"):
        baseline.kiem_sau_restore(
            van_tay_baseline="a" * 64, van_tay_hien_tai="a" * 64,
            alembic_baseline="ovp20260811", alembic_hien_tai="mkchk20260811",
        )


def test_van_tay_lech_sau_restore_bao_db_hong():
    with pytest.raises(baseline.ChanLai, match="KHÔNG"):
        baseline.kiem_sau_restore(
            van_tay_baseline="a" * 64, van_tay_hien_tai="b" * 64,
            alembic_baseline="ovp20260811", alembic_hien_tai="ovp20260811",
        )


@pytest.mark.parametrize("thieu", ["van_tay_hien_tai", "alembic_hien_tai"])
def test_thieu_du_lieu_doi_soat_khong_duoc_tinh_la_pass(thieu):
    kw = {
        "van_tay_baseline": "a" * 64, "van_tay_hien_tai": "a" * 64,
        "alembic_baseline": "ovp20260811", "alembic_hien_tai": "ovp20260811",
    }
    kw[thieu] = ""
    mau = "SHA-256" if thieu == "van_tay_hien_tai" else "thiếu"
    with pytest.raises(baseline.ChanLai, match=mau):
        baseline.kiem_sau_restore(**kw)


# =============================================================================
# registry
# =============================================================================
def _mo(tmp_path: Path, run_id="SMKTEST01") -> registry.Registry:
    return registry.Registry.mo(
        tmp_path, run_id=run_id, git_sha="0" * 40, pack="P2",
        project="qltssmoke", database="qlts_smoke",
    )


def _bl(reg, tmp_path, **doi):
    kw = dict(
        duong_dump=str(tmp_path / "b.dump"), sha256="a" * 64,
        alembic_head="ovp20260811", van_tay_metrics="c" * 64,
        danh_tinh={"project": "qltssmoke", "container_id": "a1b2c3d4e5f6"},
    )
    kw.update(doi)
    reg.ghi_baseline(**kw)


def test_mo_hai_lan_cung_run_id_bi_chan(tmp_path):
    _mo(tmp_path)
    with pytest.raises(registry.LoiRegistry, match="MỘT lần"):
        _mo(tmp_path)


@pytest.mark.parametrize(
    "xau",
    [{"password": "x"}, {"actor": {"A": {"api_key": "x"}}},
     {"ds": [{"session_id": "x"}]}, {"Authorization": "Bearer x"}],
)
def test_khong_duoc_ghi_bi_mat(tmp_path, xau):
    reg = _mo(tmp_path)
    with pytest.raises(registry.LoiRegistry, match="bí mật"):
        reg._ghi(lambda d: d.update({"linh_tinh": xau}))


def test_ghi_hong_thi_RAM_khong_lech_dia(tmp_path, monkeypatch):
    """Bản đầu mutate rồi mới ghi: ghi hỏng là RAM đã đổi, lần sau lưu luôn."""
    reg = _mo(tmp_path)
    cu_ram = json.dumps(reg.du_lieu, sort_keys=True)
    cu_dia = reg.duong.read_text("utf-8")

    monkeypatch.setattr(registry.json, "dump", lambda *a, **k: (_ for _ in ()).throw(OSError("đĩa đầy")))
    with pytest.raises(OSError):
        reg.them_goc(profile_ids=[1])

    assert json.dumps(reg.du_lieu, sort_keys=True) == cu_ram
    assert reg.duong.read_text("utf-8") == cu_dia
    assert list(reg.duong.parent.glob("*.tmp")) == []


def test_ghi_bang_ngoai_danh_sach_bi_chan(tmp_path):
    with pytest.raises(registry.LoiRegistry, match="BANG_THEO_DOI"):
        _mo(tmp_path).ghi_ids("bang_la", [1])


def test_baseline_sha_khong_hop_le_bi_chan(tmp_path):
    with pytest.raises(registry.LoiRegistry, match="sha256"):
        _bl(_mo(tmp_path), tmp_path, sha256="khong-phai-sha")


# --- doc(): không tin tệp trên đĩa ------------------------------------------
def test_doc_thieu_khoa_bi_chan(tmp_path):
    reg = _mo(tmp_path)
    d = json.loads(reg.duong.read_text("utf-8")); del d["ids"]
    reg.duong.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(registry.LoiRegistry, match="thiếu khoá"):
        registry.Registry.doc(tmp_path, "SMKTEST01")


def test_doc_run_id_lech_thu_muc_bi_chan(tmp_path):
    reg = _mo(tmp_path)
    d = json.loads(reg.duong.read_text("utf-8")); d["run_id"] = "KHAC"
    reg.duong.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(registry.LoiRegistry, match="chép nhầm chỗ"):
        registry.Registry.doc(tmp_path, "SMKTEST01")


@pytest.mark.parametrize("khoa,gia_tri,mau", [("project", "qlts", "project"), ("database", "qlts_dev", "database")])
def test_doc_project_hoac_database_lech_bi_chan(tmp_path, khoa, gia_tri, mau):
    reg = _mo(tmp_path)
    d = json.loads(reg.duong.read_text("utf-8")); d[khoa] = gia_tri
    reg.duong.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(registry.LoiRegistry, match=mau):
        registry.Registry.doc(
            tmp_path, "SMKTEST01", project_mong_doi="qltssmoke",
            database_mong_doi="qlts_smoke",
        )


def test_doc_duong_dump_ngoai_goc_bi_chan(tmp_path):
    """Đường dump sửa tay là đường nạp dữ liệu lạ vào database."""
    reg = _mo(tmp_path)
    _bl(reg, tmp_path, duong_dump="/etc/passwd")
    with pytest.raises(registry.LoiRegistry, match="nằm ngoài"):
        registry.Registry.doc(tmp_path, "SMKTEST01", goc_dump_cho_phep=tmp_path / "dumps")


def test_doc_hop_le_thi_qua(tmp_path):
    goc = tmp_path / "dumps"; goc.mkdir()
    reg = _mo(tmp_path)
    _bl(reg, tmp_path, duong_dump=str(goc / "b.dump"))
    ok = registry.Registry.doc(
        tmp_path, "SMKTEST01", project_mong_doi="qltssmoke",
        database_mong_doi="qlts_smoke", goc_dump_cho_phep=goc,
    )
    assert ok.du_lieu["run_id"] == "SMKTEST01"


# --- action: intent khai trước ----------------------------------------------
def test_action_dung_du_kien_thi_qua(tmp_path):
    reg = _mo(tmp_path)
    i = reg.bat_dau_action(
        "FIN-10.b1", {"payment": {"1": "v1"}},
        bang_du_kien=["payment"], them_du_kien={"payment": ["2"]},
    )
    delta = reg.ket_thuc_action(i, {"payment": {"1": "v1", "2": "v2"}})
    assert delta["payment"]["them"] == ["2"]
    assert 2 in reg.tat_ca_ids()["payment"]


def test_them_ngoai_du_kien_lam_pack_dung(tmp_path):
    reg = _mo(tmp_path)
    i = reg.bat_dau_action("FIN-10.b2", {"payment": {}}, bang_du_kien=["payment"])
    with pytest.raises(registry.LoiRegistry, match="ngoài dự kiến"):
        reg.ket_thuc_action(i, {"payment": {"99": "v"}})


def test_ban_ghi_MAT_cung_bi_bat(tmp_path):
    """Chỉ so id mới thì một bản ghi biến mất đi qua không ai thấy."""
    reg = _mo(tmp_path)
    i = reg.bat_dau_action("FIN-11", {"payment": {"1": "v1"}}, bang_du_kien=["payment"])
    with pytest.raises(registry.LoiRegistry, match="ngoài dự kiến"):
        reg.ket_thuc_action(i, {"payment": {}})


def test_doi_noi_dung_cung_id_bi_bat(tmp_path):
    """amount/status đổi ở cùng id — bằng chứng riêng, không phải id mới."""
    reg = _mo(tmp_path)
    i = reg.bat_dau_action("FIN-12", {"payment": {"1": "v1"}}, bang_du_kien=["payment"])
    with pytest.raises(registry.LoiRegistry, match="ngoài dự kiến"):
        reg.ket_thuc_action(i, {"payment": {"1": "v2"}})


def test_doi_noi_dung_khai_truoc_thi_qua(tmp_path):
    reg = _mo(tmp_path)
    i = reg.bat_dau_action(
        "FIN-12", {"payment": {"1": "v1"}}, bang_du_kien=["payment"],
        doi_du_kien={"payment": ["1"]},
    )
    assert reg.ket_thuc_action(i, {"payment": {"1": "v2"}})["payment"]["doi"] == ["1"]


def test_anh_chup_lech_tap_bang_bi_chan(tmp_path):
    reg = _mo(tmp_path)
    i = reg.bat_dau_action("FIN-13", {"payment": {}, "fee": {}}, bang_du_kien=["payment", "fee"])
    with pytest.raises(registry.LoiRegistry, match="lệch tập bảng"):
        reg.ket_thuc_action(i, {"payment": {}})


def test_ket_thuc_hai_lan_bi_chan(tmp_path):
    reg = _mo(tmp_path)
    i = reg.bat_dau_action("FIN-14", {"payment": {}}, bang_du_kien=["payment"])
    reg.ket_thuc_action(i, {"payment": {}})
    with pytest.raises(registry.LoiRegistry, match="hai lần"):
        reg.ket_thuc_action(i, {"payment": {}})


def test_intent_duoc_ghi_xuong_dia_TRUOC_mutation(tmp_path):
    """Bằng chứng nằm ở đĩa ngay sau `bat_dau_action`, không phải lúc kết thúc."""
    reg = _mo(tmp_path)
    reg.bat_dau_action("FIN-15", {"payment": {}}, bang_du_kien=["payment"],
                       them_du_kien={"payment": ["7"]})
    tren_dia = json.loads(reg.duong.read_text("utf-8"))
    bg = tren_dia["actions"][-1]
    assert bg["trang_thai"] == "DANG_CHAY"
    assert bg["du_kien"]["them"] == {"payment": ["7"]}


def test_bang_du_kien_ngoai_danh_sach_bi_chan(tmp_path):
    with pytest.raises(registry.LoiRegistry, match="BANG_THEO_DOI"):
        _mo(tmp_path).bat_dau_action("X", {"bang_la": {}}, bang_du_kien=["bang_la"])


def test_van_tay_on_dinh_theo_noi_dung():
    assert registry.van_tay({"a": [2, 1]}) == registry.van_tay({"a": [2, 1]})
    assert registry.van_tay({"a": [1]}) != registry.van_tay({"a": [2]})


def test_cleanup_trang_thai_la_bi_chan(tmp_path):
    with pytest.raises(registry.LoiRegistry, match="trạng thái cleanup"):
        _mo(tmp_path).ghi_cleanup(trang_thai="xong_roi", van_tay_sau="a" * 64)


# =============================================================================
# .gitignore — ngoại lệ phải HẸP, và tệp được mở phải sạch
# =============================================================================
def test_gitignore_ngoai_le_smoke_chi_mo_dung_seed():
    gi = (_GOC.parent / ".gitignore").read_text(encoding="utf-8")
    assert "Backend_FastAPI/scripts/smoke_*.py" in gi, "hàng rào rộng đã biến mất"
    mo = re.findall(r"^!Backend_FastAPI/scripts/(.+)$", gi, re.MULTILINE)
    assert mo == ["smoke_finance_seed.py"], (
        f"ngoại lệ phải HẸP, chỉ đúng seed Finance; hiện mở: {mo}"
    )


def test_seed_duoc_mo_khong_co_credential_hard_coded():
    """Lý do hàng rào rộng tồn tại: một script cũ có mật khẩu trong mã."""
    seed = _GOC / "scripts" / "smoke_finance_seed.py"
    assert seed.is_file(), (
        f"thiếu {seed} — seed P1 nay là artifact BẮT BUỘC của harness "
        "(.gitignore đã mở ngoại lệ cho nó). Thiếu nó thì phép quét credential "
        "dưới đây không canh gì cả."
    )
    ma = seed.read_text(encoding="utf-8")
    xau = re.findall(
        r"""(?im)^\s*(?!#).*\b(password|passwd|secret|token|api_key)\b\s*=\s*['"][^'"]+['"]""",
        ma,
    )
    assert not xau, f"seed có credential hard-coded: {xau}"


# =============================================================================
# NĂM ĐỐI CHỨNG PHÁ GUARD — mỗi cái từng ĐI QUA khi lẽ ra phải bị chặn
# =============================================================================
@pytest.mark.parametrize("app_env", ["", "   ", "staging", "local", "test", "developement"])
def test_doi_chung_app_env_khong_phai_development_deu_BLOCK(app_env):
    """Blocklist chỉ cấm prod ⇒ `APP_ENV=""` (biến chưa đặt) đi lọt vào DROP DB."""
    with pytest.raises(baseline.ChanLai, match="allowlist"):
        baseline.kiem_moi_truong(
            app_env=app_env, ten_db="qlts_smoke", moi_truong=_ENV_DU
        )


@pytest.mark.parametrize("service", ["backend", "frontend", "redis", "", "postgres-2"])
def test_doi_chung_service_khong_phai_postgres_deu_BLOCK(service):
    """Mọi container trong project đều mang nhãn `project` — kể cả backend."""
    d = dict(
        _DANH_TINH,
        nhan_container={
            "com.docker.compose.project": "qltssmoke",
            "com.docker.compose.service": service,
        },
    )
    with pytest.raises(baseline.ChanLai, match="service"):
        baseline.kiem_danh_tinh(**d)


@pytest.mark.parametrize("rac", ["x", "", "PASS", "0" * 63, "g" * 64, "A" * 64])
def test_doi_chung_van_tay_rac_bang_nhau_van_BLOCK(rac):
    """Hai giá trị rác giống nhau không phải bằng chứng database đã về nền."""
    with pytest.raises(baseline.ChanLai, match="SHA-256|thiếu"):
        baseline.kiem_sau_restore(
            van_tay_baseline=rac, van_tay_hien_tai=rac,
            alembic_baseline="ovp20260811", alembic_hien_tai="ovp20260811",
        )


@pytest.mark.parametrize(
    "dong_gia",
    [
        "3401; 0 16401 TABLE DATA evil payment qlts",       # schema khác
        "215; 1259 16409 TABLE public payment qlts",         # chỉ định nghĩa, không có DATA
        "3401; 0 16401 TABLE DATA publicx payment qlts",     # schema gần giống
    ],
)
def test_doi_chung_TOC_gia_mao_deu_BLOCK(tmp_path, dong_gia):
    """`TABLE evil payment` từng được đếm như bảng `payment`."""
    toc = "\n".join(
        [dong_gia]
        + [
            f"34{i:02d}; 0 164{i:02d} TABLE DATA public {t} qlts"
            for i, t in enumerate(baseline.BANG_TRONG_YEU)
            if t != "payment"
        ]
    )
    with pytest.raises(baseline.ChanLai, match="thiếu bảng trọng yếu"):
        baseline.kiem_archive(
            duong=_dump_gia(tmp_path), dau_ra_pg_restore_list=toc,
            ma_thoat_pg_restore_list=0,
        )


def test_doi_chung_du_kien_noi_ve_bang_khong_duoc_chup_BLOCK(tmp_path):
    """Khai dự kiến `fee` mà chỉ chụp `payment` ⇒ chẳng phép kiểm nào chạm `fee`."""
    reg = _mo(tmp_path)
    with pytest.raises(registry.LoiRegistry, match="khác tập bảng"):
        reg.bat_dau_action("FIN-X", {"payment": {}}, bang_du_kien=["fee"])


# --- khai phần thêm bằng SỐ LƯỢNG (id do server sinh) -----------------------
def test_them_so_luong_dung_thi_qua(tmp_path):
    reg = _mo(tmp_path)
    i = reg.bat_dau_action(
        "FIN-10.ui", {"payment": {}}, bang_du_kien=["payment"],
        them_so_luong_du_kien={"payment": 1},
    )
    delta = reg.ket_thuc_action(i, {"payment": {"9001": "v"}})
    assert delta["payment"]["them"] == ["9001"]


def test_them_so_luong_sai_thi_BLOCK(tmp_path):
    """Khai 1 hàng mà ra 2 — 'một' và 'hai' là hai kết quả khác nhau."""
    reg = _mo(tmp_path)
    i = reg.bat_dau_action(
        "FIN-10.ui", {"payment": {}}, bang_du_kien=["payment"],
        them_so_luong_du_kien={"payment": 1},
    )
    with pytest.raises(registry.LoiRegistry, match="ngoài dự kiến"):
        reg.ket_thuc_action(i, {"payment": {"9001": "v", "9002": "v"}})


def test_them_so_luong_bang_ngoai_du_kien_bi_chan(tmp_path):
    """Khai số lượng cho bảng không được chụp — nay bị chặn ngay ở lối vào."""
    reg = _mo(tmp_path)
    with pytest.raises(registry.LoiRegistry, match="không có trong ảnh chụp"):
        reg.bat_dau_action(
            "X", {"payment": {}}, bang_du_kien=["payment"],
            them_so_luong_du_kien={"fee": 1},
        )


# --- doc_cho_cleanup: ba tham số bắt buộc ------------------------------------
def test_doc_cho_cleanup_doi_du_ba_tham_so(tmp_path):
    goc = tmp_path / "dumps"; goc.mkdir()
    reg = _mo(tmp_path)
    _bl(reg, tmp_path, duong_dump=str(goc / "b.dump"))
    ok = registry.Registry.doc_cho_cleanup(
        tmp_path, "SMKTEST01", project="qltssmoke",
        database="qlts_smoke", goc_dump_cho_phep=goc,
    )
    assert ok.du_lieu["baseline"]["sha256"] == "a" * 64


def test_doc_cho_cleanup_khong_co_baseline_thi_BLOCK(tmp_path):
    goc = tmp_path / "dumps"; goc.mkdir()
    _mo(tmp_path)
    with pytest.raises(registry.LoiRegistry, match="chưa có baseline"):
        registry.Registry.doc_cho_cleanup(
            tmp_path, "SMKTEST01", project="qltssmoke",
            database="qlts_smoke", goc_dump_cho_phep=goc,
        )


def test_van_tay_metrics_khong_phai_sha_thi_BLOCK(tmp_path):
    goc = tmp_path / "dumps"; goc.mkdir()
    reg = _mo(tmp_path)
    _bl(reg, tmp_path, duong_dump=str(goc / "b.dump"))
    d = json.loads(reg.duong.read_text("utf-8"))
    d["baseline"]["van_tay_metrics"] = "v"
    reg.duong.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(registry.LoiRegistry, match="van_tay_metrics"):
        registry.Registry.doc(tmp_path, "SMKTEST01")


def test_co_baseline_ma_thieu_danh_tinh_thi_BLOCK(tmp_path):
    reg = _mo(tmp_path)
    _bl(reg, tmp_path)
    d = json.loads(reg.duong.read_text("utf-8"))
    d["danh_tinh"] = None
    reg.duong.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(registry.LoiRegistry, match="danh_tinh"):
        registry.Registry.doc(tmp_path, "SMKTEST01")


# =============================================================================
# BẤT BIẾN HAI CHIỀU — "khai mà KHÔNG xảy ra" cũng phải BLOCK
# =============================================================================
# Bốn ca dưới đây từng PASS_FALSE: vòng lặp chỉ duyệt bảng CÓ delta rồi bỏ qua
# khi delta rỗng, nên nhánh expected−actual không bao giờ chạy. Hệ quả thực tế:
# một refund/payment được kỳ vọng nhưng hệ thống KHÔNG tạo ra vẫn cho `DAT`.
def test_hai_chieu_exact_id_khai_ma_khong_xay_ra_BLOCK(tmp_path):
    reg = _mo(tmp_path)
    i = reg.bat_dau_action(
        "FIN-10.exact", {"payment": {}}, bang_du_kien=["payment"],
        them_du_kien={"payment": ["7"]},
    )
    with pytest.raises(registry.LoiRegistry, match="KHONG_xay_ra"):
        reg.ket_thuc_action(i, {"payment": {}})


def test_hai_chieu_so_luong_khai_1_sinh_0_BLOCK(tmp_path):
    """Kỳ vọng một refund, hệ thống tạo 0 — đây là ca đắt nhất."""
    reg = _mo(tmp_path)
    i = reg.bat_dau_action(
        "FIN-10.count", {"refund_request": {}}, bang_du_kien=["refund_request"],
        them_so_luong_du_kien={"refund_request": 1},
    )
    with pytest.raises(registry.LoiRegistry, match="sai_so_luong"):
        reg.ket_thuc_action(i, {"refund_request": {}})


def test_hai_chieu_doi_khai_ma_khong_xay_ra_BLOCK(tmp_path):
    """Khai status sẽ đổi, nhưng hàng giữ nguyên ⇒ nghiệp vụ đã không chạy."""
    reg = _mo(tmp_path)
    i = reg.bat_dau_action(
        "FIN-12.change", {"payment": {"1": "v1"}}, bang_du_kien=["payment"],
        doi_du_kien={"payment": ["1"]},
    )
    with pytest.raises(registry.LoiRegistry, match="doi_khai_ma_KHONG_xay_ra"):
        reg.ket_thuc_action(i, {"payment": {"1": "v1"}})


def test_hai_chieu_mat_khai_ma_khong_xay_ra_BLOCK(tmp_path):
    reg = _mo(tmp_path)
    i = reg.bat_dau_action(
        "FIN-09.void", {"payment": {"1": "v1"}}, bang_du_kien=["payment"],
        mat_du_kien={"payment": ["1"]},
    )
    with pytest.raises(registry.LoiRegistry, match="mat_khai_ma_KHONG_xay_ra"):
        reg.ket_thuc_action(i, {"payment": {"1": "v1"}})


def test_hai_chieu_dung_du_ca_ba_loai_thi_qua(tmp_path):
    """Guard không được chặn nhầm khi mọi thứ xảy ra đúng như khai."""
    reg = _mo(tmp_path)
    i = reg.bat_dau_action(
        "FIN-10.full", {"payment": {"1": "v1", "2": "v2"}}, bang_du_kien=["payment"],
        them_du_kien={"payment": ["3"]},
        doi_du_kien={"payment": ["1"]},
        mat_du_kien={"payment": ["2"]},
    )
    delta = reg.ket_thuc_action(i, {"payment": {"1": "vMOI", "3": "v3"}})
    assert delta["payment"] == {"them": ["3"], "mat": ["2"], "doi": ["1"]}


def test_so_luong_dung_0_khai_0_thi_qua(tmp_path):
    """Khai 'không có gì thêm' và đúng là không có gì — phải qua."""
    reg = _mo(tmp_path)
    i = reg.bat_dau_action(
        "FIN-17.readonly", {"payment": {"1": "v1"}}, bang_du_kien=["payment"],
        them_so_luong_du_kien={"payment": 0},
    )
    assert reg.ket_thuc_action(i, {"payment": {"1": "v1"}}) == {}


def test_khai_ca_id_lan_so_luong_cho_cung_bang_BLOCK(tmp_path):
    reg = _mo(tmp_path)
    with pytest.raises(registry.LoiRegistry, match="CẢ id cụ thể lẫn số lượng"):
        reg.bat_dau_action(
            "X", {"payment": {}}, bang_du_kien=["payment"],
            them_du_kien={"payment": ["1"]}, them_so_luong_du_kien={"payment": 1},
        )


@pytest.mark.parametrize("loai", ["them_du_kien", "doi_du_kien", "mat_du_kien"])
def test_khai_cho_bang_khong_duoc_chup_BLOCK(tmp_path, loai):
    reg = _mo(tmp_path)
    with pytest.raises(registry.LoiRegistry, match="không có trong ảnh chụp"):
        reg.bat_dau_action(
            "X", {"payment": {}}, bang_du_kien=["payment"], **{loai: {"fee": ["1"]}}
        )


def test_kiem_nguoc_bo_nhanh_hai_chieu_thi_bon_ca_di_lot(tmp_path):
    """Chứng minh bốn ca trên xanh NHỜ nhánh expected−actual, không vì lý do khác.

    Dựng lại đúng hình dạng mã cũ — chỉ so actual−expected — rồi khẳng định cả
    bốn kịch bản đều không bị phát hiện.
    """
    def _cu(truoc, sau, du_kien):
        ngoai = {}
        for bang in sorted(set(truoc) | set(sau)):
            t, s = truoc.get(bang, {}), sau.get(bang, {})
            them = sorted(set(s) - set(t))
            mat = sorted(set(t) - set(s))
            doi = sorted(k for k in (set(t) & set(s)) if t[k] != s[k])
            if not (them or mat or doi):
                continue  # ← đúng dòng làm hỏng
            phan = {
                loai: sorted(set(gt) - set(du_kien.get(loai, {}).get(bang, [])))
                for loai, gt in (("them", them), ("mat", mat), ("doi", doi))
            }
            phan = {k: v for k, v in phan.items() if v}
            if phan:
                ngoai[bang] = phan
        return ngoai

    kich_ban = [
        ({"payment": {}}, {"payment": {}}, {"them": {"payment": ["7"]}}),
        ({"refund_request": {}}, {"refund_request": {}}, {"them": {"refund_request": ["9"]}}),
        ({"payment": {"1": "v1"}}, {"payment": {"1": "v1"}}, {"doi": {"payment": ["1"]}}),
        ({"payment": {"1": "v1"}}, {"payment": {"1": "v1"}}, {"mat": {"payment": ["1"]}}),
    ]
    for truoc, sau, dk in kich_ban:
        assert _cu(truoc, sau, dk) == {}, "logic cũ lẽ ra phải MÙ với ca này"


# =============================================================================
# SNAPSHOT RỖNG — "không quan sát gì" không được đọc thành "không có gì sai"
# =============================================================================
def test_doi_chung_snapshot_rong_hoan_toan_BLOCK(tmp_path):
    """`{} → {}` với `bang_du_kien=[]` từng cho DAT: hai tập rỗng bằng nhau,
    rồi vòng đối soát không duyệt bảng nào."""
    reg = _mo(tmp_path)
    with pytest.raises(registry.LoiRegistry, match="rỗng"):
        reg.bat_dau_action("FIN-rong", {}, bang_du_kien=[])


def test_bang_du_kien_rong_BLOCK(tmp_path):
    reg = _mo(tmp_path)
    with pytest.raises(registry.LoiRegistry, match="`bang_du_kien` rỗng"):
        reg.bat_dau_action("X", {"payment": {}}, bang_du_kien=[])


def test_anh_chup_truoc_rong_BLOCK(tmp_path):
    reg = _mo(tmp_path)
    with pytest.raises(registry.LoiRegistry, match="TRƯỚC rỗng"):
        reg.bat_dau_action("X", {}, bang_du_kien=["payment"])


def test_anh_chup_sau_rong_BLOCK(tmp_path):
    """Phòng thủ đầu thứ hai — người gọi vẫn có thể truyền `{}` lúc kết thúc."""
    reg = _mo(tmp_path)
    i = reg.bat_dau_action("X", {"payment": {}}, bang_du_kien=["payment"])
    with pytest.raises(registry.LoiRegistry, match="SAU rỗng"):
        reg.ket_thuc_action(i, {})


def test_bang_duoc_quan_sat_nhung_KHONG_co_hang_van_qua(tmp_path):
    """Ca LÀNH phải phân biệt được với ca rỗng: có quan sát, bảng không có hàng."""
    reg = _mo(tmp_path)
    i = reg.bat_dau_action("FIN-17.readonly", {"payment": {}}, bang_du_kien=["payment"])
    assert reg.ket_thuc_action(i, {"payment": {}}) == {}
