# -*- coding: utf-8 -*-
"""Hợp đồng tài sản rollback: mọi image runtime bị build ghi đè phải được GHIM trước.

Nợ mà tệp này khoá lại (đo 23-09-2026 trên production):

* `deploy.sh` chạy ``compose build`` KHÔNG liệt kê service ⇒ nó dựng **5** image
  runtime (4 app + nginx), nhưng danh sách ghim tài sản là một **hằng chép tay**
  chỉ có 4. Trên VPS: ``qlts-nginx`` có **đúng một** tag (``local``), và ảnh đang
  phục vụ có **đúng một** RepoTag. Build kế tiếp cướp tên ấy ⇒ ảnh cũ thành
  dangling ⇒ **không còn đường lùi cho nginx**.
* Lô thay đổi chính cơ chế áp nginx (#647) lại là lô duy nhất chạm đúng thứ
  không có tài sản rollback.

⚠️ VÌ SAO KHÔNG ĐỌC ``docker-compose.yml`` BẰNG grep/awk

Service ``nginx`` lấy ``build:`` qua **YAML anchor** (``<<: *nginx-base``), nên
mọi phép đọc VĂN BẢN đều không thấy nó — đúng cách mà bất đối xứng này lọt qua
nhiều tháng. Tệp này dùng ``yaml.safe_load``, vốn tự giải merge key.

⚠️ NHÓM THEO ẢNH, KHÔNG THEO SERVICE

``nginx``, ``nginx-bootstrap``, ``nginx-candidate`` dùng CHUNG ``qlts-nginx:local``.
Ghim theo service sẽ đi tìm hai ảnh không tồn tại. Đại diện của mỗi ảnh là
service có profile rỗng hoặc chứa ``production`` — hai service kia chỉ sống
trong lúc áp cấu hình nên không có container để đọc image ID.
"""

from __future__ import annotations

import collections
import json
import pathlib
import re
import subprocess
import sys

import pytest
import yaml

_GOC = pathlib.Path(__file__).resolve().parents[3]
DUONG_COMPOSE = _GOC / "docker-compose.yml"
DUONG_ROLLBACK = _GOC / "docker-compose.rollback.yml"
DUONG_DEPLOY = _GOC / "scripts" / "deploy.sh"
DUONG_PREFLIGHT = _GOC / "scripts" / "rollback-preflight.sh"
DUONG_NGINX_APPLY = _GOC / "scripts" / "nginx-apply.sh"
DUONG_RUNBOOK = _GOC / "Documents" / "ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md"

#: Bỏ mọi đoạn nằm trong nháy đơn hoặc nháy kép.
_TRONG_NHAY = re.compile(r"'[^']*'|\"[^\"]*\"")


def _doc(d: pathlib.Path) -> str:
    return d.read_text(encoding="utf-8")


def _bo_nhay(dong: str) -> str:
    """Bỏ phần trong nháy rồi bỏ chú thích cuối dòng.

    Bài học ``_GIT_VIET_LAI_CAY``: một guard từng khớp trúng chữ nằm trong DÒNG
    THÔNG BÁO thay vì dòng lệnh, nên nó xoá hiệu lực của chính cổng đứng trên.
    Hỏi trên phần đã bóc nháy mới là hỏi về LỆNH.
    """
    return _TRONG_NHAY.sub(" ", dong).split("#", 1)[0]


