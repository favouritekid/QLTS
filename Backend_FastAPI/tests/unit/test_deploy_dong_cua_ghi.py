"""Khoá Step 4c của `scripts/deploy.sh` — ĐÓNG CỬA GHI ở đường A (vá 12-10-2026).

Vì sao tệp này tồn tại
----------------------
Review F28: khi migration ĐỎ, Step 6 (cũ) phát lại bản sao của Step 5 bằng
`psql`. Bản sao chỉ chứa thứ đã commit TRƯỚC lúc `pg_dump` bắt đầu, mà `backend`,
`celery-worker`, `celery-beat` CŨ chạy suốt Step 5 → 7 ⇒ lượt phát lại xoá mọi
ghi trong cửa sổ, kể cả request đã nhận 2xx.

Vòng 1 (12-10): PA1 đóng cửa ghi trước `pg_dump`; tự phát lại chỉ khi bước (d)
đo được cửa còn đóng. Vòng 2 (F35/F37): vân tay lược đồ, tệp trạng thái, phục hồi
nginx. VÒNG 3 (13-10, owner chốt F28): diễn tập vòng 2 đo được một phiên CSDL
ngoài nối SAU T1, ghi rồi ngắt TRƯỚC (d) — lọt mọi lớp, lượt tự phát lại xoá
20/20 giao dịch ⇒ BỎ HẲN TỰ PHÁT LẠI. Migration đỏ ⇒ ứng dụng giữ DỪNG, CSDL
giữ nguyên, (d) + PA2 chỉ còn ĐO để in cho người đối soát. Cùng vòng: F39 — nhánh
lùi về nginx CŨ chỉ BẮT BUỘC phục hồi dịch vụ (TLS/SNI thật, route, so thân);
`nginx-verify.sh` (mã mới, có đầu dò token/PII) chạy lên nginx cũ CHỈ để thông
tin. Dọn one-off alembic CHỈ theo CID đã ghi nhận của chính lượt, CHỈ khi exited.

Cách kiểm: chạy THẬT `scripts/deploy.sh` trên sân khấu của
`test_deploy_startup_gates.py` (stub `docker`/`git`), với mô hình cửa ghi
`_MANH_STUB_CUA_GHI`: trạng thái container suy từ NHẬT KÝ LỆNH mà chính script
vừa phát ra. Mỗi guard có một ca kiểm ngược gỡ đúng guard ấy trên một bản sao
và chứng minh điều xấu lại xảy ra. Mỗi ca `test_v3_*` hành vi đã chạy trên
`e1c6c9fc` (trước vá vòng 3) và ĐỎ.

Bằng chứng "0 mất ghi" bằng request thật (đối soát TỪNG KHOÁ) nằm ở bộ diễn tập
LOCAL (stack Docker thật), không ở đây: tệp này khoá HỢP ĐỒNG lệnh.

Vòng 3b (review độc lập 13-10): phép "không phát lại" cũ bám CHUỖI (`postgres psql`
thiếu ` -c `) nên `exec -T postgres sh -c 'psql …' < bản_sao` LỌT. Nay mọi phép
"không phát lại" / "không mở app" / "không dựng container" đọc nhật ký HÀNH VI của
stub (`lenh.log.goi`: stdin từng lời gọi docker + argv) qua các helper
`_vi_pham_phat_lai`, `_lenh_mo_app`, `_lenh_dung_moi`, `_lenh_mo_lai_cu` của
`test_deploy_startup_gates.py`; mỗi luật có biến thể phá riêng
(`test_kiem_nguoc_phat_lai_bien_the`, `test_kiem_nguoc_mo_app_dang_lenh_khac`).
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
    _cac_loi_goi,
    _chay_deploy,
    _cid_gia,
    _dung_san_khau,
    _lenh_dung_moi,
    _lenh_mo_app,
    _lenh_mo_lai_cu,
    _tach_exec,
    _tach_lenh,
    _vi_pham_phat_lai,
    _vi_tri_alembic,
)

yaml = pytest.importorskip("yaml", reason="cần PyYAML để đọc docker-compose.yml")

_DV_GHI = ("backend", "celery-worker", "celery-beat")
_THU_TU_DUNG = ("celery-beat", "backend", "celery-worker")
_THU_TU_MO = ("backend", "celery-worker", "celery-beat")
_MOC_TAG_3B = "docker tag "
_MOC_MOC_NGOAI = "# tac-nhan-ngoai"
_MOC_DO_DICH_VU = "THAN-NGINX"          # đầu dò PHỤC HỒI DỊCH VỤ (docker run … -c)
_OO = "6" * 64                          # CID one-off alembic của CHÍNH lượt (stub)
_OO_KHAC = "7" * 64                     # one-off của LƯỢT KHÁC (stub)
_VERIFY_THAT = _DEPLOY.parent / "nginx-verify.sh"
# Hạn ngắn cho MỌI ca: cùng ngữ nghĩa, không đốt 30 s ở nhánh "còn phiên lạ".
_NHANH = {"QLTS_HAN_PHIEN_LA": "1", "QLTS_HEALTH_TIMEOUT": "4", "QLTS_HAN_CHO_ONEOFF": "1"}


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


def _moc(goc: Path) -> int:
    """Chỉ số lời gọi migration trong nhật ký HÀNH VI (phải có)."""
    i = _vi_tri_alembic(_cac_loi_goi(goc))
    assert i >= 0, "không thấy lời gọi migration trong nhật ký hành vi"
    return i


def _sau_lan_dung_cuoi(goc: Path) -> int:
    """Chỉ số NGAY SAU lời gọi `docker stop` cuối cùng (Step 4c)."""
    goi = _cac_loi_goi(goc)
    dung = [i for i, g in enumerate(goi) if g["args"][:1] == ["stop"]]
    assert dung, "không thấy lời gọi `docker stop`"
    return dung[-1] + 1


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


def _ban_dot_bien(cu: str, moi: str, than: str | None = None) -> str:
    than = _DEPLOY.read_text(encoding="utf-8") if than is None else than
    assert than.count(cu) == 1, f"neo đột biến không khớp DUY NHẤT: {cu[:70]!r}"
    return than.replace(cu, moi, 1)


def _ra(ket) -> str:
    return (ket.stdout or "") + (ket.stderr or "")


def _lenh_restart_nginx(nhat_ky: str) -> list[int]:
    cn = _cid_gia("nginx")
    return [i for i, d in enumerate(_dong(nhat_ky)) if d.startswith("docker restart ") and d.endswith(cn)]


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
    assert _lenh_mo_lai_cu(goc) == [], f"đường xanh mở lại container CŨ: {_lenh_mo_lai_cu(goc)}"
    assert _vi_pham_phat_lai(goc) == [], f"đường xanh mà phát lại bản sao: {_vi_pham_phat_lai(goc)}"


@_bo_qua_neu_khong_posix
def test_xanh_tep_trang_thai_ghi_du_pha(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(goc, **_NHANH)
    assert ket.returncode == 0, _ra(ket)[-2000:]
    assert _cac_pha(goc) == [
        "chua_dong", "dang_dong", "da_dong", "dang_migrate", "da_migrate", "buoc8", "xong",
    ]
    tt = _tep_trang_thai(goc)
    for dv in _DV_GHI:
        assert _cid_gia(dv) in tt, f"tệp trạng thái thiếu CID cũ của {dv}"
    assert "matkhau-gia" not in tt, "tệp trạng thái chứa giá trị bí mật"
    assert "thoat\trc=0" in tt
    assert "\tT0\t" in tt, "thiếu mốc T0 (thời điểm bản sao Step 5 khớp) trong tệp trạng thái"
    assert " run --rm --name dcg-mig-" in nk, "one-off alembic không mang tên riêng của lượt"


# =============================================================================
# II. Migration ĐỎ — F28 vòng 3: KHÔNG phát lại, ứng dụng giữ DỪNG, CSDL nguyên
# =============================================================================
@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,kich_ban,bang_chung",
    [
        # Ca QUAN TRỌNG NHẤT: mọi hàng rào đều ĐẠT. Vòng 1/2 phát lại ở đây — đúng
        # ca mà phiên ngoài nối sau T1 và ngắt trước (d) đã mất 20/20 giao dịch.
        ("rào ĐẠT: cửa còn đóng, 0 phiên lạ, PA2 = 0", {},
         "✓ [d] 3 container ghi đều exited"),
        ("(d): backend cũ ĐANG CHẠY lại", {"STUB_HOI_SINH": "chay"}, "ĐANG CHẠY"),
        ("(d): backend cũ bật rồi tắt lại — mốc vòng đời đổi",
         {"STUB_HOI_SINH": "dung_lai"}, "ĐÃ CHẠY LẠI giữa chừng"),
        ("(d): có phiên lạ sau migrate", {"STUB_PHIEN_LA_SAU_MIGRATE": "1"}, "còn 1 phiên lạ"),
        ("PA2: bộ đếm T1 ≠ T0", {"STUB_DEM_T1_LECH": "1"}, "public.ghi_thu: hiệu = 1"),
    ],
)
def test_v3_migration_do_khong_phat_lai_giu_dung(
    tmp_path: Path, ten_ca: str, kich_ban: dict, bang_chung: str
) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(goc, STUB_ALEMBIC_RC="1", **kich_ban, **_NHANH)
    ra = _ra(ket)

    assert ket.returncode != 0, f"{ten_ca}: migration đỏ mà deploy thoát 0"
    # Vòng 3b: theo HÀNH VI — dữ liệu bản sao không đi vào lời gọi docker nào,
    # và sau migration mọi `exec` đều đúng dạng phép đo `psql -c` với stdin rỗng.
    assert _vi_pham_phat_lai(goc) == [], f"{ten_ca}: VẪN phát lại bản sao (F28): {_vi_pham_phat_lai(goc)}"
    moc = _moc(goc)
    # Phép R1 không được rỗng nghĩa: sau migration PHẢI có các phép đo `exec … psql -c` (bước (d), PA2).
    assert any(_tach_exec(g["args"]) for g in _cac_loi_goi(goc)[moc + 1:]), "không có exec nào sau migration — R1 rỗng nghĩa"
    assert _lenh_mo_app(goc, moc + 1) == [], f"{ten_ca}: mở/dựng ứng dụng sau migration đỏ: {_lenh_mo_app(goc, moc + 1)}"
    assert _cac_pha(goc)[-1] == "migrate_do", f"{ten_ca}: dừng sai pha {_cac_pha(goc)}"
    assert "KHÔNG phát lại bản sao (F28)" in ra, ra[-2000:]
    assert "PHỤC HỒI CÓ ĐỐI SOÁT" in ra, f"{ten_ca}: thiếu hướng dẫn phục hồi có đối soát"
    # (d) + PA2 vẫn ĐO — để IN cho người đối soát, không còn là cổng.
    assert bang_chung in ra, f"{ten_ca}: thiếu bằng chứng đối soát {bang_chung!r}:\n{ra[-2500:]}"
    assert "[PA2] đo để ĐỐI SOÁT" in ra
    ban_sao = list((goc / "backups").glob("pre_deploy_*.sql"))
    assert len(ban_sao) == 1 and ban_sao[0].stat().st_size > 0, "bản sao Step 5 phải còn nguyên để phục hồi TAY"


@_bo_qua_neu_khong_posix
def test_v3_migration_do_huong_dan_doi_soat_noi_moc_va_duong_tien(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, _ = _chay_deploy(goc, STUB_ALEMBIC_RC="1", **_NHANH)
    ra = _ra(ket)
    assert "mốc T0 20" in ra, "hướng dẫn không nói mốc T0 của bản sao (ghi SAU mốc ấy sẽ mất nếu phát lại)"
    assert "Ưu tiên ĐI TIẾP" in ra
    assert "ĐỐI SOÁT TRƯỚC" in ra and "TỪNG khoá" in ra
    assert "dump --clean --if-exists KHÔNG xoá object" in ra
    assert "Database restored" not in ra, "còn lời khẳng định đã khôi phục"


@_bo_qua_neu_khong_posix
def test_v3_migration_do_van_tay_lech_thi_huong_dan_noi_lech(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(goc, STUB_ALEMBIC_RC="1", STUB_VAN_TAY_LECH_SAU_MIGRATE="1", **_NHANH)
    ra = _ra(ket)
    assert "vân tay lược đồ BÂY GIỜ: LỆCH bản 4c — KHÔNG được bật mã cũ" in ra, ra[-2500:]
    assert _lenh_mo_app(goc, _moc(goc) + 1) == [] and _vi_pham_phat_lai(goc) == []


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
    # Nhánh lùi chỉ được `docker start` ĐÚNG CID cũ — không dựng/bật container nào khác (mọi dạng lệnh).
    assert _lenh_dung_moi(goc, _sau_lan_dung_cuoi(goc)) == [], (
        f"{ten_ca}: nhánh lùi dựng container — ảnh MỚI: {_lenh_dung_moi(goc, _sau_lan_dung_cuoi(goc))}")
    assert "✓ [nginx · dịch vụ] PHỤC HỒI DỊCH VỤ ĐẠT" in ra, f"{ten_ca}: không đo phục hồi dịch vụ"
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
    assert _lenh_mo_app(goc, _moc(goc) + 1) == [], f"mở/dựng ứng dụng sau Step 7 đỏ: {_lenh_mo_app(goc, _moc(goc) + 1)}"
    assert _vi_pham_phat_lai(goc) == []
    assert "KHÔNG tự mở ứng dụng" in _ra(ket)
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
    assert _lenh_mo_app(goc, _moc(goc) + 1) == [], f"{tin_hieu}: tự mở/dựng ứng dụng trên lược đồ chưa rõ"
    assert _vi_pham_phat_lai(goc) == []
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


# --- One-off alembic của CHÍNH lượt: dọn theo CID ghi nhận, chỉ khi exited ----
@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,kich_ban",
    [
        ("bị ngắt TERM khi đang migrate", {"STUB_TIN_HIEU_O_MIGRATE": "TERM"}),
        ("migration đỏ", {"STUB_ALEMBIC_RC": "1"}),
    ],
)
def test_v3_oneoff_exited_cua_chinh_luot_duoc_don_theo_cid_ghi_nhan(
    tmp_path: Path, ten_ca: str, kich_ban: dict
) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(goc, STUB_ONEOFF="exited", **kich_ban, **_NHANH)
    assert f"docker rm {_OO}" in _dong(nk), f"{ten_ca}: không dọn one-off exited của lượt:\n{_ra(ket)[-2000:]}"
    assert f"docker rm {_OO_KHAC}" not in _dong(nk)
    assert f"oneoff\t{_OO} da_don" in _tep_trang_thai(goc)


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "trang_thai,thong_diep",
    [
        # Vòng 4: `running` ⇒ trap CHỜ (hữu hạn, _NHANH = 1 s) rồi báo còn chạy.
        ("running", "CÒN CHẠY / CHƯA XÁC ĐỊNH"),
        # Trạng thái không chờ được mà cũng không phải exited ⇒ điều kiện "chỉ khi exited".
        ("dead", "KHÔNG dọn (chỉ dọn khi exited)"),
    ],
)
def test_v3_oneoff_dang_chay_thi_khong_don(tmp_path: Path, trang_thai: str, thong_diep: str) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(goc, STUB_ONEOFF=trang_thai, STUB_TIN_HIEU_O_MIGRATE="TERM", **_NHANH)
    assert not any(d.startswith("docker rm ") for d in _dong(nk)), f"dọn one-off '{trang_thai}'"
    assert thong_diep in _ra(ket), _ra(ket)[-2000:]


@_bo_qua_neu_khong_posix
def test_v3_cid_ghi_nhan_mang_ten_khac_thi_khong_don(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(
        goc, STUB_ONEOFF="exited", STUB_ONEOFF_TEN_KHAC="1", STUB_TIN_HIEU_O_MIGRATE="TERM", **_NHANH
    )
    assert not any(d.startswith("docker rm ") for d in _dong(nk)), "dọn container không phải one-off của lượt"
    assert "KHÔNG khớp one-off của lượt này" in _ra(ket), _ra(ket)[-2000:]


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
# VI. Phục hồi nginx ở nhánh lùi (pha CHƯA migrate) — F39: dịch vụ BẮT BUỘC,
#     PII chỉ là THÔNG TIN
# =============================================================================
_LUI = {"STUB_PGDUMP_RC": "1"}   # pg_dump hỏng SAU khi cửa đã đóng ⇒ trap mở lại cũ


@_bo_qua_neu_khong_posix
def test_v3_ip_backend_doi_thi_khoi_dong_lai_dung_nginx_cu_roi_do_dich_vu(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(goc, STUB_IP_DOI="1", **_LUI, **_NHANH)
    ra = _ra(ket)
    st = _start_cua_deploy(nk)
    assert st, "không mở lại container cũ"
    rs = _lenh_restart_nginx(nk)
    assert len(rs) == 1, f"IP backend đổi mà không khởi động lại ĐÚNG container nginx cũ:\n{nk}"
    assert rs[0] > max(i for i, _ in st), "khởi động lại nginx TRƯỚC khi backend cũ chạy lại"
    i_dv = _vt(nk, _MOC_DO_DICH_VU)
    i_vf = _vt(nk, f"nginx-verify {_cid_gia('nginx')} vidu.test")
    assert rs[0] < i_dv < i_vf, f"thứ tự restart → đo dịch vụ → kiểm PII sai:\n{nk}"
    assert "✓ [nginx · dịch vụ] PHỤC HỒI DỊCH VỤ ĐẠT" in ra and "ĐÃ mở lại container CŨ" in ra, ra[-2000:]


@_bo_qua_neu_khong_posix
def test_v3_ip_khong_doi_van_do_dich_vu_khong_restart(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    _, nk = _chay_deploy(goc, **_LUI, **_NHANH)
    assert _lenh_restart_nginx(nk) == [], "IP không đổi mà vẫn khởi động lại nginx"
    assert _vt(nk, _MOC_DO_DICH_VU) >= 0, "nhánh lùi không đo đường của người dùng (nginx, SNI thật)"


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,kich_ban,thong_diep",
    [
        ("/health qua nginx 502", {"STUB_MA_HEALTH": "502"}, "cần /health 200"),
        ("thân qua nginx khác thân backend", {"STUB_THAN_LECH": "1"}, "KHÁC thân lấy thẳng từ backend"),
    ],
)
def test_v3_dich_vu_khong_dat_thi_khong_bao_da_mo(
    tmp_path: Path, ten_ca: str, kich_ban: dict, thong_diep: str
) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, _ = _chay_deploy(goc, STUB_IP_DOI="1", **kich_ban, **_LUI, **_NHANH)
    ra = _ra(ket)
    assert ket.returncode != 0
    assert thong_diep in ra, f"{ten_ca}:\n{ra[-2000:]}"
    assert "ĐÃ mở lại container CŨ" not in ra, f"{ten_ca}: báo đã mở lại dù dịch vụ không phục hồi"
    assert "Trạng thái ĐO THẬT" in ra, f"{ten_ca}: thiếu hướng dẫn kèm trạng thái đo"


@_bo_qua_neu_khong_posix
def test_v3_f39_kiem_pii_do_tren_nginx_cu_khong_chan_phuc_hoi(tmp_path: Path) -> None:
    """F39: `nginx-verify.sh` (mã mới, có đầu dò token) ĐỎ trên nginx CŨ là kết
    quả đúng về nginx cũ — không được làm nhánh lùi báo phục hồi KHÔNG ĐẠT."""
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(goc, STUB_NGINX_VERIFY_RC="1", **_LUI, **_NHANH)
    ra = _ra(ket)
    assert [_cid_ve_dv(c) for _, c in _start_cua_deploy(nk)] == list(_THU_TU_MO)
    assert "ĐÃ mở lại container CŨ" in ra, f"kiểm PII đỏ đã chặn phục hồi dịch vụ:\n{ra[-2500:]}"
    assert "[nginx · PII — THÔNG TIN, KHÔNG chặn] nginx-verify.sh KHÔNG ĐẠT (rc=1)" in ra
    assert "pii_nginx_cu\tKHONG_DAT rc=1" in _tep_trang_thai(goc)


# `curl` GIẢ mô phỏng nginx CŨ (ảnh dựng từ 3b2097ef): phục vụ đúng mọi route qua
# SNI thật, nhưng access log ghi `$request` và `$http_referer` THÔ. Đoạn `sh -c`
# của `nginx-verify.sh` THẬT và của đầu dò dịch vụ chạy thật với curl này
# (STUB_CHAY_SH_THAT=1); `docker logs` đọc $QLTS_NGINX_LOG.
_CURL_NGINX_CU = r"""#!/usr/bin/env bash
w=""; ua="curl/gia"; ref="-"; url=""; ra_tep=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        -w) w="$2"; shift 2 ;;
        --user-agent|-A) ua="$2"; shift 2 ;;
        --referer|-e) ref="$2"; shift 2 ;;
        -o|--output) ra_tep="$2"; shift 2 ;;
        --resolve|--max-time|--retry) shift 2 ;;
        -*) shift ;;
        *) url="$1"; shift ;;
    esac
