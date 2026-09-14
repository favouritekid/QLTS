# tests/unit/test_totp_coordinator_inventory.py
# -*- coding: utf-8 -*-
"""Khoá ĐIỀU PHỐI TOTP: một nguồn chuẩn, nguyên tử, fail xác định.

Vì sao tệp này tồn tại — ba lỗ đã đo được, không phải ba giả thuyết:

1. **Counter dùng lại giữa các tiến trình.** Nightly run ``34744228787``:
   ``smoke-all-pages`` đăng nhập admin ĐÚNG MỘT LẦN mà cả ba lượt thử đều 401
   với CÙNG ``totp_counter=59642789``. Backend chống phát lại bằng bất biến
   ĐƠN ĐIỆU NGHIÊM NGẶT theo NGƯỜI DÙNG (``app/database.py`` →
   ``safe_redis_consume_totp_counter``, chấp nhận khi và chỉ khi
   ``counter > counter_đã_lưu``), nên hai tiến trình ``npx playwright test``
   rơi vào cùng cửa sổ 30 giây là lượt sau bị coi là replay.

2. **Bản vá đầu tiên chỉ chạm MỘT suite.** ``totpChuaTieu`` cũ chỉ được
   ``smoke-all-pages`` gọi; mười sáu consumer còn lại và
   ``.github/scripts/nightly_mfa_gate.py`` vẫn tự tính counter riêng.

3. **Bản vá đầu tiên là read-modify-write.** Đọc JSON → sửa → ghi đè KHÔNG
   nguyên tử: hai tiến trình cùng đọc trạng thái cũ rồi ghi đè nhau, đúng lúc
   cần nó nhất.

⚠️ **TỆP NÀY KHÔNG ĐƯỢC PHÉP SKIP.** Không ``pytest.skip``, không
``importorskip``. GitHub coi check ``skipped`` là thành công; một hợp đồng tự
tan thành skip đúng lúc nguồn chuẩn của nó biến mất là fail-open — đúng lớp lỗi
mà tệp này sinh ra để đóng. Thiếu ``node`` cũng ĐỎ: ca chứng minh "hai tiến
trình không lấy cùng counter" là một tuyên bố về HAI TIẾN TRÌNH; đọc mã rồi tin
thì không chứng minh được gì, và một lát CI không chạy được nó phải nói ra.

Các bất biến được TÁCH thành ca riêng — gộp lại thì phép kiểm vẫn xanh khi vài
cái đã hỏng (bài học ``composite-check-hides-what-it-guards``):

* **KK1** mọi consumer ``/verify-mfa`` đi qua điều phối viên;
* **KK2** không tệp nào dưới ``src/test/e2e/**`` import ``otpauth``;
* **KK3** không có ``generateTOTP`` cục bộ ở bất cứ đâu trong ``src/test/e2e``;
* **KK4** không còn retry mù 31 giây sau một lỗi MFA;
* **KK5** sáu suite nightly (+ ``admission-ui-smoke`` + ``auth.setup.ts``)
  đều có mặt và đều nối được tới điều phối viên;
* **WF**  cả tám bước dùng TOTP trong workflow ghim CÙNG ``QLTS_TOTP_STATE_DIR``;
* **PAR** Node và Python sinh CÙNG mã cho cùng counter, và đặt CÙNG tên tệp;
* **NT**  hai tiến trình Node cạnh tranh KHÔNG lấy cùng counter;
* **ĐL**  hai tài khoản khác nhau KHÔNG chặn nhau;
* **XĐ**  state hỏng / ở tương lai ⇒ thoát khác 0 với mã phân loại ĐÚNG;
* **BM**  thư mục state KHÔNG chứa secret hay mã TOTP.
"""
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.unit


# ===========================================================================
# Định vị
# ===========================================================================
def _goc_repo() -> pathlib.Path:
    for cha in pathlib.Path(__file__).resolve().parents:
        if (cha / ".github" / "workflows").is_dir():
            return cha
    raise AssertionError(
        "không tìm được gốc repo (thư mục chứa .github/workflows). Hợp đồng "
        "điều phối TOTP KHÔNG được skip khi thiếu — nó phải đỏ."
    )


GOC = _goc_repo()
THU_MUC_E2E = GOC / "frontend" / "src" / "test" / "e2e"
DIEU_PHOI_JS = THU_MUC_E2E / "helpers" / "totp-coordinator.js"
DIEU_PHOI_DTS = THU_MUC_E2E / "helpers" / "totp-coordinator.d.ts"
RESERVE_CLI = THU_MUC_E2E / "helpers" / "totp-reserve-cli.js"
FIXTURES_TS = THU_MUC_E2E / "helpers" / "e2e-fixtures.ts"
DUONG_WF = GOC / ".github" / "workflows" / "nightly-regression.yml"
DUONG_MFA_GATE = GOC / ".github" / "scripts" / "nightly_mfa_gate.py"

#: Đúng sáu suite mà `nightly-regression.yml` chạy, cộng hai tệp đi kèm bước
#: smoke. `auth.setup.ts` nằm trong danh sách vì project `chromium` khai
#: `dependencies: ['setup']` — nó là đường tạo `storageState`.
SUITE_NIGHTLY = (
    "lead-workflow.spec.ts",
    "admission-lifecycle.spec.ts",
    "finance-lifecycle.spec.ts",
    "bugfix-regression.spec.ts",
    "lead-to-admission-workflow.spec.ts",
    "smoke-all-pages.spec.ts",
    "admission-ui-smoke.spec.ts",
    "auth.setup.ts",
)

#: Tên các hàm HỢP LỆ để hoàn tất một challenge MFA. Mọi đường khác là vi phạm.
CUA_DIEU_PHOI = ("voiMaTotp", "xacThucMfa")

#: Biến môi trường ghim thư mục state dùng chung.
BIEN_STATE_DIR = "QLTS_TOTP_STATE_DIR"


def _phai_ton_tai(p: pathlib.Path, mo_ta: str) -> pathlib.Path:
    assert p.is_file() or p.is_dir(), (
        f"thiếu {mo_ta}: {p}. Hợp đồng điều phối TOTP không được biến thành "
        "skipped khi nguồn chuẩn của nó biến mất."
    )
    return p


# ===========================================================================
# Bóc chú thích — guard phải nhìn MÃ, không nhìn lời bình
# ===========================================================================
def boc_chu_thich(ma: str) -> str:
    """Xoá ``//``, ``/* */`` nhưng GIỮ nguyên nội dung chuỗi và template.

    Cần thiết theo cả hai hướng:

    * **Không báo động giả.** Docstring của chính điều phối viên nhắc tới
      ``otpauth`` và ``generateTOTP`` để giải thích vì sao chúng bị cấm. Một
      guard quét văn bản thô sẽ đỏ vì đúng lời giải thích ấy, rồi bị nới lỏng.
    * **Không bỏ sót.** Chuỗi được GIỮ: ``eval("generateTOTP")`` hay một URL
      ``"/api/auth/verify-mfa"`` vẫn phải nhìn thấy được.

    Độ dài được giữ nguyên (thay bằng dấu cách / xuống dòng) để số dòng không
    lệch khi báo lỗi.
    """
    ra = []
    i = 0
    n = len(ma)
    trong_chuoi = None  # ký tự mở chuỗi đang dở
    while i < n:
        c = ma[i]
        if trong_chuoi:
            ra.append(c)
            if c == "\\" and i + 1 < n:
                ra.append(ma[i + 1])
                i += 2
                continue
            if c == trong_chuoi:
                trong_chuoi = None
            i += 1
            continue
        if c in "\"'`":
            trong_chuoi = c
            ra.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and ma[i + 1] == "/":
            while i < n and ma[i] != "\n":
                ra.append(" ")
                i += 1
            continue
        if c == "/" and i + 1 < n and ma[i + 1] == "*":
            while i < n and not (ma[i] == "*" and i + 1 < n and ma[i + 1] == "/"):
                ra.append("\n" if ma[i] == "\n" else " ")
                i += 1
            ra.append("  ")
            i += 2
            continue
        ra.append(c)
        i += 1
    return "".join(ra)