@pytest.fixture(scope="module")
def dich_vu_bi_build() -> list[str]:
    """Đại diện (theo ẢNH) của mọi service mà ``compose build`` sẽ dựng lại.

    ⚠️ Gom theo TÊN ẢNH là **chưa đủ**. Hai service dùng chung một tag nhưng có
    cấu hình ``build`` KHÁC nhau thì phép gom che mất một image: ta ghim đại diện
    của build A trong khi build B mới là thứ cuối cùng ghi đè tag ấy. Nên khoá
    gom là cặp ``(ảnh, build đã chuẩn hoá)``, và một ảnh ứng với >1 cấu hình
    build thì DỪNG chứ không chọn bừa.
    """
    sv = yaml.safe_load(_doc(DUONG_COMPOSE))["services"]
    theo_anh: dict[str, dict[str, list[tuple[str, list]]]] = collections.defaultdict(
        lambda: collections.defaultdict(list)
    )
    for ten, cau in sv.items():
        if not isinstance(cau, dict) or not cau.get("build"):
            continue
        anh = cau.get("image") or ten
        assert "${" not in anh, (
            "service %r có placeholder trong TÊN ẢNH (%r) — không biết ảnh thật là "
            "gì thì không ghim được." % (ten, anh)
        )
        khoa = json.dumps(cau["build"], sort_keys=True, default=str)
        theo_anh[anh][khoa].append((ten, cau.get("profiles") or []))
    ra = []
    for anh, nhom in theo_anh.items():
        assert len(nhom) == 1, (
            "ảnh %r được dựng bởi %d cấu hình `build` KHÁC nhau (%r). Ghim một đại "
            "diện sẽ che mất các build còn lại, và ảnh được ghim có thể là ảnh của "
            "build kia." % (anh, len(nhom), [t for ds in nhom.values() for t, _ in ds])
        )
        ds = next(iter(nhom.values()))
        dai_dien = [t for t, p in ds if not p or "production" in p]
        assert len(dai_dien) == 1, (
            "ảnh %r có %d đại diện thuộc profile production (%r) — không biết đọc "
            "image ID từ container nào." % (anh, len(dai_dien), dai_dien)
        )
        ra.append(dai_dien[0])
    return sorted(ra)


@pytest.fixture(scope="module")
def rollback_yml() -> dict:
    # `!reset` là thẻ riêng của Compose, `safe_load` không biết. Bỏ thẻ đi vì ở
    # đây ta chỉ cần BIẾT khoá `build` có mặt; giá trị của nó kiểm bằng văn bản.
    return yaml.safe_load(_doc(DUONG_ROLLBACK).replace("!reset ", ""))


def _vung_8_1() -> list[str]:
    tho = _doc(DUONG_RUNBOOK).replace("\r\n", "\n").split("\n")
    dau = next(i for i, l in enumerate(tho) if l.startswith("### 8.1."))
    cuoi = next(
        (i for i, l in enumerate(tho[dau + 1:], dau + 1) if l.startswith(("## ", "### "))),
        len(tho),
    )
    return tho[dau:cuoi]


def _nhanh_schema(nhan: str) -> str:
    """Trả thân nhánh v2 (nhan='v2') hoặc nhánh legacy v1 (nhan='v1')."""
    nguon = _doc(DUONG_PREFLIGHT)
    i = nguon.find('if [ "$SCHEMA" = "2" ]')
    assert i > 0, "rollback-preflight.sh không còn phân biệt schema-version"
    j = nguon.find("else", i)
    k = nguon.find("\nfi", j)
    assert 0 < j < k, "không đọc được cấu trúc if/else của nhánh schema"
    return nguon[i:j] if nhan == "v2" else nguon[j:k]


# ===========================================================================
# 1. BẤT BIẾN GỐC: mọi ảnh bị build ghi đè đều có tài sản rollback
#    Kiểm ngược: gỡ `nginx:` khỏi docker-compose.rollback.yml ⇒ ca này đỏ.
# ===========================================================================


class TestMoiAnhBiBuildDeuCoTaiSan:
    def test_rollback_yml_phu_het_service_bi_build(self, dich_vu_bi_build, rollback_yml):
        """Ca DUY NHẤT cưỡng chế bất biến đầu bài; sáu ca sau là hệ quả.

        Nó bắt CẢ hai hướng hỏng: gỡ ``nginx`` khỏi bản ghim, VÀ thêm một
        service ``build:`` thứ sáu mà quên ghim nó.
        """
        co_ghim = set(rollback_yml.get("services") or {})
        thieu = sorted(set(dich_vu_bi_build) - co_ghim)
        assert not thieu, (
            "service %r bị `compose build` dựng lại nhưng KHÔNG có mục ghim ảnh "
            "trong docker-compose.rollback.yml. Build kế tiếp ghi đè tag của "
            "chúng, ảnh cũ mất tên duy nhất ⇒ không còn đường lùi." % thieu
        )

    def test_nginx_that_su_nam_trong_tap_bi_build(self, dich_vu_bi_build):
        """Tiền đề của ca trên: `nginx` rơi khỏi tập này thì ca kia vô nghĩa."""
        assert "nginx" in dich_vu_bi_build, (
            "nginx không còn trong tập service bị build — hoặc compose đã đổi, hoặc "
            "phép đọc YAML merge key đã hỏng. Kiểm lại trước khi tin màu xanh."
        )


