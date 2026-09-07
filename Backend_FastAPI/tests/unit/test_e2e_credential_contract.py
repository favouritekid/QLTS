# tests/unit/test_e2e_credential_contract.py
# -*- coding: utf-8 -*-
"""Khoá tài khoản E2E: workflow ↔ consumer ↔ workbook seed phải nói CÙNG một thứ.

Vì sao tệp này tồn tại — sự cố nightly run ``34092354121`` (SHA ``d91b8c32``):
cả **sáu** suite E2E đỏ, 0 tín hiệu test, chỉ vì ba nguồn nói ba giọng.

* Workflow chỉ khai ``TEST_USERNAME`` / ``TEST_PASSWORD``.
* Mọi spec workflow lại đọc ``E2E_ADMIN_*`` / ``E2E_OFFICER_*``.
* Thiếu biến ⇒ spec rơi về literal cứng: ``admin`` / ``Admin@12345`` (mật khẩu
  SAI — seed là ``Admin@123``) và ``vothuhien`` / ``@Matkhau123!`` (tài khoản
  KHÔNG TỒN TẠI — officer thật là ``vothithuthuhien``).

Hai chuỗi 401 ấy kích ``ACCOUNT_LOCKOUT_MAX_ATTEMPTS=5`` ⇒ khoá 15 phút ⇒ 429 ⇒
``loginViaAPI`` retry 65s × 3. Suite ``finance`` đốt 652 giây để không đo được gì.

⚠️ **TỆP NÀY KHÔNG ĐƯỢC PHÉP SKIP.** Nó là hợp đồng xác thực; nếu nguồn chuẩn
(workbook), tệp cấu hình (workflow), thư mục consumer, hay thư viện đọc workbook
biến mất, phép kiểm phải **ĐỎ**, không được biến thành ``skipped``. GitHub coi
check ``skipped`` là thành công — một hợp đồng tự tan thành skip đúng lúc nguồn
chuẩn của nó mất là fail-open, đúng lớp lỗi mà PR này sinh ra để đóng. Vì vậy ở
đây **không có** ``pytest.skip`` và **không có** ``importorskip``.

Năm bất biến, mỗi cái một ca riêng — gộp lại thì phép kiểm vẫn xanh khi vài cái
đã hỏng:

* **C1**  mọi biến credential mà consumer ĐỌC đều phải được workflow KHAI
  (trừ biến có ``test.skip`` bảo vệ — tính bằng mã, không liệt kê tay);
* **C1b** tên biến ``E2E_*`` phải theo lược đồ — bắt ca *sai tên*, thứ C1 mù;
* **C2**  workflow phải khai ĐỦ TÁM khoá, và mỗi giá trị phải BẰNG đúng hàng
  workbook, ghép theo vai;
* **C3**  literal fallback phải ghép ĐÚNG CẶP username↔password của cùng một
  hàng workbook — không chỉ "có mặt đâu đó";
* **MANAGER** phải được khai, nếu không ca IDOR skip thành xanh giả.
"""
import pathlib
import re

import openpyxl  # KHÔNG importorskip: thiếu nó là hợp đồng hỏng, phải ĐỎ.
import pytest

pytestmark = pytest.mark.unit


def _goc_repo() -> pathlib.Path:
    for cha in pathlib.Path(__file__).resolve().parents:
        if (cha / ".github" / "workflows").is_dir():
            return cha
    raise AssertionError(
        "không tìm được gốc repo (thư mục chứa .github/workflows). Hợp đồng "
        "credential KHÔNG được skip khi thiếu — nó phải đỏ.")


GOC = _goc_repo()

DUONG_WF = GOC / ".github" / "workflows" / "nightly-regression.yml"
DUONG_XLSX = GOC / "Backend_FastAPI" / "seed_data_template.xlsx"
THU_MUC_E2E = GOC / "frontend" / "src" / "test" / "e2e"

