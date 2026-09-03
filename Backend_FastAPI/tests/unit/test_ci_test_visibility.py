# -*- coding: utf-8 -*-
"""Cổng độ-nhìn-thấy của test: nối dây hiệu lực, lược đồ ledger, và canh chéo.

Ba nhóm khẳng định, ba mục đích khác nhau:

1. **Nối dây HIỆU LỰC** — không chỉ "step có tồn tại". Một step mang đúng tên
   vẫn có thể không bao giờ chạy: ``if: false``, hoặc ``if:
   matrix.visibility_guard`` trong khi KHÔNG leg nào đặt cờ ấy. Đây đúng bài
   học "có tên trong workflow ≠ thật sự chạy" — cùng gốc với vụ scalar gấp nuốt
   tám nodeid mà required check vẫn xanh.

2. **Lược đồ ledger** — fail-closed, kiểm giá trị dùng được chứ không kiểm sự
   tồn tại của khoá.

3. **Canh chéo** với ``TestCongCIThayDuocThuNoCanh`` ở
   ``tests/services/test_finance_killswitch.py``.

⚠️ VỀ CANH CHÉO — ĐỌC TRƯỚC KHI "DỌN TRÙNG LẶP"

Tệp này khẳng định ``test_finance_killswitch.py`` còn whole-file ở Tier 2b, và
tệp kia khẳng định ngược lại rằng tệp này còn whole-file ở Tier 5. Cả hai cùng
khẳng định step visibility còn được nối dây.

Sự trùng lặp ấy là **CỐ Ý**. Một tệp test không thể tự canh selector của chính
nó: gỡ selector ⇒ tệp không chạy ⇒ không còn ai báo đỏ. Chỉ một neo ĐỘC LẬP,
nằm ở shard KHÁC, mới bắt được. Gộp hai phép kiểm này lại "cho đỡ trùng" sẽ phá
đúng tính chất khiến chúng có giá trị.

Ranh giới với luật một-nguồn-chuẩn: phép kiểm ``#`` trong scalar gấp có **đúng
một** nguồn là ``TestCongCIThayDuocThuNoCanh`` và KHÔNG được cài lại ở đây. Chỉ
"neo còn sống" mới cố tình có hai bản.

Không cơ chế nội bộ nào chặn được một thay đổi cố ý gỡ CẢ HAI neo — mức đó
thuộc về review/ruleset bên ngoài. Canh chéo chỉ bắt lỗi thao tác thông thường,
và đó đã là phần lớn các ca thật.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml")


def _goc_repo() -> pathlib.Path | None:
    for cha in pathlib.Path(__file__).resolve().parents:
        if (cha / ".github" / "workflows").is_dir():
            return cha
    return None


GOC = _goc_repo()

if GOC is None:  # pragma: no cover - chỉ xảy ra ngoài cây nguồn
    pytest.skip("không tìm thấy gốc repo", allow_module_level=True)

DUONG_WF = GOC / ".github" / "workflows" / "backend-test.yml"
DUONG_LEDGER = GOC / "Backend_FastAPI" / "tests" / "VISIBILITY_LEDGER.yml"
DUONG_SCRIPT = GOC / ".github" / "scripts" / "pytest_visibility_guard.py"

TEP_NAY = "tests/unit/test_ci_test_visibility.py"
TEP_NEO_CHEO = "tests/services/test_finance_killswitch.py"
DUONG_SCRIPT_TRONG_WF = ".github/scripts/pytest_visibility_guard.py"
IF_HOP_LE = {"matrix.visibility_guard", "matrix.visibility_guard == true"}


def _nap_guard():
    """Nạp script guard theo đường dẫn — nó nằm ngoài package của backend."""
    spec = importlib.util.spec_from_file_location("_guard_do_nhin_thay", DUONG_SCRIPT)
    assert spec and spec.loader, "không nạp được %s" % DUONG_SCRIPT
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _nap_guard()


@pytest.fixture(scope="module")
def wf() -> dict:
    return yaml.safe_load(DUONG_WF.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cac_leg(wf) -> list[dict]:
    return wf["jobs"]["pytest-shard"]["strategy"]["matrix"]["include"]


def _selector_whole_file(cac_leg) -> set[str]:
    ra = set()
    for leg in cac_leg:
        for sel in str(leg.get("tests", "")).split():
            if "::" not in sel:
                ra.add(sel)
    return ra


def _tier_cua(cac_leg, selector: str) -> str | None:
    for leg in cac_leg:
        if selector in str(leg.get("tests", "")).split():
            return str(leg.get("tier", ""))
    return None


# ---------------------------------------------------------------------------
# 1. Nối dây HIỆU LỰC
# ---------------------------------------------------------------------------


class TestNoiDayHieuLuc:
    """Không hỏi "step có tồn tại", hỏi "step có thể chạy"."""

    def test_dung_mot_leg_bat_co_visibility_guard(self, cac_leg):
        # Đếm bằng YAML đã phân tích, KHÔNG bằng khớp chuỗi trên tệp thô: chú
        # thích ở dòng 511 có nhắc `coverage_script: true` nên `grep -c` cho 2
        # trong khi khoá matrix thật chỉ có 1. Cùng cái bẫy sẽ áp cho cờ này.
        bat = [
            str(leg.get("tier"))
            for leg in cac_leg
            if leg.get("visibility_guard") is True
        ]
        assert len(bat) == 1, (
            "phải có ĐÚNG MỘT leg đặt visibility_guard: true — 0 leg nghĩa là "
            "step không bao giờ chạy, 2 leg nghĩa là cổng chạy hai lần. "
            "Đang có: %r" % (bat,)
        )

    def test_step_goi_dung_script_va_dung_dieu_kien(self, wf):
        steps = wf["jobs"]["pytest-shard"]["steps"]
        khop = [
            s for s in steps
            if DUONG_SCRIPT_TRONG_WF in " ".join(
                # Chỉ soi DÒNG LỆNH thực thi. Một substring nằm trong `echo`
                # hay chú thích không chứng minh script được chạy — đây đúng
                # kiểu khớp trúng dòng thông báo thay vì dòng lệnh.
                dong.strip()
                for dong in str(s.get("run", "")).splitlines()
                if dong.strip() and not dong.strip().startswith("#")
            )
        ]
        assert len(khop) == 1, (
            "phải có ĐÚNG MỘT step chạy %s, đang có %d"
            % (DUONG_SCRIPT_TRONG_WF, len(khop))
        )
        step = khop[0]

        dong_lenh = [
            d.strip() for d in str(step["run"]).splitlines()
            if d.strip() and not d.strip().startswith("#")
        ]
        assert any(
            re.fullmatch(r"python3? %s" % re.escape(DUONG_SCRIPT_TRONG_WF), d)
            for d in dong_lenh
        ), "phải có một DÒNG LỆNH gọi chính xác script, đang có: %r" % (dong_lenh,)

        dieu_kien = str(step.get("if", "")).strip()
        assert dieu_kien in IF_HOP_LE, (
            "điều kiện step phải thuộc %s — `if: false` hay biểu thức khác làm "
            "step tồn tại mà không bao giờ chạy. Đang là: %r"
            % (sorted(IF_HOP_LE), dieu_kien)
        )

    def test_step_khong_duoc_continue_on_error(self, wf):
        # Khoá lệnh và khoá `if` vẫn CHƯA đủ. `continue-on-error: true` để step
        # thất bại mà job vẫn pass — cổng trả RC=1 trong khi required check
        # xanh. Đó là biến cổng thành fail-open bằng đúng MỘT dòng YAML, không
        # đụng tới lệnh, điều kiện, hay bất kỳ tệp test nào.
        steps = wf["jobs"]["pytest-shard"]["steps"]
        step = next(
            s for s in steps if DUONG_SCRIPT_TRONG_WF in str(s.get("run", ""))
        )
        coe = step.get("continue-on-error", False)
        assert coe is False, (
            "step guard KHÔNG được có `continue-on-error` khác False — nó cho "
            "phép job pass dù step đỏ. Đang là: %r" % (coe,)
        )

    def test_step_truyen_du_base_va_merge_sha(self, wf):
        steps = wf["jobs"]["pytest-shard"]["steps"]
        step = next(
            s for s in steps
            if DUONG_SCRIPT_TRONG_WF in str(s.get("run", ""))
        )
        env = step.get("env") or {}
        assert "BASE_SHA" in env and "MERGE_SHA" in env, (
            "thiếu BASE_SHA/MERGE_SHA thì script thoát 2 và cổng không đo gì"
        )
        assert "pull_request.base.sha" in str(env["BASE_SHA"])
        assert "github.sha" in str(env["MERGE_SHA"])

    def test_khong_bat_fetch_depth_0_o_checkout_chung(self, wf):
        # Bước checkout là bước CHUNG của MỌI leg. Bật full history ở đó bắt
        # từng runner matrix tải toàn bộ lịch sử + tags cho một phép so hai cây
        # vốn chỉ cần thêm đúng một commit.
        for s in wf["jobs"]["pytest-shard"]["steps"]:
            if "actions/checkout" in str(s.get("uses", "")):
                sau = (s.get("with") or {}).get("fetch-depth")
                assert sau in (None, 1), (
                    "checkout chung không được đặt fetch-depth: %r — dùng "
                    "`git fetch --no-tags --depth=1 origin $BASE_SHA` trong "
                    "riêng step guard" % (sau,)
                )


# ---------------------------------------------------------------------------
# 2. Canh chéo
# ---------------------------------------------------------------------------


class TestCanhCheoNeoDocLap:
    """Xem docstring module trước khi "dọn trùng lặp" — dư thừa là cố ý."""

    def test_neo_cheo_finance_killswitch_con_whole_file(self, cac_leg):
        assert TEP_NEO_CHEO in _selector_whole_file(cac_leg), (
            "%s phải còn whole-file trong tier: nó chứa "
            "TestCongCIThayDuocThuNoCanh — neo ĐỘC LẬP duy nhất khẳng định tệp "
            "này còn được gate. Gỡ nó đi thì không ai bắt được việc gỡ selector "
            "của chính cổng độ-nhìn-thấy." % TEP_NEO_CHEO
        )

    def test_hai_neo_o_HAI_tier_khac_nhau(self, cac_leg):
        tier_nay = _tier_cua(cac_leg, TEP_NAY)
        tier_kia = _tier_cua(cac_leg, TEP_NEO_CHEO)
        assert tier_nay and tier_kia, "cả hai neo phải nằm trong một tier nào đó"
        assert tier_nay != tier_kia, (
            "hai neo phải ở HAI shard khác nhau (%r vs %r): chung shard thì một "
            "sự cố hạ tầng của shard ấy làm im cả hai" % (tier_nay, tier_kia)
        )

    def test_khong_cai_lai_phep_kiem_dau_thang(self):
        # Luật một-nguồn-chuẩn: phép kiểm `#` trong scalar gấp thuộc về
        # TestCongCIThayDuocThuNoCanh. Nếu nó bị nhân bản sang đây thì hai bản
        # sẽ trôi khỏi nhau, và bản yếu hơn sẽ là bản còn sống.
        tho = pathlib.Path(__file__).read_text(encoding="utf-8")
        than = tho.split('"""', 2)[-1]  # bỏ docstring module
        assert "folded" not in than.lower() or "TestCongCIThayDuoc" in than, (
            "phép kiểm '#' trong scalar gấp phải ở NGUYÊN một nguồn: "
            "TestCongCIThayDuocThuNoCanh"
        )