# ===========================================================================
# 2. BẤT BIẾN: danh sách ghim DẪN XUẤT, không chép tay
# ===========================================================================


class TestDanhSachGhimDanXuat:
    def test_deploy_khong_con_hang_chep_tay(self):
        nguon = _doc(DUONG_DEPLOY)
        assert '_RA_DICH_VU="backend celery-worker celery-beat frontend"' not in nguon, (
            "deploy.sh quay lại danh sách service CHÉP TAY — đúng hình dạng đã để "
            "lọt nginx. Danh sách phải dẫn xuất từ model Compose."
        )

    def test_deploy_dan_xuat_tu_model_compose(self):
        nguon = _doc(DUONG_DEPLOY)
        assert "_ra_dan_xuat_dich_vu" in nguon, "deploy.sh thiếu hàm dẫn xuất danh sách"
        assert "--no-interpolate" in nguon and "--no-env-resolution" in nguon, (
            "phép dẫn xuất phải dùng CẢ `--no-interpolate` LẪN `--no-env-resolution`: "
            "`compose config` trần render env_file ra plaintext — tự tạo một bản sao "
            "secret production trên stdout."
        )
        assert "--format json" in nguon, "phải render JSON mới phân giải được YAML anchor"


# ===========================================================================
# 3. BẤT BIẾN: preflight đọc danh sách service TỪ MANIFEST
# ===========================================================================


class TestPreflightDocTuManifest:
    def test_khong_con_ban_chep_thu_hai(self):
        nguon = _doc(DUONG_PREFLIGHT)
        assert "DICH_VU=(backend celery-worker celery-beat frontend)" not in nguon, (
            "rollback-preflight.sh giữ lại bản CHÉP THỨ HAI của danh sách service. "
            "Hai bản chép của cùng một danh sách sẽ trôi khỏi nhau, và bản yếu hơn "
            "là bản còn sống."
        )

    def test_doc_dich_vu_tu_manifest(self):
        nguon = _doc(DUONG_PREFLIGHT)
        assert re.search(r"DICH_VU.*<\(awk[^\n]*MANIFEST", nguon), (
            "preflight phải đọc danh sách service từ chính bản kê của lượt deploy ấy"
        )

    def test_doi_chieu_ca_reference_lan_image_id(self):
        nguon = _doc(DUONG_PREFLIGHT)
        assert "REF_GHI" in nguon and '[ "$REF_GHI" = "$REF" ]' in nguon, (
            "preflight tính `REF` nhưng không so nó với cột reference của bản kê ⇒ "
            "một bản kê ghi TAG KHÁC vẫn qua sạch, và ta lùi bằng một tag không "
            "phải tag bản kê nói."
        )


# ===========================================================================
# 4. BẤT BIẾN: mỗi mục ghim đều gỡ `build:`
# ===========================================================================


class TestRollbackYmlGoBuild:
    def test_moi_service_deu_reset_build(self, rollback_yml):
        tho = _doc(DUONG_ROLLBACK).replace("\r\n", "\n")
        for ten in sorted(rollback_yml.get("services") or {}):
            khoi = re.search(
                r"^  %s:\n(?:    .*\n|\n)*" % re.escape(ten), tho, re.MULTILINE
            )
            assert khoi, "không đọc được khối service %r" % ten
            assert "build: !reset null" in khoi.group(0), (
                "docker-compose.rollback.yml: %r thiếu `build: !reset null` ⇒ `up` "
                "có thể DỰNG LẠI từ mã MỚI thay vì dùng ảnh đã ghim." % ten
            )

    def test_nginx_dung_bien_tag_chung(self, rollback_yml):
        anh = (rollback_yml["services"]["nginx"] or {}).get("image", "")
        assert "QLTS_ROLLBACK_TAG" in anh, (
            "mục nginx phải ghim theo cùng biến tag với bốn service kia, nếu không "
            "một lệnh rollback sẽ lùi bốn ảnh về mốc A và nginx về mốc B."
        )


# ===========================================================================
# 5. BẤT BIẾN: bản kê v2 THIẾU nginx ⇒ ĐỎ
# ===========================================================================