done
con=${url#*://}; host=${con%%/*}
case "$con" in */*) duong="/${con#*/}" ;; *) duong="/" ;; esac
than=""
case "$url" in
    https://khong-thuoc-ve.invalid/*)
        [ -n "$w" ] && printf '000'      # mọi `-w` ở đây đều là "%{http_code}"
        exit 35 ;;
    http://backend:8000/health) ma=200; than='{"status":"ok","detail":"gia"}' ;;
    http://*/.well-known/acme-challenge/*) ma=404 ;;
    http://*) ma=301 ;;
    https://*/health) ma=200; than='{"status":"ok","detail":"gia"}' ;;
    https://*/login*) ma=200; than='<html>login</html>' ;;
    https://*/api/*) ma=401; than='{"detail":"Not authenticated"}' ;;
    https://*/confirm/*) ma=404 ;;
    *) ma=200 ;;
esac
if [ "$host" != "backend:8000" ]; then
    # nginx CŨ: `$request` + `$http_referer` THÔ.
    printf '172.30.0.6 - - [13/Oct/2026:00:00:00 +0000] "GET %s HTTP/1.1" %s 0 "%s" "%s"\n' \
        "$duong" "$ma" "$ref" "$ua" >> "$QLTS_NGINX_LOG"
fi
[ "$ra_tep" = "/dev/null" ] || printf '%s' "$than"
if [ -n "$w" ]; then printf '%s' "$ma"; fi
exit 0
"""


@_bo_qua_neu_khong_posix
def test_v3_f39_nginx_verify_that_tren_nginx_cu_khong_chan_phuc_hoi(tmp_path: Path) -> None:
    """Chạy `scripts/nginx-verify.sh` THẬT của kho (sau khi ghép V6: có đầu dò
    token) lên nginx CŨ mô phỏng (log thô) ở nhánh lùi IP đổi.

    Phục hồi dịch vụ phải ĐẠT (đo bằng đoạn sh THẬT của deploy.sh); kết quả PII
    chỉ là thông tin. Nếu `nginx-verify.sh` của kho có đầu dò token thì nó PHẢI
    đỏ ở đây (nginx cũ lộ token) — chứng minh sân khấu thật sự mô phỏng F39.
    """
    goc = _dung_san_khau(tmp_path)
    verify = _VERIFY_THAT.read_text(encoding="utf-8")
    (goc / "scripts" / "nginx-verify.sh").write_text(verify, encoding="utf-8", newline="\n")
    curl = goc / "bin" / "curl"
    curl.write_text(_CURL_NGINX_CU, encoding="utf-8", newline="\n")
    curl.chmod(0o755)
    log_nginx = goc / "nginx-access.log"
    log_nginx.write_text("", encoding="utf-8")

    ket, nk = _chay_deploy(
        goc, STUB_CHAY_SH_THAT="1", QLTS_NGINX_LOG=str(log_nginx), STUB_IP_DOI="1", **_LUI, **_NHANH
    )
    ra = _ra(ket)
    # Bất biến F39 kiểm TRƯỚC (đỏ-trước trên e1c6c9fc phải đỏ ĐÚNG ở đây), kèm các dòng của verify để thấy lý do.
    dong_verify = [d for d in ra.splitlines() if "đầu dò token" in d or "nginx-verify" in d or "HỎNG —" in d]
    assert "ĐÃ mở lại container CŨ" in ra, (
        "kiểm PII trên nginx cũ chặn phục hồi:\n" + "\n".join(dong_verify[-12:]) + "\n---\n" + ra[-1500:]
    )
    assert len(_lenh_restart_nginx(nk)) == 1
    assert "[nginx · dịch vụ] SNI=vidu.test → /health 200 · /login 200 · /api/payments/1 401 · chứng thư 200" in ra, ra[-3000:]
    assert "✓ [nginx · dịch vụ] PHỤC HỒI DỊCH VỤ ĐẠT" in ra, ra[-3000:]
    if "đầu dò token" in verify:
        assert "qltsgiap" in log_nginx.read_text(encoding="utf-8"), "sân khấu không mô phỏng log THÔ"
        assert "phép kiểm chức năng rc=0, đầu dò token rc=1" in ra, ra[-3000:]
        assert "nginx-verify.sh KHÔNG ĐẠT (rc=1)" in ra
    else:
        assert "nginx-verify.sh ĐẠT trên nginx cũ" in ra, ra[-3000:]


@_bo_qua_neu_khong_posix
def test_v3_duong_ban_moi_van_bat_buoc_kiem_qua_nginx_apply(tmp_path: Path) -> None:
    """Đường deploy bản MỚI: Step 8b `nginx-apply.sh` (gọi `nginx-verify.sh` trên
    candidate, gồm đầu dò PII sau V6) đỏ ⇒ deploy đỏ. F39 chỉ nới nhánh LÙI."""
    goc = _dung_san_khau(tmp_path)
    (goc / "scripts" / "nginx-apply.sh").write_text(
        '#!/usr/bin/env bash\necho "nginx-apply $*" >> "$QLTS_STUB_LOG"\nexit 1\n',
        encoding="utf-8", newline="\n",
    )
    ket, nk = _chay_deploy(goc, **_NHANH)
    assert ket.returncode != 0 and "không áp được cấu hình nginx" in _ra(ket)
    apply_sh = (_DEPLOY.parent / "nginx-apply.sh").read_text(encoding="utf-8")
    assert 'if ! bash "$SCRIPT_DIR/nginx-verify.sh" "$_CID_CANDIDATE" "$DOMAIN"; then' in apply_sh


# =============================================================================
# VII. Tệp trạng thái (F37) + hướng dẫn ĐO THẬT (F35)
# =============================================================================
_TS_CO_DINH = "20261012_000000"
_SHIM_DATE = """#!/usr/bin/env bash
# Chỉ cố định TIMESTAMP của deploy.sh (để ca kiểm biết trước tên tệp trạng thái);
# mọi định dạng khác đi thẳng tới `date` thật.
if [ "$#" = "1" ] && [ "$1" = "+%Y%m%d_%H%M%S" ]; then
    echo "20261012_000000"
    exit 0
fi
for d in /bin/date /usr/bin/date; do [ -x "$d" ] && exec "$d" "$@"; done
exit 127
"""


def _san_khau_ts(tmp_path: Path, deploy_sh: str | None = None) -> Path:
    goc = _dung_san_khau(tmp_path, deploy_sh=deploy_sh)
    p = goc / "bin" / "date"
    p.write_text(_SHIM_DATE, encoding="utf-8", newline="\n")
    p.chmod(0o755)
    return goc


def _tep_tt_co_dinh(goc: Path) -> Path:
    return goc / "backups" / f"deploy_{_TS_CO_DINH}.trang-thai"


@_bo_qua_neu_khong_posix
def test_v2_huong_dan_khong_suy_tu_revision_va_in_trang_thai_do(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, _ = _chay_deploy(goc, STUB_TIN_HIEU_O_MIGRATE="TERM", **_NHANH)
    ra = _ra(ket)
    assert "Revision = bản CŨ" not in ra, "hướng dẫn còn suy lược đồ từ revision (F35)"
    assert "ĐANG DỪNG — CỐ Ý" not in ra, "hướng dẫn khẳng định trạng thái thay vì ĐO"
    assert "Trạng thái ĐO THẬT" in ra, ra[-2500:]
    for dv in _DV_GHI:
        assert f"'{dv}': container cũ {_cid_gia(dv)}" in ra and "đo: exited|" in ra, ra[-2500:]
    assert "So vân tay lược đồ với bản 4c" in ra
    assert "vân tay lược đồ BÂY GIỜ: KHỚP bản 4c" in ra


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,kich_ban,thong_diep",
    [
        ("DDL ngoài trong cửa sổ dump", {"STUB_VAN_TAY_LECH_SAU_DUMP": "1"}, "+ rel|public.bang_ngoai_ddl|r"),
        ("không đo được vân tay sau dump", {"STUB_VAN_TAY_RC_SAU_DUMP": "2"}, "KHÔNG đo được vân tay"),
    ],
)
def test_v3_mo_lai_truoc_migrate_van_qua_cong_van_tay(
    tmp_path: Path, ten_ca: str, kich_ban: dict, thong_diep: str
) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(goc, **kich_ban, **_LUI, **_NHANH)
    ra = _ra(ket)
    assert ket.returncode != 0
    assert _lenh_mo_app(goc) == [], f"{ten_ca}: mở mã CŨ lên lược đồ CHƯA chứng minh tương thích: {_lenh_mo_app(goc)}"
    assert thong_diep in ra, f"{ten_ca}: thiếu {thong_diep!r}:\n{ra[-2500:]}"
    assert "mo_lai_cu\tKHONG_DAT" in _tep_trang_thai(goc)


@_bo_qua_neu_khong_posix
def test_v2_tep_trang_thai_khong_ghi_duoc_truoc_khi_dung_thi_dung(tmp_path: Path) -> None:
    goc = _san_khau_ts(tmp_path)
    (goc / "backups").mkdir()
    _tep_tt_co_dinh(goc).mkdir()   # cùng tên ⇒ `>>` không ghi được
    ket, nk = _chay_deploy(goc, **_NHANH)
    ra = _ra(ket)
    assert ket.returncode != 0, "tệp trạng thái không ghi được mà deploy thoát 0"
    assert "KHÔNG ghi được" in ra, ra[-1500:]
    assert "docker stop " not in nk, "đã dừng container dù không ghi được tệp trạng thái"
    assert _MOC_PGDUMP not in nk


@_bo_qua_neu_khong_posix
def test_v3_tep_trang_thai_hong_sau_migrate_van_in_huong_dan_khong_phat_lai(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(goc, STUB_ALEMBIC_RC="1", STUB_TT_HONG_O_MIGRATE="1", **_NHANH)
    ra = _ra(ket)
    assert "KHÔNG ghi được" in ra, "lỗi ghi tệp trạng thái bị NUỐT"
    assert "[pha] migrate_do" in ra, f"pha migrate_do không còn trong log deploy:\n{ra[-2500:]}"
    assert "PHỤC HỒI CÓ ĐỐI SOÁT" in ra, "tệp trạng thái hỏng đã bẻ gãy hướng dẫn"
    assert "đã có lần KHÔNG ghi được" in ra
    assert _vi_pham_phat_lai(goc) == [] and _lenh_mo_app(goc, _moc(goc) + 1) == []


# =============================================================================
# VIII. Kiểm ngược — gỡ đúng từng guard trên một BẢN SAO, điều xấu phải xảy ra
# =============================================================================
# --- F28: thêm lại phát lại tự động -----------------------------------------
_NEO_LOI_DO = '        error "Migration failed. KHÔNG phát lại bản sao (F28)'


@_bo_qua_neu_khong_posix
def test_kiem_nguoc_them_lai_phat_lai_khi_rao_dat_thi_phat_lai(tmp_path: Path) -> None:
    """Biến thể TINH VI nhất: phát lại CHỈ khi (d) + PA2 đều đạt — đúng logic
    vòng 1/2. Ca "rào ĐẠT" của F28 phải bắt được nó."""
    dot_bien = _ban_dot_bien(
        _NEO_LOI_DO,
        '        if _dcg_cua_dong "d" && _dcg_phien_la_bang_0 "d" && _dcg_pa2; then\n'
        '            docker compose -f docker-compose.yml --env-file .env.production exec -T postgres psql'
        ' -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-qlts}" "${POSTGRES_DB:-qlts_production}" < "$_BAN_SAO"\n'
        '        fi\n' + _NEO_LOI_DO,
    )
    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    _chay_deploy(goc, STUB_ALEMBIC_RC="1", **_NHANH)
    assert _vi_pham_phat_lai(goc), "thêm lại phát lại mà ca F28 không thấy ⇒ ca F28 không canh gì"


# Vòng 3b — review độc lập: `exec -T postgres sh -c 'psql …' < bản_sao` LỌT phép cũ
# (bám chuỗi `postgres psql` thiếu ` -c `). Mỗi biến thể dưới đây là MỘT cách phát lại
# (một đột biến, cùng cổng "(d) + PA2 đạt" như vòng 1/2), chèn ngay sau dọn one-off ở
# nhánh đỏ; cột cuối là ĐÚNG tập luật bắt được nó — ba biến thể cuối mỗi cái chỉ chạm
# MỘT luật, chứng minh từng luật tự có sức bắt riêng.
_NEO_SAU_DON_ONEOFF = "        _dcg_don_oneoff || true\n"
_CONG_RAO = "        if _dcg_cua_dong d && _dcg_phien_la_bang_0 d && _dcg_pa2; then "
_PSQL_UD = '-U "${POSTGRES_USER:-qlts}" -d "${POSTGRES_DB:-qlts_production}"'


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,dong_chen,luat",
    [
        ("M1 exec sh -c 'psql' < bản sao",
         _CONG_RAO + """$_RA_COMPOSE exec -T postgres sh -c 'psql -X -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$_BAN_SAO" || true; fi\n""",
         {"R1", "R2"}),
        ("M2 exec psql < bản sao",
         _CONG_RAO + f'$_RA_COMPOSE exec -T postgres psql -X -q {_PSQL_UD} < "$_BAN_SAO" || true; fi\n',
         {"R1", "R2"}),
        ("cat bản sao | exec psql",
         _CONG_RAO + f'cat "$_BAN_SAO" | $_RA_COMPOSE exec -T postgres psql -X -q {_PSQL_UD} || true; fi\n',
         {"R1", "R2"}),
        ("docker cp + exec psql -f",
         _CONG_RAO + 'docker cp "$_BAN_SAO" qlts-postgres-1:/tmp/x.sql || true; '
         f'$_RA_COMPOSE exec -T postgres psql -X -q {_PSQL_UD} -f /tmp/x.sql </dev/null || true; fi\n',
         {"R1", "R3"}),
        ("exec sh -c 'psql -f /dev/stdin' < bản sao",
         _CONG_RAO + """$_RA_COMPOSE exec -T postgres sh -c 'psql -f /dev/stdin' < "$_BAN_SAO" || true; fi\n""",
         {"R1", "R2"}),
        ("CHỈ R2: container client psql nối qua mạng, stdin = bản sao",
         _CONG_RAO + f'docker run -i --rm --network qlts_default postgres:16-alpine psql -h postgres {_PSQL_UD} < "$_BAN_SAO" || true; fi\n',
         {"R2"}),
        ("CHỈ R3: psql -c \"$(cat bản sao)\" — đúng dạng phép đo, stdin rỗng",
         _CONG_RAO + f'$_RA_COMPOSE exec -T postgres psql -X -A -t -q -v ON_ERROR_STOP=1 {_PSQL_UD} -c "$(cat "$_BAN_SAO")" </dev/null || true; fi\n',
         {"R3"}),
        ("CHỈ R1: exec psql -f tệp đặt sẵn trong container",
         _CONG_RAO + f'$_RA_COMPOSE exec -T postgres psql -X -q {_PSQL_UD} -f /var/lib/postgresql/data/ban_sao.sql </dev/null || true; fi\n',
         {"R1"}),
        ("CHỈ R3: docker cp bản sao vào initdb của container",
         _CONG_RAO + 'docker cp "$_BAN_SAO" qlts-postgres-1:/docker-entrypoint-initdb.d/zz.sql || true; fi\n',
         {"R3"}),
    ],
)
def test_kiem_nguoc_phat_lai_bien_the(tmp_path: Path, ten_ca: str, dong_chen: str, luat: set) -> None:
    dot_bien = _ban_dot_bien(_NEO_SAU_DON_ONEOFF, _NEO_SAU_DON_ONEOFF + dong_chen)
    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    _chay_deploy(goc, STUB_ALEMBIC_RC="1", **_NHANH)
    vp = _vi_pham_phat_lai(goc)
    assert {v.split()[0] for v in vp} == luat, f"{ten_ca}: luật bắt được {vp}, mong {sorted(luat)}"


