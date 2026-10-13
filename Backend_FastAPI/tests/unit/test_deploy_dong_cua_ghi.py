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
def test_v3_oneoff_dang_chay_thi_khong_don(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    ket, nk = _chay_deploy(goc, STUB_ONEOFF="running", STUB_TIN_HIEU_O_MIGRATE="TERM", **_NHANH)
    assert not any(d.startswith("docker rm ") for d in _dong(nk)), "dọn one-off ĐANG CHẠY"
    assert "KHÔNG dọn (chỉ dọn khi exited)" in _ra(ket), _ra(ket)[-2000:]


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
        "        dang_dong|da_dong)\n",
        f"        dang_dong|da_dong|{pha})\n",
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
        '        if ! docker start "${_DCG_CID[$s]}" >/dev/null; then\n',
        '        if ! $_RA_COMPOSE up -d "$s" >/dev/null; then\n',
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
        '        docker stop -t "$(_dcg_han_dung "$_S")" "${_DCG_CID[$_S]}" >/dev/null \\\n',
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
    dau = than.index('    ip=$(_dcg_ip "${_DCG_CID[backend]}" 2>/dev/null || true)\n')
    cuoi_neo = '        _cho_healthy_dv nginx "$_HAN_HEALTH"\n    fi\n'
    cuoi = than.index(cuoi_neo, dau) + len(cuoi_neo)
    than = than[:dau] + than[cuoi:]
    goc = _dung_san_khau(tmp_path, deploy_sh=than)
    _, nk = _chay_deploy(goc, STUB_IP_DOI="1", **_LUI, **_NHANH)
    assert _start_cua_deploy(nk)
    assert _lenh_restart_nginx(nk) == [], "gỡ khởi động lại nginx mà vẫn restart ⇒ ca IP-đổi xanh vì lý do khác"


@_bo_qua_neu_khong_posix
def test_kiem_nguoc_bo_do_dich_vu_thi_bao_mo_du_502(tmp_path: Path) -> None:
    dot_bien = _ban_dot_bien("    _dcg_do_dich_vu_nginx || return 1\n", "")
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
    _, nk = _chay_deploy(goc, STUB_ONEOFF="running", STUB_TIN_HIEU_O_MIGRATE="TERM", **_NHANH)
    assert f"docker rm {_OO}" in _dong(nk), "bỏ điều kiện exited mà one-off đang chạy còn ⇒ ca 'đang chạy' không canh gì"


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