def _tep_ts_e2e() -> list[pathlib.Path]:
    _phai_ton_tai(THU_MUC_E2E, "thư mục consumer E2E")
    tep = sorted(
        p
        for p in THU_MUC_E2E.rglob("*.ts")
        if p.is_file() and not p.name.endswith(".d.ts")
    )
    assert len(tep) >= 20, (
        "chỉ thấy %d tệp .ts trong %s — thư mục consumer hình như đã đổi chỗ, "
        "và một guard quét thư mục rỗng thì xanh vô nghĩa" % (len(tep), THU_MUC_E2E)
    )
    return tep


@pytest.fixture(scope="module")
def ma_e2e() -> dict[pathlib.Path, str]:
    """Mã của mọi ``.ts`` dưới ``src/test/e2e``, ĐÃ bóc chú thích."""
    return {p: boc_chu_thich(p.read_text(encoding="utf-8")) for p in _tep_ts_e2e()}


# ===========================================================================
# KIỂM KÊ — sáu bất biến TĨNH, mỗi cái một ca
# ===========================================================================
RE_VERIFY_MFA = re.compile(r"/api/auth/verify-mfa")
RE_IMPORT_OTPAUTH = re.compile(r"""["']otpauth["']""")
RE_GENERATE_TOTP = re.compile(r"\bgenerateTOTP\b")
RE_TOTP_CTOR = re.compile(r"\bnew\s+(?:OTPAuth\.)?TOTP\b")
RE_NGU_31 = re.compile(r"\b(?:setTimeout|waitForTimeout)\b[^;\n]*\b31[_,]?000\b")


class TestKiemKeConsumer:
    """KK1–KK5 — kiểm kê TĨNH trên toàn bộ ``src/test/e2e``."""

    def test_kk1_moi_consumer_verify_mfa_di_qua_dieu_phoi(self, ma_e2e):
        """Chạm ``/api/auth/verify-mfa`` thì phải gọi điều phối viên.

        Ngoại lệ DUY NHẤT là ``helpers/e2e-fixtures.ts``: nó CHÍNH LÀ lớp nối,
        và nó gọi ``voiMaTotp`` ngay trong thân ``xacThucMfa``.
        """
        vi_pham = []
        for p, ma in ma_e2e.items():
            if not RE_VERIFY_MFA.search(ma):
                continue
            if any(f"{t}(" in ma for t in CUA_DIEU_PHOI):
                continue
            vi_pham.append(str(p.relative_to(GOC)))
        assert not vi_pham, (
            "các tệp gọi /api/auth/verify-mfa mà KHÔNG đi qua %s:\n  %s"
            % (" / ".join(CUA_DIEU_PHOI), "\n  ".join(vi_pham))
        )

    def test_kk2_khong_tep_nao_import_otpauth(self, ma_e2e):
        """``otpauth`` là đường sinh mã THỨ HAI — luật một-nguồn-chuẩn cấm.

        Điều phối viên tự cài RFC 6238 bằng ``node:crypto`` (ca ``PAR`` chứng
        minh nó khớp từng chữ số với bản Python), nên không consumer nào còn
        lý do chạm thư viện ấy.
        """
        vi_pham = [
            str(p.relative_to(GOC))
            for p, ma in ma_e2e.items()
            if RE_IMPORT_OTPAUTH.search(ma)
        ]
        assert not vi_pham, "còn import 'otpauth' ở:\n  " + "\n  ".join(vi_pham)

    def test_kk3_khong_con_generateTOTP_cuc_bo(self, ma_e2e):
        """Mười bảy bản sao ``generateTOTP`` là mười bảy bộ đếm độc lập."""
        vi_pham = [
            str(p.relative_to(GOC))
            for p, ma in ma_e2e.items()
            if RE_GENERATE_TOTP.search(ma) or RE_TOTP_CTOR.search(ma)
        ]
        assert not vi_pham, (
            "còn generateTOTP / new TOTP(...) cục bộ ở:\n  " + "\n  ".join(vi_pham)
        )

    def test_kk4_khong_con_retry_mu_31_giay(self, ma_e2e):
        """Ngủ 31 giây rồi thử lại = che nguyên nhân + đốt hạn mức đăng nhập.

        Va counter được đóng TRƯỚC khi gửi; giữ lại nhánh chờ-rồi-thử-lại là
        giữ một lối thoát cho chính cái bug vừa vá — nó sẽ im lặng che mọi lần
        điều phối viên hỏng.
        """
        vi_pham = []
        for p, ma in ma_e2e.items():
            for khop in RE_NGU_31.finditer(ma):
                dong = ma[: khop.start()].count("\n") + 1
                vi_pham.append(f"{p.relative_to(GOC)}:{dong}")
        assert not vi_pham, (
            "còn chờ-31-giây-rồi-thử-lại ở:\n  " + "\n  ".join(vi_pham)
        )

    def test_kk5_sau_suite_nightly_deu_co_mat_va_noi_toi_dieu_phoi(self, ma_e2e):
        """Tập suite được đặt TƯỜNG MINH — thư mục rỗng không được xanh."""
        theo_ten = {p.name: (p, ma) for p, ma in ma_e2e.items()}
        thieu = [t for t in SUITE_NIGHTLY if t not in theo_ten]
        assert not thieu, "thiếu suite nightly: %s" % (thieu,)

        khong_noi = []
        for ten in SUITE_NIGHTLY:
            p, ma = theo_ten[ten]
            dung_totp = bool(RE_VERIFY_MFA.search(ma)) or "TOTP_SECRET" in ma
            if not dung_totp:
                # `auth.setup.ts` và `admission-ui-smoke.spec.ts` đi bằng tài
                # khoản officer KHÔNG bật MFA. Không chạm TOTP là ĐÚNG, không
                # phải thiếu sót — nhưng phải đọc ra được từ mã, không suy.
                continue
            # Hai đường HỢP LỆ, và chỉ hai:
            #   (a) gọi thẳng điều phối viên;
            #   (b) uỷ thác cho `helpers/e2e-fixtures` (ví dụ `loginPrincipal`),
            #       nơi KK1 đã chứng minh mọi lối `/verify-mfa` đều đi qua
            #       điều phối viên. `bugfix-regression.spec.ts` đi đường này:
            #       nó truyền secret vào `loginPrincipal` và không tự gọi
            #       `/api/auth/verify-mfa` lần nào.
            noi = any(f"{t}(" in ma for t in CUA_DIEU_PHOI) or (
                "./helpers/e2e-fixtures" in ma
            )
            if not noi:
                khong_noi.append(ten)
        assert not khong_noi, (
            "suite dùng TOTP mà không nối tới điều phối viên: %s" % (khong_noi,)
        )

    def test_kk5c_suite_uy_thac_khong_tu_mo_duong_mfa_rieng(self, ma_e2e):
        """Ca ĐÔI của nhánh (b) ở KK5.

        Uỷ thác chỉ hợp lệ khi suite ấy THẬT SỰ không tự chạm `/verify-mfa`.
        Không có ca này thì "có import helpers" trở thành một tấm vé miễn trừ:
        một suite vừa import helpers vừa tự dựng đường MFA riêng vẫn lọt KK5
        (KK1 vẫn bắt, nhưng lúc ấy KK5 đang nói dối về cái nó canh).
        """
        theo_ten = {p.name: ma for p, ma in ma_e2e.items()}
        for ten in SUITE_NIGHTLY:
            ma = theo_ten[ten]
            if not any(f"{t}(" in ma for t in CUA_DIEU_PHOI):
                assert not RE_VERIFY_MFA.search(ma), (
                    f"{ten} uỷ thác qua helpers NHƯNG vẫn tự gọi "
                    "/api/auth/verify-mfa — hai đường song song"
                )

    def test_kk5b_hai_suite_officer_that_su_khong_cham_totp(self, ma_e2e):
        """Ca ĐÔI của KK5 — chứng minh hai ngoại lệ kia là ngoại lệ THẬT.

        Không có ca này thì nhánh ``continue`` ở KK5 là một lỗ: một suite bỗng
        dưng dùng TOTP theo đường riêng vẫn lọt nếu nó cũng bỏ luôn chuỗi
        ``/api/auth/verify-mfa`` (ví dụ ghép URL từ mảnh).
        """
        theo_ten = {p.name: ma for p, ma in ma_e2e.items()}
        for ten in ("auth.setup.ts", "admission-ui-smoke.spec.ts"):
            ma = theo_ten[ten]
            assert "TOTP" not in ma and "mfa" not in ma.lower(), (
                f"{ten} nay có dấu vết MFA — nó không còn là đường officer "
                "không-MFA, phải đưa vào tập consumer của KK5"
            )