#: ``auth.setup.ts`` nằm trong tập consumer vì project ``chromium`` khai
#: ``dependencies: ['setup']`` — nó là đường tạo ``storageState`` cho mọi spec
#: dùng project ấy. Bỏ sót nó thì hợp đồng không canh chính đường đăng nhập
#: DUY NHẤT đã hoạt động trong run 34092354121.
CONSUMER_NGOAI_SPEC = ("auth.setup.ts",)

MAU_BIEN = re.compile(r"\bE2E_[A-Z]+_(?:USERNAME|PASSWORD)\b|\bTEST_(?:USERNAME|PASSWORD)\b")

#: Tám khoá BẮT BUỘC. Danh sách đóng và tường minh: nếu chỉ kiểm "khoá nào có
#: mặt thì phải đúng", xoá cả cụm ``TEST_*`` vẫn xanh.
KHOA_BAT_BUOC = (
    "E2E_ADMIN_USERNAME", "E2E_ADMIN_PASSWORD",
    "E2E_OFFICER_USERNAME", "E2E_OFFICER_PASSWORD",
    "E2E_MANAGER_USERNAME", "E2E_MANAGER_PASSWORD",
    "TEST_USERNAME", "TEST_PASSWORD",
)

#: ``(khoá username, khoá password)`` → vai trò trong cột ``vai_tro``.
#: ``TEST_*`` trỏ officer vì ``auth.setup.ts`` đăng nhập bằng tài khoản officer.
CAP_THEO_VAI = {
    ("E2E_ADMIN_USERNAME", "E2E_ADMIN_PASSWORD"): "admin",
    ("E2E_OFFICER_USERNAME", "E2E_OFFICER_PASSWORD"): "officer",
    ("E2E_MANAGER_USERNAME", "E2E_MANAGER_PASSWORD"): "manager",
    ("TEST_USERNAME", "TEST_PASSWORD"): "officer",
}

#: Cặp hằng trong consumer: hằng username ↔ hằng password của cùng một vai,
#: **và vai trò mà hàng workbook ấy PHẢI có**.
#:
#: Vai trò là phần thứ ba, không phải trang trí: một cặp username/password
#: "đăng nhập được" chưa chứng minh gì về QUYỀN. Đổi cả cặp fallback của ADMIN
#: sang một cặp officer hợp lệ thì đăng nhập vẫn 200, C3 vẫn xanh, mà spec chạy
#: kịch bản admin dưới quyền officer — hoặc 403 hàng loạt, hoặc tệ hơn: khẳng
#: định về quyền được đo trên sai chủ thể. ``CTV`` không có trong seed nên để
#: ``None`` (fallback của nó là chuỗi rỗng, đã được ``test.skip`` bảo vệ).
VAI_CUA_TIEN_TO = {"ADMIN": "admin", "OFFICER": "officer", "MANAGER": "manager",
                   "CTV": None}
TIEN_TO_HANG = tuple(VAI_CUA_TIEN_TO)

#: ``auth.setup.ts`` dùng cặp hằng không mang tiền tố vai; nó đăng nhập bằng
#: tài khoản OFFICER để dựng ``storageState``.
VAI_CUA_SETUP = "officer"

HAU_TO_HOP_LE = ("USERNAME", "PASSWORD", "TOTP_SECRET", "MFA_CODE")
BIEN_E2E_KHAC_CHO_PHEP = {"E2E_API_URL"}
VAI_HOP_LE = ("ADMIN", "OFFICER", "MANAGER", "CTV")


def _phai_ton_tai(p: pathlib.Path, mo_ta: str) -> pathlib.Path:
    assert p.exists(), (
        f"thiếu {mo_ta}: {p}\n"
        "Hợp đồng credential phải ĐỎ khi nguồn chuẩn biến mất — skip ở đây là "
        "fail-open, vì GitHub coi check `skipped` là thành công.")
    return p


@pytest.fixture(scope="module")
def than_wf() -> str:
    return _phai_ton_tai(DUONG_WF, "workflow nightly").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def env_wf(than_wf) -> dict[str, str]:
    """Cặp ``KEY: value`` trong khối ``env:`` cấp job của workflow nightly."""
    ra: dict[str, str] = {}
    for dong in than_wf.splitlines():
        m = re.match(r"^\s{6}([A-Z][A-Z0-9_]*):\s*(.+?)\s*$", dong)
        if m and MAU_BIEN.fullmatch(m.group(1)):
            ra[m.group(1)] = m.group(2)
    return ra