# --- §6 "KHÔNG mở ứng dụng": các dạng lệnh mà phép cũ (chuỗi `docker start `,
# `up -d`, Step 8) để LỌT — phép hành vi phải bắt; phép cũ được khẳng định lọt
# để ghi lại VÌ SAO phải đổi.
@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,dong_chen,cu_lot",
    [
        ("docker container start CID cũ", '        docker container start "${_DCG_CID[backend]}" >/dev/null || true\n', True),
        ("compose start service", "        $_RA_COMPOSE start backend >/dev/null || true\n", True),
        ("compose up KHÔNG -d", "        $_RA_COMPOSE up --no-deps backend celery-worker celery-beat >/dev/null || true\n", True),
        ("compose up --detach", "        $_RA_COMPOSE up --detach --no-deps backend >/dev/null || true\n", True),
        ("docker restart CID cũ", '        docker restart "${_DCG_CID[celery-worker]}" >/dev/null || true\n', True),
        # Phép cũ bắt được ca này (có chữ "up -d") — giữ để canh luật "không nêu service = tất cả".
        ("compose up -d không nêu service (= tất cả)", "        $_RA_COMPOSE up -d --wait-timeout 30 >/dev/null || true\n", False),
    ],
)
def test_kiem_nguoc_mo_app_dang_lenh_khac(tmp_path: Path, ten_ca: str, dong_chen: str, cu_lot: bool) -> None:
    dot_bien = _ban_dot_bien(_NEO_SAU_DON_ONEOFF, _NEO_SAU_DON_ONEOFF + dong_chen)
    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    _, nk = _chay_deploy(goc, STUB_ALEMBIC_RC="1", **_NHANH)
    moc = _moc(goc)
    assert _lenh_mo_app(goc, moc + 1), f"{ten_ca}: phép HÀNH VI không thấy lệnh mở app"
    # Phép cũ bám chuỗi (`docker start `, "up -d", mốc Step 8) — ghi lại nó LỌT ở đâu (lý do vòng 3b).
    i_mig = _vt(nk, _MOC_ALEMBIC)
    lot_cu = (_start_cua_deploy(nk) == [] and _MOC_STEP8 not in nk
              and "up -d" not in "\n".join(_dong(nk)[i_mig:]))
    assert lot_cu == cu_lot, f"{ten_ca}: phép cũ lọt={lot_cu}, mong {cu_lot}"


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,pha,kich_ban",
    [
        ("trap mở cả ở dang_migrate", "dang_migrate", {"STUB_TIN_HIEU_O_MIGRATE": "TERM"}),
        ("trap mở cả ở migrate_do", "migrate_do", {"STUB_ALEMBIC_RC": "1"}),
    ],
)
def test_kiem_nguoc_trap_mo_sau_khi_migrate_chay_thi_app_chay_tren_luoc_do_chua_ro(
    tmp_path: Path, ten_ca: str, pha: str, kich_ban: dict
) -> None:
    dot_bien = _ban_dot_bien(
        "        chua_dong|dang_dong|da_dong)\n",
        f"        chua_dong|dang_dong|da_dong|{pha})\n",
    )
    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    _, nk = _chay_deploy(goc, **kich_ban, **_NHANH)
    assert _lenh_mo_app(goc, _moc(goc) + 1), f"{ten_ca}: đột biến không mở app ⇒ ca tương ứng xanh vì lý do khác"


@_bo_qua_neu_khong_posix
def test_kiem_nguoc_d_chi_so_status_thi_doi_soat_mat_bang_chung(tmp_path: Path) -> None:
    dot_bien = _ban_dot_bien(
        '        if [ "$m" != "${_DCG_MOC[$s]}" ]; then\n',
        "        if false; then\n",
    )
    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    ket, _ = _chay_deploy(goc, STUB_ALEMBIC_RC="1", STUB_HOI_SINH="dung_lai", **_NHANH)
    assert "ĐÃ CHẠY LẠI giữa chừng" not in _ra(ket), (
        "bỏ so mốc vòng đời mà bằng chứng vẫn in ⇒ ca đối soát mốc không canh gì")


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
        '        timeout -k 5 "$_DCG_HAN_KHOI_DONG" docker start "${_DCG_CID[$s]}" >/dev/null && kq=0 || kq=$?\n',
        '        $_RA_COMPOSE up -d "$s" >/dev/null && kq=0 || kq=$?\n',
    )
    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    _, nk = _chay_deploy(goc, **_LUI, **_NHANH)
    assert _lenh_dung_moi(goc, _sau_lan_dung_cuoi(goc)), "đột biến không đổi được lệnh mở lại"
    assert _start_cua_deploy(nk) == []


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
    assert _lenh_mo_app(goc) == [], "bỏ trap mà app vẫn được mở lại ⇒ ca trap xanh vì lý do khác"


@_bo_qua_neu_khong_posix
def test_kiem_nguoc_doi_4c_xuong_sau_pg_dump_thi_lo_thu_tu(tmp_path: Path) -> None:
    """Biến thể TINH VI: vẫn dừng, vẫn đo — chỉ sai CHỖ (sau pg_dump)."""
    than = _DEPLOY.read_text(encoding="utf-8")
    dau = than.index('if [ "${IS_CUTOVER}" -eq 1 ]; then\n    cutover "Step 4c:')
    cuoi_neo = '    log "  ✓ cửa ghi ĐÓNG — giữ đóng xuyên suốt dump → migrate → (nếu đỏ) ứng dụng giữ DỪNG"\nfi\n'
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
        # Vòng 7c: lệnh dừng nay có `timeout` bọc ngoài — gỡ CẢ dòng như cũ.
        '        timeout -k 5 "$(( $(_dcg_han_dung "$_S") + _DCG_HAN_LENH ))" docker stop -t "$(_dcg_han_dung "$_S")" "${_DCG_CID[$_S]}" >/dev/null \\\n',
        '        true \\\n',
    )
    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    ket, nk = _chay_deploy(goc, **_NHANH)
    assert ket.returncode != 0
    assert _MOC_PGDUMP not in nk, "không dừng container mà vẫn sao lưu/migrate"
    assert "ĐANG CHẠY" in _ra(ket)


# --- Vân tay / tệp trạng thái ------------------------------------------------
@_bo_qua_neu_khong_posix
def test_v2_kiem_nguoc_bo_so_van_tay_thi_mo_tren_luoc_do_lech(tmp_path: Path) -> None:
    dot_bien = _ban_dot_bien(
        "        if _dcg_so_van_tay; then kq=0; else kq=$?; fi\n",
        "        kq=0\n",
    )
    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    _, nk = _chay_deploy(goc, STUB_VAN_TAY_LECH_SAU_DUMP="1", **_LUI, **_NHANH)
    assert _start_cua_deploy(nk), "bỏ so vân tay mà vẫn không mở ⇒ ca vân tay xanh vì lý do khác"


@_bo_qua_neu_khong_posix
def test_v2_kiem_nguoc_mo_chi_dua_revision_thi_mo_tren_luoc_do_lech(tmp_path: Path) -> None:
    dot_bien = _ban_dot_bien(
        "        if _dcg_so_van_tay; then kq=0; else kq=$?; fi\n",
        '        if [ -n "$(_dcg_psql "SELECT version_num FROM alembic_version")" ]; then kq=0; else kq=4; fi\n',
    )
    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    _, nk = _chay_deploy(goc, STUB_VAN_TAY_LECH_SAU_DUMP="1", **_LUI, **_NHANH)
    assert _start_cua_deploy(nk), "cổng 'revision' vẫn chặn ⇒ đột biến không tái hiện F35"


@_bo_qua_neu_khong_posix
def test_v2_kiem_nguoc_nuot_loi_ghi_tep_trang_thai_thi_deploy_chay_tiep(tmp_path: Path) -> None:
    dot_bien = _ban_dot_bien(
        """    if printf '%s\\n' "$dong" >> "$_DCG_TT" 2>/dev/null; then\n""",
        """    if printf '%s\\n' "$dong" >> "$_DCG_TT" 2>/dev/null || true; then\n""",
    )
    goc = _san_khau_ts(tmp_path, deploy_sh=dot_bien)
    (goc / "backups").mkdir()
    _tep_tt_co_dinh(goc).mkdir()
    _, nk = _chay_deploy(goc, **_NHANH)
    assert _MOC_PGDUMP in nk, "nuốt lỗi ghi mà deploy vẫn dừng ⇒ ca F37 xanh vì lý do khác"


# --- nginx: phục hồi dịch vụ BẮT BUỘC, PII THÔNG TIN (F39) ---------------------
@_bo_qua_neu_khong_posix
def test_kiem_nguoc_bo_khoi_dong_lai_nginx_khi_ip_doi(tmp_path: Path) -> None:
    than = _DEPLOY.read_text(encoding="utf-8")
    # Vòng 6: khối IP + khởi động lại nginx nay kết thúc ngay trước đầu dò dịch vụ.
    dau = than.index("    ip=$(_dcg_doc_ct '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' \"${_DCG_CID[backend]}\") && kq=0 || kq=$?\n")
    cuoi = than.index('    _dcg_do_dich_vu_nginx && kq=0 || kq=$?\n', dau)
    than = than[:dau] + than[cuoi:]
    goc = _dung_san_khau(tmp_path, deploy_sh=than)
    _, nk = _chay_deploy(goc, STUB_IP_DOI="1", **_LUI, **_NHANH)
    assert _start_cua_deploy(nk)
    assert _lenh_restart_nginx(nk) == [], "gỡ khởi động lại nginx mà vẫn restart ⇒ ca IP-đổi xanh vì lý do khác"


@_bo_qua_neu_khong_posix
def test_kiem_nguoc_bo_do_dich_vu_thi_bao_mo_du_502(tmp_path: Path) -> None:
    dot_bien = _ban_dot_bien('    _dcg_do_dich_vu_nginx && kq=0 || kq=$?\n    [ "$kq" -eq 0 ] || return "$kq"\n', "")
    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    ket, _ = _chay_deploy(goc, STUB_MA_HEALTH="502", **_LUI, **_NHANH)
    assert "ĐÃ mở lại container CŨ" in _ra(ket), "bỏ đo dịch vụ mà vẫn không báo mở ⇒ ca 502 xanh vì lý do khác"


@_bo_qua_neu_khong_posix
def test_kiem_nguoc_do_dich_vu_chi_xem_ma_khong_so_than(tmp_path: Path) -> None:
    """Biến thể TINH VI: vẫn đo mã qua SNI, chỉ bỏ so THÂN (200 từ catch-all lọt)."""
    dot_bien = _ban_dot_bien(
        '    if [ -z "$a" ] || [ "$a" = "$rong" ] || [ "$a" != "$b" ]; then\n',
        "    if false; then\n",
    )
    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    ket, _ = _chay_deploy(goc, STUB_THAN_LECH="1", **_LUI, **_NHANH)
    assert "ĐÃ mở lại container CŨ" in _ra(ket), "bỏ so thân mà vẫn chặn ⇒ ca thân lệch xanh vì lý do khác"


@_bo_qua_neu_khong_posix
def test_kiem_nguoc_pii_lai_thanh_cong_chan_thi_phuc_hoi_bao_khong_dat(tmp_path: Path) -> None:
    """Đột biến = hành vi của e1c6c9fc: `nginx-verify.sh` là cổng bắt buộc ở nhánh lùi."""
    dot_bien = _ban_dot_bien(
        "    _dcg_thong_tin_pii_nginx\n",
        '    bash "$SCRIPT_DIR/nginx-verify.sh" "$_DCG_NGINX_CID" "$DOMAIN" || return 1\n',
    )
    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    ket, _ = _chay_deploy(goc, STUB_NGINX_VERIFY_RC="1", **_LUI, **_NHANH)
    assert "ĐÃ mở lại container CŨ" not in _ra(ket), "PII lại thành cổng mà phục hồi vẫn báo đạt ⇒ ca F39 không canh gì"


# --- One-off: CHỈ CID ghi nhận của CHÍNH lượt, CHỈ khi exited -----------------
@_bo_qua_neu_khong_posix
def test_kiem_nguoc_don_theo_nhan_chung_thi_xoa_oneoff_luot_khac(tmp_path: Path) -> None:
    dot_bien = _ban_dot_bien(
        "    _DCG_ONEOFF_XONG=1\n    _dcg_dung_theo_oneoff\n",
        "    _DCG_ONEOFF_XONG=1\n    _dcg_dung_theo_oneoff\n"
        "    for _c in $(docker ps -aq --filter label=com.docker.compose.oneoff=True --filter status=exited); do\n"
        '        docker rm "$_c" >/dev/null || true\n'
        "    done\n",
    )
    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    _, nk = _chay_deploy(goc, STUB_ONEOFF="exited", STUB_TIN_HIEU_O_MIGRATE="TERM", **_NHANH)
    assert f"docker rm {_OO_KHAC}" in _dong(nk), "dọn theo nhãn mà one-off lượt khác còn ⇒ ca 'lượt khác' không canh gì"


@_bo_qua_neu_khong_posix
def test_kiem_nguoc_bo_dieu_kien_exited_thi_xoa_oneoff_dang_chay(tmp_path: Path) -> None:
    dot_bien = _ban_dot_bien(
        '        "/$_DCG_ONEOFF_TEN|True|backend|exited")\n',
        '        "/$_DCG_ONEOFF_TEN|True|backend|"*)\n',
    )
    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    _, nk = _chay_deploy(goc, STUB_ONEOFF="dead", STUB_TIN_HIEU_O_MIGRATE="TERM", **_NHANH)
    assert f"docker rm {_OO}" in _dong(nk), "bỏ điều kiện exited mà one-off 'dead' còn ⇒ ca 'chỉ khi exited' không canh gì"


@_bo_qua_neu_khong_posix
def test_kiem_nguoc_bo_so_ten_thi_xoa_container_khong_phai_cua_luot(tmp_path: Path) -> None:
    dot_bien = _ban_dot_bien(
        '        "/$_DCG_ONEOFF_TEN|True|backend|exited")\n',
        '        *"|True|backend|exited")\n',
    )
    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    _, nk = _chay_deploy(
        goc, STUB_ONEOFF="exited", STUB_ONEOFF_TEN_KHAC="1", STUB_TIN_HIEU_O_MIGRATE="TERM", **_NHANH
    )
    assert f"docker rm {_OO}" in _dong(nk), "bỏ so tên mà vẫn không dọn ⇒ ca 'tên khác' không canh gì"


@_bo_qua_neu_khong_posix
def test_kiem_nguoc_khong_ghi_nhan_cid_thi_khong_don_duoc(tmp_path: Path) -> None:
    dot_bien = _ban_dot_bien(
        "    _dcg_theo_oneoff </dev/null >/dev/null 2>&1 &\n",
        "    true &\n",
    )
    goc = _dung_san_khau(tmp_path, deploy_sh=dot_bien)
    _, nk = _chay_deploy(goc, STUB_ONEOFF="exited", STUB_TIN_HIEU_O_MIGRATE="TERM", **_NHANH)
    assert f"docker rm {_OO}" not in _dong(nk), "không ghi nhận CID mà vẫn dọn ⇒ dọn không theo CID ghi nhận"


# =============================================================================
# IX. Vòng 4 (F40) — ĐI TIẾP sau migration đỏ; trap CHỜ one-off có hạn
# =============================================================================
# Hai lượt trên CÙNG một sân khấu: lượt 1 migration đỏ (ba service nằm dừng), lượt 2
# đi tiếp bằng `QLTS_DI_TIEP_SAU_MIGRATE_DO=1 QLTS_DI_TIEP_TU=<tệp trạng thái lượt 1>`.
# Mô hình container của stub suy từ nhật ký lệnh ⇒ lượt 2 giữ nhật ký (`_giu_nhat_ky`).
_TS_DO = "20261013_010000"
_TS_TIEP = "20261013_020000"
_SHIM_DATE_BIEN = """#!/usr/bin/env bash
# TIMESTAMP của deploy.sh (và tên thư mục tài sản rollback) lấy từ QLTS_TEST_TS khi
# có: hai lượt trong cùng một giây không được đè tệp trạng thái của nhau.
if [ -n "${QLTS_TEST_TS:-}" ]; then
    if [ "$#" = "1" ] && [ "$1" = "+%Y%m%d_%H%M%S" ]; then echo "$QLTS_TEST_TS"; exit 0; fi
    if [ "$#" = "2" ] && [ "$1" = "-u" ] && [ "$2" = "+%Y%m%dT%H%M%SZ" ]; then echo "${QLTS_TEST_TS/_/T}Z"; exit 0; fi
fi
for d in /bin/date /usr/bin/date; do [ -x "$d" ] && exec "$d" "$@"; done
exit 127
"""
_NGUON_DO = f"backups/deploy_{_TS_DO}.trang-thai"


def _san_khau_hai_luot(tmp_path: Path, deploy_sh: str | None = None, env_them: str = "") -> Path:
    goc = _dung_san_khau(tmp_path, deploy_sh=deploy_sh, env_them=env_them)
    p = goc / "bin" / "date"
    p.write_text(_SHIM_DATE_BIEN, encoding="utf-8", newline="\n")
    p.chmod(0o755)
    return goc


def _luot_do(goc: Path, **kich_ban: str):
    ket, _ = _chay_deploy(goc, STUB_ALEMBIC_RC="1", QLTS_TEST_TS=_TS_DO, **{**_NHANH, **kich_ban})
    assert ket.returncode != 0, "lượt 1 phải đỏ (migration đỏ)"
    return ket


def _luot_tiep(goc: Path, **kich_ban):
    """Lượt 2. Giá trị None trong kich_ban = GỠ biến đó. Trả (ket, chỉ số lời gọi đầu tiên của lượt 2)."""
    n0 = len(_cac_loi_goi(goc)) if (goc / "lenh.log.goi").exists() else 0
    env = {**_NHANH, "QLTS_TEST_TS": _TS_TIEP, "QLTS_DI_TIEP_SAU_MIGRATE_DO": "1", "QLTS_DI_TIEP_TU": _NGUON_DO}
    env.update(kich_ban)
    env = {k: v for k, v in env.items() if v is not None}
    ket, _ = _chay_deploy(goc, _giu_nhat_ky=True, **env)
    return ket, n0