@pytest.fixture(scope="module")
def nguon() -> str:
    """Mã của điều phối viên, ĐÃ bóc chú thích.

    Bóc là bắt buộc: docstring của chính tệp ấy trích lại nguyên văn nhánh
    ``fail-OPEN có chủ ý`` cũ để giải thích vì sao nó bị gỡ. Guard quét văn bản
    thô sẽ đỏ vì đúng lời giải thích ấy, rồi bị nới lỏng — và bản nới sẽ mù.
    """
    return boc_chu_thich(
        _phai_ton_tai(DIEU_PHOI_JS, "điều phối viên TOTP").read_text(encoding="utf-8")
    )


def _than_ham_js(nguon: str, ten: str) -> str:
    """Thân một hàm khai ở cấp module (tới dòng ``}`` đầu tiên ở cột 0)."""
    i = nguon.index(f"function {ten}(")
    j = nguon.index("\n}\n", i)
    return nguon[i:j]


class TestCauTrucDieuPhoi:
    """Điều phối viên phải NGUYÊN TỬ theo đúng cơ chế, không chỉ "có khoá"."""

    def test_dat_khoa_bang_O_EXCL(self, nguon):
        """``openSync(..., "wx")`` = ``O_CREAT|O_EXCL``: nguyên tử cả hai OS."""
        assert re.search(r'fs\.openSync\([^)]*"wx"', nguon), (
            'không thấy fs.openSync(..., "wx") — khoá không còn nguyên tử'
        )

    def test_ghi_state_bang_rename_chu_khong_ghi_de(self, nguon):
        """Ghi tệp tạm rồi ``renameSync``: người đọc không thấy tệp nửa vời."""
        assert "renameSync" in nguon, "không thấy fs.renameSync — ghi state không nguyên tử"
        assert re.search(r"\.tmp-\$\{process\.pid\}", nguon), (
            "tệp tạm không mang PID ⇒ hai tiến trình dùng chung một tệp tạm"
        )

    def test_khong_doc_sua_ghi_de_thang_len_state(self, nguon):
        """``writeFileSync`` chỉ được ghi vào tệp TẠM, không ghi thẳng state."""
        for khop in re.finditer(r"fs\.writeFileSync\(\s*([A-Za-z_$][\w$]*)", nguon):
            assert khop.group(1) == "tam", (
                "fs.writeFileSync ghi thẳng vào %r thay vì tệp tạm — đó là "
                "read-modify-write, đúng lỗ mà bản vá này đóng" % khop.group(1)
            )

    def test_khoa_theo_TUNG_tai_khoan(self, nguon):
        """Khoá dẫn xuất từ tên tài khoản ⇒ hai tài khoản không chặn nhau."""
        assert re.search(r"function duongKhoa\(taiKhoan\)", nguon)
        assert "nhanTep(taiKhoan)" in nguon

    def test_fail_xac_dinh_co_du_bon_ma_phan_loai(self, nguon):
        """Một 401 trần không phân biệt được bốn nguyên nhân khác hẳn nhau."""
        for ma_loi in ("CORRUPT", "FUTURE", "KHOA_QUA_HAN", "CHO_QUA_HAN"):
            assert f'"{ma_loi}"' in nguon, f"mất mã phân loại lỗi {ma_loi}"

    def test_doc_ghi_state_khong_nuot_loi(self, nguon):
        """Bản cũ ``catch { return {} }`` — fail-OPEN có chủ ý, và nó SAI.

        Một tệp state hỏng khi ấy tắt CÂM LẶNG chống va cho mọi suite, với
        triệu chứng đúng bằng triệu chứng nó sinh ra để chữa. Ca này canh
        ĐÚNG hai hàm chạm đĩa, không canh cả tệp — những ``catch`` rỗng hợp lệ
        khác (đập nhịp, gỡ khoá đã bị thu hồi) không được phép làm nó đỏ.
        """
        for ten in ("docCounter", "ghiCounter"):
            than = _than_ham_js(nguon, ten)
            assert "return {}" not in than, f"{ten} vẫn nuốt lỗi thành giá trị rỗng"
            assert than.count("throw new LoiTotp") >= 2, (
                f"{ten} chỉ ném {than.count('throw new LoiTotp')} lần — "
                "có nhánh lỗi đang đi tiếp im lặng"
            )

    def test_giu_khoa_XUYEN_QUA_luot_gui(self, nguon):
        """``gui`` phải được ``await`` BÊN TRONG ``try`` của khoá.

        Buông khoá rồi mới gửi thì hai tiến trình có thể gửi NGƯỢC thứ tự, và
        backend từ chối khi ``counter <= counter_đã_lưu`` — tiến trình giữ
        counter nhỏ hơn đỏ dù không ai tiêu counter của nó.
        """
        than = nguon[nguon.index("async function voiMaTotp") :]
        than = than[: than.index("\nmodule.exports")]
        i_khoa = than.index("await datKhoa(")
        i_gui = than.index("await gui(")
        i_nha = than.index("khoa.nha()")
        assert i_khoa < i_gui < i_nha, (
            "thứ tự sai trong voiMaTotp: khoá=%d gửi=%d nhả=%d" % (i_khoa, i_gui, i_nha)
        )

    def test_cong_bo_counter_TRUOC_khi_gui(self, nguon):
        """Request hỏng giữa chừng vẫn có thể đã tiêu counter ở backend."""
        than = nguon[nguon.index("async function voiMaTotp") :]
        than = than[: than.index("\nmodule.exports")]
        assert than.index("ghiCounter(") < than.index("await gui("), (
            "counter được ghi SAU lượt gửi — một request hỏng giữa chừng vẫn "
            "tiêu counter ở backend, và tiến trình sau sẽ dùng lại nó"
        )

    def test_khai_bao_kieu_phu_KHOP_voi_export_that(self, node_bin):
        """``.d.ts`` là thứ TypeScript tin; ``.js`` là thứ Node chạy.

        Hai tệp trôi khỏi nhau là lỗi CÂM: consumer gọi một hàm mà `tsc` nói
        có, còn runtime thì `undefined`. Ca này so TẬP TÊN, không chỉ vài tên
        được nhớ tới lúc viết.
        """
        _phai_ton_tai(DIEU_PHOI_DTS, "khai báo kiểu của điều phối viên")
        js = (
            "console.log(JSON.stringify(Object.keys(require(%s)).sort()));"
            % json.dumps(str(DIEU_PHOI_JS))
        )
        kq = _node(node_bin, js, GOC, {})
        assert kq.returncode == 0, kq.stderr
        xuat_that = set(json.loads(kq.stdout.strip()))

        dts = DIEU_PHOI_DTS.read_text(encoding="utf-8")
        khai_bao = set(
            re.findall(r"export declare (?:function|const|class)\s+([A-Za-z_$][\w$]*)", dts)
        )
        assert xuat_that == khai_bao, (
            "lệch giữa .js và .d.ts — chỉ .js: %s | chỉ .d.ts: %s"
            % (sorted(xuat_that - khai_bao), sorted(khai_bao - xuat_that))
        )
        for ten in ("voiMaTotp", "duongState", "docCounter"):
            assert ten in xuat_that, f"thiếu {ten}"