# ---------------------------------------------------------------------------
# 3. Lược đồ ledger — trên ledger THẬT đang có trong cây
# ---------------------------------------------------------------------------


class TestLuocDoLedgerThat:
    def test_ledger_ton_tai_va_hop_le(self, guard):
        assert DUONG_LEDGER.is_file(), "thiếu %s" % DUONG_LEDGER
        ledger = {}
        doc = yaml.safe_load(DUONG_LEDGER.read_text(encoding="utf-8")) or []
        assert isinstance(doc, list), "ledger phải là danh sách"
        for muc in doc:
            ledger[muc["path"]] = muc

        goc = GOC / "Backend_FastAPI"
        tep_test = {
            str(p.relative_to(goc)).replace("\\", "/")
            for p in (goc / "tests").rglob("test_*.py")
        }
        loi = guard.kiem_luoc_do_ledger(ledger, tep_test)
        assert loi == [], "ledger thật vi phạm lược đồ:\n  " + "\n  ".join(loi)

    def test_moi_entry_partial_khop_dung_tap_nodeid_trong_tier(self, cac_leg):
        doc = yaml.safe_load(DUONG_LEDGER.read_text(encoding="utf-8")) or []
        trong_tier: dict[str, set[str]] = {}
        for leg in cac_leg:
            for sel in str(leg.get("tests", "")).split():
                if "::" in sel:
                    trong_tier.setdefault(sel.split("::", 1)[0], set()).add(sel)
        for muc in doc:
            if muc.get("status") != "partial":
                continue
            khai = set(muc.get("nodeids") or ())
            thuc = trong_tier.get(muc["path"], set())
            assert khai == thuc, (
                "%s: ledger khai %s nhưng tier có %s — mất coverage nodeid là "
                "thứ phải được KHAI BÁO, không phải xảy ra âm thầm"
                % (muc["path"], sorted(khai), sorted(thuc))
            )