def _lenh_ghi(goc: Path, tu: int) -> list[str]:
    """Lời gọi docker KHÔNG chỉ-đọc kể từ ``tu`` (mọi thứ ngoài ps/inspect/logs/config)."""
    ra = []
    for g in _cac_loi_goi(goc)[tu:]:
        ho, lenh, con = _tach_lenh(g["args"])
        if ho == "compose" and lenh in ("ps", "config"):
            continue
        if ho == "docker" and (lenh in ("inspect", "ps", "logs") or (lenh == "image" and con[:1] == ["inspect"])):
            continue
        ra.append(" ".join(g["args"])[:120])
    return ra


def _tt(goc: Path, ts: str) -> Path:
    return goc / "backups" / f"deploy_{ts}.trang-thai"


def _pha_cua(tep: Path) -> list[str]:
    return [d.split("\t")[2] for d in tep.read_text(encoding="utf-8").splitlines() if d.split("\t")[1:2] == ["pha"]]


@_bo_qua_neu_khong_posix
def test_v4_trap_in_dung_lenh_di_tiep_va_lenh_ay_dua_he_thong_len(tmp_path: Path) -> None:
    import re

    goc = _san_khau_hai_luot(tmp_path)
    ra1 = _ra(_luot_do(goc))
    m = re.search(r"QLTS_DI_TIEP_SAU_MIGRATE_DO=1 QLTS_DI_TIEP_TU=(\S+) bash scripts/deploy\.sh", ra1)
    assert m, f"trap không in lệnh đi tiếp:\n{ra1[-2500:]}"
    assert m.group(1) == str(_tt(goc, _TS_DO)), f"lệnh in sai tệp trạng thái: {m.group(1)}"
    # Chạy ĐÚNG đường dẫn trap in ra.
    ket, n0 = _luot_tiep(goc, QLTS_DI_TIEP_TU=m.group(1))
    ra = _ra(ket)
    assert ket.returncode == 0, ra[-3000:]
    assert _pha_cua(_tt(goc, _TS_TIEP)) == ["chua_dong", "da_dong", "dang_migrate", "da_migrate", "buoc8", "xong"]
    tt2 = _tt(goc, _TS_TIEP).read_text(encoding="utf-8")
    assert f"di_tiep_tu\t{m.group(1)}" in tt2
    goi = _cac_loi_goi(goc)[n0:]
    assert not any(g["args"][:1] == ["stop"] for g in goi), "đi tiếp mà vẫn `docker stop` — ba service đã dừng từ lượt đỏ"
    assert _lenh_mo_lai_cu(goc, n0) == [], f"đi tiếp mà bật mã CŨ: {_lenh_mo_lai_cu(goc, n0)}"
    assert any("up -d backend celery-worker celery-beat" in " ".join(g["args"]) for g in goi), "không dựng mã MỚI"
    assert _vi_pham_phat_lai(goc, n0) == []
    assert "✓ [đi tiếp] hậu kiểm dịch vụ qua SNI thật ĐẠT" in ra
    # Tài sản rollback của lượt 2 ghim ảnh cũ từ ĐÚNG ba CID exited đã ghi nhận.
    bk = list((goc / "ops").glob("*20261013T020000Z/rollback_manifest_*.txt"))
    assert len(bk) == 1, bk
    dong = {d.split("\t")[0]: d.split("\t") for d in bk[0].read_text(encoding="utf-8").splitlines() if not d.startswith("#")}
    for dv, k in (("backend", "b"), ("celery-worker", "c"), ("celery-beat", "d")):
        assert dong[dv][1] == _cid_gia(dv) and dong[dv][2] == "sha256:" + k * 64, dong[dv]
    assert "# deployed-sha\t" + "1" * 40 in (goc / "ops" / "last-deploy.marker").read_text(encoding="utf-8")


# --- Từ chối khi trạng thái thật KHÔNG khớp — mỗi ca vi phạm ĐÚNG MỘT bất biến ---
def _bat_roi_tat_tu_ngoai(goc: Path) -> None:
    with (goc / "lenh.log").open("a", encoding="utf-8") as f:
        f.write(f"docker start {_cid_gia('celery-beat')} # tac-nhan-ngoai\n")
        f.write(f"docker stop {_cid_gia('celery-beat')} # tac-nhan-ngoai\n")


def _them_pha_buoc8(goc: Path) -> None:
    with _tt(goc, _TS_DO).open("a", encoding="utf-8") as f:
        f.write("2026-10-13T01:30:00Z\tpha\tbuoc8\n")


# Vòng 4b (X4): symlink NẰM TRONG backups/, đúng khuôn tên, trỏ tới tệp trạng thái
# HỢP LỆ của lượt đỏ — biến thể tinh vi nhất: chỉ "là symlink" sai, mọi thứ khác đúng.
_TS_SYMLINK = "20261013_015959"


def _tao_symlink_tt(goc: Path) -> None:
    lk = _tt(goc, _TS_SYMLINK)
    lk.symlink_to(_tt(goc, _TS_DO).name)
    assert lk.is_symlink() and lk.resolve() == _tt(goc, _TS_DO).resolve()


_TU_CHOI = [
    # Một container KHÁC của service đang chạy (vd ai đó `up -d`); CID cũ vẫn exited đúng mốc.
    ("service có container khác ĐANG CHẠY", None, {}, {"STUB_PS_Q_KHAC": "backend"}, "có container ĐANG CHẠY"),
    ("bật rồi tắt — vẫn exited nhưng mốc vòng đời đổi", _bat_roi_tat_tu_ngoai, {}, {}, "ĐÃ CHẠY LẠI từ lúc đóng"),
    ("CID ghi nhận không còn", None, {}, {"STUB_CID_MAT": "celery-worker"}, "KHÔNG còn"),
    ("one-off của lượt đỏ còn chạy", None, {"STUB_ONEOFF": "running"}, {"STUB_ONEOFF": "running"},
     "one-off alembic của lượt đỏ"),
    ("one-off khác của backend còn chạy (theo nhãn project)", None, {}, {"STUB_ONEOFF_NHAN_CHAY": "1"},
     "còn one-off của service backend ĐANG CHẠY"),
    ("pha cuối không phải dừng-sau-migration", _them_pha_buoc8, {}, {}, "KHÔNG phải pha dừng-có-chủ-ý"),
    ("nginx khác CID ghi nhận", None, {}, {"STUB_NGINX_CID_KHAC": "1"}, "KHÁC CID ghi nhận"),
    ("tệp trạng thái là symlink (trong backups/, trỏ tới tệp hợp lệ)", _tao_symlink_tt, {},
     {"QLTS_DI_TIEP_TU": f"backups/deploy_{_TS_SYMLINK}.trang-thai"}, "không có tệp trạng thái thường"),
    # Vòng 5 (F43): đọc lỗi KHÔNG phải "one-off đã hết" — one-off ghi nhận của lượt đỏ
    # đã exited (đã dọn) nhưng lần này daemon trả lỗi khi hỏi nó.
    ("đọc lỗi one-off ghi nhận của lượt đỏ", None, {"STUB_ONEOFF": "exited"},
     {"STUB_ONEOFF": "exited", "STUB_ONEOFF_DOC": "loi"}, "KHÔNG ĐỌC ĐƯỢC trạng thái one-off alembic của lượt đỏ"),
    # Lưới đỡ theo nhãn project: phép quét đọc lỗi ⇒ fail-closed.
    ("quét one-off theo nhãn đọc lỗi", None, {}, {"STUB_PS_NHAN_LOI": "1"}, "không liệt kê được one-off đang chạy"),
]


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize("ten_ca,chen_giua,kb_do,kb_tiep,thong_diep", _TU_CHOI)
def test_v4_di_tiep_tu_choi_khi_trang_thai_that_khong_khop(
    tmp_path: Path, ten_ca, chen_giua, kb_do: dict, kb_tiep: dict, thong_diep: str
) -> None:
    goc = _san_khau_hai_luot(tmp_path)
    _luot_do(goc, **kb_do)
    if chen_giua:
        chen_giua(goc)
    ket, n0 = _luot_tiep(goc, **kb_tiep)
    ra = _ra(ket)
    # HÀNH VI trước, chữ sau: đột biến gỡ guard phải đỏ vì "đã đụng hệ thống".
    assert _lenh_ghi(goc, n0) == [], f"{ten_ca}: từ chối nhưng ĐÃ đụng vào hệ thống: {_lenh_ghi(goc, n0)}"
    assert not _tt(goc, _TS_TIEP).exists(), f"{ten_ca}: đã sang Step 4c"
    assert ket.returncode != 0, f"{ten_ca}: đi tiếp mà KHÔNG từ chối"
    assert thong_diep in ra, f"{ten_ca}: thiếu {thong_diep!r}:\n{ra[-2000:]}"


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,kich_ban,env_them,thong_diep",
    [
        ("chỉ có QLTS_DI_TIEP_TU", {"QLTS_DI_TIEP_SAU_MIGRATE_DO": None}, "", "ý định mâu thuẫn"),
        ("cờ =1 mà thiếu QLTS_DI_TIEP_TU", {"QLTS_DI_TIEP_TU": None}, "", "THIẾU QLTS_DI_TIEP_TU"),
        ("cờ giá trị lạ", {"QLTS_DI_TIEP_SAU_MIGRATE_DO": "yes"}, "", "chỉ nhận '0' hoặc '1'"),
        ("tệp trạng thái ngoài backups/", {"QLTS_DI_TIEP_TU": f"/tmp/deploy_{_TS_DO}.trang-thai"}, "",
         "phải nằm trong"),
        ("cờ nằm trong .env.production", {"QLTS_DI_TIEP_SAU_MIGRATE_DO": None, "QLTS_DI_TIEP_TU": None},
         "QLTS_DI_TIEP_SAU_MIGRATE_DO=1\n", "[đi tiếp] QLTS_DI_TIEP_SAU_MIGRATE_DO / QLTS_DI_TIEP_TU nằm trong .env.production"),
    ],
)
def test_v4_co_di_tiep_sai_cach_thi_tu_choi(
    tmp_path: Path, ten_ca: str, kich_ban: dict, env_them: str, thong_diep: str
) -> None:
    goc = _san_khau_hai_luot(tmp_path, env_them=env_them)
    _luot_do(goc) if not env_them else None
    ket, n0 = _luot_tiep(goc, **kich_ban)
    ra = _ra(ket)
    assert ket.returncode != 0, f"{ten_ca}: không từ chối"
    assert thong_diep in ra, f"{ten_ca}: thiếu {thong_diep!r}:\n{ra[-1500:]}"
    assert _lenh_ghi(goc, n0) == [], f"{ten_ca}: đã đụng vào hệ thống: {_lenh_ghi(goc, n0)}"


@_bo_qua_neu_khong_posix
def test_v4_di_tiep_do_truoc_migrate_thi_khong_mo_ma_cu_va_in_lenh_voi_tep_goc(tmp_path: Path) -> None:
    goc = _san_khau_hai_luot(tmp_path)
    _luot_do(goc)
    ket, n0 = _luot_tiep(goc, STUB_PGDUMP_RC="1")
    ra = _ra(ket)
    assert ket.returncode != 0
    assert "ĐI TIẾP dừng TRƯỚC migration" in ra, ra[-2500:]
    assert _lenh_mo_lai_cu(goc, n0) == [], f"đi tiếp đỏ trước migrate mà BẬT mã cũ: {_lenh_mo_lai_cu(goc, n0)}"
    assert f"QLTS_DI_TIEP_TU={_tt(goc, _TS_DO)} bash scripts/deploy.sh" in ra, "không in lệnh đi tiếp với tệp GỐC"


# --- Vòng 4b: hai guard SAU Step 3a (kiểm độc lập của coordinator: X6, X7 sống) ---
def _co_pg_dump(goc: Path, tu: int) -> bool:
    return any(_MOC_PGDUMP in " ".join(g["args"]) for g in _cac_loi_goi(goc)[tu:])


def _ca_x6(goc: Path):
    """Lượt đỏ, rồi lượt đi tiếp mà tác nhân ngoài bật-rồi-tắt celery-beat lúc build."""
    _luot_do(goc)
    return _luot_tiep(goc, STUB_BAT_TAT_O_BUILD="celery-beat")


def _ca_x7(goc: Path):
    """Lượt đỏ, rồi lượt đi tiếp mà đầu dò dịch vụ qua SNI thấy /health 502 sau Step 8b."""
    _luot_do(goc)
    marker = (goc / "ops" / "last-deploy.marker").read_bytes()
    ket, n0 = _luot_tiep(goc, STUB_MA_HEALTH="502")
    return ket, n0, marker


@_bo_qua_neu_khong_posix
def test_v4_di_tiep_container_chay_lai_giua_3a_va_4c_thi_dung_truoc_pg_dump(tmp_path: Path) -> None:
    # Bất biến DUY NHẤT bị vi phạm: mốc vòng đời của container ghi nhận đổi SAU khi
    # Step 3a đã đo khớp (vẫn `exited`, không container nào khác chạy).
    goc = _san_khau_hai_luot(tmp_path)
    ket, n0 = _ca_x6(goc)
    ra = _ra(ket)
    assert "✓ [đi tiếp] trạng thái khớp lượt đỏ" in ra, "tiền đề: Step 3a phải ĐẠT (bật-tắt xảy ra SAU 3a)"
    assert _MOC_MOC_NGOAI in (goc / "lenh.log").read_text(encoding="utf-8"), "tiền đề: tác nhân ngoài chưa chạy"
    assert not _co_pg_dump(goc, n0), "container chạy lại giữa 3a và 4c mà VẪN pg_dump"
    assert _lenh_mo_lai_cu(goc, n0) == [], f"trap BẬT mã cũ: {_lenh_mo_lai_cu(goc, n0)}"
    assert _lenh_dung_moi(goc, n0) == [], f"vẫn dựng mã mới: {_lenh_dung_moi(goc, n0)}"
    assert ket.returncode != 0
    assert "'celery-beat' ĐÃ CHẠY LẠI sau Step 3a" in ra, ra[-2500:]
    assert "ĐI TIẾP dừng TRƯỚC migration" in ra, ra[-2500:]


@_bo_qua_neu_khong_posix
def test_v4_di_tiep_hau_kiem_sni_khong_dat_thi_do_khong_ghi_marker(tmp_path: Path) -> None:
    # Bất biến DUY NHẤT bị vi phạm: đầu dò dịch vụ qua SNI sau Step 8b không đạt.
    goc = _san_khau_hai_luot(tmp_path)
    ket, n0, marker_truoc = _ca_x7(goc)
    ra = _ra(ket)
    assert any(_MOC_STEP8 in " ".join(g["args"]) for g in _cac_loi_goi(goc)[n0:]), "tiền đề: phải tới Step 8"
    assert "[nginx · dịch vụ] KHÔNG ĐẠT" in ra, "tiền đề: đầu dò phải thấy KHÔNG ĐẠT"
    assert (goc / "ops" / "last-deploy.marker").read_bytes() == marker_truoc, "hậu kiểm SNI KHÔNG ĐẠT mà vẫn ghi marker Step 8c"
    assert ket.returncode != 0, "hậu kiểm SNI KHÔNG ĐẠT mà deploy thoát 0"
    assert "Deployment completed successfully" not in ra
    assert "✓ [đi tiếp] hậu kiểm dịch vụ qua SNI thật ĐẠT" not in ra


