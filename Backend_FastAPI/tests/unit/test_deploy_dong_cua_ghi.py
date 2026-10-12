"""Khoá Step 4c của `scripts/deploy.sh` — ĐÓNG CỬA GHI ở đường A (vá 12-10-2026).

Vì sao tệp này tồn tại
----------------------
Review F28: khi migration ĐỎ, Step 6 phát lại bản sao của Step 5 bằng `psql`.
Bản sao chỉ chứa thứ đã commit TRƯỚC lúc `pg_dump` bắt đầu, mà `backend`,
`celery-worker`, `celery-beat` CŨ chạy suốt Step 5 → 7 ⇒ lượt phát lại xoá mọi
ghi trong cửa sổ, kể cả request đã nhận 2xx.

Review F32: bộ đếm `pg_stat_user_tables` (PA2) có thể CHE KHUẤT ghi thật, nên
PA2 chỉ là lớp PHÁT HIỆN. Bảo đảm là PA1: cửa ghi đóng xuyên suốt dump →
migrate → phát lại, và chỉ tự phát lại khi bất biến ấy được ĐO là còn giữ ngay
trước khi phát lại — bước (d).

Cách kiểm: chạy THẬT `scripts/deploy.sh` trên sân khấu của
`test_deploy_startup_gates.py` (stub `docker`/`git`), với mô hình cửa ghi
`_MANH_STUB_CUA_GHI`: trạng thái container suy từ NHẬT KÝ LỆNH mà chính script
vừa phát ra. Mỗi ca vi phạm ĐÚNG MỘT bất biến. Mỗi guard có một ca kiểm ngược
gỡ đúng guard ấy trên một bản sao và chứng minh điều xấu lại xảy ra.

Bằng chứng "0 mất ghi" bằng request thật nằm ở bộ diễn tập LOCAL (stack Docker
thật), không ở đây: tệp này khoá HỢP ĐỒNG lệnh — dừng gì, lúc nào, mở lại bằng
gì, và khi nào TUYỆT ĐỐI không phát lại.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.test_deploy_startup_gates import (
    _COMPOSE,
    _DEPLOY,
    _MOC_ALEMBIC,
    _MOC_PGDUMP,
    _MOC_STEP8,
    _bo_qua_neu_khong_posix,
    _chay_deploy,
    _cid_gia,
    _dung_san_khau,
)

yaml = pytest.importorskip("yaml", reason="cần PyYAML để đọc docker-compose.yml")

_DV_GHI = ("backend", "celery-worker", "celery-beat")
_THU_TU_DUNG = ("celery-beat", "backend", "celery-worker")
_THU_TU_MO = ("backend", "celery-worker", "celery-beat")
_MOC_PHAT_LAI = "exec -T postgres psql -v ON_ERROR_STOP=1"
_MOC_TAG_3B = "docker tag "
_MOC_MOC_NGOAI = "# tac-nhan-ngoai"
# Hạn ngắn cho MỌI ca: cùng ngữ nghĩa, không đốt 30 s ở nhánh "còn phiên lạ".
_NHANH = {"QLTS_HAN_PHIEN_LA": "1", "QLTS_HEALTH_TIMEOUT": "4"}


def _dong(nhat_ky: str) -> list[str]:
    return nhat_ky.splitlines()


def _vt(nhat_ky: str, moc: str) -> int:
    for i, d in enumerate(_dong(nhat_ky)):
        if moc in d:
            return i
    return -1


def _vt_dung(nhat_ky: str, dv: str) -> int:
    cid = _cid_gia(dv)
    for i, d in enumerate(_dong(nhat_ky)):
        if d.startswith("docker stop ") and d.endswith(cid):
            return i
    return -1


def _start_cua_deploy(nhat_ky: str) -> list[tuple[int, str]]:
    """`docker start` do CHÍNH deploy.sh phát ra (loại dòng tác nhân ngoài)."""
    ra = []
    for i, d in enumerate(_dong(nhat_ky)):
        if d.startswith("docker start ") and _MOC_MOC_NGOAI not in d:
            ra.append((i, d.split()[-1]))
    return ra


def _cid_ve_dv(cid: str) -> str:
    for dv in _DV_GHI:
        if _cid_gia(dv) == cid:
            return dv
    return "?" + cid[:8]


def _tep_trang_thai(goc: Path) -> str:
    tep = list((goc / "backups").glob("deploy_*.trang-thai"))
    assert len(tep) == 1, f"cần đúng 1 tệp trạng thái, thấy {tep}"
    return tep[0].read_text(encoding="utf-8")


def _cac_pha(goc: Path) -> list[str]:
    return [
        d.split("\t")[2]
        for d in _tep_trang_thai(goc).splitlines()
        if d.split("\t")[1:2] == ["pha"]
    ]


def _ban_dot_bien(cu: str, moi: str) -> str:
    than = _DEPLOY.read_text(encoding="utf-8")
    assert than.count(cu) == 1, f"neo đột biến không khớp DUY NHẤT: {cu[:70]!r}"
    return than.replace(cu, moi, 1)


def _ra(ket) -> str:
    return (ket.stdout or "") + (ket.stderr or "")


# =============================================================================
# I. Đường XANH — đóng đúng chỗ, mở bằng container MỚI ở Step 8
# =============================================================================
@_bo_qua_neu_khong_posix
def test_xanh_dong_ba_container_sau_3b_truoc_pg_dump(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(goc, **_NHANH)
    assert ket.returncode == 0, _ra(ket)[-2500:]

    i_tag = _vt(nk, _MOC_TAG_3B)
    i_build = _vt(nk, "build --parallel")
    i_dung = [_vt_dung(nk, dv) for dv in _THU_TU_DUNG]
    i_dump = _vt(nk, _MOC_PGDUMP)
    i_mig = _vt(nk, _MOC_ALEMBIC)
    i_8 = _vt(nk, _MOC_STEP8)
    assert -1 not in i_dung, f"thiếu lệnh dừng: {dict(zip(_THU_TU_DUNG, i_dung))}\n{nk}"
    # 3b đọc ID ảnh bằng `ps -q` (chỉ container ĐANG chạy) ⇒ dừng phải SAU 3b.
    assert 0 <= i_tag < min(i_dung), f"dừng TRƯỚC Step 3b — 3b sẽ đổ:\n{nk}"
    assert i_build < min(i_dung), "dừng trước build — kéo dài cửa sổ ngừng ghi vô ích"
    assert i_dung == sorted(i_dung), f"thứ tự dừng phải là {_THU_TU_DUNG}:\n{nk}"
    assert max(i_dung) < i_dump < i_mig < i_8, (
        f"thứ tự sai: dừng={i_dung} pg_dump={i_dump} migrate={i_mig} step8={i_8}\n{nk}"
    )
    assert _start_cua_deploy(nk) == [], "đường xanh KHÔNG được mở lại container CŨ"
    assert _MOC_PHAT_LAI not in nk, "đường xanh mà phát lại bản sao"


@_bo_qua_neu_khong_posix
def test_xanh_tep_trang_thai_ghi_du_pha(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, _ = _chay_deploy(goc, **_NHANH)
    assert ket.returncode == 0, _ra(ket)[-2000:]
    assert _cac_pha(goc) == [
        "chua_dong", "dang_dong", "da_dong", "dang_migrate", "da_migrate", "buoc8", "xong",
    ]
    tt = _tep_trang_thai(goc)
    for dv in _DV_GHI:
        assert _cid_gia(dv) in tt, f"tệp trạng thái thiếu CID cũ của {dv}"
    assert "matkhau-gia" not in tt, "tệp trạng thái chứa giá trị bí mật"
    assert "thoat\trc=0" in tt


# =============================================================================
# II. Migration ĐỎ — (d) → PA2 → phát lại → `docker start` ĐÚNG container cũ
# =============================================================================
@_bo_qua_neu_khong_posix
def test_do_cua_con_dong_thi_phat_lai_roi_start_dung_cid_cu(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(goc, STUB_ALEMBIC_RC="1", **_NHANH)
    ra = _ra(ket)

    assert ket.returncode != 0, "migration đỏ mà deploy thoát 0"
    i_pl = _vt(nk, _MOC_PHAT_LAI)
    assert i_pl > _vt(nk, _MOC_ALEMBIC) > -1, f"không phát lại sau migration đỏ:\n{nk}"
    st = _start_cua_deploy(nk)
    assert [_cid_ve_dv(c) for _, c in st] == list(_THU_TU_MO), f"mở lại sai container/thứ tự: {st}"
    assert all(i > i_pl for i, _ in st), "mở container TRƯỚC khi phát lại xong"
    sau = "\n".join(_dong(nk)[i_pl:])
    assert "up -d" not in sau, f"nhánh lùi dùng `up -d` — dựng ảnh MỚI trên lược đồ CŨ:\n{sau}"
    assert _MOC_STEP8 not in nk
    assert "Database restored from backup" in ra
    assert "cùng container, cùng ảnh" in ra, ra[-1500:]


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,kich_ban,thong_diep",
    [
        ("(d): backend cũ ĐANG CHẠY lại", {"STUB_HOI_SINH": "chay"}, "ĐANG CHẠY"),
        ("(d): backend cũ bật rồi tắt lại — mốc vòng đời đổi",
         {"STUB_HOI_SINH": "dung_lai"}, "ĐÃ CHẠY LẠI giữa chừng"),
        ("(d): có phiên lạ sau migrate", {"STUB_PHIEN_LA_SAU_MIGRATE": "1"}, "phiên lạ"),
        ("PA2: bộ đếm T1 ≠ T0", {"STUB_DEM_T1_LECH": "1"}, "public.ghi_thu: hiệu = 1"),
    ],
)
def test_do_khong_chung_minh_duoc_cua_dong_thi_khong_phat_lai_khong_mo(
    tmp_path: Path, ten_ca: str, kich_ban: dict, thong_diep: str
) -> None:
    """Bước (d) hoặc PA2 chặn ⇒ KHÔNG phát lại, KHÔNG `docker start`: lược đồ có
    thể LAI (AUTOCOMMIT), cửa giữ ĐÓNG tới khi người vận hành quyết định."""
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(goc, STUB_ALEMBIC_RC="1", **kich_ban, **_NHANH)
    ra = _ra(ket)

    assert ket.returncode != 0, f"{ten_ca}: deploy thoát 0"
    assert _MOC_PHAT_LAI not in nk, f"{ten_ca}: VẪN phát lại bản sao:\n{nk}"
    assert _start_cua_deploy(nk) == [], f"{ten_ca}: script tự mở ứng dụng trên lược đồ chưa rõ"
    assert thong_diep in ra, f"{ten_ca}: thiếu thông điệp {thong_diep!r}:\n{ra[-2000:]}"
    assert "KHÔNG phát lại" in ra
    assert _cac_pha(goc)[-1] == "dang_migrate", f"{ten_ca}: dừng sai pha {_cac_pha(goc)}"


# =============================================================================
# III. Trước khi chạm CSDL — đo không đạt ⇒ dừng, MỞ LẠI đúng container cũ
# =============================================================================
@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,kich_ban,thong_diep",
    [
        ("4c: còn phiên lạ", {"STUB_PHIEN_LA": "1"}, "còn phiên lạ trên CSDL"),
        ("4c: không đo được phiên", {"STUB_PSQL_RC": "2"}, "KHÔNG đo được pg_stat_activity"),
        ("4c: không chụp được T0", {"STUB_DEM_RC": "2"}, "bộ đếm T0"),
        ("Step 5: pg_dump hỏng sau khi đã đóng", {"STUB_PGDUMP_RC": "1"}, "pg_dump THẤT BẠI"),
    ],
)
def test_do_truoc_khi_cham_csdl_thi_dung_va_mo_lai_dung_container_cu(
    tmp_path: Path, ten_ca: str, kich_ban: dict, thong_diep: str
) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(goc, **kich_ban, **_NHANH)
    ra = _ra(ket)

    assert ket.returncode != 0, f"{ten_ca}: deploy thoát 0"
    assert thong_diep in ra, f"{ten_ca}: thiếu {thong_diep!r}:\n{ra[-2000:]}"
    assert _MOC_ALEMBIC not in nk, f"{ten_ca}: đã chạy migration"
    st = _start_cua_deploy(nk)
    assert [_cid_ve_dv(c) for _, c in st] == list(_THU_TU_MO), (
        f"{ten_ca}: CSDL chưa bị chạm mà không mở lại đủ 3 container cũ: {st}\n{ra[-1500:]}"
    )
    assert "ĐÃ mở lại container CŨ" in ra


@_bo_qua_neu_khong_posix
def test_restart_policy_khac_thi_dung_truoc_khi_dung_container(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(goc, STUB_RESTART_POLICY="always", **_NHANH)
    assert ket.returncode != 0
    assert "restart policy 'always'" in _ra(ket)
    assert "docker stop " not in nk, "đã dừng container dù chính sách restart không an toàn"
    assert _MOC_PGDUMP not in nk


@_bo_qua_neu_khong_posix
def test_thieu_container_dang_chay_thi_dung_truoc_khi_dung_gi(tmp_path: Path) -> None:
    """Đường bỏ qua tài sản (3b không chạy) vẫn phải biết CHÍNH XÁC container cũ."""
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(
        goc,
        QLTS_SKIP_ROLLBACK_ASSET="1",
        QLTS_SKIP_ROLLBACK_ASSET_REASON="ca kiem 4c",
        STUB_PS_Q_THIEU="celery-beat",
        **_NHANH,
    )
    assert ket.returncode != 0
    assert "'celery-beat' có 0 container ĐANG CHẠY" in _ra(ket), _ra(ket)[-1500:]
    assert "docker stop " not in nk
    assert _MOC_PGDUMP not in nk


@_bo_qua_neu_khong_posix
def test_pre_deploy_check_do_sau_migrate_xanh_thi_giu_dung(tmp_path: Path) -> None:
    """Lược đồ đã MỚI ⇒ không mở mã CŨ lên (cửa sổ CK5), không tự dựng mã mới."""
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(goc, STUB_PREDEPLOY_RC="1", **_NHANH)
    assert ket.returncode != 0
    assert _start_cua_deploy(nk) == []
    assert _MOC_STEP8 not in nk
    assert "lược đồ CHƯA RÕ hoặc đã MỚI" in _ra(ket)
    assert _cac_pha(goc)[-1] == "da_migrate"


# =============================================================================
# IV. Bị NGẮT giữa chừng — trap theo pha
# =============================================================================
@_bo_qua_neu_khong_posix
@pytest.mark.parametrize("tin_hieu,rc", [("TERM", 143), ("HUP", 129), ("INT", 130), ("PIPE", 141)])
def test_ngat_trong_migrate_thi_khong_mo_khong_phat_lai(
    tmp_path: Path, tin_hieu: str, rc: int
) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(goc, STUB_TIN_HIEU_O_MIGRATE=tin_hieu, **_NHANH)
    assert ket.returncode == rc, f"{tin_hieu}: rc={ket.returncode}\n{_ra(ket)[-1500:]}"
    assert _start_cua_deploy(nk) == [], f"{tin_hieu}: tự mở ứng dụng trên lược đồ chưa rõ"
    assert _MOC_PHAT_LAI not in nk
    assert _MOC_STEP8 not in nk
    tt = _tep_trang_thai(goc)
    assert f"rc={rc} tin_hieu={tin_hieu} pha=dang_migrate" in tt, tt


@_bo_qua_neu_khong_posix
def test_ngat_trong_pg_dump_thi_mo_lai_dung_container_cu(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(goc, STUB_TIN_HIEU_O_DUMP="TERM", **_NHANH)
    assert ket.returncode == 143, _ra(ket)[-1500:]
    assert _MOC_ALEMBIC not in nk
    st = _start_cua_deploy(nk)
    assert [_cid_ve_dv(c) for _, c in st] == list(_THU_TU_MO), st
    assert "rc=143 tin_hieu=TERM pha=da_dong" in _tep_trang_thai(goc)


@_bo_qua_neu_khong_posix
def test_cold_cutover_khong_dong_cua(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(goc, COLD_CUTOVER="true", **_NHANH)
    assert "docker stop " not in nk
    assert "Step 4c: KHÔNG đóng cửa ghi" in _ra(ket)


# =============================================================================
# V. Model Compose — chính sách restart của ba service ghi
# =============================================================================
def test_model_compose_ba_service_ghi_khong_tu_bat_lai_sau_stop() -> None:
    """`unless-stopped`/`no`: dừng tay thì dockerd KHÔNG tự bật lại (kể cả khi
    dockerd khởi động lại). `always` bật lại khi dockerd khởi động lại."""
    mo_hinh = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    for dv in _DV_GHI:
        cs = str((mo_hinh["services"][dv] or {}).get("restart", "no"))
        assert cs in ("unless-stopped", "no"), f"{dv}: restart={cs!r}"


# =============================================================================
# VI. Kiểm ngược — gỡ đúng từng guard trên một BẢN SAO, điều xấu phải xảy ra
# =============================================================================
@_bo_qua_neu_khong_posix
def test_kiem_nguoc_bo_buoc_d_thi_phat_lai_khi_container_dang_chay(tmp_path: Path) -> None:
    dot_bien = _ban_dot_bien(
        '        if ! _dcg_cua_dong "d" || ! _dcg_phien_la_bang_0 "d"; then\n',
        "        if false; then\n",
    )
    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    _, nk = _chay_deploy(goc, STUB_ALEMBIC_RC="1", STUB_HOI_SINH="chay", **_NHANH)
    assert _MOC_PHAT_LAI in nk, "bỏ (d) mà vẫn không phát lại ⇒ ca (d) xanh vì lý do khác"


@_bo_qua_neu_khong_posix
def test_kiem_nguoc_d_chi_so_status_thi_lot_container_bat_roi_tat(tmp_path: Path) -> None:
    dot_bien = _ban_dot_bien(
        '        if [ "$m" != "${_DCG_MOC[$s]}" ]; then\n',
        "        if false; then\n",
    )
    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    _, nk = _chay_deploy(goc, STUB_ALEMBIC_RC="1", STUB_HOI_SINH="dung_lai", **_NHANH)
    assert _MOC_PHAT_LAI in nk, "bỏ so mốc vòng đời mà vẫn chặn ⇒ ca mốc xanh vì lý do khác"


@_bo_qua_neu_khong_posix
def test_kiem_nguoc_bo_do_phien_la_o_4c_thi_pg_dump_chay(tmp_path: Path) -> None:
    dot_bien = _ban_dot_bien(
        '    _dcg_phien_la_bang_0 "4c" || error',
        '    true || error',
    )
    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    _, nk = _chay_deploy(goc, STUB_PHIEN_LA="1", **_NHANH)
    assert _MOC_PGDUMP in nk, "bỏ phép đo phiên ở 4c mà pg_dump vẫn không chạy"


@_bo_qua_neu_khong_posix
def test_kiem_nguoc_nhanh_lui_dung_up_d_thi_lo_ra(tmp_path: Path) -> None:
    dot_bien = _ban_dot_bien(
        '        if ! docker start "${_DCG_CID[$s]}" >/dev/null; then\n',
        '        if ! $_RA_COMPOSE up -d "$s" >/dev/null; then\n',
    )
    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    _, nk = _chay_deploy(goc, STUB_ALEMBIC_RC="1", **_NHANH)
    i_pl = _vt(nk, _MOC_PHAT_LAI)
    assert i_pl >= 0
    assert "up -d" in "\n".join(_dong(nk)[i_pl:]), "đột biến không đổi được lệnh mở lại"


@_bo_qua_neu_khong_posix
def test_kiem_nguoc_trap_mo_ca_o_dang_migrate_thi_app_chay_tren_luoc_do_chua_ro(
    tmp_path: Path,
) -> None:
    dot_bien = _ban_dot_bien(
        "        dang_dong|da_dong|da_phat_lai)\n",
        "        dang_dong|da_dong|da_phat_lai|dang_migrate)\n",
    )
    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    _, nk = _chay_deploy(goc, STUB_TIN_HIEU_O_MIGRATE="TERM", **_NHANH)
    assert _start_cua_deploy(nk), "đột biến trap không mở app ⇒ ca ngắt-trong-migrate xanh vì lý do khác"


@_bo_qua_neu_khong_posix
def test_kiem_nguoc_bo_trap_thi_ngat_trong_dump_bo_app_nam_chet(tmp_path: Path) -> None:
    than = _DEPLOY.read_text(encoding="utf-8")
    dong_trap = [
        "    trap '_dcg_bat_tin_hieu HUP 129' HUP\n",
        "    trap '_dcg_bat_tin_hieu INT 130' INT\n",
        "    trap '_dcg_bat_tin_hieu TERM 143' TERM\n",
        "    trap '_dcg_bat_tin_hieu PIPE 141' PIPE\n",
        "    trap '_dcg_khi_thoat' EXIT\n",
    ]
    for d in dong_trap:
        assert than.count(d) == 1, d
        than = than.replace(d, "")
    goc = _dung_san_khau(tmp_path, deploy_sh=than)
    ket, nk = _chay_deploy(goc, STUB_TIN_HIEU_O_DUMP="TERM", **_NHANH)
    assert ket.returncode != 0
    assert _start_cua_deploy(nk) == [], "bỏ trap mà app vẫn được mở lại ⇒ ca trap xanh vì lý do khác"


@_bo_qua_neu_khong_posix
def test_kiem_nguoc_doi_4c_xuong_sau_pg_dump_thi_lo_thu_tu(tmp_path: Path) -> None:
    """Biến thể TINH VI: vẫn dừng, vẫn đo — chỉ sai CHỖ (sau pg_dump)."""
    than = _DEPLOY.read_text(encoding="utf-8")
    dau = than.index('if [ "${IS_CUTOVER}" -eq 1 ]; then\n    cutover "Step 4c:')
    cuoi_neo = '    log "  ✓ cửa ghi ĐÓNG — giữ đóng xuyên suốt dump → migrate → (nếu đỏ) phát lại"\nfi\n'
    cuoi = than.index(cuoi_neo) + len(cuoi_neo)
    khoi = than[dau:cuoi]
    than = than[:dau] + than[cuoi:]
    neo = 'log "Database backup saved: pre_deploy_${TIMESTAMP}.sql"\n'
    assert than.count(neo) == 1
    than = than.replace(neo, neo + khoi, 1)
    goc = _dung_san_khau(tmp_path, deploy_sh=than)
    _, nk = _chay_deploy(goc, **_NHANH)
    i_dump = _vt(nk, _MOC_PGDUMP)
    assert 0 <= i_dump < _vt_dung(nk, "backend"), (
        "dời 4c xuống sau pg_dump mà thứ tự vẫn đúng ⇒ ca thứ tự không canh gì"
    )


@_bo_qua_neu_khong_posix
def test_bo_lenh_dung_thi_phep_do_4c_chan_truoc_pg_dump(tmp_path: Path) -> None:
    """Phòng thủ chiều sâu TRONG PA1: quên `docker stop` thì phép đo 4c chặn."""
    dot_bien = _ban_dot_bien(
        '        docker stop -t "$(_dcg_han_dung "$_S")" "${_DCG_CID[$_S]}" >/dev/null \\\n',
        '        true \\\n',
    )
    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    ket, nk = _chay_deploy(goc, **_NHANH)
    assert ket.returncode != 0
    assert _MOC_PGDUMP not in nk, "không dừng container mà vẫn sao lưu/migrate"
    assert "ĐANG CHẠY" in _ra(ket)