# ---------------------------------------------------------------------------
# 4. Unit test cho logic thuần của script
# ---------------------------------------------------------------------------


def _rec(**ghi_de):
    goc = {
        "exists": True,
        "blob_oid": "a" * 40,
        "whole_selector": False,
        "nodeid_selectors": frozenset(),
        "ledger_entry": None,
        "nightly_included": True,
    }
    goc.update(ghi_de)
    return goc


class TestLuatTrangThai:
    def test_whole_file_khong_duoc_con_ledger(self, guard):
        rec = _rec(whole_selector=True, ledger_entry={"status": "partial"})
        assert any("LỖI THỜI" in d for d in guard.kiem_trang_thai_head("x.py", rec))

    def test_whole_file_sach_thi_dat(self, guard):
        assert guard.kiem_trang_thai_head("x.py", _rec(whole_selector=True)) == []

    def test_partial_khong_ledger_thi_do(self, guard):
        rec = _rec(nodeid_selectors=frozenset({"x.py::a"}))
        loi = guard.kiem_trang_thai_head("x.py", rec)
        assert loi and "KHÔNG tính là whole-file" in loi[0]

    def test_partial_lech_blob_thi_do(self, guard):
        rec = _rec(
            nodeid_selectors=frozenset({"x.py::a"}),
            ledger_entry={
                "status": "partial", "blob": "b" * 40, "nodeids": ["x.py::a"]},
        )
        loi = guard.kiem_trang_thai_head("x.py", rec)
        assert any("nội dung tệp đã đổi" in d for d in loi)

    def test_partial_lech_tap_nodeid_thi_do(self, guard):
        rec = _rec(
            nodeid_selectors=frozenset({"x.py::b"}),
            ledger_entry={
                "status": "partial", "blob": "a" * 40, "nodeids": ["x.py::a"]},
        )
        loi = guard.kiem_trang_thai_head("x.py", rec)
        assert any("tập nodeid lệch" in d for d in loi)

    def test_partial_ma_nightly_bo_qua_thi_do(self, guard):
        # Thiếu điều kiện này, một lượt thêm --ignore-glob nuốt trọn tệp trong
        # khi ledger/blob/nodeids đều khớp — và phần ngoài nodeid rơi khỏi CẢ
        # HAI cổng mà không gì đỏ.
        rec = _rec(
            nodeid_selectors=frozenset({"x.py::a"}),
            ledger_entry={
                "status": "partial", "blob": "a" * 40, "nodeids": ["x.py::a"]},
            nightly_included=False,
        )
        loi = guard.kiem_trang_thai_head("x.py", rec)
        assert any("nightly BỎ QUA" in d for d in loi)

    def test_none_khong_ledger_thi_do(self, guard):
        loi = guard.kiem_trang_thai_head("x.py", _rec())
        assert loi and "không có ledger entry" in loi[0]

    def test_none_co_nightly_only_hop_le_thi_dat(self, guard):
        rec = _rec(ledger_entry={"status": "nightly-only", "blob": "a" * 40})
        assert guard.kiem_trang_thai_head("x.py", rec) == []

    def test_none_nightly_only_ma_nightly_bo_qua_thi_do(self, guard):
        rec = _rec(
            ledger_entry={"status": "nightly-only", "blob": "a" * 40},
            nightly_included=False,
        )
        loi = guard.kiem_trang_thai_head("x.py", rec)
        assert any("nightly BỎ QUA" in d for d in loi)

    def test_tep_da_xoa_con_selector_thi_do(self, guard):
        rec = _rec(exists=False, blob_oid=None, whole_selector=True)
        loi = guard.kiem_trang_thai_head("x.py", rec)
        assert any("selector vẫn còn" in d for d in loi)