# ===========================================================================
# Workflow — cổng phải NHÌN THẤY thứ nó canh
# ===========================================================================
@pytest.fixture(scope="module")
def than_wf() -> str:
    return _phai_ton_tai(DUONG_WF, "workflow nightly").read_text(encoding="utf-8")


class TestWorkflowGhimStateDir:
    def test_moi_buoc_dung_totp_deu_ghim_cung_state_dir(self, than_wf):
        """Tám bước: hai bước Python + sáu tiến trình Playwright.

        Một bước thiếu biến này là một tiến trình rơi về thư mục mặc định của
        riêng nó ⇒ nó KHÔNG thấy counter của bảy bước kia, và triệu chứng đúng
        bằng triệu chứng trước khi vá. Đếm là phần chịu lực: bản trước của lỗi
        này chính là "chỉ một suite được nối".
        """
        gia_tri = re.findall(rf"{BIEN_STATE_DIR}:\s*(\S.*?)\s*$", than_wf, re.M)
        assert len(gia_tri) == 8, (
            "%s xuất hiện %d lần, cần ĐÚNG 8 (2 bước gate Python + 6 bước "
            "Playwright): %r" % (BIEN_STATE_DIR, len(gia_tri), gia_tri)
        )
        assert len(set(gia_tri)) == 1, (
            "tám bước ghim %d giá trị khác nhau: %r" % (len(set(gia_tri)), set(gia_tri))
        )

    def test_sau_buoc_playwright_deu_co_bien(self, than_wf):
        """Buộc biến đi KÈM từng lệnh ``npx playwright test``.

        Ca trên đếm tổng; ca này soi ĐÚNG CHỖ. Gộp hai phép lại thì khi đỏ
        không biết đỏ vì thiếu bước nào hay vì thừa một khai báo ở chỗ khác.
        """
        khoi = than_wf.split("\n      - name:")
        thieu = []
        for k in khoi:
            if "npx playwright test" not in k:
                continue
            ten = k.split("\n", 1)[0].strip()
            if BIEN_STATE_DIR not in k:
                thieu.append(ten)
        assert not thieu, "bước Playwright thiếu %s: %s" % (BIEN_STATE_DIR, thieu)

    def test_hai_buoc_gate_python_deu_co_bien(self, than_wf):
        khoi = than_wf.split("\n      - name:")
        thay = []
        for k in khoi:
            if "nightly_mfa_gate.py" not in k:
                continue
            if "sync-casbin" in k or "preflight" in k:
                thay.append((k.split("\n", 1)[0].strip(), BIEN_STATE_DIR in k))
        assert len(thay) == 2, "thấy %d bước gate dùng TOTP, cần 2: %r" % (
            len(thay),
            thay,
        )
        assert all(co for _, co in thay), "bước gate thiếu %s: %r" % (
            BIEN_STATE_DIR,
            thay,
        )


# ===========================================================================
# Python ↔ Node phải là MỘT giao thức
# ===========================================================================
@pytest.fixture(scope="module")
def mfa_gate():
    duong = _phai_ton_tai(DUONG_MFA_GATE, "script cổng MFA nightly")
    spec = importlib.util.spec_from_file_location("nightly_mfa_gate_totp", duong)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def node_bin() -> str:
    duong = shutil.which("node")
    assert duong, (
        "không tìm thấy `node` trên PATH. KHÔNG skip: bất biến 'hai tiến trình "
        "không lấy cùng counter' chỉ chứng minh được bằng hai tiến trình thật; "
        "một lát CI không chạy được nó phải ĐỎ chứ không được im lặng xanh."
    )
    return duong