class TestManifestV2DoiNginx:
    def test_preflight_chan_v2_thieu_nginx(self):
        nhanh = _nhanh_schema("v2")
        assert "error" in nhanh and "nginx" in nhanh, (
            "nhánh v2 phải DỪNG (error) khi bản kê thiếu hàng nginx — cảnh báo là "
            "chưa đủ: v2 nghĩa là mọi image bị build ghi đè đều có tài sản."
        )


# ===========================================================================
# 6. BẤT BIẾN: bản kê v1 vẫn chạy được, NHƯNG phải cảnh báo rõ
# ===========================================================================


class TestManifestV1Legacy:
    def test_v1_khong_bi_chan(self):
        assert "error" not in _nhanh_schema("v1"), (
            "nhánh bản kê LEGACY (v1) gọi `error` ⇒ chặn hẳn. Làm thế là huỷ đường "
            "lùi của mọi mốc cũ — 10 bản kê hiện có trên production đều là v1."
        )

    def test_v1_phai_canh_bao_khong_co_image_rollback(self):
        nhanh = _nhanh_schema("v1")
        assert "warn" in nhanh, "nhánh v1 không cảnh báo gì cả"
        assert "KHÔNG có image rollback" in nhanh, (
            "cảnh báo v1 phải nói THẲNG là không có image rollback cho nginx. Một "
            "dòng cảnh báo mơ hồ để người trực tưởng vẫn còn đường lùi."
        )


# ===========================================================================
# 7. BẤT BIẾN: rollback KHÔNG BAO GIỜ `up -d` chạm nginx
#    Chính khối `nginx:` trong rollback.yml tự sinh lối fail-open này.
# ===========================================================================


class TestRollbackKhongUpNginxTran:
    def test_khong_lenh_up_nao_cham_nginx_trong_8_1(self):
        xau = []
        for so, dong in enumerate(_vung_8_1(), 1):
            lenh = _bo_nhay(dong)
            if "up -d" in lenh and "nginx" in lenh:
                xau.append((so, dong.strip()[:100]))
        assert not xau, (
            "§8.1 có lệnh `up -d` chạm nginx: %r\n"
            "nginx PHẢI đi qua `nginx-apply.sh` (candidate → G1 → nginx-verify → G2). "
            "Một `up -d` thẳng bỏ qua toàn bộ chuỗi ấy — và khối `nginx:` trong "
            "docker-compose.rollback.yml làm điều đó trở nên KHẢ THI." % xau
        )

    def test_8_1_van_goi_nginx_apply_voi_anh_ghim(self):
        vung = "\n".join(_bo_nhay(x) for x in _vung_8_1())
        assert "nginx-apply.sh" in vung, "§8.1 không còn gọi nginx-apply.sh"
        assert "QLTS_NGINX_ANH_GHIM" in vung, (
            "§8.1 gọi nginx-apply.sh mà KHÔNG truyền ảnh ghim ⇒ nó sẽ áp ảnh đang "
            "nằm trên tag `:local`, không phải ảnh của mốc đang lùi về."
        )

    def test_checkout_nginx_dung_truoc_lenh_ap_anh_ghim(self):
        """G1 so ảnh với cây `nginx/` HIỆN TẠI ⇒ thứ tự này là bắt buộc.

        ⚠️ Neo vào ĐÚNG lời gọi mang ``QLTS_NGINX_ANH_GHIM``, không vào lời gọi
        ``nginx-apply.sh`` đầu tiên: §8.1 mở đầu bằng một bước đóng băng lại
        bằng cấu hình HIỆN TẠI — bước ấy CỐ Ý đứng trước checkout, và neo vào nó
        sẽ đỏ ở đúng ca đang làm đúng.
        """
        vung = _vung_8_1()
        i_co = next(
            (i for i, l in enumerate(vung) if "checkout" in _bo_nhay(l) and "nginx/" in _bo_nhay(l)),
            None,
        )
        i_ap = next(
            (
                i
                for i, l in enumerate(vung)
                if "nginx-apply.sh" in _bo_nhay(l) and "QLTS_NGINX_ANH_GHIM" in _bo_nhay(l)
            ),
            None,
        )
        assert i_co is not None, "§8.1 không còn `git checkout … -- nginx/`"
        assert i_ap is not None, (
            "§8.1 không có lời gọi nginx-apply.sh nào mang QLTS_NGINX_ANH_GHIM — "
            "không có bước nào thật sự TIÊU THỤ tài sản rollback của nginx."
        )
        assert i_co < i_ap, (
            "lệnh áp ảnh ghim (dòng #%d của §8.1) đứng TRƯỚC `git checkout … nginx/` "
            "(#%d). G1 sẽ so ảnh cũ với cây MỚI và từ chối — người trực sẽ học cách "
            "bỏ qua cổng." % (i_ap, i_co)
        )