@pytest.fixture(scope="module")
def tai_khoan_seed() -> dict[str, tuple[str, str]]:
    """``{username: (mat_khau, vai_tro)}`` đọc thẳng từ workbook seed.

    Đây là NGUỒN CHUẨN: ``seed_from_xlsx.py::seed_02_tai_khoan`` băm chính cột
    ``mat_khau`` này thành ``password_hash``, nên đăng nhập thật dùng đúng nó.
    """
    ws = openpyxl.load_workbook(
        _phai_ton_tai(DUONG_XLSX, "workbook seed"), data_only=True)["2_TaiKhoan"]
    tieu_de = [str(c.value or "").strip().lower() for c in ws[1]]
    i_u, i_p, i_v = (tieu_de.index("username"), tieu_de.index("mat_khau"),
                     tieu_de.index("vai_tro"))
    ra: dict[str, tuple[str, str]] = {}
    for hang in ws.iter_rows(min_row=2, values_only=True):
        u = str(hang[i_u] or "").strip()
        if u:
            ra[u] = (str(hang[i_p] or "").strip(), str(hang[i_v] or "").strip())
    assert ra, "sheet 2_TaiKhoan rỗng — không có nguồn chuẩn để đối chiếu"
    return ra


@pytest.fixture(scope="module")
def consumer(than_wf) -> list[pathlib.Path]:
    """Tệp THẬT SỰ đăng nhập trong lượt nightly: spec trích từ ``run:`` + setup.

    Tên spec đọc từ chính dòng lệnh chạy, không liệt kê tay — danh sách gõ tay
    sẽ trôi ngay lần ai đó thêm một suite.

    ⚠️ Tệp được nhắc trong workflow mà KHÔNG tồn tại là lỗi, **không** được lọc
    im lặng: một typo tên spec sẽ làm suite ấy biến mất khỏi cả lượt chạy lẫn
    hợp đồng này, và cả hai cùng xanh.
    """
    _phai_ton_tai(THU_MUC_E2E, "thư mục spec E2E")
    ten = sorted(set(re.findall(r"src/test/e2e/([A-Za-z0-9_.-]+\.spec\.ts)", than_wf)))
    assert ten, "không trích được spec nào từ dòng `run:` của workflow"
    thieu = [t for t in ten if not (THU_MUC_E2E / t).exists()]
    assert not thieu, (
        "workflow nhắc spec KHÔNG tồn tại — suite ấy im lặng không chạy:\n"
        + "\n".join(f"    {t}" for t in thieu))
    ra = [THU_MUC_E2E / t for t in ten]
    for t in CONSUMER_NGOAI_SPEC:
        ra.append(_phai_ton_tai(THU_MUC_E2E / t, f"consumer {t}"))
    return ra


def _hang_theo_bien(than: str) -> dict[str, str]:
    """``{TÊN_BIẾN: tên hằng JS nhận nó}``."""
    return {m.group(2): m.group(1)
            for m in re.finditer(r"const\s+(\w+)\s*=\s*process\.env\.(\w+)", than)}


def _bien_bat_buoc(p: pathlib.Path) -> set[str]:
    """Biến consumer đọc mà KHÔNG có ``test.skip`` bảo vệ.

    Miễn trừ được TÍNH, không liệt kê: một biến chỉ được bỏ qua nếu chính tệp ấy
    có ``test.skip(`` nhắc tới hằng nhận nó. Gỡ ``test.skip`` sẽ tự động biến
    biến đó thành bắt buộc.
    """
    than = p.read_text(encoding="utf-8")
    cac_skip = re.findall(r"test\.skip\([^)]*\)", than)
    bat_buoc = set()
    for bien, hang in _hang_theo_bien(than).items():
        if not MAU_BIEN.fullmatch(bien):
            continue
        if not any(hang in d for d in cac_skip):
            bat_buoc.add(bien)
    return bat_buoc