class TestGrandfatherVaThayThe:
    def test_record_khong_doi_thi_grandfather(self, guard):
        cu = {"x.py": _rec()}          # legacy NONE, không ledger
        moi = {"x.py": _rec()}
        loi, _ = guard.so_sanh(cu, moi)
        assert loi == [], "nợ cũ đứng yên thì không được chặn ai"

    def test_legacy_bi_sua_thi_do(self, guard):
        cu = {"x.py": _rec(blob_oid="a" * 40)}
        moi = {"x.py": _rec(blob_oid="c" * 40)}
        loi, _ = guard.so_sanh(cu, moi)
        assert loi, "legacy vừa bị sửa mà vẫn ngoài tier thì phải đỏ"

    def test_thay_the_nodeid_giu_nguyen_so_luong_van_do(self, guard):
        # {A,B} -> {B,C} KHÔNG phải quan hệ tập con, nhưng A đã mất coverage.
        entry = {
            "status": "partial", "blob": "a" * 40,
            "nodeids": ["x.py::A", "x.py::B"]}
        cu = {"x.py": _rec(
            nodeid_selectors=frozenset({"x.py::A", "x.py::B"}), ledger_entry=entry)}
        moi = {"x.py": _rec(
            nodeid_selectors=frozenset({"x.py::B", "x.py::C"}), ledger_entry=entry)}
        loi, ghi_chu = guard.so_sanh(cu, moi)
        assert loi, "đổi ngang số lượng vẫn là mất coverage"
        assert any("MẤT coverage nodeid" in d and "x.py::A" in d for d in ghi_chu)
        assert any("có thêm" in d and "x.py::C" in d for d in ghi_chu), (
            "chẩn đoán phải in RIÊNG mất và thêm; gộp lại thì người sửa ledger "
            "không thấy mình vừa bỏ rơi nodeid nào"
        )

    def test_tep_moi_khong_phan_loai_thi_do(self, guard):
        cu: dict = {}
        moi = {"x.py": _rec()}
        loi, _ = guard.so_sanh(cu, moi)
        assert loi, "ABSENT → NONE khác hẳn legacy NONE → NONE"