# ===========================================================================
# 8-9. Hai cổng phụ trợ — hai chỗ dễ bị nới nhất
# ===========================================================================


class TestPhepDanXuatChayDuoc:
    """Phép dẫn xuất phải CHẠY ĐƯỢC, không chỉ CÓ MẶT.

    Vì sao lớp này tồn tại: bản đầu của `_ra_dan_xuat_dich_vu` mang hai lỗi
    escape — một ``\\n`` literal cắt đôi lệnh ``docker compose``, và hai chuỗi
    Python bị xuống dòng thật. ``bash -n`` không thấy (chúng nằm trong chuỗi), và
    mọi phép kiểm "có chứa tên hàm" vẫn XANH. Guard xanh trên mã hỏng còn nguy
    hiểm hơn không có guard.
    """

    @staticmethod
    def _doan_nhung() -> str:
        nguon = _doc(DUONG_DEPLOY)
        i = nguon.index('"$_py" -c ' + "'") + len('"$_py" -c ' + "'")
        j = nguon.index("\n' || return 13", i)
        return nguon[i:j]

    @staticmethod
    def _chay(model: dict) -> tuple[int, str, str]:
        p = subprocess.run(
            [sys.executable, "-c", TestPhepDanXuatChayDuoc._doan_nhung()],
            input=json.dumps(model).encode("utf-8"),
            capture_output=True,
        )
        return (
            p.returncode,
            p.stdout.decode("utf-8", "replace").strip(),
            p.stderr.decode("utf-8", "replace").strip(),
        )

    def test_doan_python_nhung_compile_duoc(self):
        compile(self._doan_nhung(), "<nhung trong deploy.sh>", "exec")

    def test_lenh_compose_khong_bi_escape_lam_gay(self):
        nguon = _doc(DUONG_DEPLOY)
        i = nguon.index("_ra_dan_xuat_dich_vu() {")
        than = nguon[i : nguon.index("\n}", i)]
        dong_docker = [l for l in than.split("\n") if "docker compose" in l]
        assert dong_docker, "không tìm thấy lệnh `docker compose` trong hàm dẫn xuất"
        for l in dong_docker:
            assert "\\n" not in l, (
                "lệnh `docker compose` chứa `\\n` LITERAL — nó sẽ được truyền vào "
                "như một ĐỐI SỐ chứ không phải xuống dòng, và lệnh gãy khi chạy "
                "thật trong khi `bash -n` vẫn xanh: %r" % l.strip()[:110]
            )

    def test_cho_dung_nam_dai_dien(self):
        b = {"context": "/x", "dockerfile": "Dockerfile"}
        rc, ra, _ = self._chay(
            {
                "services": {
                    "backend": {"build": b},
                    "celery-worker": {"build": b},
                    "celery-beat": {"build": b},
                    "frontend": {"build": b},
                    "nginx": {"image": "qlts-nginx:local", "build": b, "profiles": ["production"]},
                    "nginx-candidate": {
                        "image": "qlts-nginx:local",
                        "build": b,
                        "profiles": ["candidate"],
                    },
                    "postgres": {"image": "postgres:16-alpine"},
                }
            }
        )
        assert rc == 0, "phép dẫn xuất đổ trên model hợp lệ"
        assert ra.split() == [
            "backend",
            "celery-beat",
            "celery-worker",
            "frontend",
            "nginx",
        ], ra

    def test_cung_anh_khac_build_thi_fail_closed(self):
        rc, _, er = self._chay(
            {
                "services": {
                    "nginx": {
                        "image": "qlts-nginx:local",
                        "build": {"context": "/a"},
                        "profiles": ["production"],
                    },
                    "nginx-khac": {
                        "image": "qlts-nginx:local",
                        "build": {"context": "/b"},
                        "profiles": ["candidate"],
                    },
                }
            }
        )
        assert rc != 0, (
            "hai cấu hình build KHÁC nhau cùng ghi `qlts-nginx:local` mà phép dẫn "
            "xuất vẫn chọn một đại diện ⇒ nó che mất một image."
        )
        assert "build" in er.lower()

    def test_placeholder_trong_ten_anh_thi_fail_closed(self):
        rc, _, _ = self._chay({"services": {"x": {"image": "qlts-x:${TAG}", "build": {"context": "/x"}}}})
        assert rc != 0, "tên ảnh còn `${…}` mà vẫn ghim ⇒ ghim một cái tên không tồn tại"

    def test_json_hong_thi_fail_closed(self):
        p = subprocess.run(
            [sys.executable, "-c", self._doan_nhung()],
            input=b"khong phai json",
            capture_output=True,
        )
        assert p.returncode != 0, "JSON hỏng mà vẫn trả 0 ⇒ danh sách rỗng đi tiếp"

    def test_khong_co_service_build_nao_thi_fail_closed(self):
        rc, _, _ = self._chay({"services": {"postgres": {"image": "postgres:16-alpine"}}})
        assert rc != 0, "0 service có build mà vẫn trả 0 ⇒ ghim rỗng, tưởng là đã ghim"