# --- Kiểm ngược: gỡ từng guard của đường đi tiếp (biến thể tinh vi nhất) ---------
@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,cu,moi,chen_giua,kb_do,kb_tiep",
    [
        ("bỏ phép 'không container đang chạy'",
         """        [ -z "${_DS//[[:space:]]/}" ] || error "[đi tiếp] '$_S' có container ĐANG CHẠY""",
         """        true || error "[đi tiếp] '$_S' có container ĐANG CHẠY""",
         None, {}, {"STUB_PS_Q_KHAC": "backend"}),
        ("bỏ so mốc vòng đời (chỉ còn xem exited)",
         """        [ "$_M" = "${_DT_MOC[$_S]}" ] || error "[đi tiếp] container ghi nhận của '$_S' ĐÃ CHẠY LẠI từ lúc đóng""",
         """        true || error "[đi tiếp] container ghi nhận của '$_S' ĐÃ CHẠY LẠI từ lúc đóng""",
         _bat_roi_tat_tu_ngoai, {}, {}),
        ("giả số đo khi CID mất",
         """            || error "[đi tiếp] CID ghi nhận của '$_S' ($_CID) KHÔNG còn""",
         """            || _M="${_DT_MOC[$_S]}" || error "[đi tiếp] CID ghi nhận của '$_S' ($_CID) KHÔNG còn""",
         None, {}, {"STUB_CID_MAT": "celery-worker"}),
        ("bỏ phép one-off ghi nhận còn chạy",
         """*) error "[đi tiếp] one-off alembic của lượt đỏ ($_DT_OO) đang '$_M'""",
         """*) : "[đi tiếp] one-off alembic của lượt đỏ ($_DT_OO) đang '$_M'""",
         None, {"STUB_ONEOFF": "running"}, {"STUB_ONEOFF": "running"}),
        ("bỏ quét one-off theo nhãn project",
         """    [ -z "${_DS//[[:space:]]/}" ] || error "[đi tiếp] còn one-off""",
         """    true || error "[đi tiếp] còn one-off""",
         None, {}, {"STUB_ONEOFF_NHAN_CHAY": "1"}),
        ("nhận thêm pha buoc8",
         "        dang_migrate|migrate_do|da_migrate) : ;;\n",
         "        dang_migrate|migrate_do|da_migrate|buoc8) : ;;\n",
         _them_pha_buoc8, {}, {}),
        ("bỏ so CID nginx",
         """    [ "${_DS//[[:space:]]/}" = "$_DT_NGINX" ] || error""",
         """    true || error""",
         None, {}, {"STUB_NGINX_CID_KHAC": "1"}),
        ("bỏ cấm symlink tệp trạng thái",
         """    [ ! -L "$_DT_TT_CU" ] && [ -f "$_DT_TT_CU" ] || error""",
         """    [ -f "$_DT_TT_CU" ] || error""",
         _tao_symlink_tt, {}, {"QLTS_DI_TIEP_TU": f"backups/deploy_{_TS_SYMLINK}.trang-thai"}),
        ("đọc lỗi one-off lượt đỏ coi như đã hết (F43)",
         """            *) error "[đi tiếp] KHÔNG ĐỌC ĐƯỢC trạng thái one-off alembic của lượt đỏ""",
         """            *) : "[đi tiếp] KHÔNG ĐỌC ĐƯỢC trạng thái one-off alembic của lượt đỏ""",
         None, {"STUB_ONEOFF": "exited"}, {"STUB_ONEOFF": "exited", "STUB_ONEOFF_DOC": "loi"}),
        ("quét nhãn đọc lỗi mà bỏ qua (F43)",
         """        || error "[đi tiếp] không liệt kê được one-off đang chạy""",
         """        || true "[đi tiếp] không liệt kê được one-off đang chạy""",
         None, {}, {"STUB_PS_NHAN_LOI": "1"}),
    ],
)
def test_kiem_nguoc_v4_go_tung_guard_di_tiep_thi_dung_vao_he_thong(
    tmp_path: Path, ten_ca: str, cu: str, moi: str, chen_giua, kb_do: dict, kb_tiep: dict
) -> None:
    goc = _san_khau_hai_luot(tmp_path, deploy_sh=_ban_dot_bien(cu, moi))
    _luot_do(goc, **kb_do)
    if chen_giua:
        chen_giua(goc)
    _, n0 = _luot_tiep(goc, **kb_tiep)
    assert _lenh_ghi(goc, n0), f"{ten_ca}: gỡ guard mà lượt đi tiếp vẫn không đụng gì ⇒ ca tương ứng xanh vì lý do khác"


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,cu,moi",
    [
        ("4c không so lại mốc (X6)",
         """        [ "${_DCG_MOC[$_S]}" = "${_DT_MOC[$_S]}" ] || error "[đi tiếp] '$_S' ĐÃ CHẠY LẠI sau Step 3a""",
         """        true || error "[đi tiếp] '$_S' ĐÃ CHẠY LẠI sau Step 3a"""),
        ("hậu kiểm SNI chỉ cảnh báo (X7)",
         """    _dcg_do_dich_vu_nginx || error "[đi tiếp] hậu kiểm dịch vụ qua SNI thật KHÔNG ĐẠT""",
         """    _dcg_do_dich_vu_nginx || warn "[đi tiếp] hậu kiểm dịch vụ qua SNI thật KHÔNG ĐẠT"""),
    ],
)
def test_kiem_nguoc_v4b_go_guard_sau_3a_thi_lo_mo_lai(tmp_path: Path, ten_ca: str, cu: str, moi: str) -> None:
    goc = _san_khau_hai_luot(tmp_path, deploy_sh=_ban_dot_bien(cu, moi))
    if "X6" in ten_ca:
        _, n0 = _ca_x6(goc)
        assert _co_pg_dump(goc, n0), f"{ten_ca}: gỡ guard mà vẫn không pg_dump ⇒ ca X6 xanh vì lý do khác"
    else:
        ket, _, marker_truoc = _ca_x7(goc)
        assert (goc / "ops" / "last-deploy.marker").read_bytes() != marker_truoc and ket.returncode == 0, (
            f"{ten_ca}: gỡ guard mà vẫn không ghi marker/thoát 0 ⇒ ca X7 xanh vì lý do khác"
        )


@_bo_qua_neu_khong_posix
def test_kiem_nguoc_v4_bo_cam_env_file_thi_co_trong_tep_bi_bo_qua_am_tham(tmp_path: Path) -> None:
    than = _DEPLOY.read_text(encoding="utf-8")
    dau = than.index('if [ "${QLTS_DI_TIEP_SAU_MIGRATE_DO+co}" = "co" ] || [ "${QLTS_DI_TIEP_TU+co}" = "co" ]; then\n')
    cuoi = than.index("fi\n", dau) + len("fi\n")
    goc = _san_khau_hai_luot(tmp_path, deploy_sh=than[:dau] + than[cuoi:], env_them="QLTS_DI_TIEP_SAU_MIGRATE_DO=1\n")
    ket, _ = _luot_tiep(goc, QLTS_DI_TIEP_SAU_MIGRATE_DO=None, QLTS_DI_TIEP_TU=None)
    assert "nằm trong .env.production" not in _ra(ket)
    assert ket.returncode == 0, "gỡ cấm mà deploy vẫn đỏ ⇒ ca .env.production xanh vì lý do khác"


@_bo_qua_neu_khong_posix
def test_kiem_nguoc_v4_trap_mo_ma_cu_o_duong_di_tiep(tmp_path: Path) -> None:
    dot_bien = _ban_dot_bien('            if [ "$_DCG_DI_TIEP" = "1" ]; then\n', "            if false; then\n")
    goc = _san_khau_hai_luot(tmp_path, deploy_sh=dot_bien)
    _luot_do(goc)
    _, n0 = _luot_tiep(goc, STUB_PGDUMP_RC="1")
    assert _lenh_mo_lai_cu(goc, n0), "gỡ nhánh đi tiếp của trap mà vẫn không mở mã cũ ⇒ ca trap đi tiếp xanh vì lý do khác"


# --- Trap CHỜ one-off của lượt (owner chốt): hữu hạn, không dọn cưỡng bức ---------
# Dòng ĐẦU khối hướng dẫn (không phải dòng cảnh báo của bước dọn): đánh dấu mọi số
# đo in sau là ảnh chụp giữa chừng.
_DAU_CHUA_CUOI = "số đo dưới là LÚC IN, KHÔNG phải trạng thái cuối"
@_bo_qua_neu_khong_posix
def test_v4_trap_cho_oneoff_het_han_thi_bao_con_chay_khong_don(tmp_path: Path) -> None:
    import time

    goc = _dung_san_khau(tmp_path)
    t = time.monotonic()
    ket, nk = _chay_deploy(goc, STUB_ONEOFF="running", STUB_TIN_HIEU_O_MIGRATE="TERM",
                           **{**_NHANH, "QLTS_HAN_CHO_ONEOFF": "2"})
    ra = _ra(ket)
    assert time.monotonic() - t >= 2, "trap không CHỜ one-off"
    assert "VẪN 'running' sau 2s chờ — CÒN CHẠY / CHƯA XÁC ĐỊNH" in ra, ra[-2500:]
    assert _DAU_CHUA_CUOI in ra, "hướng dẫn in số đo mà không nói đó KHÔNG phải trạng thái cuối"
    assert not any(d.startswith("docker rm") for d in _dong(nk)), "hết hạn mà dọn cưỡng bức"
    assert f"oneoff\t{_OO} con_chay_sau_2s" in _tep_trang_thai(goc)


@_bo_qua_neu_khong_posix
def test_v4_trap_cho_oneoff_ket_thuc_trong_han_thi_don_dung_cid(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(goc, STUB_ONEOFF="chay_roi_xong", STUB_ONEOFF_SO_LAN_CHAY="3",
                           STUB_TIN_HIEU_O_MIGRATE="TERM", **{**_NHANH, "QLTS_HAN_CHO_ONEOFF": "20"})
    ra = _ra(ket)
    assert "CHỜ tối đa 20s" in ra, ra[-2500:]
    assert f"docker rm {_OO}" in _dong(nk), "one-off đã kết thúc trong hạn mà không dọn"
    assert _DAU_CHUA_CUOI not in ra


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,cu,moi,kich_ban,ky_vong",
    [
        ("bỏ vòng chờ",
         """    while :; do\n        tt=$(_dcg_doc_ct '{{.State.Status}}' "$cid") && kq=0 || kq=$?\n""",
         """    while false; do\n        tt=$(_dcg_doc_ct '{{.State.Status}}' "$cid") && kq=0 || kq=$?\n""",
         {"STUB_ONEOFF": "chay_roi_xong", "STUB_ONEOFF_SO_LAN_CHAY": "3", "QLTS_HAN_CHO_ONEOFF": "20"},
         "khong_don"),
        ("hết hạn thì dọn cưỡng bức",
         """            _dcg_ghi "oneoff" "$cid con_chay_sau_${_DCG_HAN_ONEOFF}s" || true\n""",
         """            _dcg_ghi "oneoff" "$cid con_chay_sau_${_DCG_HAN_ONEOFF}s" || true; docker rm -f "$cid" >/dev/null\n""",
         {"STUB_ONEOFF": "running", "QLTS_HAN_CHO_ONEOFF": "1"},
         "don_cuong_buc"),
        # Vòng 5: HAI lớp cùng che — vòng chờ hết hạn đặt cờ, VÀ hướng dẫn tự đo lại
        # one-off lúc in (thấy 'running' thì đặt cờ). Gỡ một lớp vẫn xanh (§3) ⇒ gỡ CẢ HAI.
        ("không đánh dấu 'chưa phải trạng thái cuối'",
         ["            _DCG_ONEOFF_CON_CHAY=1\n",
          """|| _dcg_oneoff_chua_xd "đang '$m' lúc in hướng dẫn\""""],
         ["",
          """|| : "đang '$m' lúc in hướng dẫn\""""],
         {"STUB_ONEOFF": "running", "QLTS_HAN_CHO_ONEOFF": "1"},
         "khong_canh_bao"),
    ],
)
def test_kiem_nguoc_v4_trap_cho_oneoff(tmp_path: Path, ten_ca: str, cu, moi, kich_ban: dict, ky_vong: str) -> None:
    than = None
    for a, b in zip(*((cu, moi) if isinstance(cu, list) else ([cu], [moi]))):
        than = _ban_dot_bien(a, b, than)
    goc = _dung_san_khau(tmp_path, deploy_sh=than)
    ket, nk = _chay_deploy(goc, STUB_TIN_HIEU_O_MIGRATE="TERM", **{**_NHANH, **kich_ban})
    ra = _ra(ket)
    if ky_vong == "khong_don":
        assert f"docker rm {_OO}" not in _dong(nk), f"{ten_ca}: vẫn dọn ⇒ ca 'chờ rồi dọn' không canh vòng chờ"
    elif ky_vong == "don_cuong_buc":
        assert any(d.startswith(f"docker rm -f {_OO}") for d in _dong(nk)), f"{ten_ca}: đột biến không dọn"
    else:
        assert _DAU_CHUA_CUOI not in ra, f"{ten_ca}: vẫn cảnh báo ⇒ ca cảnh báo không canh cờ"


# =============================================================================
# X. Vòng 5 (F43) — lỗi đọc Docker KHÔNG phải "container đã biến mất"
# =============================================================================
# Trap / hướng dẫn chỉ được nói "không còn" khi phép liệt kê theo id CHẠY ĐƯỢC và
# RỖNG. Không đọc được (lỗi, treo), hoặc chưa ghi được CID khi migration có thể đã
# chạy mà tra theo tên cũng không đọc được ⇒ CHƯA XÁC ĐỊNH: bật cờ, ghi tệp trạng
# thái, không dọn, hướng dẫn không gọi số đo là trạng thái cuối.
def _cid_ghi_nhan(goc: Path) -> str:
    tep = list((goc / "backups").glob("deploy_*.oneoff-cid"))
    return tep[0].read_text(encoding="utf-8").strip() if tep else ""


def _noi_khong_con(ra: str) -> list[str]:
    """Dòng one-off nói 'không còn' (đã dọn / đo: không còn)."""
    return [d for d in ra.splitlines() if "one-off" in d and "không còn" in d and "KHÔNG còn migration" not in d]


_V5_HAN = {**_NHANH, "QLTS_HAN_CHO_ONEOFF": "2", "QLTS_HAN_LENH_DOCKER": "1"}


def _ca_a(goc: Path):
    """(a) one-off còn chạy; CID đã ghi; daemon đọc LỖI từ lúc lệnh migration trả về."""
    return _chay_deploy(goc, STUB_ONEOFF="running", STUB_ONEOFF_DOC="loi_sau_migrate",
                        STUB_TIN_HIEU_O_MIGRATE="TERM", **_V5_HAN)


def _ca_b(goc: Path, treo_giay: str = "45"):
    """(b) one-off còn chạy; CID đã ghi; `docker inspect` của nó TREO."""
    return _chay_deploy(goc, STUB_ONEOFF="running", STUB_ONEOFF_DOC="treo", STUB_TREO_GIAY=treo_giay,
                        STUB_TIN_HIEU_O_MIGRATE="TERM", **_V5_HAN)


def _ca_d(goc: Path):
    """(d) CID CHƯA ghi (đọc lỗi từ đầu) + pha dang_migrate + tra theo tên đọc lỗi."""
    return _chay_deploy(goc, STUB_ONEOFF="running", STUB_ONEOFF_DOC="loi",
                        STUB_TIN_HIEU_O_MIGRATE="TERM", **_V5_HAN)