class TestNightlyIgnoreLayTuNguonChuan:
    def test_tach_duoc_ignore_glob(self, guard):
        noi_dung = (
            'env:\n  BO_QUA: '
            '"--ignore-glob=tests/integration/test_debug*.py"\n'
        )
        assert guard.cac_ignore_glob_nightly(noi_dung) == [
            "tests/integration/test_debug*.py"
        ]

    def test_them_glob_moi_lam_doi_nightly_included(self, guard):
        globs = ["tests/utils/test_file_*.py"]
        tep = "tests/utils/test_file_helpers.py"
        assert guard.nightly_thu_thap(tep, globs) is False
        assert guard.nightly_thu_thap("tests/unit/test_khac.py", globs) is True


class TestLuocDoFailClosed:
    @pytest.mark.parametrize(
        "gia_tri_nodeids",
        [[], "", {}],
        ids=["danh-sach-rong", "chuoi-rong", "anh-xa-rong"],
    )
    def test_nightly_only_co_khoa_nodeids_thi_do_du_gia_tri_falsy(
        self, guard, gia_tri_nodeids
    ):
        """Phải kiểm SỰ TỒN TẠI của khoá, không kiểm tính truthy.

        Bản đầu viết ``elif trang_thai == "nightly-only" and nodeids:`` nên
        ``[]``, ``""`` và ``{}`` đều lọt — mục ledger khi ấy hứa một đằng
        (nightly-only) mà mang cấu trúc của một đằng khác, và cổng không nói gì.

        Cùng họ với bẫy ``"skip_reason" in dep`` của ``pip_audit_count.py``,
        chỉ ngược chiều: ở đó thiếu GIÁ TRỊ dùng được là lỗi, ở đây KHOÁ CÓ MẶT
        mới là lỗi.
        """
        muc = {
            "path": "tests/x/test_a.py",
            "status": "nightly-only",
            "reason": "ly do that su",
            "blob": "a" * 40,
            "nodeids": gia_tri_nodeids,
        }
        loi = guard.kiem_luoc_do_ledger(
            {"tests/x/test_a.py": muc}, {"tests/x/test_a.py"}
        )
        assert any("nightly-only không được khai nodeids" in d for d in loi), (
            "nodeids=%r là falsy nhưng KHOÁ vẫn có mặt — phải đỏ. Lỗi thu được: %r"
            % (gia_tri_nodeids, loi)
        )

    def test_nightly_only_khong_co_khoa_nodeids_thi_dat(self, guard):
        """Ca XANH đối chứng: thiếu ca này thì một guard 'đỏ mọi thứ' cũng qua."""
        muc = {
            "path": "tests/x/test_a.py",
            "status": "nightly-only",
            "reason": "ly do that su",
            "blob": "a" * 40,
        }
        loi = guard.kiem_luoc_do_ledger(
            {"tests/x/test_a.py": muc}, {"tests/x/test_a.py"}
        )
        assert loi == [], "nightly-only hợp lệ không được báo lỗi: %r" % (loi,)

    def test_reason_toan_khoang_trang_thi_do(self, guard):
        ledger = {"tests/x/test_a.py": {
            "path": "tests/x/test_a.py", "status": "partial",
            "reason": "   ", "blob": "a" * 40, "nodeids": ["tests/x/test_a.py::t"]}}
        loi = guard.kiem_luoc_do_ledger(ledger, {"tests/x/test_a.py"})
        assert any("reason" in d for d in loi), (
            "kiểm GIÁ TRỊ dùng được, không phải sự tồn tại của khoá"
        )

    def test_ledger_chet_thi_do(self, guard):
        ledger = {"tests/x/test_da_xoa.py": {
            "path": "tests/x/test_da_xoa.py", "status": "nightly-only",
            "reason": "ly do", "blob": "a" * 40}}
        loi = guard.kiem_luoc_do_ledger(ledger, set())
        assert any("ledger chết" in d for d in loi)

    def test_khoa_la_thi_do(self, guard):
        ledger = {"tests/x/test_a.py": {
            "path": "tests/x/test_a.py", "status": "nightly-only",
            "reason": "ly do", "blob": "a" * 40, "khoa_bia_dat": 1}}
        loi = guard.kiem_luoc_do_ledger(ledger, {"tests/x/test_a.py"})
        assert any("khoá lạ" in d for d in loi)

    def test_path_vuot_thu_muc_thi_do(self, guard):
        ledger = {"../test_a.py": {
            "path": "../test_a.py", "status": "nightly-only",
            "reason": "ly do", "blob": "a" * 40}}
        loi = guard.kiem_luoc_do_ledger(ledger, set())
        assert any("tương đối" in d for d in loi)

    def test_partial_khong_co_nodeid_thi_do(self, guard):
        ledger = {"tests/x/test_a.py": {
            "path": "tests/x/test_a.py", "status": "partial",
            "reason": "ly do", "blob": "a" * 40, "nodeids": []}}
        loi = guard.kiem_luoc_do_ledger(ledger, {"tests/x/test_a.py"})
        assert any("≥1 nodeid" in d for d in loi)

    def test_nodeid_trung_lap_thi_do(self, guard):
        ledger = {"tests/x/test_a.py": {
            "path": "tests/x/test_a.py", "status": "partial", "reason": "ly do",
            "blob": "a" * 40,
            "nodeids": ["tests/x/test_a.py::t", "tests/x/test_a.py::t"]}}
        loi = guard.kiem_luoc_do_ledger(ledger, {"tests/x/test_a.py"})
        assert any("TRÙNG LẶP" in d for d in loi)