def _node(node_bin, ma_js: str, cwd: pathlib.Path, env: dict) -> subprocess.CompletedProcess:
    moi = dict(os.environ)
    moi.update(env)
    moi["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [node_bin, "-e", ma_js],
        cwd=str(cwd),
        env=moi,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


class TestParityPythonNode:
    #: 160 bit base32 không padding — đúng dạng mà `_decode_totp_secret` đòi.
    SECRET = "AAAQEAYEAUDAOCAJBIFQYDIOB4IBCEQT"

    def test_ma_node_va_python_trung_nhau(self, node_bin, mfa_gate):
        """Cùng secret + cùng counter ⇒ cùng sáu chữ số.

        Có ca này thì việc điều phối viên BỎ ``otpauth`` không phải là niềm
        tin. ``2**31 + 7`` nằm trong tập mẫu vì nó vượt 32 bit có dấu — đúng
        chỗ một phép dịch bit sai sẽ lộ ra.
        """
        counters = [0, 1, 42, 59_643_294, 2**31 + 7]
        js = (
            "const c=require(%s);"
            "console.log(JSON.stringify(%s.map(n=>c.sinhMaTheoCounter(%s,n))));"
            % (
                json.dumps(str(DIEU_PHOI_JS)),
                json.dumps(counters),
                json.dumps(self.SECRET),
            )
        )
        kq = _node(node_bin, js, GOC, {})
        assert kq.returncode == 0, f"node lỗi: {kq.stderr}"
        node_ma = json.loads(kq.stdout.strip())
        py_ma = [
            mfa_gate._totp_tu_counter(self.SECRET, "ca kiểm", n) for n in counters
        ]
        assert node_ma == py_ma, (
            "Node và Python sinh mã KHÁC nhau: %r ≠ %r" % (node_ma, py_ma)
        )

    def test_ten_tep_state_trung_nhau(self, node_bin, mfa_gate):
        """Hai bên phải trỏ vào ĐÚNG một tệp, nếu không thì không chia sẻ gì."""
        tai_khoan = ["admin", "vothithuthuhien", "Nguyễn Văn A", "a" * 60]
        js = (
            "const c=require(%s);const path=require('path');"
            "console.log(JSON.stringify(%s.map(u=>path.basename(c.duongState(u)))));"
            % (json.dumps(str(DIEU_PHOI_JS)), json.dumps(tai_khoan))
        )
        kq = _node(node_bin, js, GOC, {})
        assert kq.returncode == 0, f"node lỗi: {kq.stderr}"
        node_ten = json.loads(kq.stdout.strip())
        py_ten = [f"{mfa_gate._nhan_tep_totp(u)}.counter" for u in tai_khoan]
        assert node_ten == py_ten, (
            "tên tệp state lệch giữa Node và Python: %r ≠ %r" % (node_ten, py_ten)
        )

    def test_python_doc_duoc_state_do_node_ghi(self, node_bin, mfa_gate, tmp_path):
        """Vòng khép kín chiều NODE → PYTHON."""
        js = (
            "const c=require(%s);"
            "c.datChoCounter('admin').then(r=>console.log(JSON.stringify(r)));"
            % json.dumps(str(DIEU_PHOI_JS))
        )
        kq = _node(node_bin, js, GOC, {BIEN_STATE_DIR: str(tmp_path)})
        assert kq.returncode == 0, f"node lỗi: {kq.stderr}"
        counter_node = json.loads(kq.stdout.strip())["counter"]
        duong = mfa_gate._duong_state_totp(tmp_path, "admin")
        assert mfa_gate._doc_counter_chung(duong) == counter_node

    def test_hai_ben_dong_y_nguong_khoa_mo_coi(self, node_bin, mfa_gate):
        """Ngưỡng có hiệu lực là ngưỡng của KẺ THU HỒI.

        Hai bên lệch nhau ⇒ bên khắt khe hơn cướp khoá của bên kia trong khi
        bên kia CÒN SỐNG và đang chờ gửi ``/verify-mfa`` — và lúc ấy hai tiến
        trình cùng tiến tới counter, đúng thứ cả bản vá này chống.

        Ngưỡng cũng phải phủ khoảng KHÔNG chạm khoá dài nhất phía Python:
        ``TOTP_MIN_REMAINING_SECONDS`` (căn mép cửa sổ) + ``HTTP_TIMEOUT_SECONDS``.
        """
        js = (
            "const c=require(%s);"
            "console.log(JSON.stringify({moCoi:c.KHOA_MO_COI_MS,han:c.KHOA_HAN_MS}));"
            % json.dumps(str(DIEU_PHOI_JS))
        )
        kq = _node(node_bin, js, GOC, {})
        assert kq.returncode == 0, kq.stderr
        node_hang = json.loads(kq.stdout.strip())

        assert node_hang["moCoi"] == mfa_gate.TOTP_KHOA_MO_COI_GIAY * 1000, (
            "ngưỡng khoá mồ côi lệch: Node %sms vs Python %ss"
            % (node_hang["moCoi"], mfa_gate.TOTP_KHOA_MO_COI_GIAY)
        )
        assert node_hang["han"] == mfa_gate.TOTP_KHOA_HAN_GIAY * 1000, (
            "hạn đặt khoá lệch: Node %sms vs Python %ss"
            % (node_hang["han"], mfa_gate.TOTP_KHOA_HAN_GIAY)
        )

        khoang_mu_python = (
            mfa_gate.TOTP_MIN_REMAINING_SECONDS
            + mfa_gate.TOTP_BOUNDARY_OVERSHOOT_SECONDS
            + mfa_gate.HTTP_TIMEOUT_SECONDS
        )
        assert mfa_gate.TOTP_KHOA_MO_COI_GIAY > khoang_mu_python, (
            "ngưỡng mồ côi %ss KHÔNG phủ nổi khoảng không-chạm-khoá dài nhất "
            "của Python (%.2fs) — một tiến trình Node sẽ cướp khoá của một "
            "tiến trình Python còn sống"
            % (mfa_gate.TOTP_KHOA_MO_COI_GIAY, khoang_mu_python)
        )
        assert mfa_gate.TOTP_KHOA_HAN_GIAY > mfa_gate.TOTP_KHOA_MO_COI_GIAY, (
            "hạn đặt khoá phải lớn hơn ngưỡng mồ côi, nếu không kẻ chờ bỏ cuộc "
            "TRƯỚC khi kịp thu hồi một khoá thật sự mồ côi"
        )

    def test_node_thay_counter_do_python_cong_bo(self, node_bin, mfa_gate, tmp_path):
        """Vòng khép kín chiều PYTHON → NODE — chiều CHỊU LỰC của lượt nightly.

        Trong workflow, ``sync-casbin`` và ``preflight`` chạy TRƯỚC cả sáu bước
        Playwright. Nếu Node không thấy counter mà Python vừa đốt thì suite đầu
        tiên dùng lại đúng nó, và đó chính là bốn dòng "MFA failed for admin
        (401)" của run 34678745325.

        Hằng số ``+2`` là phần chịu lực: backend từ chối khi
        ``counter <= counter_đã_lưu`` (ĐƠN ĐIỆU NGHIÊM NGẶT), nên "lớn hơn" mới
        đúng, "lớn hơn hoặc bằng" là sai.
        """
        duong = mfa_gate._duong_state_totp(tmp_path, "admin")
        moc = int(time.time() // 30)
        mfa_gate._ghi_counter_chung(duong, moc)
        assert duong.read_text(encoding="utf-8") == f"{moc}\n"

        js = (
            "const c=require(%s);"
            "console.log(JSON.stringify({daThay:c.docCounter('admin')}));"
            % json.dumps(str(DIEU_PHOI_JS))
        )
        kq = _node(node_bin, js, GOC, {BIEN_STATE_DIR: str(tmp_path)})
        assert kq.returncode == 0, f"node lỗi: {kq.stderr}"
        assert json.loads(kq.stdout.strip())["daThay"] == moc, (
            "Node KHÔNG đọc được counter do Python công bố"
        )

    def test_python_dang_nhap_cong_bo_counter_vao_state_dung(
        self, mfa_gate, tmp_path, monkeypatch
    ):
        """Chạy THẬT ``_dang_nhap_va_chung_minh`` và đọc tệp state sau đó.

        Ca cấu trúc (``test_python_gate_khong_tu_tinh_counter_ngoai_giao_thuc``)
        chỉ chứng minh mã có mặt; ca này chứng minh nó CHẠY và ghi đúng chỗ —
        đúng tệp mà điều phối viên phía Node sẽ đọc.
        """
        monkeypatch.setenv(BIEN_STATE_DIR, str(tmp_path))
        phan_hoi = [
            (200, {"mfa_required": True, "mfa_token": "challenge"}),
            (401, {"detail": "Not authenticated"}),
            (200, {"user": {"role": "admin"}}),
        ]
        da_gui: list[tuple] = []

        def gia_request(opener, method, url, **kwargs):
            da_gui.append((method, url, kwargs))
            return phan_hoi.pop(0)

        monkeypatch.setattr(mfa_gate, "_request_json", gia_request)
        monkeypatch.setattr(
            mfa_gate, "_totp_for_preflight", lambda *a: ("123456", 55_000_000)
        )

        phien = mfa_gate._dang_nhap_va_chung_minh(
            ("admin", "nguoi-dung-thu", "matkhau", "admin", "A" * 32),
            "http://localhost:8000",
        )
        assert phien.counter_da_tieu == 55_000_000

        duong = mfa_gate._duong_state_totp(tmp_path, "nguoi-dung-thu")
        assert duong.is_file(), "counter KHÔNG được công bố vào state dùng chung"
        assert duong.read_text(encoding="utf-8") == "55000000\n"

        # Khoá phải được NHẢ sau khi xong — nếu không, bước Playwright kế tiếp
        # sẽ chờ tới hết hạn rồi đỏ vì một lý do không liên quan.
        assert not mfa_gate._duong_khoa_totp(tmp_path, "nguoi-dung-thu").exists()

        # Và state KHÔNG chứa secret (ở đây secret là chuỗi "AAAA…").
        assert "A" * 32 not in duong.read_text(encoding="utf-8")


# ===========================================================================
# NGUYÊN TỬ — hai tiến trình THẬT
# ===========================================================================
def _chay_cli(node_bin, tmp_path, tai_khoan, them_env=None, timeout=120):
    env = dict(os.environ)
    env[BIEN_STATE_DIR] = str(tmp_path)
    env["PYTHONIOENCODING"] = "utf-8"
    if them_env:
        env.update(them_env)
    return subprocess.Popen(
        [node_bin, str(RESERVE_CLI), tai_khoan],
        cwd=str(GOC),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )


class TestDatChoNguyenTu:
    def test_hai_tien_trinh_cung_tai_khoan_khong_lay_cung_counter(
        self, node_bin, tmp_path
    ):
        """Bất biến CHỊU LỰC của cả bản vá.

        Hai tiến trình ``node`` khởi động cùng lúc, cùng tài khoản, cùng thư
        mục state. Bản read-modify-write cũ cho HAI counter BẰNG NHAU ở đây.
        """
        _phai_ton_tai(RESERVE_CLI, "CLI đặt chỗ counter")
        p1 = _chay_cli(node_bin, tmp_path, "admin")
        p2 = _chay_cli(node_bin, tmp_path, "admin")
        ra1, loi1 = p1.communicate(timeout=120)
        ra2, loi2 = p2.communicate(timeout=120)
        assert p1.returncode == 0, f"tiến trình 1 đỏ: {ra1} {loi1}"
        assert p2.returncode == 0, f"tiến trình 2 đỏ: {ra2} {loi2}"
        j1, j2 = json.loads(ra1.strip()), json.loads(ra2.strip())
        assert j1["ok"] and j2["ok"], (j1, j2)
        assert j1["pid"] != j2["pid"], "hai lượt chạy trong CÙNG một tiến trình"
        assert j1["counter"] != j2["counter"], (
            "HAI TIẾN TRÌNH LẤY CÙNG COUNTER %d — chống replay của backend sẽ "
            "từ chối lượt gửi sau" % j1["counter"]
        )

    def test_counter_da_cong_bo_bang_gia_tri_lon_hon(self, node_bin, tmp_path):
        """State phải giữ giá trị LỚN HƠN — ghi lùi là mở lại cửa sổ va chạm."""
        p1 = _chay_cli(node_bin, tmp_path, "admin")
        p2 = _chay_cli(node_bin, tmp_path, "admin")
        j1 = json.loads(p1.communicate(timeout=120)[0].strip())
        j2 = json.loads(p2.communicate(timeout=120)[0].strip())
        tep = list(tmp_path.glob("admin.*.counter"))
        assert len(tep) == 1, "thấy %d tệp counter, cần đúng 1: %r" % (len(tep), tep)
        assert int(tep[0].read_text(encoding="utf-8").strip()) == max(
            j1["counter"], j2["counter"]
        )

    def test_hai_tai_khoan_khac_nhau_khong_chan_nhau(self, node_bin, tmp_path):
        """ĐỘC LẬP — đo bằng CẤU TRÚC, không bằng đồng hồ.

        Một phép đo theo thời gian ("B xong nhanh hơn A") là race trá hình.
        Thay vào đó: giữ khoá của ``admin`` bằng một tệp khoá TƯƠI, rồi
        chứng minh (a) ``manager`` vẫn đặt chỗ được, (b) ``admin`` thì ĐỎ với
        đúng mã ``KHOA_QUA_HAN``. Hai kết luận ngược nhau từ cùng một trạng
        thái — không có cách nào cả hai cùng đúng do may.
        """
        khoa_admin = tmp_path / "admin.8c6976e5.lock"
        khoa_admin.write_text("999999 giu-boi-ca-kiem\n", encoding="utf-8")
        os.utime(khoa_admin, None)

        p_mgr = _chay_cli(
            node_bin, tmp_path, "manager", {"QLTS_TOTP_LOCK_TIMEOUT_MS": "3000"}
        )
        ra_mgr = p_mgr.communicate(timeout=60)[0]
        assert p_mgr.returncode == 0, f"tài khoản ĐỘC LẬP bị chặn: {ra_mgr}"
        assert json.loads(ra_mgr.strip())["ok"] is True

        # Khoá phải còn TƯƠI khi `admin` thử — chạm lại ngay trước lượt chạy.
        os.utime(khoa_admin, None)
        p_adm = _chay_cli(
            node_bin,
            tmp_path,
            "admin",
            {"QLTS_TOTP_LOCK_TIMEOUT_MS": "2000", "QLTS_TOTP_LOCK_STALE_MS": "60000"},
        )
        ra_adm = p_adm.communicate(timeout=60)[0]
        assert p_adm.returncode == 1, (
            "khoá đang bị giữ mà vẫn đặt chỗ được ⇒ khoá không có tác dụng: %s"
            % ra_adm
        )
        assert json.loads(ra_adm.strip())["ma"] == "KHOA_QUA_HAN", ra_adm

    def test_khoa_mo_coi_duoc_thu_hoi(self, node_bin, tmp_path):
        """Tiến trình chết giữa chừng KHÔNG được treo cả lượt nightly.

        An toàn vì counter được công bố TRƯỚC lượt gửi: chủ khoá chết trước
        khi công bố thì chưa gửi mã nào đi.
        """
        khoa = tmp_path / "admin.8c6976e5.lock"
        khoa.write_text("999999 chu-cu-da-chet\n", encoding="utf-8")
        cu = time.time() - 600
        os.utime(khoa, (cu, cu))
        p = _chay_cli(node_bin, tmp_path, "admin", {"QLTS_TOTP_LOCK_TIMEOUT_MS": "5000"})
        ra = p.communicate(timeout=60)[0]
        assert p.returncode == 0, ra
        j = json.loads(ra.strip())
        assert j["ok"] and j["thuHoi"] == 1, "khoá mồ côi không bị thu hồi: %r" % j


# ===========================================================================
# FAIL XÁC ĐỊNH
# ===========================================================================
class TestFailXacDinh:
    @pytest.mark.parametrize(
        "noi_dung,ma_mong_doi",
        [
            ("khong-phai-so\n", "CORRUPT"),
            ('{"admin": 123}\n', "CORRUPT"),
            ("", "CORRUPT"),
            ("-5\n", "CORRUPT"),
            ("12 34\n", "CORRUPT"),
        ],
    )
    def test_state_hong_thi_do_voi_ma_CORRUPT(
        self, node_bin, tmp_path, noi_dung, ma_mong_doi
    ):
        """Bản cũ nuốt hết bằng ``catch { return {} }`` — fail-OPEN có chủ ý.

        Hệ quả: một tệp hỏng tắt câm lặng chống va cho MỌI suite, và triệu
        chứng đúng bằng triệu chứng nó sinh ra để chữa.
        """
        (tmp_path / "admin.8c6976e5.counter").write_text(noi_dung, encoding="utf-8")
        p = _chay_cli(node_bin, tmp_path, "admin")
        ra = p.communicate(timeout=60)[0]
        assert p.returncode == 1, "state hỏng mà vẫn đi tiếp: %s" % ra
        assert json.loads(ra.strip())["ma"] == ma_mong_doi, ra

    def test_state_o_tuong_lai_thi_do_voi_ma_FUTURE(self, node_bin, tmp_path):
        """Chờ thì có thể hàng giờ; đi tiếp thì chắc chắn 401. Phải ĐỎ.

        Một counter vượt đồng hồ nghĩa là lệch đồng hồ giữa runner hoặc có kẻ
        ghi ngoài giao thức — cả hai là sự cố thật, không phải thứ để ngủ qua.
        """
        tuong_lai = int(time.time() // 30) + 500
        (tmp_path / "admin.8c6976e5.counter").write_text(
            f"{tuong_lai}\n", encoding="utf-8"
        )
        p = _chay_cli(node_bin, tmp_path, "admin")
        ra = p.communicate(timeout=60)[0]
        assert p.returncode == 1, "state ở tương lai mà vẫn đi tiếp: %s" % ra
        assert json.loads(ra.strip())["ma"] == "FUTURE", ra

    def test_state_CU_khong_phai_loi(self, node_bin, tmp_path):
        """Ca ĐỐI — "lâu rồi không ai đăng nhập" phải đi tiếp bình thường.

        Không có ca này thì một guard quá tay (đỏ với MỌI state lệch) vẫn
        xanh, và nó sẽ làm đỏ mọi lượt nightly thứ hai trở đi.
        """
        cu = int(time.time() // 30) - 100_000
        (tmp_path / "admin.8c6976e5.counter").write_text(f"{cu}\n", encoding="utf-8")
        p = _chay_cli(node_bin, tmp_path, "admin")
        ra = p.communicate(timeout=60)[0]
        assert p.returncode == 0, "state CŨ bị coi là lỗi: %s" % ra
        j = json.loads(ra.strip())
        assert j["counter"] > cu

    def test_python_cung_fail_xac_dinh_tren_state_hong(self, mfa_gate, tmp_path):
        """Hai bên cùng giao thức thì cũng phải cùng thái độ với tệp hỏng."""
        duong = mfa_gate._duong_state_totp(tmp_path, "admin")
        duong.write_text("khong-phai-so\n", encoding="utf-8")
        with pytest.raises(mfa_gate.GateError, match="số nguyên thập phân"):
            mfa_gate._doc_counter_chung(duong)

    def test_python_khong_ghi_lui_counter(self, mfa_gate, tmp_path):
        duong = mfa_gate._duong_state_totp(tmp_path, "admin")
        mfa_gate._ghi_counter_chung(duong, 100)
        mfa_gate._ghi_counter_chung(duong, 50)
        assert mfa_gate._doc_counter_chung(duong) == 100
        mfa_gate._ghi_counter_chung(duong, 101)
        assert mfa_gate._doc_counter_chung(duong) == 101

    def test_python_khoa_cung_la_O_EXCL(self, mfa_gate, tmp_path):
        """Khoá thứ hai trên CÙNG tài khoản phải ĐỎ, không được đi tiếp."""
        with mfa_gate._khoa_tai_khoan_totp(tmp_path, "admin"):
            truoc = mfa_gate.TOTP_KHOA_HAN_GIAY
            mfa_gate.TOTP_KHOA_HAN_GIAY = 0.5
            try:
                with pytest.raises(mfa_gate.GateError, match="không đặt được khoá"):
                    with mfa_gate._khoa_tai_khoan_totp(tmp_path, "admin"):
                        pass
                # ... nhưng tài khoản KHÁC thì vào được ngay.
                with mfa_gate._khoa_tai_khoan_totp(tmp_path, "manager"):
                    pass
            finally:
                mfa_gate.TOTP_KHOA_HAN_GIAY = truoc


# ===========================================================================
# BÍ MẬT — đọc NỘI DUNG THẬT của tệp, không tin thiết kế
# ===========================================================================
class TestStateKhongChuaBiMat:
    SECRET = "AAAQEAYEAUDAOCAJBIFQYDIOB4IBCEQT"

    def test_thu_muc_state_chi_chua_so_va_khoa(self, node_bin, mfa_gate, tmp_path):
        """Sau một lượt đặt chỗ THẬT có sinh mã, quét TỪNG BYTE của thư mục.

        Không đọc lại thiết kế — đọc tệp. Kiểm cả secret lẫn mã TOTP mà chính
        lượt ấy sinh ra: mã còn hiệu lực tới hết cửa sổ 30 giây, nên nó cũng
        là bí mật ngắn hạn.
        """
        p = subprocess.run(
            [
                node_bin,
                str(RESERVE_CLI),
                "admin",
                "--ma-secret",
                self.SECRET,
            ],
            cwd=str(GOC),
            env={**os.environ, BIEN_STATE_DIR: str(tmp_path)},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        assert p.returncode == 0, p.stdout + p.stderr
        j = json.loads(p.stdout.strip())
        ma_totp = mfa_gate._totp_tu_counter(self.SECRET, "ca kiểm", j["counter"])
        assert (
            hashlib.sha256(ma_totp.encode()).hexdigest() == j["code_sha256"]
        ), "CLI và Python sinh mã khác nhau cho cùng counter"

        tep = sorted(x for x in tmp_path.rglob("*") if x.is_file())
        assert tep, "không tệp nào được tạo — lượt đặt chỗ đã không xảy ra"
        for x in tep:
            tho = x.read_bytes()
            assert self.SECRET.encode() not in tho, f"{x.name} CHỨA SECRET TOTP"
            assert ma_totp.encode() not in tho, f"{x.name} chứa mã TOTP còn hiệu lực"
            if x.name.endswith(".counter"):
                assert re.fullmatch(rb"[0-9]+\n", tho), (
                    "%s không chỉ chứa một số: %r" % (x.name, tho[:40])
                )

    def test_stdout_cua_cli_khong_mang_ma_totp(self, node_bin, tmp_path):
        """Dòng JSON đi thẳng vào log CI — nó chỉ được mang BĂM, không mang mã."""
        p = subprocess.run(
            [node_bin, str(RESERVE_CLI), "admin", "--ma-secret", self.SECRET],
            cwd=str(GOC),
            env={**os.environ, BIEN_STATE_DIR: str(tmp_path)},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        assert p.returncode == 0
        assert self.SECRET not in p.stdout
        j = json.loads(p.stdout.strip())
        assert set(j) <= {"ok", "counter", "thuHoi", "pid", "code_sha256"}

    def test_loi_cua_dieu_phoi_khong_in_secret(self, node_bin, tmp_path):
        """Secret hỏng ⇒ chỉ được nói ĐỘ DÀI, không được nói giá trị."""
        js = (
            "const c=require(%s);"
            "try{c.sinhMaTheoCounter('KHONG-PHAI-BASE32-@@@',1)}"
            "catch(e){console.log(JSON.stringify({ma:e.ma,msg:e.message}))}"
            % json.dumps(str(DIEU_PHOI_JS))
        )
        kq = _node(node_bin, js, GOC, {BIEN_STATE_DIR: str(tmp_path)})
        assert kq.returncode == 0, kq.stderr
        j = json.loads(kq.stdout.strip())
        assert j["ma"] == "SECRET"
        assert "KHONG-PHAI-BASE32" not in j["msg"], j["msg"]


# ===========================================================================
# KIỂM NGƯỢC — guard phải ĐỎ khi bất biến bị phá
# ===========================================================================
class TestKiemNguocGuardCoRang:
    """Mỗi ca phá ĐÚNG MỘT bất biến, và biến thể phá là bản TINH VI NHẤT.

    Chạy trên một bản sao trong bộ nhớ, không chạm cây làm việc — nhưng đi qua
    ĐÚNG hàm mà ca thật dùng, nên nó không thể xanh trong khi ca thật mù.
    """

    def _quet(self, ma: str) -> dict[str, bool]:
        sach = boc_chu_thich(ma)
        return {
            "kk1": bool(RE_VERIFY_MFA.search(sach))
            and not any(f"{t}(" in sach for t in CUA_DIEU_PHOI),
            "kk2": bool(RE_IMPORT_OTPAUTH.search(sach)),
            "kk3": bool(RE_GENERATE_TOTP.search(sach) or RE_TOTP_CTOR.search(sach)),
            "kk4": bool(RE_NGU_31.search(sach)),
        }

    def test_consumer_quay_lai_goi_generateTOTP_thi_guard_do(self):
        """Ca kiểm ngược mà đề bài đòi đích danh."""
        tai_pham = """
import * as OTPAuth from "otpauth";
function generateTOTP(secret: string): string {
  return new OTPAuth.TOTP({ secret: OTPAuth.Secret.fromBase32(secret) }).generate();
}
const r = await page.request.post(`${API_URL}/api/auth/verify-mfa`, {
  data: { mfa_token: t, code: generateTOTP(s) },
});
"""
        kq = self._quet(tai_pham)
        assert kq["kk1"], "KK1 mù: chạm verify-mfa mà không qua điều phối viên"
        assert kq["kk2"], "KK2 mù: import otpauth"
        assert kq["kk3"], "KK3 mù: generateTOTP cục bộ"

    def test_bien_the_TINH_VI_doi_ten_ham_van_bi_bat(self):
        """Đổi tên hàm để né KK3 thì KK1 và KK2 vẫn phải bắt.

        Đây là biến thể tinh vi nhất mà một người "chỉ muốn cho nhanh" sẽ viết:
        không có chữ ``generateTOTP`` nào cả.
        """
        tai_pham = """
import * as OTPAuth from "otpauth";
const maNhanh = (s: string) =>
  new OTPAuth.TOTP({ secret: OTPAuth.Secret.fromBase32(s) }).generate();
await page.request.post(`${API_URL}/api/auth/verify-mfa`, {
  data: { mfa_token: t, code: maNhanh(s) },
});
"""
        kq = self._quet(tai_pham)
        assert kq["kk3"], "KK3 mù với `new OTPAuth.TOTP` khi tên hàm đã đổi"
        assert kq["kk2"], "KK2 mù: vẫn còn import otpauth"
        assert kq["kk1"], "KK1 mù: vẫn chạm verify-mfa ngoài điều phối viên"

    def test_bien_the_TINH_VI_giu_dieu_phoi_nhung_them_retry_mu(self):
        """Vi phạm DUY NHẤT là retry — mọi thứ khác đúng chuẩn.

        Nếu ca này xanh thì KK4 chỉ đang ăn theo ba ca kia (luật
        ``composite-check-hides-what-it-guards``).
        """
        tai_pham = """
import { xacThucMfa } from "./helpers/e2e-fixtures";
try {
  authResp = await xacThucMfa(u, s, t, (p) =>
    page.request.post(`${API_URL}/api/auth/verify-mfa`, { data: p }));
} catch {
  await page.waitForTimeout(31_000);
  continue;
}
"""
        kq = self._quet(tai_pham)
        assert kq["kk4"], "KK4 mù với retry 31 giây"
        assert not kq["kk1"], "KK1 báo động giả: mã này CÓ đi qua điều phối viên"
        assert not kq["kk2"] and not kq["kk3"], "KK2/KK3 báo động giả"

    def test_khong_bao_dong_gia_tren_chu_thich(self):
        """Lời giải thích vì sao cấm KHÔNG được làm guard đỏ.

        Đây là nửa còn lại của "guard phải có răng": một guard đỏ vì chú thích
        sẽ bị nới, và bản nới sẽ mù thật.
        """
        lanh = """
// Không được `import "otpauth"`, không được `generateTOTP` cục bộ,
/* và không được gọi thẳng /api/auth/verify-mfa. */
import { xacThucMfa } from "./helpers/e2e-fixtures";
await xacThucMfa(u, s, t, (p) => ctx.post(URL_MFA, { data: p }));
"""
        kq = self._quet(lanh)
        assert not any(kq.values()), "guard đỏ vì CHÚ THÍCH: %r" % kq

    def test_boc_chu_thich_giu_nguyen_chuoi(self):
        """Chuỗi phải sống sót — nếu không thì che bằng chuỗi là né được guard."""
        ma = 'const u = "/api/auth/verify-mfa"; // chú thích bị xoá\n'
        sach = boc_chu_thich(ma)
        assert "/api/auth/verify-mfa" in sach
        assert "chú thích bị xoá" not in sach
        assert sach.count("\n") == ma.count("\n"), "số dòng bị lệch sau khi bóc"


# ===========================================================================
# Số lượng — cổng phải biết nó đang canh BAO NHIÊU thứ
# ===========================================================================
def test_so_luong_consumer_khong_tu_nhien_tut_xuong(ma_e2e):
    """Một thư mục bị đổi chỗ làm mọi ca trên xanh vì KHÔNG QUÉT GÌ CẢ.

    Ca này là hàng rào chống đúng kiểu xanh-rỗng ấy: đếm số tệp thực sự chạm
    ``/api/auth/verify-mfa`` và đòi nó không tụt dưới mức đã đo (17 tệp
    consumer + ``helpers/e2e-fixtures.ts``).
    """
    cham = [p for p, ma in ma_e2e.items() if RE_VERIFY_MFA.search(ma)]
    assert len(cham) >= 17, (
        "chỉ %d tệp chạm /api/auth/verify-mfa (đo được 17+ lúc viết ca này) — "
        "kiểm xem thư mục consumer có còn ở %s không" % (len(cham), THU_MUC_E2E)
    )


def test_python_gate_khong_tu_tinh_counter_ngoai_giao_thuc(mfa_gate):
    """``_dang_nhap_va_chung_minh`` phải công bố counter nó vừa đốt.

    Không có ca này thì phía Python có thể lặng lẽ quay về tự tính counter
    riêng — đúng lỗ #2 ở đầu tệp, chỉ đổi bên.
    """
    import inspect

    nguon = inspect.getsource(mfa_gate._dang_nhap_va_chung_minh)
    assert "_khoa_tai_khoan_totp" in nguon, "Python không còn giữ khoá tài khoản"
    assert "_ghi_counter_chung" in nguon, "Python không còn công bố counter"
    i_ghi = nguon.index("_ghi_counter_chung")
    i_gui = nguon.index("/api/auth/verify-mfa")
    assert i_ghi < i_gui, (
        "Python công bố counter SAU lượt gửi — request hỏng giữa chừng vẫn "
        "tiêu counter ở backend"
    )
