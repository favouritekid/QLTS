"""Cong ghi nguyen tu cua scripts/deploy.sh — hai writer, cung mot lop loi.

Truoc ban va, CA HAI writer dat ten tep tam theo PID (doan duoc) roi cat trang.
Mot dangling symlink dat san o dung duong do lam phep kiem ton tai tra FALSE —
vi no THEO symlink — nen cong di qua, va lenh cat trang GHI XUYEN symlink ra
NGOAI thu muc dich voi quyen root.

mktemp dong ca hai ve: O_EXCL|O_CREAT nen khong theo symlink, khong ghi de, va
ten khong doan duoc.

Moi ca duoi day vi pham DUNG MOT bat bien, va phai do voi DUNG thong bao cua
cong tuong ung — exit code khac 0 mot minh khong chung minh duoc nhanh nao chay.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from tests.unit.test_deploy_startup_gates import (
    _SHA_MOI,
    _chay_deploy,
    _dung_san_khau,
    _tim_goc,
)

_DEPLOY = _tim_goc() / "scripts" / "deploy.sh"
_NL = chr(10)
_BS = chr(92)
_TAB = chr(9)


def _ban_va(thay):
    """Noi dung deploy.sh voi cac phep thay the da ap — dung cho mutation."""
    than = _DEPLOY.read_text(encoding="utf-8")
    for cu, moi in thay:
        assert than.count(cu) == 1, "mutation khong khop duy nhat"
        than = than.replace(cu, moi)
    return than


def _viet_stub(p: Path, dong):
    p.write_text(_NL.join(dong) + _NL, encoding="utf-8", newline=_NL)
    p.chmod(0o755)


def _stub_mktemp(goc: Path, kieu: str, muc_tieu: str) -> None:
    """mktemp gia, chi can thiep DUNG MOT writer.

    muc_tieu: "manifest" (mau .manifest.*) hoac "marker" (.last-deploy.*).
    Writer con lai van goi mktemp that, nen ca kiem khong troi sang nhanh khac.
    """
    mau = ".manifest." if muc_tieu == "manifest" else ".last-deploy."
    d = ["#!/usr/bin/env bash",
         'ARG="${@: -1}"',
         'case "$ARG" in',
         '  *' + mau + '*) ;;',
         '  *) exec /usr/bin/mktemp "$@" ;;',
         "esac",
         'D=$(dirname -- "$ARG")']
    if kieu == "rc_khac_0":
        d += ['echo "mktemp gia: loi" >&2', "exit 7"]
    elif kieu == "rong":
        d += ['echo ""', "exit 0"]
    elif kieu == "ngoai_thu_muc":
        d += ['T="$D/../ngoai_pham_vi.tmp"', ': > "$T"', 'chmod 600 "$T"',
              'echo "$T"', "exit 0"]
    elif kieu == "symlink":
        d += ['T="$D/' + mau + 'SYM"', 'rm -f "$T"',
              'ln -s "$D/khong_ton_tai_nan_nhan" "$T"', 'echo "$T"', "exit 0"]
    elif kieu == "non_regular":
        d += ['T="$D/' + mau + 'FIFO"', 'rm -f "$T"', 'mkfifo "$T"',
              'echo "$T"', "exit 0"]
    elif kieu == "sai_mode":
        d += ['T=$(/usr/bin/mktemp "$ARG")', 'chmod 644 "$T"', 'echo "$T"', "exit 0"]
    elif kieu == "size_khac_0":
        d += ['T=$(/usr/bin/mktemp "$ARG")', 'printf X >> "$T"', 'echo "$T"', "exit 0"]
    elif kieu == "links_hon_1":
        d += ['T=$(/usr/bin/mktemp "$ARG")', 'ln "$T" "$T.themlink"',
              'echo "$T"', "exit 0"]
    else:
        raise AssertionError("kieu la: " + kieu)
    _viet_stub(goc / "bin" / "mktemp", d)


def _do(goc: Path, **kb):
    ket, _ = _chay_deploy(goc, **kb)
    return ket.returncode, ket.stdout


# ===========================================================================
# 1. Duong thuan loi — tao du tai san + marker, KHONG de lai tep tam
# ===========================================================================
def test_aw_duong_thuan_loi_khong_de_lai_tep_tam(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    rc, out = _do(goc)
    assert rc == 0, out
    ops = goc / "ops"
    assert (ops / "last-deploy.marker").is_file()
    ban_ke = sorted(ops.glob("pre-*/rollback_manifest_*.txt"))
    assert len(ban_ke) == 1, "ban ke: " + str(ban_ke)
    con_lai = [p.name for p in ops.rglob("*")
               if p.name.startswith(".manifest.")
               or p.name.startswith(".last-deploy.")]
    assert con_lai == [], "con tep tam: " + str(con_lai)


# ===========================================================================
# 2. Cong $OPS — moi ca mot bat bien
# ===========================================================================
def test_aw_ops_la_symlink_thi_dung(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    that = tmp_path / "ops_that"
    (goc / "ops").rename(that)
    (goc / "ops").symlink_to(that, target_is_directory=True)
    rc, out = _do(goc)
    assert rc != 0
    assert "SYMLINK" in out, out


def test_aw_ops_dangling_symlink_thi_dung(tmp_path: Path) -> None:
    """Dangling symlink o $OPS: deploy phai DUNG va KHONG ghi xuyen ra ngoai.

    Ghi chu do duoc: trong kich ban nay reader marker cua Step 3b dung TRUOC
    cong -L (vi $OPS tro vao hu khong nen khong co marker). Bat bien can khoa
    la "chan + khong ghi xuyen", khong phai "dung o cong nao" — mot phep kiem
    ghim vao thong bao cu the se do oan khi thu tu cong doi.
    """
    goc = _dung_san_khau(tmp_path, marker=None)
    shutil.rmtree(goc / "ops")
    nan_nhan = tmp_path / "khong_bao_gio_ton_tai"
    (goc / "ops").symlink_to(nan_nhan, target_is_directory=True)
    rc, out = _do(goc)
    assert rc != 0, out
    assert not nan_nhan.exists(), "da ghi xuyen symlink ra ngoai"



def test_aw_ops_sai_mode_thi_dung(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    os.chmod(goc / "ops", 0o755)
    rc, out = _do(goc)
    assert rc != 0
    assert ("sai quyen" in out) or ("sai quy" in out), out


def test_aw_ops_khong_ton_tai_thi_dung(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path, marker=None)
    shutil.rmtree(goc / "ops")
    rc, out = _do(goc)
    assert rc != 0
    assert ("KHONG ton tai" in out) or ("KH" in out and "ti" in out), out


# ===========================================================================
# 3. mktemp — tam cach hong, chay RIENG cho tung writer
# ===========================================================================
_KIEU_MOC = [
    ("rc_khac_0", "nguyên tử"),
    ("rong", "RONG"),
    ("ngoai_thu_muc", "NGOÀI"),
    ("symlink", "SYMLINK"),
    ("non_regular", "regular file"),
    ("sai_mode", "600 root:root 0 1"),
    ("size_khac_0", "600 root:root 0 1"),
    ("links_hon_1", "600 root:root 0 1"),
]


@pytest.mark.parametrize("kieu,moc", _KIEU_MOC)
@pytest.mark.parametrize("muc_tieu", ["manifest", "marker"])
def test_aw_mktemp_hong_thi_dung(tmp_path, muc_tieu, kieu, moc) -> None:
    goc = _dung_san_khau(tmp_path)
    _stub_mktemp(goc, kieu, muc_tieu)
    rc, out = _do(goc)
    assert rc != 0, out
    assert moc in out, "kieu=" + kieu + " muc_tieu=" + muc_tieu + " out=" + out[-400:]


# ===========================================================================
# 4. Cong bo manifest — no-clobber
# ===========================================================================
def test_aw_manifest_dich_chen_ngang_thi_khong_ghi_de(tmp_path: Path) -> None:
    """FINAL xuat hien ngay truoc khi cong bo => ln do, noi dung chen nguyen."""
    goc = _dung_san_khau(tmp_path)
    _viet_stub(goc / "scripts" / "rollback-preflight.sh", [
        "#!/usr/bin/env bash",
        'M="${QLTS_ROLLBACK_MANIFEST:-}"',
        'D=$(dirname -- "$M")',
        'F="$D/rollback_manifest_${QLTS_ROLLBACK_TAG}.txt"',
        'echo "CHEN NGANG" > "$F"',
        "exit 0",
    ])
    rc, out = _do(goc)
    assert rc != 0, out
    xam_pham = sorted((goc / "ops").glob("pre-*/rollback_manifest_*.txt"))
    assert len(xam_pham) == 1, str(xam_pham)
    assert xam_pham[0].read_text(encoding="utf-8") == "CHEN NGANG" + _NL, "da ghi de"


# ===========================================================================
# 5. Marker — dich la THU MUC
# ===========================================================================
def test_aw_marker_dich_la_thu_muc_thi_dung(tmp_path: Path) -> None:
    """mv src dst tran se CHUYEN VAO TRONG va tra 0 — thanh cong gia."""
    goc = _dung_san_khau(tmp_path, marker=None)
    (goc / "ops" / "last-deploy.marker").mkdir()
    rc, out = _do(goc)
    assert rc != 0, out
    tm = goc / "ops" / "last-deploy.marker"
    assert tm.is_dir(), "dich khong con la thu muc"
    ben_trong = list(tm.iterdir())
    assert ben_trong == [], "da move TMP vao trong: " + str(ben_trong)


# ===========================================================================
# 6. Loi o Step 8c => marker CU byte-identical
# ===========================================================================
def test_aw_loi_8c_giu_marker_cu_byte_identical(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    mk = goc / "ops" / "last-deploy.marker"
    truoc = mk.read_bytes()
    _stub_mktemp(goc, "symlink", "marker")
    rc, out = _do(goc)
    assert rc != 0, out
    assert mk.read_bytes() == truoc, "marker cu da bi doi"


# ===========================================================================
# 7. Cong $OPS — vector OWNER (mode va owner la hai bat bien khac nhau)
# ===========================================================================
def test_aw_ops_sai_owner_thi_dung_truoc_moi_ghi(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    os.chown(goc / "ops", 65534, 65534)
    rc, out = _do(goc)
    assert rc != 0, out
    # Chan TRUOC docker tag / TMP / build: khong co thu muc tai san nao sinh ra
    assert sorted((goc / "ops").glob("pre-*")) == [], "da tao thu muc tai san"
    nhat_ky = (goc / "lenh.log").read_text(encoding="utf-8") if (goc / "lenh.log").exists() else ""
    assert "docker tag" not in nhat_ky, "da chay docker tag truoc khi dung"


# ===========================================================================
# 8. KIEM NGUOC — moi mutation phai doi mau DUNG hien vat, khong chi thong bao
# ===========================================================================
def _ops_tro_ra_ngoai(tmp_path: Path, goc: Path) -> Path:
    """Bien $OPS thanh symlink tro toi mot directory THAT 700 root:root.

    Dung directory that (khong phai dangling) de reader marker di qua duoc,
    nho do cong -L moi that su la thu dang chan.
    """
    ngoai = tmp_path / "ops_ngoai_pham_vi"
    (goc / "ops").rename(ngoai)
    os.chmod(ngoai, 0o700)
    (goc / "ops").symlink_to(ngoai, target_is_directory=True)
    return ngoai


def test_aw_ops_symlink_toi_dir_that_thi_chan_truoc_moi_ghi(tmp_path: Path) -> None:
    """Nen: $OPS la symlink toi dir that => chan, KHONG ghi gi vao dir ngoai."""
    goc = _dung_san_khau(tmp_path)
    ngoai = _ops_tro_ra_ngoai(tmp_path, goc)
    truoc = sorted(p.name for p in ngoai.iterdir())
    rc, out = _do(goc)
    assert rc != 0, out
    sau = sorted(p.name for p in ngoai.iterdir())
    assert sau == truoc, "da tao hien vat trong thu muc ngoai: " + str(set(sau) - set(truoc))


# KHOANG TRONG DA BIET — khong co mutation nao o day, va do la co y.
#
# Toi KHONG dung duoc mot mutation chung minh cong `-L` cua $OPS la doc lap
# can thiet. Ly do do duoc: `stat -c %a` KHONG di theo symlink, nen mot symlink
# luon bao mode 777 va bi cong mode chan truoc. Go rieng `-L` => van do o cong
# mode; go CA HAI (`-L` + doi sang `stat -L`) => deploy VAN dung, va toi chua
# xac dinh duoc cong nao chan (het ngan sach dieu tra trong luot nay).
#
# Nghia la: `-L` hien la PHONG THU THEO CHIEU SAU, tinh doc lap CHUA duoc chung
# minh. Dung doc ca `test_aw_ops_symlink_toi_dir_that_thi_chan_truoc_moi_ghi`
# (dang xanh) thanh "cong -L dang ganh" — no chi chung minh "bi chan va khong
# ghi ra ngoai", khong chi ra lop nao chan.


# --- TMP doan duoc: tai hien GHI XUYEN symlink ra nan nhan ngoai thu muc ---
def _mutation_tmp_doan_duoc(muc_tieu: str) -> tuple[str, str]:
    """Doi writer ve dung ten TMP BIET TRUOC + cat trang, nhu ban goc."""
    than = _DEPLOY.read_text(encoding="utf-8")
    if muc_tieu == "manifest":
        neo = '    _RA_TMP=$(mktemp "$_RA_DIR/.manifest.XXXXXXXXXX")'
        bien, ten = "_RA_TMP", ".manifest.DOAN_DUOC"
        thu_muc = '"$_RA_DIR"'
        thut = "    "
    else:
        neo = '_RA_MK_TMP=$(mktemp "$_RA_OPS/.last-deploy.XXXXXXXXXX")'
        bien, ten = "_RA_MK_TMP", ".last-deploy.DOAN_DUOC"
        thu_muc = '"$_RA_OPS"'
        thut = ""
    assert than.count(neo) == 1
    i = than.index(neo)
    j = than.index("_ra_kiem_tmp", i)
    k = than.index(_NL, j)
    cu = (thut + bien + "=" + thu_muc[:-1] + "/" + ten + '"' + _NL
          + thut + ': > "$' + bien + '"' + _NL
          + thut + 'chmod 600 "$' + bien + '"')
    return than[:i] + cu + than[k:], ten


@pytest.mark.parametrize("muc_tieu", ["manifest", "marker"])
def test_kiem_nguoc_tmp_doan_duoc_ghi_xuyen_symlink(tmp_path: Path, muc_tieu: str) -> None:
    """Ten TMP biet truoc + cat trang => GHI XUYEN dangling symlink ra nan nhan.

    Day moi la bang chung cua lop loi. Viec shim mktemp khong con duoc goi chi
    la bang chung phu.
    """
    moi, ten_tmp = _mutation_tmp_doan_duoc(muc_tieu)
    goc = _dung_san_khau(tmp_path, deploy_sh=moi)
    nan_nhan = tmp_path / ("nan_nhan_" + muc_tieu)
    assert not nan_nhan.exists()
    if muc_tieu == "marker":
        (goc / "ops" / ten_tmp).symlink_to(nan_nhan)
    else:
        # Thu muc tai san do chinh script tao; dat symlink bang mot shim mkdir
        # chay ngay sau khi thu muc ra doi.
        _viet_stub(goc / "bin" / "mkdir", [
            "#!/usr/bin/env bash",
            '/bin/mkdir "$@" || exit $?',
            'D="${@: -1}"',
            'case "$D" in',
            '  *' + "/pre-" + '*) ln -s "' + str(nan_nhan) + '" "$D/' + ten_tmp + '" ;;',
            "esac",
            "exit 0",
        ])
    _do(goc)
    assert nan_nhan.exists(), (
        "khoi phuc ten TMP doan duoc ma KHONG ghi xuyen symlink => ca kiem "
        "khong tai hien duoc lop loi")


@pytest.mark.parametrize("muc_tieu", ["manifest", "marker"])
def test_aw_ban_va_khong_ghi_xuyen_symlink(tmp_path: Path, muc_tieu: str) -> None:
    """Nen: voi mktemp, cung kich ban tren KHONG cham toi nan nhan."""
    goc = _dung_san_khau(tmp_path)
    ten_tmp = ".manifest.DOAN_DUOC" if muc_tieu == "manifest" else ".last-deploy.DOAN_DUOC"
    nan_nhan = tmp_path / ("nan_nhan_sach_" + muc_tieu)
    if muc_tieu == "marker":
        (goc / "ops" / ten_tmp).symlink_to(nan_nhan)
    else:
        _viet_stub(goc / "bin" / "mkdir", [
            "#!/usr/bin/env bash",
            '/bin/mkdir "$@" || exit $?',
            'D="${@: -1}"',
            'case "$D" in',
            '  *' + "/pre-" + '*) ln -s "' + str(nan_nhan) + '" "$D/' + ten_tmp + '" ;;',
            "esac",
            "exit 0",
        ])
    _do(goc)
    assert not nan_nhan.exists(), "mktemp van ghi xuyen symlink"


# --- no-clobber manifest: dich xuat hien SAU tien kiem, ngay truoc ln ---
def _stub_stat_tao_final(goc: Path) -> None:
    """stat gia: lan `-c %d:%i` dau tien tren TMP manifest thi TAO san FINAL.

    Do la lenh ngoai cuoi cung truoc `ln`, nen moi tien kiem da chay xong tren
    mot dich chua ton tai. Sau diem nay chi con `ln` dung giua.
    """
    _viet_stub(goc / "bin" / "stat", [
        "#!/usr/bin/env bash",
        'ARG="${@: -1}"',
        'if [ "${1:-}" = "-c" ] && [ "${2:-}" = "%d:%i" ]; then',
        '  case "$ARG" in',
        '    *.manifest.*)',
        '      D=$(dirname -- "$ARG")',
        '      F="$D/rollback_manifest_$(basename -- "$D").txt"',
        '      [ -e "$F" ] || echo "CHEN NGANG" > "$F" ;;',
        "  esac",
        "fi",
        'exec /usr/bin/stat "$@"',
    ])


def test_aw_final_chen_ngang_ngay_truoc_ln_thi_ln_chan(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    _stub_stat_tao_final(goc)
    rc, out = _do(goc)
    assert rc != 0, out
    xam = sorted((goc / "ops").glob("pre-*/rollback_manifest_*.txt"))
    assert len(xam) == 1, str(xam)
    assert xam[0].read_text(encoding="utf-8") == "CHEN NGANG" + _NL, "ln da ghi de"


def test_kiem_nguoc_ln_thanh_mv_T_thi_ghi_de_nan_nhan(tmp_path: Path) -> None:
    """Doi `ln` thanh phep cong bo GHI DE => noi dung nan nhan bi thay."""
    moi = _ban_va([('    ln "$_RA_TMP" "$_RA_MANIFEST"',
                    '    mv -T -- "$_RA_TMP" "$_RA_MANIFEST"')])
    goc = _dung_san_khau(tmp_path, deploy_sh=moi)
    _stub_stat_tao_final(goc)
    _do(goc)
    xam = sorted((goc / "ops").glob("pre-*/rollback_manifest_*.txt"))
    noi_dung = xam[0].read_text(encoding="utf-8") if xam else ""
    assert noi_dung != "CHEN NGANG" + _NL, (
        "mv -T KHONG ghi de => ca nen khong chung minh duoc `ln` dang ganh")


def test_bo_sung_go_tien_kiem_dich_da_ton_tai(tmp_path: Path) -> None:
    """Bo sung (KHONG phai mutation cua lop no-clobber): go tien kiem -e/-L.

    `ln` van phai tu chan va giu nguyen noi dung nan nhan.
    """
    moi = _ban_va([(
        '    [ -L "$_RA_MANIFEST" ] && error "bản kê đích là SYMLINK — từ chối."',
        '    :')])
    moi = moi.replace(
        '    [ -e "$_RA_MANIFEST" ] && error "bản kê đích xuất hiện trước khi công bố — từ chối ghi đè."',
        '    :')
    goc = _dung_san_khau(tmp_path, deploy_sh=moi)
    _viet_stub(goc / "scripts" / "rollback-preflight.sh", [
        "#!/usr/bin/env bash",
        'M="${QLTS_ROLLBACK_MANIFEST:-}"',
        'D=$(dirname -- "$M")',
        'F="$D/rollback_manifest_${QLTS_ROLLBACK_TAG}.txt"',
        'echo "CHEN NGANG" > "$F"',
        "exit 0",
    ])
    rc, out = _do(goc)
    assert rc != 0, out
    xam = sorted((goc / "ops").glob("pre-*/rollback_manifest_*.txt"))
    assert xam[0].read_text(encoding="utf-8") == "CHEN NGANG" + _NL, "ln da ghi de"


# --- niem phong manifest: doi mot byte SAU preflight ---
def test_aw_doi_byte_manifest_sau_preflight_thi_do_truoc_cong_bo(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    _viet_stub(goc / "scripts" / "rollback-preflight.sh", [
        "#!/usr/bin/env bash",
        'printf X >> "${QLTS_ROLLBACK_MANIFEST:?}"',
        "exit 0",
    ])
    rc, out = _do(goc)
    assert rc != 0, out
    assert "HASH" in out, out
    xam = sorted((goc / "ops").glob("pre-*/rollback_manifest_*.txt"))
    assert xam == [], "ban ke chinh thuc da xuat hien du hash lech: " + str(xam)


def test_kiem_nguoc_go_niem_phong_manifest(tmp_path: Path) -> None:
    """Go phep so hash sau preflight => byte doi van duoc cong bo.

    Ca bon diem deu qua `_ban_va` (co assert khop duy nhat): mot chuoi moc
    lac hau se lam ca kiem DO thay vi im lang bo qua phep thay the.
    """
    moi = _ban_va([
        ('    _ra_kiem_hash_pf "sau-preflight" "$_RA_TMP"', '    :'),
        ('    _ra_kiem_hash_pf "truoc-ln" "$_RA_TMP"', '    :'),
        ('    _ra_kiem_hash_sau_ln "sau-ln-tren-FINAL" "$_RA_MANIFEST" "$_RA_FD" "$_RA_INO_T"',
         '    :'),
        ('    _ra_kiem_hash_sau_ln "sau-bo-TMP" "$_RA_MANIFEST" "$_RA_FD" "$_RA_INO_T"',
         '    :'),
    ])
    goc = _dung_san_khau(tmp_path, deploy_sh=moi)
    _viet_stub(goc / "scripts" / "rollback-preflight.sh", [
        "#!/usr/bin/env bash",
        'printf X >> "${QLTS_ROLLBACK_MANIFEST:?}"',
        "exit 0",
    ])
    _do(goc)
    xam = sorted((goc / "ops").glob("pre-*/rollback_manifest_*.txt"))
    assert xam != [], "go niem phong ma van khong cong bo => ca nen khong canh dung"


# --- marker: deployed-sha hop le nhung KHAC HEAD ---
def test_aw_deployed_sha_khac_head_thi_do_truoc_mv(tmp_path: Path) -> None:
    gia = "0" * 40
    moi = _ban_va([("printf '# deployed-sha" + chr(92) + "t%s" + chr(92) + "n' \"$_RA_SHA_MOI\"",
                    "printf '# deployed-sha" + chr(92) + "t%s" + chr(92) + "n' \"" + gia + "\"")])
    goc = _dung_san_khau(tmp_path, deploy_sh=moi)
    mk = goc / "ops" / "last-deploy.marker"
    truoc = mk.read_bytes()
    rc, out = _do(goc)
    assert rc != 0, out
    assert "KHÁC HEAD" in out or "KHAC HEAD" in out, out
    assert mk.read_bytes() == truoc, "marker cu bi doi du do truoc mv"


# --- marker: race dich thanh thu muc NGAY TRUOC mv (sau moi checkpoint) ---
def _stub_mv_bien_dich_thanh_thu_muc(goc: Path) -> None:
    _viet_stub(goc / "bin" / "mv", [
        "#!/usr/bin/env bash",
        'DICH="${@: -1}"',
        'case "$DICH" in',
        '  */last-deploy.marker)',
        '    rm -rf -- "$DICH"',
        '    /bin/mkdir -p -- "$DICH" ;;',
        "esac",
        'exec /bin/mv "$@"',
    ])


def test_aw_race_dich_thanh_thu_muc_ngay_truoc_mv(tmp_path: Path) -> None:
    """Dich thanh thu muc SAU moi checkpoint => `mv -T` phai do, khong move vao."""
    goc = _dung_san_khau(tmp_path)
    _stub_mv_bien_dich_thanh_thu_muc(goc)
    rc, out = _do(goc)
    assert rc != 0, out
    tm = goc / "ops" / "last-deploy.marker"
    ben_trong = [p.name for p in tm.iterdir()] if tm.is_dir() else []
    assert ben_trong == [], "da move TMP vao trong thu muc: " + str(ben_trong)


def test_kiem_nguoc_mv_T_thanh_mv_tran(tmp_path: Path) -> None:
    """`mv` tran => TMP bi CHUYEN VAO TRONG thu muc, va lenh tra 0."""
    moi = _ban_va([('mv -T -- "$_RA_MK_TMP" "$_RA_MARKER"',
                    'mv -- "$_RA_MK_TMP" "$_RA_MARKER"')])
    goc = _dung_san_khau(tmp_path, deploy_sh=moi)
    _stub_mv_bien_dich_thanh_thu_muc(goc)
    _do(goc)
    tm = goc / "ops" / "last-deploy.marker"
    ben_trong = [p.name for p in tm.iterdir()] if tm.is_dir() else []
    assert ben_trong != [], "mv tran KHONG move vao trong => ca nen khong chung minh `mv -T`"


# --- marker cu bi doi giua chung ---
def _stub_tr_doi_marker_cu(goc: Path) -> None:
    """tr gia: lan dau chay (trong kiem schema TMP) thi DOI marker cu.

    Diem nay nam SAU khi da niem phong hash/inode marker cu o dau Step 8c va
    TRUOC checkpoint ngay truoc `mv`.
    """
    _viet_stub(goc / "bin" / "tr", [
        "#!/usr/bin/env bash",
        'OPS="${QLTS_ROLLBACK_OPS_DIR:?}"',
        'CO="$OPS/.da_doi_marker"',
        'M="$OPS/last-deploy.marker"',
        'if [ ! -e "$CO" ] && [ -f "$M" ]; then',
        '  : > "$CO"',
        '  printf "DA BI THAY" >> "$M"',
        "fi",
        'exec /usr/bin/tr "$@"',
    ])


def test_aw_marker_cu_doi_giua_chung_thi_do(tmp_path: Path) -> None:
    goc = _dung_san_khau(tmp_path)
    mk = goc / "ops" / "last-deploy.marker"
    _stub_tr_doi_marker_cu(goc)
    rc, out = _do(goc)
    assert rc != 0, out
    assert "ĐỔI nội dung" in out, out
    # Doi chieu voi ca kiem nguoc ngay duoi: o day thay doi canh tranh phai CON
    # NGUYEN tren dia — nghia la `mv` chua chay, khong phai da chay roi bao do.
    assert "DA BI THAY" in mk.read_text(encoding="utf-8"), (
        "marker cu khong con dau vet thay doi => ca kiem dang noi ve chuyen khac")


def test_kiem_nguoc_go_checkpoint_hash_marker_cu(tmp_path: Path) -> None:
    """Go phep so hash marker cu => deploy RA 0 va thay doi canh tranh MAT.

    Chi doi "khong con thong bao" la ca kiem yeu: mot dot bien lam script chet
    som vi ly do khac cung lam thong bao bien mat. Nen o day doi du ba dieu:
    rc=0 (khong con cong nao chan), marker cuoi cung KHONG con dau vet thay doi
    canh tranh (tuc no da bi GHI DE that), va dung la ban MOI da duoc cong bo.
    """
    moi = _ban_va([(
        '[ "$_RA_MK_H3" = "$_RA_MK_CU_HASH" ]',
        '[ "1" = "1" ]')])
    goc = _dung_san_khau(tmp_path, deploy_sh=moi)
    mk = goc / "ops" / "last-deploy.marker"
    _stub_tr_doi_marker_cu(goc)
    rc, out = _do(goc)
    assert rc == 0, "go guard ma van chan => ca nen khong canh dung:" + _NL + out
    assert "ĐỔI nội dung" not in out, "van bat duoc du da go phep so hash"
    than = mk.read_text(encoding="utf-8")
    assert "DA BI THAY" not in than, (
        "thay doi canh tranh van con tren dia => chua chung minh duoc viec ghi de")
    assert "# deployed-sha" + _TAB + _SHA_MOI in than, than

# ===========================================================================
# 9. Thu tu lenh quanh diem cong bo — "gan nhat" chua phai "cuoi cung"
# ===========================================================================
# Mot phep so dat DUNG cho nhung KHONG phai lenh ngoai cuoi cung truoc thao tac
# cong bo la mot cai cong canh hut: bat cu lenh ngoai nao chen giua no va thao
# tac cong bo deu co the sinh ra dung thu no dang canh, va luc ay do bi phat
# hien SAU khi da cong bo.
#
# RC=1 di kem mot tep SAI mang TEN CHINH THUC con te hon RC=1 khong co gi — su
# ton tai cua ten do chinh la bang chung "da qua preflight" cho luot sau.
#
# KHE CON LAI, DA BIET, CHUA DONG:
# Ngay ca khi phep so hash la lenh ngoai CUOI, ban than lenh ay van la mot
# tien trinh ngoai — mot thay doi sinh ra BEN TRONG chinh no (giua luc doc va
# luc tra ve) thi khong phep so nao con chay sau de bat. Voi manifest, khe do
# duoc dong o phia SAU bang fail-secure: `_ra_loi_sau_ln` GO ban ke da cong bo
# khi hash lech (ca `test_aw_ban_ke_ban_sau_ln_thi_bi_go_khoi_ten_chinh_thuc`).
# Voi marker thi KHONG co doi xung: `mv` ghi de, ban cu khong con de khoi phuc,
# nen khe tuong duong o checkpoint marker cu VAN MO. Dung doc cac ca duoi day
# thanh "da dong het race" — chung chi chung minh thu tu dang ganh.

_BAM_TMP = ("_RA_MK_HASH=$(sha256sum " + chr(34) + "$_RA_MK_TMP" + chr(34)
            + " | awk " + chr(39) + "{print $1}" + chr(39) + ")")
_MV_T = 'mv -T -- "$_RA_MK_TMP" "$_RA_MARKER"'

_THU_TU_DUNG = _NL.join([
    "    _RA_INO_T=$(stat -c " + chr(39) + "%d:%i" + chr(39) + ' "$_RA_TMP")',
    '    _ra_kiem_hash_pf "truoc-ln" "$_RA_TMP"',
])
_THU_TU_CU = _NL.join([
    '    _ra_kiem_hash_pf "truoc-ln" "$_RA_TMP"',
    "    _RA_INO_T=$(stat -c " + chr(39) + "%d:%i" + chr(39) + ' "$_RA_TMP")',
])


def _stub_stat_doi_tmp(goc: Path) -> None:
    """stat gia: lan `-c %d:%i` tren TMP manifest thi DOI chinh TMP do.

    Do la lenh ngoai NGAY TRUOC `ln`. Hash phai chay SAU no, neu khong thi thay
    doi nay chi bi bat khi ban ke ban da mang ten chinh thuc.
    """
    _viet_stub(goc / "bin" / "stat", [
        "#!/usr/bin/env bash",
        'ARG="${@: -1}"',
        'if [ "${1:-}" = "-c" ] && [ "${2:-}" = "%d:%i" ]; then',
        '  case "$ARG" in',
        '    *.manifest.*) printf X >> "$ARG" ;;',
        "  esac",
        "fi",
        'exec /usr/bin/stat "$@"',
    ])


def test_aw_tmp_doi_trong_chinh_lenh_stat_thi_do_truoc_cong_bo(tmp_path: Path) -> None:
    """Hash la lenh ngoai CUOI truoc `ln` => bat duoc TRUOC khi cong bo."""
    goc = _dung_san_khau(tmp_path)
    _stub_stat_doi_tmp(goc)
    rc, out = _do(goc)
    assert rc != 0, out
    assert "truoc-ln" in out, out
    assert "sau-ln-tren-FINAL" not in out, (
        "bi bat SAU `ln` => `ln` da chay, tuc ban ke ban da tung mang ten "
        "chinh thuc:" + _NL + out)
    xam = sorted((goc / "ops").glob("pre-*/rollback_manifest_*.txt"))
    assert xam == [], "RC=1 ma ban ke chinh thuc van ton tai: " + str(xam)


def test_kiem_nguoc_dao_thu_tu_inode_va_hash(tmp_path: Path) -> None:
    """Dao lai thu tu cu => thay doi chi bi bat SAU khi da `ln`."""
    moi = _ban_va([(_THU_TU_DUNG, _THU_TU_CU)])
    goc = _dung_san_khau(tmp_path, deploy_sh=moi)
    _stub_stat_doi_tmp(goc)
    rc, out = _do(goc)
    assert rc != 0, out
    assert "sau-ln-tren-FINAL" in out, (
        "dao thu tu ma van bat truoc `ln` => ca nen khong chung minh duoc thu "
        "tu dang ganh:" + _NL + out)


def _stub_ln_lam_ban(goc: Path) -> None:
    """ln gia: link that roi DOI noi dung qua chinh inode vua cong bo.

    Day la khe con lai sau khi da dao thu tu: mot lenh xen vao giua phep so
    hash va `ln`. Khong dong duoc bang thu tu, nen phai fail-SECURE.
    """
    _viet_stub(goc / "bin" / "ln", [
        "#!/usr/bin/env bash",
        '/usr/bin/ln "$@" || exit $?',
        'DICH="${@: -1}"',
        'case "$DICH" in',
        '  *rollback_manifest_*) printf X >> "$DICH" ;;',
        "esac",
        "exit 0",
    ])


def test_aw_ban_ke_ban_sau_ln_thi_bi_go_khoi_ten_chinh_thuc(tmp_path: Path) -> None:
    """RC=1 thi KHONG duoc con tep sai o ten chinh thuc."""
    goc = _dung_san_khau(tmp_path)
    _stub_ln_lam_ban(goc)
    rc, out = _do(goc)
    assert rc != 0, out
    assert "sau-ln-tren-FINAL" in out, out
    assert "ĐÃ GỠ" in out, out
    xam = sorted((goc / "ops").glob("pre-*/rollback_manifest_*.txt"))
    assert xam == [], "ban ke ban van mang ten chinh thuc: " + str(xam)


def test_kiem_nguoc_go_don_dep_sau_ln(tmp_path: Path) -> None:
    """Tra ve `error` tran (khong don dep) => tep ban nam lai o ten chinh thuc."""
    moi = _ban_va([(
        '    _ra_kiem_hash_sau_ln "sau-ln-tren-FINAL" "$_RA_MANIFEST" "$_RA_FD" "$_RA_INO_T"',
        '    _ra_kiem_hash_pf "sau-ln-tren-FINAL" "$_RA_MANIFEST"')])
    goc = _dung_san_khau(tmp_path, deploy_sh=moi)
    _stub_ln_lam_ban(goc)
    rc, out = _do(goc)
    assert rc != 0, out
    xam = sorted((goc / "ops").glob("pre-*/rollback_manifest_*.txt"))
    assert xam != [], (
        "go don dep ma tep van bien mat => ca nen khong chung minh duoc don dep")


def _stub_sha256sum_doi_marker_cu(goc: Path) -> None:
    """sha256sum gia: khi bam TMP marker thi DOI marker cu.

    `_RA_MK_HASH` la lenh ngoai duy nhat bam mot duong `.last-deploy.*`. Dat no
    SAU checkpoint marker cu thi thay doi nay khong con phep so nao bat duoc.
    """
    _viet_stub(goc / "bin" / "sha256sum", [
        "#!/usr/bin/env bash",
        'ARG="${@: -1}"',
        'OPS="${QLTS_ROLLBACK_OPS_DIR:?}"',
        'M="$OPS/last-deploy.marker"',
        'case "$ARG" in',
        "  *.last-deploy.*)",
        '    if [ -f "$M" ]; then printf "DA BI THAY" >> "$M"; fi ;;',
        "esac",
        'exec /usr/bin/sha256sum "$@"',
    ])


def test_aw_marker_cu_doi_trong_chinh_lenh_bam_tmp_thi_do(tmp_path: Path) -> None:
    """Bam TMP dung TRUOC checkpoint => thay doi sinh ra o do van bi bat."""
    goc = _dung_san_khau(tmp_path)
    mk = goc / "ops" / "last-deploy.marker"
    _stub_sha256sum_doi_marker_cu(goc)
    rc, out = _do(goc)
    assert rc != 0, out
    assert "ĐỔI nội dung" in out, out
    assert "DA BI THAY" in mk.read_text(encoding="utf-8"), (
        "marker cu da bi ghi de => cong checkpoint khong con y nghia")


def test_kiem_nguoc_dua_bam_tmp_xuong_sau_checkpoint(tmp_path: Path) -> None:
    """Thu tu cu => rc=0 va thay doi canh tranh bi ghi de MAT."""
    moi = _ban_va([(_BAM_TMP, ":")])
    assert moi.count(_MV_T) == 1, "moc `mv -T` khong khop duy nhat"
    moi = moi.replace(_MV_T, _BAM_TMP + _NL + _MV_T)
    goc = _dung_san_khau(tmp_path, deploy_sh=moi)
    mk = goc / "ops" / "last-deploy.marker"
    _stub_sha256sum_doi_marker_cu(goc)
    rc, out = _do(goc)
    assert rc == 0, (
        "dua bam xuong ma van chan => ca nen khong canh dung:" + _NL + out)
    than = mk.read_text(encoding="utf-8")
    assert "DA BI THAY" not in than, "thay doi canh tranh van con => chua ghi de"
    assert "# deployed-sha" + _TAB + _SHA_MOI in than, than

# ===========================================================================
# 10. LOI DOC metadata sau `ln` — fail-closed y het metadata SAI
# ===========================================================================
# `_RA_INO_F=$(stat …)` gan TRAN: `stat` hong thi `set -e` cho script thoat
# THANG voi ma thoat cua chinh `stat` — khong thong diep, khong don dep, va ten
# chinh thuc nam lai nguyen ven. Do la fail-OPEN o dung cho nguy hiem nhat: su
# ton tai cua ten do LA bang chung "da qua preflight" cho luot deploy sau.
#
# Nhanh don dep cung khong duoc chi dua vao `stat` — no hong dung luc can no
# nhat. `-ef` la phep hoi CUA SHELL (stat(2) truc tiep, khong goi nhi phan
# `stat`), nen van tra loi duoc khi nhi phan `stat` da hong. Vi the TMP phai
# song den het moi hau kiem tren FINAL.

_DANG_STAT = {
    "dev-inode": "%d:%i",
    "link-count": "%h",
    "mode-owner": "%a %U:%G",
}
_BIEN_STAT = {
    "dev-inode": "_RA_INO_F",
    "link-count": "_RA_LINK",
    "mode-owner": "_RA_QF",
}
_DONG_EF = '        if [ "$_f" -ef "$_ghim" ]; then'
_DONG_CONG_DON_DEP = (
    '    if [ ! -L "$_f" ] && [ -f "$_f" ] && [ -n "$_fd" ]'
    ' && [ -e "$_ghim" ]; then'
)


def _stub_stat_loi_tren_final(goc: Path, dang: str) -> None:
    """stat gia: TRA LOI (rc=77) dung MOT dinh dang, va chi tren FINAL manifest.

    Khong lam hong moi lenh `stat`: nhu vay se chan ngay o `_ra_cong_ops`, tu
    truoc khi co gi de don dep, va ca kiem se xanh vi mot ly do khac han.
    """
    _viet_stub(goc / "bin" / "stat", [
        "#!/usr/bin/env bash",
        'ARG="${@: -1}"',
        'if [ "${1:-}" = "-c" ] && [ "${2:-}" = "' + dang + '" ]; then',
        '  case "$ARG" in',
        "    *rollback_manifest_*)",
        '      echo "stat gia: khong doc duoc metadata" >&2; exit 77 ;;',
        "  esac",
        "fi",
        'exec /usr/bin/stat "$@"',
    ])


def _tmp_manifest_con_lai(goc: Path):
    return sorted((goc / "ops").glob("pre-*/.manifest.*"))


@pytest.mark.parametrize("ten", sorted(_DANG_STAT))
def test_aw_stat_loi_sau_ln_thi_go_final_va_giu_tmp(tmp_path: Path, ten: str) -> None:
    """Loi DOC metadata => rc != 0, FINAL bien mat, TMP dieu tra con nguyen."""
    goc = _dung_san_khau(tmp_path)
    _stub_stat_loi_tren_final(goc, _DANG_STAT[ten])
    rc, out = _do(goc)
    assert rc != 0, out
    assert "KHÔNG ĐỌC ĐƯỢC" in out, out
    assert "ĐÃ GỠ" in out, out
    xam = sorted((goc / "ops").glob("pre-*/rollback_manifest_*.txt"))
    assert xam == [], "RC != 0 ma ten chinh thuc van ton tai: " + str(xam)
    assert _tmp_manifest_con_lai(goc) != [], "TMP dieu tra da bi xoa"


def _go_don_dep_cua_stat(bien: str):
    """(cu, moi) — bo nhanh `|| _ra_loi_sau_ln` cua dong gan `bien`."""
    than = _DEPLOY.read_text(encoding="utf-8")
    dong = [d for d in than.split(_NL) if d.strip().startswith(bien + "=$(stat ")]
    assert len(dong) == 1, bien + ": " + str(dong)
    cu = dong[0]
    assert "|| _ra_loi_sau_ln" in cu, cu
    return cu, cu[:cu.index("|| _ra_loi_sau_ln")].rstrip()


@pytest.mark.parametrize("ten", sorted(_DANG_STAT))
def test_kiem_nguoc_stat_loi_khong_qua_don_dep(tmp_path: Path, ten: str) -> None:
    """Gan tran => `set -e` thoat thang va FINAL nam lai o ten chinh thuc."""
    moi = _ban_va([_go_don_dep_cua_stat(_BIEN_STAT[ten])])
    goc = _dung_san_khau(tmp_path, deploy_sh=moi)
    _stub_stat_loi_tren_final(goc, _DANG_STAT[ten])
    rc, out = _do(goc)
    assert rc != 0, out
    xam = sorted((goc / "ops").glob("pre-*/rollback_manifest_*.txt"))
    assert xam != [], (
        "go nhanh don dep ma FINAL van bien mat => ca nen khong canh dung:"
        + _NL + out)


def test_kiem_nguoc_bo_phep_so_ef(tmp_path: Path) -> None:
    """Bo `-ef` => khi chinh `stat` hong thi khong con duong nao chung minh.

    Day la ca duy nhat tach bach duoc HAI duong cua nhanh don dep: bo `-ef` thi
    chi con `stat`, ma `stat` dang la thu vua hong.
    """
    moi = _ban_va([(_DONG_EF, "        if false; then")])
    goc = _dung_san_khau(tmp_path, deploy_sh=moi)
    _stub_stat_loi_tren_final(goc, _DANG_STAT["dev-inode"])
    rc, out = _do(goc)
    assert rc != 0, out
    assert "KHÔNG GỠ" in out, out
    xam = sorted((goc / "ops").glob("pre-*/rollback_manifest_*.txt"))
    assert xam != [], (
        "bo `-ef` ma van go duoc => ca nen khong chung minh `-ef` dang ganh")


def test_kiem_nguoc_vo_hieu_toan_bo_don_dep(tmp_path: Path) -> None:
    """Vo hieu ca nhanh don dep => FINAL nam lai o ten chinh thuc."""
    moi = _ban_va([(_DONG_CONG_DON_DEP, "    if false; then")])
    goc = _dung_san_khau(tmp_path, deploy_sh=moi)
    _stub_stat_loi_tren_final(goc, _DANG_STAT["mode-owner"])
    rc, out = _do(goc)
    assert rc != 0, out
    assert "KHÔNG GỠ" in out, out
    xam = sorted((goc / "ops").glob("pre-*/rollback_manifest_*.txt"))
    assert xam != [], "vo hieu don dep ma FINAL van bien mat => ca nen sai"

# ===========================================================================
# 11. ABA tren so inode — quyen xoa phai dua vao DANH TINH DANG GHIM
# ===========================================================================
# `dev:inode` da chot KHONG phai danh tinh ben. Go hardlink CUOI CUNG xong thi
# kernel duoc phep cap lai dung so inode ay cho mot tep khac. Mot nhanh don dep
# tin vao con so do se XOA NHAM tep cua luot khac:
#
#   bo TMP -> ai do thay FINAL -> kernel tai dung inode -> hash cuoi bao lech
#   -> don dep thay "khop" -> xoa tep ngoai lai.
#
# Mot file descriptor dang mo tren TMP dong ca hai ve: no GIU inode do song nen
# so inode khong the bi tai su dung, va `/proc/$$/fd/<fd>` cho `-ef` mot moc so
# sanh dung ke ca sau khi TMP da bi `rm`.
#
# Ca duoi day dung STUB de dung lai dung kich ban ABA mot cach TAT DINH: khong
# cho gap may filesystem tai dung inode, ma ep `stat` bao lai chinh so cu.

_NOI_DUNG_NGOAI_LAI = "TEP CUA LUOT KHAC"
# `_DONG_EF` (muc 10) la CHINH dong nay — dung lai, khong khai trung mot
# hang so thu hai de hai noi khong the troi khoi nhau.
_DONG_EF_FD_HONG = '        if [ "$_ino_f" = "$_ino_t" ]; then'


def _stub_rm_thay_final(goc: Path) -> None:
    """rm gia: dung luc bo TMP thi THAY FINAL bang mot tep hoan toan khac."""
    _viet_stub(goc / "bin" / "rm", [
        "#!/usr/bin/env bash",
        '/bin/rm "$@" || exit $?',
        'for A in "$@"; do',
        '  case "$A" in',
        "    */.manifest.*)",
        '      D=$(dirname -- "$A")',
        '      for F in "$D"/rollback_manifest_*.txt; do',
        '        [ -e "$F" ] || continue',
        '        /bin/rm -f -- "$F"',
        "        printf '" + _NOI_DUNG_NGOAI_LAI + "\\n' > \"$F\"",
        '        chmod 600 "$F"',
        "      done",
        "      ;;",
        "  esac",
        "done",
        "exit 0",
    ])


def _stub_stat_tai_dung_inode(goc: Path) -> None:
    """stat gia: bao lai dung dev:inode cua TMP cho tep FINAL moi.

    Day la cach dung lai viec kernel tai su dung inode ma khong phu thuoc may
    rui: ghi lai gia tri `%d:%i` doc duoc tren TMP, roi tra lai chinh no cho moi
    cau hoi `%d:%i` tren duong FINAL.
    """
    _viet_stub(goc / "bin" / "stat", [
        "#!/usr/bin/env bash",
        'ARG="${@: -1}"',
        'KHO="${QLTS_ROLLBACK_OPS_DIR:?}/.inode_da_chot"',
        'if [ "${1:-}" = "-c" ] && [ "${2:-}" = "%d:%i" ]; then',
        '  case "$ARG" in',
        "    *.manifest.*)",
        "      V=$(/usr/bin/stat -c '%d:%i' \"$ARG\") || exit $?",
        '      printf %s "$V" > "$KHO"',
        "      printf '%s\\n' \"$V\"",
        "      exit 0 ;;",
        "    *rollback_manifest_*)",
        '      if [ -s "$KHO" ]; then printf \'%s\\n\' "$(cat "$KHO")"; exit 0; fi ;;',
        "  esac",
        "fi",
        'exec /usr/bin/stat "$@"',
    ])


def _dung_san_khau_aba(tmp_path: Path, deploy_sh=None) -> Path:
    goc = _dung_san_khau(tmp_path, deploy_sh=deploy_sh)
    _stub_rm_thay_final(goc)
    _stub_stat_tai_dung_inode(goc)
    return goc


def _tep_ngoai_lai(goc: Path):
    return sorted((goc / "ops").glob("pre-*/rollback_manifest_*.txt"))


def test_aw_aba_inode_thi_khong_duoc_xoa_tep_ngoai_lai(tmp_path: Path) -> None:
    """ABA: FINAL bi thay, `stat` bao lai inode cu => TUYET DOI khong xoa."""
    goc = _dung_san_khau_aba(tmp_path)
    rc, out = _do(goc)
    assert rc != 0, out
    assert "ĐÃ GỠ" not in out, (
        "da xoa mot tep KHONG phai cua luot nay:" + _NL + out)
    assert "KHÔNG GỠ" in out, out
    con = _tep_ngoai_lai(goc)
    assert len(con) == 1, "tep ngoai lai da bien mat: " + str(con)
    assert con[0].read_text(encoding="utf-8").strip() == _NOI_DUNG_NGOAI_LAI, (
        "noi dung tep ngoai lai bi thay doi: " + con[0].read_text(encoding="utf-8"))


def test_kiem_nguoc_aba_doi_ef_fd_thanh_dev_inode(tmp_path: Path) -> None:
    """Thay `-ef` voi FD bang phep so dev:inode => tep ngoai lai BI XOA.

    Day la bang chung `-ef` voi `/proc/$$/fd/<fd>` dang ganh: chi mot dong doi
    lai theo kieu cu la lo hong xoa nham tai xuat hien.
    """
    moi = _ban_va([(_DONG_EF, _DONG_EF_FD_HONG)])
    goc = _dung_san_khau_aba(tmp_path, deploy_sh=moi)
    rc, out = _do(goc)
    assert rc != 0, out
    assert _tep_ngoai_lai(goc) == [], (
        "doi sang dev:inode ma tep ngoai lai van con => ca nen khong chung minh "
        "duoc `-ef` voi FD dang ganh:" + _NL + out)