class TestHaiCongPhuTro:
    def test_tag_ghim_phai_duy_nhat(self):
        nguon = _doc(DUONG_DEPLOY)
        assert "DA TON TAI va tro vao anh khac" in nguon, (
            "deploy.sh không còn chặn ca tag ghim đã tồn tại mà trỏ vào ảnh KHÁC. "
            "`docker tag` khi ấy cướp tên khỏi một bản kê cũ, âm thầm."
        )

    def test_phien_ban_marker_GHI_va_phien_ban_marker_KIEM_phai_khop(self):
        """Hai con số này ở hai chỗ cách nhau ~750 dòng — chúng sẽ trôi khỏi nhau.

        Đã trôi một lần: bản đầu ghi ``marker-version 2`` trong khi
        ``_ra_kiem_schema_marker`` vẫn đòi ``'1'``. Deploy khi ấy đổ ở bước NIÊM
        PHONG — sau khi đã build, đã áp, đã health-check xong.
        """
        nguon = _doc(DUONG_DEPLOY)
        ghi = re.search(r"printf '# marker-version\\t(\d+)\\n'", nguon)
        assert ghi, "không tìm thấy chỗ GHI marker-version"
        kiem = re.search(
            r'\[ "\$_v" = "(\d+)" \] \|\| error "marker mới: marker-version', nguon
        )
        assert kiem, "không tìm thấy phép KIỂM marker-version của marker mới"
        assert ghi.group(1) == kiem.group(1), (
            "deploy.sh GHI marker-version %s nhưng phép kiểm marker MỚI đòi %s — "
            "deploy sẽ đổ ở bước niêm phong." % (ghi.group(1), kiem.group(1))
        )

    def test_doc_marker_chap_nhan_ca_v1_lan_v2(self):
        nguon = _doc(DUONG_DEPLOY)
        assert re.search(r'case "\$_RA_VER" in\s*\n\s*1\|2\)', nguon), (
            "đường ĐỌC marker phải chấp nhận cả v1 lẫn v2: marker đang nằm trên "
            "production là v1, chặn nó là chặn mọi lần deploy tiếp theo."
        )

    def test_anh_ghim_van_phai_qua_verify(self):
        nguon = _doc(DUONG_NGINX_APPLY)
        i = nguon.find('if [ -n "${QLTS_NGINX_ANH_GHIM:-}" ]')
        assert i > 0, "nginx-apply.sh chưa có nhánh chế độ ảnh ghim"
        sau = nguon[i:]
        assert "nginx-verify.sh" in sau, (
            "chế độ ảnh ghim phải nằm TRƯỚC nginx-verify.sh — đứng sau nghĩa là có "
            "một đường áp ảnh mà không đo hành vi thật."
        )
        assert "_cong_noi_dung" in sau, "chế độ ảnh ghim bỏ qua cổng NỘI DUNG (G1)"