@_bo_qua_neu_khong_posix
def test_v5_a_doc_loi_khi_oneoff_con_chay_thi_chua_xac_dinh(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nk = _ca_a(goc)
    ra = _ra(ket)
    assert _cid_ghi_nhan(goc) == _OO, "tiền đề: CID phải đã được ghi nhận trước khi daemon lỗi"
    assert _noi_khong_con(ra) == [], f"đọc lỗi mà vẫn nói 'không còn': {_noi_khong_con(ra)}"
    assert _DAU_CHUA_CUOI in ra, "đọc lỗi mà hướng dẫn KHÔNG nói số đo không phải trạng thái cuối"
    assert f"oneoff\t{_OO} khong_doc_duoc_sau_2s" in _tep_trang_thai(goc)
    assert not any(d.startswith("docker rm") for d in _dong(nk)), "không đọc được mà vẫn dọn"
    assert ket.returncode == 143, f"rc={ket.returncode} (TERM ⇒ 143)"


@_bo_qua_neu_khong_posix
def test_v5_b_inspect_treo_thi_trap_ket_thuc_trong_han_va_chua_xac_dinh(tmp_path: Path) -> None:
    import time

    goc = _dung_san_khau(tmp_path)
    ket, nk = _ca_b(goc)
    t_xong = time.time()
    ra = _ra(ket)
    assert _cid_ghi_nhan(goc) == _OO, "tiền đề: CID phải đã được ghi nhận"
    t_treo = float((goc / "lenh.log.treo").read_text(encoding="utf-8"))
    assert t_xong - t_treo < 25, f"docker inspect TREO giữ trap {t_xong - t_treo:.1f}s (hạn 2s + mỗi lệnh 1s)"
    assert _noi_khong_con(ra) == [], f"treo mà vẫn nói 'không còn': {_noi_khong_con(ra)}"
    assert _DAU_CHUA_CUOI in ra
    assert "KHÔNG ĐỌC ĐƯỢC trạng thái one-off" in ra
    assert not any(d.startswith("docker rm") for d in _dong(nk))
    assert ket.returncode == 143


@_bo_qua_neu_khong_posix
def test_v5_c_oneoff_that_su_bi_rm_don_thi_van_ghi_khong_con(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(goc, STUB_ONEOFF="da_rm", STUB_TIN_HIEU_O_MIGRATE="TERM", **_V5_HAN)
    ra = _ra(ket)
    assert _cid_ghi_nhan(goc) == _OO, "tiền đề: CID phải đã được ghi nhận"
    assert "không còn (`--rm` đã dọn — ĐÃ XÁC NHẬN" in ra, ra[-2500:]
    assert f"oneoff\t{_OO} khong_con" in _tep_trang_thai(goc)
    assert _DAU_CHUA_CUOI not in ra, "container đã thật sự bị dọn mà vẫn gọi là CHƯA XÁC ĐỊNH"
    assert not any(d.startswith("docker rm") for d in _dong(nk))


@_bo_qua_neu_khong_posix
def test_v5_d_cid_chua_ghi_doc_loi_o_dang_migrate_thi_chua_xac_dinh(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nk = _ca_d(goc)
    ra = _ra(ket)
    assert _cid_ghi_nhan(goc) == "", "tiền đề: CID phải CHƯA được ghi nhận"
    assert "[pha] dang_migrate" in ra, "tiền đề: bị ngắt khi migration ĐANG chạy"
    assert "không dọn gì" not in ra, "chưa ghi CID + đọc lỗi mà vẫn kết luận 'không có gì để dọn'"
    assert _DAU_CHUA_CUOI in ra
    assert "oneoff\t- khong_doc_duoc_theo_ten" in _tep_trang_thai(goc)
    assert "tra theo tên: KHÔNG ĐỌC ĐƯỢC" in ra
    assert not any(d.startswith("docker rm") for d in _dong(nk))


@_bo_qua_neu_khong_posix
def test_v5_d_doi_chung_cid_chua_ghi_va_xac_nhan_khong_co_thi_khong_danh_dau(tmp_path: Path) -> None:
    # Đối chứng của (d): cùng pha, CID chưa ghi, nhưng tra theo tên ĐỌC ĐƯỢC và RỖNG.
    goc = _dung_san_khau(tmp_path)
    ket, _ = _chay_deploy(goc, STUB_TIN_HIEU_O_MIGRATE="TERM", **_V5_HAN)
    ra = _ra(ket)
    assert "[pha] dang_migrate" in ra
    assert "ĐÃ XÁC NHẬN không có container nào tên" in ra, ra[-2500:]
    assert _DAU_CHUA_CUOI not in ra


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,cu,moi",
    [
        ("bỏ phân biệt theo CID (lỗi liệt kê ⇒ 'không tồn tại')",
         """    ds=$(_dcg_dk ps -a -q --no-trunc --filter "id=$2" 2>/dev/null) || return 1\n""",
         """    ds=$(_dcg_dk ps -a -q --no-trunc --filter "id=$2" 2>/dev/null) || true\n"""),
        ("bỏ phân biệt theo tên (lỗi liệt kê ⇒ 'không có')",
         """    ds=$(_dcg_dk ps -a -q --no-trunc --filter "name=^/?$1\\$" 2>/dev/null) || return 1\n""",
         """    ds=$(_dcg_dk ps -a -q --no-trunc --filter "name=^/?$1\\$" 2>/dev/null) || true\n"""),
        ("bỏ hạn từng lệnh",
         # vòng 6b: `_dcg_dk` nay lấy hạn = min(hạn đọc, phần còn lại của trap) — gỡ đúng dòng có `timeout`.
         """    timeout -k 2 "$h" docker "$@"\n""",
         """    docker "$@"\n"""),
        ("bỏ cờ CHƯA XÁC ĐỊNH",
         """_dcg_oneoff_chua_xd() {\n    _DCG_ONEOFF_CON_CHAY=1\n""",
         """_dcg_oneoff_chua_xd() {\n"""),
    ],
)
def test_kiem_nguoc_v5_go_tung_guard_f43(tmp_path: Path, ten_ca: str, cu: str, moi: str) -> None:
    import time

    goc = _dung_san_khau(tmp_path, deploy_sh=_ban_dot_bien(cu, moi))
    if "theo CID" in ten_ca:
        ket, _ = _ca_a(goc)
        assert _noi_khong_con(_ra(ket)), f"{ten_ca}: vẫn không nói 'không còn' ⇒ ca (a) xanh vì lý do khác"
    elif "theo tên" in ten_ca:
        ket, _ = _ca_d(goc)
        assert "ĐÃ XÁC NHẬN không có container nào tên" in _ra(ket), f"{ten_ca}: ca (d) không canh phép liệt kê theo tên"
    elif "hạn" in ten_ca:
        _, _ = _ca_b(goc, treo_giay="20")
        tre = time.time() - float((goc / "lenh.log.treo").read_text(encoding="utf-8"))
        assert tre >= 25, f"{ten_ca}: bỏ hạn mà trap vẫn xong sau {tre:.1f}s ⇒ ca (b) không canh hạn"
    else:
        ket, _ = _ca_a(goc)
        assert _DAU_CHUA_CUOI not in _ra(ket), f"{ten_ca}: vẫn cảnh báo ⇒ ca (a) không canh cờ"


# =============================================================================
# XI. Vòng 6 (N21.07) — hạn cho TOÀN đường phục hồi; bảng quyết định sau lệnh GHI
# =============================================================================
# Lệnh GHI hết hạn KHÔNG chứng minh thao tác đã bị huỷ: đo lại bằng đường đọc có hạn —
# đúng CID/ảnh + running + LẦN KHỞI ĐỘNG MỚI ⇒ đi tiếp hậu kiểm; đã dừng / ĐÃ XÁC NHẬN không
# tồn tại ⇒ KHÔNG mở được; không đọc được / chưa thấy lần khởi động mới ⇒ CHƯA XÁC ĐỊNH.
# KHÔNG bao giờ chạy lại lệnh ghi. Mỗi ca dưới đây chỉ vi phạm MỘT bất biến.
_V6 = {
    **_NHANH,
    "QLTS_HAN_LENH_DOCKER": "1",
    "QLTS_HAN_KHOI_DONG": "2",
    "QLTS_HAN_NGINX_RESTART": "2",
    "QLTS_HAN_DO_SNI": "2",
    "QLTS_HAN_PII": "2",
    "QLTS_HAN_PSQL": "5",
}
_MO_DAT = "ĐÃ mở lại container CŨ"
_DAU_MO_CHUA_XD = "trạng thái container sau lệnh mở lại CHƯA XÁC ĐỊNH"
_TREO = "30"          # giây stub treo — hạn đúng cắt ở 1–2 s
_TREO_DOT_BIEN = "25"  # đột biến bỏ hạn ⇒ chờ trọn số giây này


def _tu_luc_treo(goc: Path) -> float:
    """Giây từ lần TREO đầu tiên (stub ghi mốc) tới lúc deploy.sh thoát."""
    import time

    return time.time() - float((goc / "lenh.log.treo").read_text(encoding="utf-8"))


def _so_lan_goi(goc: Path, lenh: str, cid: str) -> int:
    return sum(1 for g in _cac_loi_goi(goc) if g["args"][:1] == [lenh] and g["args"][-1:] == [cid])


def _ca_start(goc: Path, kieu: str, treo: str = _TREO, **them):
    return _chay_deploy(goc, STUB_GHI_TREO="start:backend", STUB_GHI_TREO_KIEU=kieu, STUB_TREO_GIAY=treo,
                        **_LUI, **{**_V6, **them})


def _ca_restart(goc: Path, kieu: str, treo: str = _TREO, **them):
    return _chay_deploy(goc, STUB_IP_DOI="1", STUB_GHI_TREO="restart", STUB_GHI_TREO_KIEU=kieu,
                        STUB_TREO_GIAY=treo, **_LUI, **{**_V6, **them})


@_bo_qua_neu_khong_posix
def test_v6_start_het_han_nhung_da_lam_thi_do_lai_va_di_tiep_hau_kiem(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, _ = _ca_start(goc, "da_lam")
    ra, t = _ra(ket), _tu_luc_treo(goc)
    assert _so_lan_goi(goc, "start", _cid_gia("backend")) == 1, "lệnh ghi bị CHẠY LẠI"
    assert t < 20, f"`docker start` treo giữ trap {t:.1f}s (hạn 2 s)"
    assert "nhưng ĐO LẠI: đúng CID, đúng ảnh, running, LẦN KHỞI ĐỘNG MỚI" in ra, ra[-2500:]
    assert _MO_DAT in ra, "đã đo lại thấy start có hiệu lực mà không đi tiếp hậu kiểm"
    assert "mo_lai_cu\tdat" in _tep_trang_thai(goc)


@_bo_qua_neu_khong_posix
def test_v6_start_het_han_chua_co_hieu_luc_thi_khong_mo_duoc_va_dung_ngay(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, _ = _ca_start(goc, "chua_lam")
    ra = _ra(ket)
    goi = _cac_loi_goi(goc)
    i_start = max(i for i, g in enumerate(goi) if g["args"][:1] == ["start"])
    sau = [" ".join(g["args"]) for g in goi[i_start + 1:]]
    assert not [x for x in sau if " ps -aq backend" in f" {x}"], f"KHÔNG mở được mà vẫn chờ healthy: {sau}"
    assert _so_lan_goi(goc, "start", _cid_gia("backend")) == 1, "lệnh ghi bị CHẠY LẠI"
    assert _so_lan_goi(goc, "start", _cid_gia("celery-worker")) == 0, "đã KHÔNG mở được backend mà vẫn mở tiếp"
    assert "mo_lai_cu\tKHONG_DAT" in _tep_trang_thai(goc)
    assert _MO_DAT not in ra
    assert "KHÔNG mở được" in ra


@_bo_qua_neu_khong_posix
def test_v6_start_het_han_khong_doc_duoc_thi_chua_xac_dinh(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, _ = _ca_start(goc, "khong_doc")
    ra = _ra(ket)
    assert "mo_lai_cu\tCHUA_XAC_DINH" in _tep_trang_thai(goc), ra[-2500:]
    assert _DAU_MO_CHUA_XD in ra and "LÚC IN, KHÔNG phải trạng thái cuối" in ra
    assert _MO_DAT not in ra
    assert _so_lan_goi(goc, "start", _cid_gia("backend")) == 1, "lệnh ghi bị CHẠY LẠI"


@_bo_qua_neu_khong_posix
def test_v6_restart_nginx_het_han_da_lam_thi_xac_nhan_lan_khoi_dong_moi(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, _ = _ca_restart(goc, "da_lam")
    ra, t = _ra(ket), _tu_luc_treo(goc)
    assert _so_lan_goi(goc, "restart", _cid_gia("nginx")) == 1, "lệnh ghi bị CHẠY LẠI"
    assert t < 20, f"`docker restart` treo giữ trap {t:.1f}s (hạn 2 s)"
    assert "LẦN KHỞI ĐỘNG MỚI (StartedAt=R1)" in ra, ra[-2500:]
    assert _MO_DAT in ra


@_bo_qua_neu_khong_posix
def test_v6_restart_nginx_het_han_chua_xong_thi_chua_xac_dinh_va_huong_dan_tay(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, _ = _ca_restart(goc, "chua_lam")
    ra = _ra(ket)
    cn = _cid_gia("nginx")
    assert "mo_lai_cu\tCHUA_XAC_DINH" in _tep_trang_thai(goc), ra[-2500:]
    assert "VẪN lần khởi động CŨ" in ra
    assert f"docker start {cn}" in ra and f"nginx_tay\t{cn}" in _tep_trang_thai(goc), "thiếu hướng dẫn tay theo ĐÚNG CID"
    assert _so_lan_goi(goc, "restart", cn) == 1, "lệnh ghi bị CHẠY LẠI"
    assert _MO_DAT not in ra


@_bo_qua_neu_khong_posix
def test_v6_restart_nginx_het_han_nginx_dung_thi_khong_mo_duoc_va_huong_dan_tay(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, _ = _ca_restart(goc, "dung")
    ra = _ra(ket)
    cn = _cid_gia("nginx")
    assert f"docker start {cn}" in ra, "nginx DỪNG mà không in hướng dẫn tay theo ĐÚNG CID"
    assert "DỪNG / KHÔNG mở được sau khởi động lại" in ra
    assert "mo_lai_cu\tKHONG_DAT" in _tep_trang_thai(goc)
    assert _MO_DAT not in ra


@_bo_qua_neu_khong_posix
def test_v6_restart_nginx_rc0_ma_khong_co_lan_khoi_dong_moi_thi_chua_xac_dinh(tmp_path: Path) -> None:
    # "running" chưa đủ: lệnh trả 0 tức thì nhưng lần chạy CŨ vẫn sống.
    goc = _dung_san_khau(tmp_path)
    ket, _ = _ca_restart(goc, "chua_lam", treo="0", STUB_GHI_RC_SAU_TREO="0")
    ra = _ra(ket)
    assert _MO_DAT not in ra, "restart trả 0 mà KHÔNG có lần khởi động mới vẫn báo đã mở lại"
    assert "mo_lai_cu\tCHUA_XAC_DINH" in _tep_trang_thai(goc)


@_bo_qua_neu_khong_posix
def test_v6_dau_do_sni_treo_thi_chua_xac_dinh_trong_han(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, _ = _chay_deploy(goc, STUB_DO_TREO="1", STUB_TREO_GIAY=_TREO, **_LUI, **_V6)
    ra, t = _ra(ket), _tu_luc_treo(goc)
    assert t < 20, f"đầu dò SNI treo giữ trap {t:.1f}s (hạn 2 s)"
    assert "đầu dò SNI HẾT HẠN" in ra
    assert "mo_lai_cu\tCHUA_XAC_DINH" in _tep_trang_thai(goc), "đầu dò hết hạn bị coi là đo được"
    assert _MO_DAT not in ra


@_bo_qua_neu_khong_posix
def test_v6_kiem_pii_treo_thi_ghi_het_han_khong_doi_ket_qua_phuc_hoi(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, _ = _chay_deploy(goc, STUB_NGINX_VERIFY_TREO="1", STUB_TREO_GIAY=_TREO, **_LUI, **_V6)
    ra, t = _ra(ket), _tu_luc_treo(goc)
    assert t < 20, f"kiểm PII treo giữ trap {t:.1f}s (hạn 2 s)"
    assert "pii_nginx_cu\tHET_HAN 2s" in _tep_trang_thai(goc)
    assert _MO_DAT in ra, "F39: kết quả kiểm PII (THÔNG TIN) đã thay kết quả phục hồi dịch vụ"


_DOC_TREO = [
    # (bước, mẫu, sau, trước) — đọc TREO ở đúng một bước; phải dừng fail-closed trong hạn.
    ("3b", "inspect -f {{.Image}} " + _cid_gia("backend"), "", "build --parallel"),
    ("4c", "inspect -f {{.Image}} " + _cid_gia("backend"), "build --parallel", _MOC_STEP8),
    ("8c", "inspect -f {{.Image}} " + _cid_gia("backend"), _MOC_STEP8, ""),
    ("healthy", "inspect -f {{if .State.Health}}*", _MOC_STEP8, ""),
]


def _ca_doc_treo(goc: Path, mau: str, sau: str, truoc: str, treo: str = _TREO):
    them = {"STUB_TREO_KHI": mau, "STUB_TREO_GIAY": treo}
    if sau:
        them["STUB_TREO_SAU"] = sau
    if truoc:
        them["STUB_TREO_TRUOC"] = truoc
    return _chay_deploy(goc, **{**_V6, **them})


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize("buoc,mau,sau,truoc", _DOC_TREO)
def test_v6_doc_treo_o_tung_buoc_thi_dung_fail_closed_trong_han(
    tmp_path: Path, buoc: str, mau: str, sau: str, truoc: str
) -> None:
    goc = _dung_san_khau(tmp_path)
    marker = (goc / "ops" / "last-deploy.marker").read_bytes()
    ket, nk = _ca_doc_treo(goc, mau, sau, truoc)
    t = _tu_luc_treo(goc)
    assert t < 20, f"{buoc}: đọc treo giữ deploy {t:.1f}s (hạn đọc 1 s)"
    assert ket.returncode != 0, f"{buoc}: đọc treo mà deploy thoát 0"
    assert (goc / "ops" / "last-deploy.marker").read_bytes() == marker, f"{buoc}: marker bị ghi"
    if buoc == "3b":
        assert "build --parallel" not in nk, "3b: đọc treo mà vẫn build"
    if buoc == "4c":
        assert not any(d.startswith("docker stop ") for d in _dong(nk)), "4c: đọc treo mà vẫn dừng container"


@_bo_qua_neu_khong_posix
def test_v6_tran_trap_mac_dinh_tinh_tu_gia_tri_mac_dinh(tmp_path: Path) -> None:
    import re

    goc = _dung_san_khau(tmp_path)
    ket, _ = _chay_deploy(goc, **_LUI)   # giá trị MẶC ĐỊNH, không ghi đè hạn nào
    ra = _ra(ket)
    m = re.search(r"\[trap\] trần thời gian của trap \(pha 'da_dong', đi tiếp=0\): (\d+)s — (.+)", ra)
    assert m, f"đầu trap KHÔNG in trần thời gian:\n{ra[-2000:]}"
    tran = int(m.group(1))
    # Mặc định (đọc 10 s, psql 60 s, start 10 s, restart 30 s, đầu dò 60 s, PII 90 s, healthy 60 s):
    # mở lại 1.029 s + hướng dẫn cuối 185 s. Đổi một hạn mặc định ⇒ ca này đỏ ⇒ xét lại trần.
    # Vòng 6b (owner): KHÔNG so với `command_timeout: 20m` — đó là hạn của CẢ phiên SSH; trần
    # 1.214 s là giới hạn phải ĐO trên VPS, không phải một con số đặt cho vừa.
    assert tran == 1214, f"trần mặc định đổi: {tran}s ({m.group(2)})"
    for phan in ("vân_tay=", "start=3×", "healthy=2×", "sni=", "pii=", "hướng_dẫn="):
        assert phan in m.group(2), f"trần thiếu thành phần {phan}: {m.group(2)}"
    assert f"tran_trap\t{tran}s pha=da_dong" in _tep_trang_thai(goc), "trần không được ghi vào nhật ký local"


@_bo_qua_neu_khong_posix
def test_v6_trap_that_ket_thuc_trong_tran_khi_cac_lenh_treo(tmp_path: Path) -> None:
    import re
    import time

    goc = _dung_san_khau(tmp_path)
    ket, _ = _chay_deploy(goc, STUB_GHI_TREO="start:backend", STUB_DO_TREO="1", STUB_TREO_GIAY=_TREO,
                          **_LUI, **_V6)
    t_xong = time.time()
    ra, tt = _ra(ket), _tep_trang_thai(goc)
    m = re.search(r"tran_trap\t(\d+)s pha=da_dong bat_dau=(\d+)", tt)
    assert m, tt
    tran, bat_dau = int(m.group(1)), int(m.group(2))
    da = t_xong - bat_dau
    assert da <= tran, f"trap chạy {da:.1f}s VƯỢT trần {tran}s"
    assert da >= 4, f"trap chỉ chạy {da:.1f}s — hai lệnh treo (2 s mỗi lệnh) KHÔNG được chờ tới hạn"
    assert re.search(r"thoi_gian_trap\t\d+s/" + str(tran) + "s", tt)
    assert "[trap] trap chạy" in ra


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,cu,moi",
    [
        ("start: bỏ hạn",
         """timeout -k 5 "$_DCG_HAN_KHOI_DONG" docker start""", "docker start"),
        ("start: hết hạn ⇒ KHÔNG mở được, không đo lại",
         """        _dcg_sau_lenh_ghi "mở lại · $s" "${_DCG_CID[$s]}" "$truoc" "${_DCG_ANH[$s]}" "$kq" || return $?\n""",
         """        [ "$kq" -eq 0 ] || return 1\n"""),
        ("start: không đo lại, tin là đã mở",
         """        _dcg_sau_lenh_ghi "mở lại · $s" "${_DCG_CID[$s]}" "$truoc" "${_DCG_ANH[$s]}" "$kq" || return $?\n""",
         """        :\n"""),
        ("nginx: running là đủ (bỏ LẦN KHỞI ĐỘNG MỚI)",
         """            if [ -n "$truoc" ] && [ "$bd" = "$truoc" ]; then\n""", """            if false; then\n"""),
        ("nginx: không in hướng dẫn tay",
         """            [ "$kq" -eq 5 ] && _dcg_nginx_tay "CHƯA XÁC ĐỊNH sau khởi động lại" "$truoc" || _dcg_nginx_tay "DỪNG / KHÔNG mở được sau khởi động lại" "$truoc"\n""",
         """            :\n"""),
        ("restart nginx: bỏ hạn",
         """timeout -k 5 "$_DCG_HAN_NGINX_RESTART" docker restart""", "docker restart"),
        ("đầu dò: bỏ hạn",
         """timeout -k 5 "$kq" docker run""", "docker run"),
        ("đầu dò: hết hạn coi là KHÔNG ĐẠT",
         """        warn "[nginx · dịch vụ] đầu dò SNI HẾT HẠN (hạn ${_DCG_HAN_DO_SNI}s, còn ngân sách trap $(_dcg_con_lai)s) — dịch vụ CHƯA ĐƯỢC CHỨNG MINH (CHƯA XÁC ĐỊNH, không phải ĐẠT)"\n        return 5\n""",
         """        return 1\n"""),
        ("PII: bỏ hạn",
         """timeout -k 5 "$h" bash "$SCRIPT_DIR/nginx-verify.sh\"""", """bash "$SCRIPT_DIR/nginx-verify.sh\""""),
        ("đọc 3b: bỏ hạn",
         """        _RA_IMG=$(_dcg_dk inspect -f '{{.Image}}' "$_RA_CID" 2>/dev/null || true)\n""",
         """        _RA_IMG=$(docker inspect -f '{{.Image}}' "$_RA_CID" 2>/dev/null || true)\n"""),
        ("đọc 4c: bỏ hạn",
         """        _ANH=$(_dcg_dk inspect -f '{{.Image}}' "$_CID")""",
         """        _ANH=$(docker inspect -f '{{.Image}}' "$_CID")"""),
        ("đọc 8c: bỏ hạn",
         """    _RA_IMG_MOI=$(_dcg_dk inspect -f '{{.Image}}' "$_RA_CID_MOI" 2>/dev/null || true)\n""",
         """    _RA_IMG_MOI=$(docker inspect -f '{{.Image}}' "$_RA_CID_MOI" 2>/dev/null || true)\n"""),
        ("chờ healthy: bỏ hạn",
         """        if ! sk=$(_dcg_dk inspect \\\n""", """        if ! sk=$(docker inspect \\\n"""),
        ("trần: bỏ phần hướng dẫn cuối",
         """                tong=$((G + HD))\n""", """                tong=$G\n"""),
    ],
)
def test_kiem_nguoc_v6_go_tung_guard(tmp_path: Path, ten_ca: str, cu: str, moi: str) -> None:
    import re

    goc = _dung_san_khau(tmp_path, deploy_sh=_ban_dot_bien(cu, moi))
    if ten_ca == "start: bỏ hạn":
        _ca_start(goc, "da_lam", treo=_TREO_DOT_BIEN)
        assert _tu_luc_treo(goc) >= 20, f"{ten_ca}: vẫn xong nhanh ⇒ ca start-treo không canh hạn"
    elif ten_ca.startswith("start: hết hạn"):
        ket, _ = _ca_start(goc, "da_lam")
        assert _MO_DAT not in _ra(ket), f"{ten_ca}: vẫn mở được ⇒ ca 'đã làm' không canh phép đo lại"
    elif ten_ca.startswith("start: không đo lại"):
        _ca_start(goc, "chua_lam")
        goi = _cac_loi_goi(goc)
        i_start = max(i for i, g in enumerate(goi) if g["args"][:1] == ["start"])
        assert any(" ps -aq backend" in " " + " ".join(g["args"]) for g in goi[i_start + 1:]), (
            f"{ten_ca}: không chờ healthy ⇒ ca 'chưa có hiệu lực' không canh phép đo lại")
    elif ten_ca.startswith("nginx: running"):
        ket, _ = _ca_restart(goc, "chua_lam", treo="0", STUB_GHI_RC_SAU_TREO="0")
        assert _MO_DAT in _ra(ket), f"{ten_ca}: vẫn không báo mở ⇒ ca rc0 không canh lần khởi động mới"
    elif ten_ca.startswith("nginx: không in"):
        ket, _ = _ca_restart(goc, "dung")
        assert f"docker start {_cid_gia('nginx')}" not in _ra(ket), f"{ten_ca}: vẫn có hướng dẫn tay"
    elif ten_ca == "restart nginx: bỏ hạn":
        _ca_restart(goc, "da_lam", treo=_TREO_DOT_BIEN)
        assert _tu_luc_treo(goc) >= 20, f"{ten_ca}: vẫn xong nhanh"
    elif ten_ca == "đầu dò: bỏ hạn":
        _chay_deploy(goc, STUB_DO_TREO="1", STUB_TREO_GIAY=_TREO_DOT_BIEN, **_LUI, **_V6)
        assert _tu_luc_treo(goc) >= 20, f"{ten_ca}: vẫn xong nhanh"
    elif ten_ca.startswith("đầu dò: hết hạn"):
        _chay_deploy(goc, STUB_DO_TREO="1", STUB_TREO_GIAY=_TREO, **_LUI, **_V6)
        assert "mo_lai_cu\tKHONG_DAT" in _tep_trang_thai(goc), f"{ten_ca}: vẫn CHƯA XÁC ĐỊNH"
    elif ten_ca == "PII: bỏ hạn":
        _chay_deploy(goc, STUB_NGINX_VERIFY_TREO="1", STUB_TREO_GIAY=_TREO_DOT_BIEN, **_LUI, **_V6)
        assert _tu_luc_treo(goc) >= 20, f"{ten_ca}: vẫn xong nhanh"
    elif ten_ca.startswith("đọc ") or ten_ca.startswith("chờ healthy"):
        buoc = {"đọc 3b": "3b", "đọc 4c": "4c", "đọc 8c": "8c", "chờ healthy": "healthy"}[ten_ca.split(":")[0]]
        _, mau, sau, truoc = next(x for x in _DOC_TREO if x[0] == buoc)
        _ca_doc_treo(goc, mau, sau, truoc, treo=_TREO_DOT_BIEN)
        assert _tu_luc_treo(goc) >= 20, f"{ten_ca}: vẫn xong nhanh ⇒ ca đọc-treo {buoc} không canh hạn"
    else:
        ket, _ = _chay_deploy(goc, **_LUI)
        m = re.search(r"\[trap\] trần thời gian của trap \(pha 'da_dong', đi tiếp=0\): (\d+)s", _ra(ket))
        assert m and int(m.group(1)) != 1214, f"{ten_ca}: trần không đổi ⇒ ca trần mặc định không canh công thức"


# =============================================================================
# XII. Vòng 6b (F45) — ngân sách trap theo pha × đi tiếp; hạn tổng được THỰC THI
# =============================================================================
# Hạn chót = lúc bắt đầu trap + ngân sách; trước mỗi bước: hạn lệnh = min(hạn riêng, phần còn
# lại); lệnh GHI chỉ bắt đầu khi phần còn lại ≥ hạn của nó + 5 s; hết ngân sách ⇒ CHƯA XÁC ĐỊNH,
# hướng dẫn NGẮN không đọc Docker/CSDL; KHÔNG chạy lại lệnh ghi. `QLTS_TRAN_TRAP` chỉ HẠ trần.
_DAU_HET_NS = "HẾT NGÂN SÁCH trap — KHÔNG đo thêm Docker/CSDL"


def _bang_ngan_sach(pha: str, di_tiep: str, deploy_sh: str | None = None) -> int:
    """Chạy ĐÚNG hàm `_dcg_ngan_sach_trap` của deploy.sh với hạn MẶC ĐỊNH."""
    import re
    import subprocess

    than = _DEPLOY.read_text(encoding="utf-8") if deploy_sh is None else deploy_sh
    ham = re.search(r"^_dcg_ngan_sach_trap\(\) \{\n.*?^\}\n", than, re.S | re.M).group(0)
    kich = (
        "set -eu\n_DCG_HAN_LENH=10; _DCG_HAN_PSQL=60; _DCG_HAN_KHOI_DONG=10; _DCG_HAN_NGINX_RESTART=30\n"
        "_DCG_HAN_DO_SNI=60; _DCG_HAN_PII=90; _HAN_HEALTH=60; _DCG_HAN_ONEOFF=60\n"
        f"_DCG_PHA={pha}; _DCG_DI_TIEP={di_tiep}\n" + ham + "\n_dcg_ngan_sach_trap\n"
    )
    ra = subprocess.run(["bash", "-c", kich], capture_output=True, text=True, timeout=30)
    assert ra.returncode == 0, ra.stderr
    return int(ra.stdout.split()[0])


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "pha,di_tiep,ky_vong",
    [
        ("chua_dong", "1", 185), ("chua_dong", "0", 0),
        ("dang_dong", "1", 185), ("dang_dong", "0", 1214),
        ("da_dong", "1", 185), ("da_dong", "0", 1214),
        ("dang_migrate", "1", 318), ("dang_migrate", "0", 318),
        ("migrate_do", "1", 318), ("migrate_do", "0", 318),
        ("da_migrate", "0", 185), ("da_migrate", "1", 185),
        ("khong_ap_dung", "0", 0), ("buoc8", "1", 0), ("xong", "0", 0),
    ],
)
def test_v6b_bang_ngan_sach_theo_pha_va_che_do_di_tiep(pha: str, di_tiep: str, ky_vong: int) -> None:
    # Mọi nhánh trap có thể gọi đều có ngân sách: đi tiếp ở pha trước migration vẫn IN hướng dẫn
    # (đọc Docker/CSDL) ⇒ > 0. Hạn MẶC ĐỊNH (đọc 10 s).
    assert _bang_ngan_sach(pha, di_tiep) == ky_vong


@_bo_qua_neu_khong_posix
def test_v6b_chua_dong_di_tiep_co_ngan_sach_va_trap_ket_thuc_trong_ngan_sach(tmp_path: Path) -> None:
    import re
    import time

    goc = _san_khau_hai_luot(tmp_path)
    ket, _ = _ca_x6(goc)   # lượt đi tiếp đỏ ở 4c (pha chua_dong) ⇒ trap IN hướng dẫn
    t_xong = time.time()
    ra = _ra(ket)
    tt = _tt(goc, _TS_TIEP).read_text(encoding="utf-8")
    m = re.search(r"tran_trap\t(\d+)s pha=chua_dong bat_dau=(\d+) di_tiep=1", tt)
    assert m, f"chua_dong + đi tiếp KHÔNG có ngân sách:\n{tt}"
    assert int(m.group(1)) > 0
    assert t_xong - int(m.group(2)) <= int(m.group(1)), "trap vượt ngân sách"
    assert "ĐI TIẾP dừng TRƯỚC migration" in ra


def _ca_ns_do_treo(goc: Path, treo: str = "40", **them):
    # Đầu dò SNI treo; hạn riêng của đầu dò LỚN (60 s) nhưng ngân sách tổng NHỎ (15 s).
    return _chay_deploy(goc, STUB_DO_TREO="1", STUB_TREO_GIAY=treo, **_LUI,
                        **{**_V6, "QLTS_HAN_DO_SNI": "60", "QLTS_TRAN_TRAP": "15", **them})


def _thoi_gian_trap(goc: Path, t_xong: float) -> tuple[int, float]:
    import re

    m = re.search(r"tran_trap\t(\d+)s pha=\w+ bat_dau=(\d+)", _tep_trang_thai(goc))
    assert m, _tep_trang_thai(goc)
    return int(m.group(1)), t_xong - int(m.group(2))


@_bo_qua_neu_khong_posix
def test_v6b_treo_voi_ngan_sach_nho_thi_trap_dung_dung_han_chua_xac_dinh(tmp_path: Path) -> None:
    import time

    goc = _dung_san_khau(tmp_path)
    ket, _ = _ca_ns_do_treo(goc)
    tran, da = _thoi_gian_trap(goc, time.time())
    ra, tt = _ra(ket), _tep_trang_thai(goc)
    assert tran == 15, f"ghi đè QLTS_TRAN_TRAP không hạ trần: {tran}"
    assert da <= tran + 3, f"trap chạy {da:.1f}s — VƯỢT ngân sách {tran}s (hạn tổng không được thực thi)"
    assert "mo_lai_cu\tCHUA_XAC_DINH" in tt
    assert _DAU_HET_NS in ra and "het_ngan_sach\thuong_dan_ngan" in tt
    for dv in ("backend", "celery-worker", "celery-beat"):
        assert _so_lan_goi(goc, "start", _cid_gia(dv)) == 1, f"lệnh ghi cho {dv} bị CHẠY LẠI"


@_bo_qua_neu_khong_posix
def test_v6b_khong_bat_dau_lenh_ghi_khi_ngan_sach_khong_du(tmp_path: Path) -> None:
    import time

    goc = _dung_san_khau(tmp_path)
    ket, _ = _chay_deploy(goc, **_LUI, **{**_V6, "QLTS_HAN_KHOI_DONG": "30", "QLTS_TRAN_TRAP": "10"})
    tran, da = _thoi_gian_trap(goc, time.time())
    tt = _tep_trang_thai(goc)
    assert sum(_so_lan_goi(goc, "start", _cid_gia(dv)) for dv in _DV_GHI) == 0, (
        "còn 10 s mà vẫn BẮT ĐẦU `docker start` hạn 30 s")
    assert "het_ngan_sach\tmở_lại_·_backend_(docker_start)" in tt, tt
    assert "mo_lai_cu\tCHUA_XAC_DINH" in tt
    assert da <= tran + 3


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,cu,moi",
    [
        ("bỏ cơ chế thực thi (chỉ còn so cuối)",
         """    if [ -z "${_DCG_TRAP_HET:-}" ]; then printf '%s\\n' 999999; return 0; fi\n""",
         """    printf '%s\\n' 999999; return 0\n"""),
        ("bảng: chua_dong = 0 khi đi tiếp",
         """                tong=$HD; ct="đi_tiếp: hướng_dẫn=$HD"\n""", """                tong=0; ct="không làm gì"\n"""),
        ("lệnh ghi bắt đầu dù không đủ ngân sách",
         """    [ "$r" -ge $(( $1 + 5 )) ] && return 0\n""", """    return 0\n"""),
        ("hết ngân sách vẫn in hướng dẫn đầy đủ",
         """    if [ -n "${_DCG_TRAP_HET:-}" ] && [ "$(_dcg_con_lai)" -le 0 ]; then\n""", """    if false; then\n"""),
        # Vòng 6c (F46) — kiểm độc lập của coordinator: W6, W5 sống trên bộ 6b.
        ("W6: hết ngân sách vẫn trả 0 (bỏ `return 1`, nguyên văn coordinator)",
         """    if [ "$r" -le 0 ]; then printf '0\\n'; return 1; fi\n""",
         """    if [ "$r" -le 0 ]; then printf '0\\n'; fi\n"""),
        ("W6b · Docker: hết ngân sách in 0 VÀ trả 0 (`timeout 0` = TẮT hạn)",
         """    if [ "$r" -le 0 ]; then printf '0\\n'; return 1; fi\n""",
         """    if [ "$r" -le 0 ]; then printf '0\\n'; return 0; fi\n"""),
        ("W6b · psql: hết ngân sách in 0 VÀ trả 0 (`timeout 0` = TẮT hạn)",
         """    if [ "$r" -le 0 ]; then printf '0\\n'; return 1; fi\n""",
         """    if [ "$r" -le 0 ]; then printf '0\\n'; return 0; fi\n"""),
        ("W5: bỏ đệm +5 s của lệnh ghi",
         """    [ "$r" -ge $(( $1 + 5 )) ] && return 0\n""", """    [ "$r" -ge "$1" ] && return 0\n"""),
    ],
)
def test_kiem_nguoc_v6b_go_tung_guard(tmp_path: Path, ten_ca: str, cu: str, moi: str) -> None:
    import time

    dot = _ban_dot_bien(cu, moi)
    if ten_ca.startswith("bỏ cơ chế"):
        goc = _dung_san_khau(tmp_path, deploy_sh=dot)
        _ca_ns_do_treo(goc, treo="25")
        tran, da = _thoi_gian_trap(goc, time.time())
        assert da > tran + 3, f"{ten_ca}: trap vẫn dừng trong {tran}s ⇒ ca treo không canh cơ chế thực thi"
    elif ten_ca.startswith("bảng"):
        assert _bang_ngan_sach("chua_dong", "1", dot) == 0
        goc = _san_khau_hai_luot(tmp_path, deploy_sh=dot)
        _ca_x6(goc)
        assert "tran_trap" not in _tt(goc, _TS_TIEP).read_text(encoding="utf-8"), (
            f"{ten_ca}: vẫn có ngân sách ⇒ ca chua_dong+đi tiếp không canh bảng")
    elif ten_ca.startswith("lệnh ghi"):
        goc = _dung_san_khau(tmp_path, deploy_sh=dot)
        _chay_deploy(goc, **_LUI, **{**_V6, "QLTS_HAN_KHOI_DONG": "30", "QLTS_TRAN_TRAP": "10"})
        assert _so_lan_goi(goc, "start", _cid_gia("backend")) >= 1, f"{ten_ca}: vẫn không start ⇒ ca không canh"
    elif ten_ca.startswith("W6:"):
        # Nguyên văn W6 in "0\n0" (nhánh dưới vẫn in phần còn lại) ⇒ GNU `timeout` từ chối hạn
        # nhiều dòng (rc 125) nên KHÔNG treo — lệnh đọc không chạy là nhờ tình cờ, không nhờ guard.
        # Thứ nó phá thật: hàm KHÔNG còn từ chối ⇒ người gọi vẫn gọi `timeout` với hạn rác.
        kq = _chay_han_con(tmp_path, "0", "docker", deploy_sh=dot)
        assert kq["timeout"], f"{ten_ca}: hết ngân sách mà vẫn KHÔNG gọi timeout ⇒ ca hợp đồng không canh `return 1`"
    elif ten_ca.startswith("W6b"):
        goc = _dung_san_khau(tmp_path, deploy_sh=dot)
        (_ca_6c_docker if "Docker" in ten_ca else _ca_6c_psql)(goc)
        tran, da = _thoi_gian_trap(goc, time.time())
        assert da > tran + 3, (
            f"{ten_ca}: trap vẫn dừng trong {da:.1f}s/{tran}s ⇒ ca đọc-SAU-khi-hết-ngân-sách không canh `timeout 0`")
    elif ten_ca.startswith("W5:"):
        goc = _dung_san_khau(tmp_path, deploy_sh=dot)
        _ca_6c_bien(goc)
        assert _so_lan_goi(goc, "start", _cid_gia("backend")) >= 1, (
            f"{ten_ca}: vẫn không start ⇒ ca biên [hạn, hạn+5) không canh đệm 5 s")
    else:
        goc = _dung_san_khau(tmp_path, deploy_sh=dot)
        ket, _ = _ca_ns_do_treo(goc)
        assert _DAU_HET_NS not in _ra(ket), f"{ten_ca}: vẫn in bản ngắn ⇒ ca không canh nhánh in ngắn"


# =============================================================================
# XIII. Vòng 6c (F46) — SAU khi ngân sách đã hết, lệnh đọc kế tiếp KHÔNG được chạy
# =============================================================================
# Kiểm độc lập của coordinator (14-10): các ca treo của 6b đều treo TRƯỚC khi hết ngân sách,
# nên không ca nào canh phép đọc ĐI SAU bước đã tiêu hết ngân sách — đúng chỗ `_dcg_han_con`
# phải TỪ CHỐI (trả 1) thay vì đưa 0 cho `timeout` (0 = TẮT hạn). Ở đây một bước Docker tiêu
# trọn ngân sách (hạn đọc 30 s > ngân sách 12 s ⇒ hạn thực = phần còn lại), rồi phép đọc KẾ
# TIẾP (Docker ở một ca, psql ở ca kia) TREO trong stub. Mỗi ca chỉ vi phạm MỘT bất biến.
_V6C = {**_V6, "QLTS_HAN_LENH_DOCKER": "30", "QLTS_TRAN_TRAP": "12"}
_TREO_6C = "25"   # giây stub treo — đúng: phép ấy KHÔNG chạy; `timeout 0`: chờ trọn


def _cac_loi_goi_va_cha(goc: Path) -> list[tuple[list[str], list[str]]]:
    """(argv lời gọi docker, argv tiến trình CHA) theo thứ tự — từ "$QLTS_STUB_LOG.cha"."""
    import base64

    def tach(b64: str) -> list[str]:
        tho = base64.b64decode(b64) if b64 else b""
        return [x.decode("utf-8", "replace") for x in tho.split(b"\0")[:-1]]

    ra = []
    for dong in (goc / "lenh.log.cha").read_text(encoding="utf-8").splitlines():
        a, _, c = dong.partition("\t")
        ra.append((tach(a), tach(c)))
    return ra


def _han_cua_cha(cha: list[str]) -> str | None:
    """Hạn mà `timeout` cha đặt cho lời gọi; None khi cha KHÔNG phải `timeout` (= không hạn)."""
    if not cha or Path(cha[0]).name != "timeout":
        return None
    i = 1
    while i < len(cha) and cha[i].startswith("-"):
        i += 2 if cha[i] in ("-k", "-s", "--kill-after", "--signal") else 1
    return cha[i] if i < len(cha) else ""


def _goi_khong_han_sau(goc: Path, moc: str) -> list[str]:
    """Lời gọi docker SAU lời gọi đầu tiên chứa `moc` mà KHÔNG chạy dưới `timeout <nguyên dương>`."""
    import re

    goi = _cac_loi_goi_va_cha(goc)
    vt = [i for i, (a, _) in enumerate(goi) if moc in " ".join(a)]
    assert vt, f"không thấy lời gọi chứa {moc!r} trong nhật ký tiến trình cha"
    xau = []
    for a, cha in goi[vt[0] + 1:]:
        h = _han_cua_cha(cha)
        if h is None or not re.fullmatch(r"[1-9][0-9]*", h):
            xau.append(f"hạn={h!r} · {' '.join(a)[:100]}")
    return xau


def _ca_6c_docker(goc: Path):
    # Sau `docker start` backend: mọi phép ĐỌC theo CID backend (inspect / ps --filter id=) TREO.
    # Phép inspect của bước đo-lại tiêu hết ngân sách; `_dcg_doc_ct` rồi hỏi `ps -a --filter id=`
    # — phép đọc Docker SAU khi hết ngân sách.
    cb = _cid_gia("backend")
    return _chay_deploy(goc, STUB_TREO_KHI=f"[ip]*{cb}*", STUB_TREO_SAU=f"docker start {cb}",
                        STUB_TREO_GIAY=_TREO_6C, **_LUI, **_V6C)


def _ca_6c_psql(goc: Path):
    # `docker start` backend hết hạn (2 s) rồi Docker KHÔNG đọc được backend (lỗi tức thì) ⇒ CHƯA
    # XÁC ĐỊNH ⇒ hướng dẫn ĐẦY ĐỦ khi còn ngân sách; trong đó phép đọc nginx TREO tiêu hết ngân
    # sách, rồi tới vân tay lược đồ (psql) — cũng TREO. Sau phép đọc nginx không còn phép Docker nào.
    cn = _cid_gia("nginx")
    return _chay_deploy(goc, STUB_GHI_TREO="start:backend", STUB_GHI_TREO_KIEU="khong_doc",
                        STUB_TREO_KHI=f"inspect -f {{{{.State.Status}}}} {cn}", STUB_TREO_SAU="docker start ",
                        STUB_PSQL_TREO_SAU="docker start ", STUB_TREO_GIAY=_TREO_6C, **_LUI, **_V6C)


@_bo_qua_neu_khong_posix
def test_v6c_doc_docker_sau_khi_het_ngan_sach_khong_chay_trap_dung_trong_ngan_sach(tmp_path: Path) -> None:
    import time

    goc = _dung_san_khau(tmp_path)
    _ca_6c_docker(goc)
    tran, da = _thoi_gian_trap(goc, time.time())
    tt = _tep_trang_thai(goc)
    assert tran == 12, f"ghi đè QLTS_TRAN_TRAP không hạ trần: {tran}"
    assert da >= tran - 3, (
        f"trap chỉ chạy {da:.1f}s/{tran}s — bước treo KHÔNG tiêu hết ngân sách ⇒ ca không canh phép đọc SAU")
    assert da <= tran + 3, (
        f"trap chạy {da:.1f}s — VƯỢT ngân sách {tran}s: phép đọc Docker SAU khi hết ngân sách vẫn chạy (không hạn)")
    xau = _goi_khong_han_sau(goc, "pg_dump")
    assert xau == [], "lời gọi docker trong trap chạy với hạn 0 / KHÔNG hạn:\n" + "\n".join(xau)
    assert "mo_lai_cu\tCHUA_XAC_DINH" in tt, tt
    assert _so_lan_goi(goc, "start", _cid_gia("backend")) == 1, "lệnh ghi bị CHẠY LẠI"
    assert sum(_so_lan_goi(goc, "start", _cid_gia(dv)) for dv in ("celery-worker", "celery-beat")) == 0, (
        "đo lại backend CHƯA XÁC ĐỊNH mà vẫn mở tiếp")


@_bo_qua_neu_khong_posix
def test_v6c_psql_sau_khi_het_ngan_sach_khong_chay_trap_dung_trong_ngan_sach(tmp_path: Path) -> None:
    import time

    goc = _dung_san_khau(tmp_path)
    ket, _ = _ca_6c_psql(goc)
    tran, da = _thoi_gian_trap(goc, time.time())
    ra, tt = _ra(ket), _tep_trang_thai(goc)
    assert tran == 12, f"ghi đè QLTS_TRAN_TRAP không hạ trần: {tran}"
    assert "vân tay lược đồ BÂY GIỜ: KHÔNG đo được" in ra, (
        "ca không tới phép vân tay (psql) của hướng dẫn ⇒ không canh psql SAU khi hết ngân sách:\n" + ra[-2000:])
    assert da >= tran - 3, (
        f"trap chỉ chạy {da:.1f}s/{tran}s — phép đọc nginx KHÔNG tiêu hết ngân sách ⇒ ca không canh psql SAU")
    assert da <= tran + 3, (
        f"trap chạy {da:.1f}s — VƯỢT ngân sách {tran}s: phép psql SAU khi hết ngân sách vẫn chạy (không hạn)")
    xau = _goi_khong_han_sau(goc, "pg_dump")
    assert xau == [], "lời gọi docker trong trap chạy với hạn 0 / KHÔNG hạn:\n" + "\n".join(xau)
    assert "mo_lai_cu\tCHUA_XAC_DINH" in tt, tt
    assert _so_lan_goi(goc, "start", _cid_gia("backend")) == 1, "lệnh ghi bị CHẠY LẠI"


# --- Hợp đồng của `_dcg_han_con` ở TẦNG chủ sở hữu (hàm thật của deploy.sh) ----------------
def _ham_cua(than: str, ten: str) -> str:
    import re

    m = re.search(rf"^{ten}\(\) \{{\n.*?^\}}\n", than, re.S | re.M)
    assert m, f"không thấy hàm {ten} trong deploy.sh"
    return m.group(0)


def _chay_han_con(thu_muc: Path, ngan_sach: str | None, lenh: str, deploy_sh: str | None = None) -> dict:
    """Chạy ĐÚNG `_dcg_con_lai` / `_dcg_han_con` / `_dcg_dk` / `_dcg_psql` của deploy.sh.

    ``ngan_sach``: số giây còn lại của trap (None = ngoài trap). `timeout` được bọc bằng một hàm
    shell ghi đối số rồi gọi `timeout` THẬT; `docker` giả ghi lời gọi. Trả rc của lời gọi, argv
    mọi lần gọi `timeout` và mọi lời gọi `docker`.
    """
    import base64
    import os
    import subprocess

    than = _DEPLOY.read_text(encoding="utf-8") if deploy_sh is None else deploy_sh
    bin_ = thu_muc / "bin"
    bin_.mkdir(parents=True, exist_ok=True)
    gia = bin_ / "docker"
    gia.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> \"$LOG_D\"\necho ok\n", encoding="utf-8")
    gia.chmod(0o755)
    lt, ld = thu_muc / "timeout.log", thu_muc / "docker.log"
    lt.write_text("", encoding="utf-8")
    ld.write_text("", encoding="utf-8")
    kich = (
        "set -u\n_DCG_HAN_LENH=10; _DCG_HAN_PSQL=60; _RA_COMPOSE='docker compose'\n"
        "timeout() { printf '%s\\0' \"$@\" | base64 -w0 >> \"$LOG_T\"; echo >> \"$LOG_T\"; command timeout \"$@\"; }\n"
        + "".join(_ham_cua(than, t) for t in ("_dcg_con_lai", "_dcg_han_con", "_dcg_dk", "_dcg_psql"))
        + ("_DCG_TRAP_HET=\n" if ngan_sach is None else f"_DCG_TRAP_HET=$((SECONDS + {ngan_sach}))\n")
        + ("_dcg_dk inspect x\n" if lenh == "docker" else "_dcg_psql 'SELECT 1'\n")
        + 'echo "rc=$?"\n'
    )
    ra = subprocess.run(
        ["bash", "-c", kich], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        env={**os.environ, "PATH": f"{bin_}:{os.environ.get('PATH', '')}", "LOG_T": str(lt), "LOG_D": str(ld)},
    )
    rc = [d for d in ra.stdout.splitlines() if d.startswith("rc=")]
    assert rc, ra.stdout + ra.stderr
    return {
        "rc": int(rc[-1][3:]),
        "timeout": [[x.decode("utf-8", "replace") for x in base64.b64decode(d).split(b"\0")[:-1]]
                    for d in lt.read_text(encoding="utf-8").splitlines() if d],
        "docker": ld.read_text(encoding="utf-8").splitlines(),
        "loi": ra.stderr,
    }


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize("lenh", ["docker", "psql"])
def test_v6c_het_ngan_sach_thi_khong_goi_timeout_khong_chay_lenh(tmp_path: Path, lenh: str) -> None:
    # Hết ngân sách ⇒ `_dcg_han_con` TỪ CHỐI (người gọi trả 124 = "không đọc được"), KHÔNG BAO GIỜ
    # đưa 0 (= TẮT hạn) hay bất cứ hạn nào cho `timeout`.
    kq = _chay_han_con(tmp_path, "0", lenh)
    assert kq["timeout"] == [], (
        f"hết ngân sách mà `{lenh}` VẪN gọi timeout với {kq['timeout']} — phải TỪ CHỐI, không chạy lệnh")
    assert kq["docker"] == [], f"hết ngân sách mà docker VẪN chạy: {kq['docker']}"
    assert kq["rc"] == 124, f"rc={kq['rc']} — hết ngân sách phải là 124 (`_dcg_het_han`):\n{kq['loi']}"


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize("lenh,han_rieng", [("docker", 10), ("psql", 60)])
def test_v6c_con_ngan_sach_thi_han_la_min_nguyen_duong(tmp_path: Path, lenh: str, han_rieng: int) -> None:
    import re

    for ten, ngan_sach, tran in (("trong trap, còn 7 s", "7", 7), ("ngoài trap", None, han_rieng)):
        kq = _chay_han_con(tmp_path / ("ngoai" if ngan_sach is None else "trong"), ngan_sach, lenh)
        assert kq["rc"] == 0 and len(kq["timeout"]) == 1 and len(kq["docker"]) == 1, f"{ten}: {kq}"
        h = _han_cua_cha(["timeout", *kq["timeout"][0]])
        assert h is not None and re.fullmatch(r"[1-9][0-9]*", h), f"{ten}: hạn {h!r} không phải số nguyên dương"
        assert tran - 1 <= int(h) <= tran, f"{ten}: hạn {h}s ≠ min(hạn riêng {han_rieng}s, phần còn lại)"


# --- Đệm 5 s của lệnh GHI: còn lại ∈ [hạn, hạn + 5) ⇒ KHÔNG bắt đầu (W5) -------------------
def _ca_6c_bien(goc: Path):
    # Hạn start 8 s, ngân sách 12 s: lúc tới `docker start` còn 8–12 s — ĐỦ cho hạn nhưng THIẾU
    # đệm 5 s cho ân hạn `-k 5` (cần ≥ 13) ⇒ không được bắt đầu.
    return _chay_deploy(goc, **_LUI, **{**_V6, "QLTS_HAN_KHOI_DONG": "8", "QLTS_TRAN_TRAP": "12"})


@_bo_qua_neu_khong_posix
def test_v6c_con_lai_giua_han_va_han_cong_5_thi_khong_bat_dau_lenh_ghi(tmp_path: Path) -> None:
    import re

    goc = _dung_san_khau(tmp_path)
    _ca_6c_bien(goc)
    tt = _tep_trang_thai(goc)
    assert sum(_so_lan_goi(goc, "start", _cid_gia(dv)) for dv in _DV_GHI) == 0, (
        "còn < hạn + 5 s mà vẫn BẮT ĐẦU `docker start` hạn 8 s — mất đệm cho ân hạn -k 5")
    m = re.search(r"het_ngan_sach\tmở_lại_·_backend_\(docker_start\) con=(\d+)s", tt)
    assert m, tt
    assert 8 <= int(m.group(1)) < 13, (
        f"còn {m.group(1)}s — ca KHÔNG rơi vào cửa sổ biên [8, 13) nên không canh đệm 5 s")
    assert "mo_lai_cu\tCHUA_XAC_DINH" in tt


# =============================================================================
# XIV. Vòng 7c — hạn cho lệnh CHƯA có hạn ở chỗ giết được an toàn
# =============================================================================
# `docker compose config` + `docker tag` (Step 3b, TRƯỚC build): hạn đọc; `docker stop`
# (4c): -t + hạn đọc + -k 5 — hết hạn ⇒ `error` ⇒ trap ĐO LẠI rồi mở lại, KHÔNG chạy lại
# `stop`. Mỗi ca một lệnh treo (stub giữ 30 s); hạn đọc 1 s ⇒ dừng ở vài giây.
_V7C = {**_NHANH, "QLTS_HAN_LENH_DOCKER": "1"}
_MAU_CONFIG = "compose * config --no-interpolate*"
_MAU_TAG = "tag *"


def _ca_7c(goc: Path, mau: str, treo: str = _TREO, **them):
    return _chay_deploy(goc, STUB_TREO_KHI=mau, STUB_TREO_GIAY=treo, **{**_V7C, **them})


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize("ten_ca,mau", [("compose config", _MAU_CONFIG), ("docker tag", _MAU_TAG)])
def test_v7c_lenh_3b_treo_thi_dung_truoc_build_trong_han(tmp_path: Path, ten_ca: str, mau: str) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nk = _ca_7c(goc, mau)
    t = _tu_luc_treo(goc)
    assert t < 20, f"{ten_ca} treo giữ deploy {t:.1f}s (hạn 1 s)"
    assert ket.returncode != 0, f"{ten_ca} treo mà deploy thoát 0"
    assert "build --parallel" not in nk, f"{ten_ca} treo mà vẫn build"
    assert not any(d.startswith("docker stop ") for d in _dong(nk)), f"{ten_ca} treo mà vẫn dừng container"


@_bo_qua_neu_khong_posix
def test_v7c_docker_stop_treo_thi_dung_trong_han_khong_chay_lai_va_mo_lai(tmp_path: Path) -> None:
    # celery-beat dừng ĐẦU TIÊN (-t 10) ⇒ hạn 10 + 1 + -k 5.
    cb = _cid_gia("celery-beat")
    goc = _dung_san_khau(tmp_path)
    ket, nk = _ca_7c(goc, f"stop -t * {cb}", treo="40")
    ra, t = _ra(ket), _tu_luc_treo(goc)
    assert t < 25, f"`docker stop` treo giữ deploy {t:.1f}s (hạn 11 s + -k 5)"
    assert "docker stop 'celery-beat' THẤT BẠI hoặc HẾT HẠN" in ra, ra[-2000:]
    assert _so_lan_goi(goc, "stop", cb) == 1, "lệnh `stop` bị CHẠY LẠI"
    assert not any(d.startswith("docker stop ") and d.endswith(_cid_gia("backend")) for d in _dong(nk)), (
        "stop của celery-beat chưa rõ mà vẫn dừng tiếp backend")
    assert _MOC_PGDUMP not in nk, "stop chưa rõ mà vẫn pg_dump"
    assert "rc=1 tin_hieu=- pha=dang_dong" in _tep_trang_thai(goc), "trap không chạy ở pha dang_dong"
    assert _so_lan_goi(goc, "start", cb) >= 1, "trap không mở lại container của lệnh stop chưa rõ"


@_bo_qua_neu_khong_posix
@pytest.mark.parametrize(
    "ten_ca,cu,moi,mau",
    [
        ("compose config: bỏ hạn",
         """    _json=$(timeout -k 2 "$_DCG_HAN_LENH" docker compose -f""", """    _json=$(docker compose -f""",
         _MAU_CONFIG),
        ("docker tag: bỏ hạn",
         """        timeout -k 2 "$_DCG_HAN_LENH" docker tag "$_RA_IMG\"""", """        docker tag "$_RA_IMG\"""", _MAU_TAG),
        ("docker stop: bỏ hạn",
         """        timeout -k 5 "$(( $(_dcg_han_dung "$_S") + _DCG_HAN_LENH ))" docker stop -t""",
         """        docker stop -t""", "stop -t * " + _cid_gia("celery-beat")),
    ],
)
def test_kiem_nguoc_v7c_go_tung_han(tmp_path: Path, ten_ca: str, cu: str, moi: str, mau: str) -> None:
    goc = _dung_san_khau(tmp_path, deploy_sh=_ban_dot_bien(cu, moi))
    _ca_7c(goc, mau, treo=_TREO_DOT_BIEN)
    assert _tu_luc_treo(goc) >= 20, f"{ten_ca}: vẫn xong nhanh ⇒ ca treo không canh hạn của lệnh này"