class TestHopDongCredentialE2E:
    def test_c1_moi_bien_consumer_doc_deu_duoc_workflow_khai(self, consumer, env_wf):
        """C1 — bao đóng TÊN biến giữa consumer và workflow."""
        thieu: dict[str, list[str]] = {}
        for p in consumer:
            for bien in sorted(_bien_bat_buoc(p) - set(env_wf)):
                thieu.setdefault(bien, []).append(p.name)
        assert not thieu, (
            "consumer đọc biến mà workflow KHÔNG khai ⇒ rơi về literal cứng và "
            "đăng nhập 401:\n" + "\n".join(
                f"    {b}  ← {', '.join(f)}" for b, f in sorted(thieu.items())))

    def test_c1b_ten_bien_e2e_phai_theo_luoc_do(self, consumer):
        """C1b — tên biến ``E2E_*`` phải khớp lược đồ, không phải tên tuỳ hứng.

        Bất biến RIÊNG khỏi C1, lý do cụ thể: C1 hỏi *"biến cần có đã khai
        chưa"*, nên nó chỉ nhìn tên ĐÚNG lược đồ. Một consumer đọc
        ``E2E_ADMIN_USER`` (thiếu ``NAME``) **rơi khỏi tầm quét của C1** — đo
        thật: đột biến ấy để C1 XANH trong khi spec đăng nhập bằng chuỗi rỗng.
        """
        la = []
        for p in consumer:
            than = p.read_text(encoding="utf-8")
            for bien in sorted(set(re.findall(r"process\.env\.(E2E_\w+)", than))):
                if bien in BIEN_E2E_KHAC_CHO_PHEP:
                    continue
                m = re.fullmatch(r"E2E_([A-Z]+)_([A-Z_]+)", bien)
                if not m or m.group(1) not in VAI_HOP_LE or m.group(2) not in HAU_TO_HOP_LE:
                    la.append(f"{p.name}: {bien}")
        assert not la, (
            "consumer đọc biến E2E_* KHÔNG theo lược đồ `E2E_<VAI>_<HẬU_TỐ>`.\n"
            f"    vai hợp lệ   : {', '.join(VAI_HOP_LE)}\n"
            f"    hậu tố hợp lệ: {', '.join(HAU_TO_HOP_LE)}\n"
            "Tên lệch sẽ đọc ra chuỗi rỗng và đăng nhập bằng thông tin trống:\n"
            + "\n".join(f"    {x}" for x in la))

    def test_c2_du_tam_khoa_va_gia_tri_bang_workbook(self, env_wf, tai_khoan_seed):
        """C2 — đủ TÁM khoá, và mỗi cặp khớp đúng một hàng workbook theo vai.

        Đòi đủ tám là cố ý: nếu chỉ kiểm "khoá nào có mặt thì phải đúng", xoá cả
        cụm ``TEST_*`` (hoặc cả sáu ``E2E_*``) vẫn cho XANH.
        """
        thieu = [k for k in KHOA_BAT_BUOC if k not in env_wf]
        assert not thieu, (
            "workflow thiếu khoá credential bắt buộc: " + ", ".join(thieu))
        loi = []
        for (ku, kp), vai_can in CAP_THEO_VAI.items():
            u, p = env_wf[ku], env_wf[kp]
            if u not in tai_khoan_seed:
                loi.append(f"{ku}={u!r} không có trong workbook seed")
                continue
            mk, vai = tai_khoan_seed[u]
            if vai != vai_can:
                loi.append(f"{ku}={u!r} có vai_tro={vai!r}, cần {vai_can!r}")
            if p != mk:
                loi.append(f"{kp} lệch mật khẩu workbook của {u!r}")
        assert not loi, "workflow ↔ workbook lệch:\n" + "\n".join(f"    {x}" for x in loi)

    def test_c3_fallback_phai_ghep_dung_cap_theo_workbook(
        self, consumer, tai_khoan_seed
    ):
        """C3 — literal fallback phải là CẶP username↔password của CÙNG một hàng.

        Không đủ nếu chỉ hỏi "password này có nằm đâu đó trong workbook không":
        đổi fallback password của ADMIN sang mật khẩu của OFFICER vẫn lọt, mà
        đăng nhập thật sẽ 401. Phải ghép theo cặp hằng của cùng một vai.
        """
        loi = []
        for p in consumer:
            than = p.read_text(encoding="utf-8")
            # {tên hằng: literal fallback}
            fb = {m.group(1): m.group(2) for m in re.finditer(
                r'const\s+(\w+)\s*=\s*process\.env\.\w+\s*\|\|\s*"([^"]*)"', than)}
            for tien_to in TIEN_TO_HANG:
                ten_u = next((h for h in fb if h.endswith("USERNAME") and tien_to in h), None)
                ten_p = next((h for h in fb if h.endswith("PASSWORD") and tien_to in h), None)
                if not ten_u or not ten_p:
                    continue
                u, mk = fb[ten_u], fb[ten_p]
                if u == "" and mk == "":
                    continue
                if u not in tai_khoan_seed:
                    loi.append(f"{p.name}: {ten_u} fallback {u!r} — tài khoản KHÔNG có trong seed")
                    continue
                mk_dung, vai = tai_khoan_seed[u]
                if mk != mk_dung:
                    loi.append(
                        f"{p.name}: {ten_p} fallback {mk!r} KHÔNG phải mật khẩu của "
                        f"{u!r} (workbook: {mk_dung!r})")
                vai_can = VAI_CUA_TIEN_TO[tien_to]
                if vai_can is not None and vai != vai_can:
                    loi.append(
                        f"{p.name}: {ten_u} fallback {u!r} có vai_tro={vai!r}, cần "
                        f"{vai_can!r} — cặp đăng nhập ĐƯỢC không có nghĩa là ĐÚNG QUYỀN")
            # auth.setup.ts dùng cặp hằng không mang tiền tố vai
            if not any(t in " ".join(fb) for t in TIEN_TO_HANG):
                u = fb.get("username", "")
                mk = fb.get("password", "")
                if u or mk:
                    if u not in tai_khoan_seed:
                        loi.append(f"{p.name}: fallback username {u!r} — không có trong seed")
                    else:
                        mk_dung, vai = tai_khoan_seed[u]
                        if mk != mk_dung:
                            loi.append(
                                f"{p.name}: fallback password {mk!r} KHÔNG phải mật khẩu "
                                f"của {u!r} (workbook: {mk_dung!r})")
                        if vai != VAI_CUA_SETUP:
                            loi.append(
                                f"{p.name}: fallback {u!r} có vai_tro={vai!r}, cần "
                                f"{VAI_CUA_SETUP!r} — storageState phải dựng bằng officer")
        assert not loi, (
            "literal fallback ghép SAI CẶP — khi biến thiếu, consumer đăng nhập "
            "bằng thông tin không tồn tại và nhận 401:\n"
            + "\n".join(f"    {x}" for x in loi))

    def test_manager_duoc_khai_de_ca_idor_chay_that(self, env_wf):
        """Bất biến RIÊNG: thiếu MANAGER thì ca IDOR skip thành XANH GIẢ.

        Tách khỏi C1 có chủ ý — C1 chỉ đòi biến *bắt buộc*, mà MANAGER được
        ``test.skip`` bảo vệ nên C1 cho phép nó vắng mặt. Chính cái vắng mặt
        "hợp lệ" ấy biến một ca IDOR thật thành xanh-do-bỏ-qua.

        ⚠️ Ca này chỉ chứng minh biến ĐƯỢC KHAI. Việc ca IDOR thật sự
        *executed* (skipped=0) là phép ĐỘNG, phải đo bằng một lượt chạy.
        """
        for k in ("E2E_MANAGER_USERNAME", "E2E_MANAGER_PASSWORD"):
            assert k in env_wf, (
                f"{k} không được khai ⇒ `lead-workflow.spec.ts` gọi `test.skip` và ca "
                "*Manager IDOR list scope* biến thành xanh giả thay vì chạy thật")