class TestSelectorTrungLapVaChongLan:
    def test_selector_trung_lap_thi_do(self, guard):
        wf = (
            "jobs:\n  pytest-shard:\n    strategy:\n      matrix:\n        include:\n"
            "          - tier: A\n            tests: >-\n              tests/a.py\n"
            "          - tier: B\n            tests: >-\n              tests/a.py\n"
        )
        with pytest.raises(guard.LoiCong, match="TRÙNG LẶP"):
            guard.phan_tich_selector(wf)

    def test_whole_file_va_nodeid_cung_tep_thi_do(self, guard):
        wf = (
            "jobs:\n  pytest-shard:\n    strategy:\n      matrix:\n        include:\n"
            "          - tier: A\n            tests: >-\n              tests/a.py\n"
            "              tests/a.py::t\n"
        )
        with pytest.raises(guard.LoiCong, match="vừa có whole-file vừa có nodeid"):
            guard.phan_tich_selector(wf)


# =============================================================================
# LEG CÁCH LY — tệp có DDL/UPDATE cấp BẢNG không được ở chung invocation
# =============================================================================

TEP_CACH_LY = "tests/api/test_adm_024_strict_default_migration.py"


class TestLegCachLy:
    """`adm_024` phải chiếm trọn một leg matrix, không chia với ai.

    Hai thao tác của tệp ấy đều ở cấp BẢNG chứ không cấp hàng:
      * ``UPDATE admission_path SET allow_unverified_submission = FALSE`` —
        không có vị từ ``id``, nên nó lật cờ của MỌI hàng, kể cả hàng mà test
        khác vừa seed;
      * ``ALTER TABLE admission_profile DISABLE TRIGGER
        enforce_applied_rules_immutability`` — DDL cấp bảng: lấy khoá
        ``SHARE ROW EXCLUSIVE`` trên cả bảng và giữ đến hết transaction
        (không nhả sau ``ENABLE``), nên mọi ``INSERT``/``UPDATE``/``DELETE``
        vào ``admission_profile`` của phiên khác phải xếp hàng — ``SELECT``
        thì không. Đây là rủi ro KHOÁ, KHÔNG phải "trigger ở lại trạng thái
        tắt": ``DISABLE`` và ``ENABLE`` nằm trong CÙNG một transaction
        (``ENABLE`` ở ``finally``), mà DDL của PostgreSQL là transactional —
        trạng thái tắt chưa commit thì phiên khác không nhìn thấy, và tiến
        trình chết thì backend abort transaction nên trigger trở lại BẬT.

    Cả hai KHÔNG phải nguy cơ TUẦN TỰ với fixture chuẩn: ``setup_test_database``
    (``tests/conftest.py:235``) dựng lược đồ MỘT lần rồi TRUNCATE toàn bộ bảng
    TRƯỚC mỗi test CSDL kế tiếp, và cả BA ca ADM-024 đều kéo fixture ấy (ca 1 qua
    ``adm024_paths`` -> ``seed_lead_dependencies``; ca 2 và 3 qua ``client``). Với
    hình dạng CI hiện tại — MỘT process pytest, không xdist, mỗi leg matrix một
    PostgreSQL/Redis RIÊNG — test tuần tự dùng fixture chuẩn KHÔNG nhìn thấy dữ
    liệu mà tệp ấy đã lật.

    ``UPDATE`` toàn bảng chỉ gây nhiễu khi có thực thi ĐỒNG THỜI trên cùng CSDL
    (xdist, tiến trình ngoài, hoặc test bỏ qua fixture chuẩn); ``SHARE ROW
    EXCLUSIVE`` giữ tới hết transaction cũng chỉ thành rủi ro BLOCKING khi có
    writer đồng thời. Ca này giữ leg riêng như DEFENSE-IN-DEPTH: cô lập hai thao
    tác cấp bảng và giữ blast radius nhỏ nếu mô hình thực thi về sau đổi — không
    phải vì đang có một nguy cơ tuần tự.

    Một lượt đo "chạy chung vẫn xanh" KHÔNG thay thế được ca này: nó chỉ nói
    về đúng thứ tự ấy, đúng bộ fixture ấy, đúng hôm ấy. Bất biến cấu trúc thì
    còn đúng với mọi thứ tự và mọi fixture thêm vào sau.
    """

    def test_tep_cach_ly_nam_dung_mot_leg(self, cac_leg):
        chua = [
            str(leg.get("tier", ""))
            for leg in cac_leg
            if TEP_CACH_LY in str(leg.get("tests", "")).split()
        ]
        assert len(chua) == 1, (
            "%s phải nằm trong ĐÚNG MỘT leg matrix, đang ở %d leg: %r. "
            "0 leg nghĩa là không shard nào chạy nó mà required check vẫn xanh; "
            ">1 leg nghĩa là nó chạy song song với chính nó trên hai DB."
            % (TEP_CACH_LY, len(chua), chua)
        )

    def test_leg_chua_tep_cach_ly_khong_chia_voi_ai(self, cac_leg):
        for leg in cac_leg:
            sel = str(leg.get("tests", "")).split()
            if TEP_CACH_LY not in sel:
                continue
            ban_cung_leg = [s for s in sel if s != TEP_CACH_LY]
            assert ban_cung_leg == [], (
                "leg %r chứa %s CÙNG VỚI %d selector khác: %r. "
                "Tệp này UPDATE toàn bảng `admission_path` rồi COMMIT và giữ khoá "
                "cấp bảng trên `admission_profile` đến hết transaction. Fixture "
                "chuẩn TRUNCATE giữa các test nên gộp KHÔNG chắc gây sai ở cấu "
                "hình hôm nay; leg riêng là defense-in-depth cho lúc mô hình thực "
                "thi đổi. Nếu thật sự muốn gộp thì phải gỡ hai thao tác cấp bảng "
                "ấy trước, và sửa ca này trong cùng một lần để việc gộp hiện ra "
                "trong diff."
                % (str(leg.get("tier", "")), TEP_CACH_LY,
                   len(ban_cung_leg), ban_cung_leg[:5])
            )

    def test_leg_cach_ly_khong_om_them_co_visibility_guard(self, cac_leg):
        """Leg cách ly không được kiêm cổng độ nhìn thấy.

        Cổng ấy đã có đúng một chỗ (ca `test_dung_mot_leg_bat_co_visibility_guard`
        khoá số 1). Ca này chặn lối "tiện tay" gắn thêm vào leg mới, vì leg cách
        ly là leg dễ đỏ nhất do hạ tầng — buộc cổng vào đó là tự tạo một điểm
        chết chung.
        """
        for leg in cac_leg:
            if TEP_CACH_LY in str(leg.get("tests", "")).split():
                assert not leg.get("visibility_guard"), (
                    "leg cách ly %r không được bật visibility_guard"
                    % str(leg.get("tier", ""))
                )
