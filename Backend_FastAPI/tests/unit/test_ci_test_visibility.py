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

import hashlib
import importlib.util
import json
import pathlib
import re
import sys
import unicodedata

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

    Hai đường nhiễu KHÁC NHAU, đừng gộp làm một:
      * ĐỒNG THỜI — xdist, hoặc một tiến trình khác dùng CÙNG CSDL, chạy xen vào;
      * TUẦN TỰ — một test chạy SAU nhưng BỎ QUA fixture reset chuẩn. Hàng đã
        COMMIT vẫn còn đó nên KHÔNG cần đồng thời gì cả. Đây là nguy cơ THẬT; nó
        chỉ không áp với test dùng fixture chuẩn, vì fixture ấy TRUNCATE trước
        khi chạy.

    Riêng khoá ``SHARE ROW EXCLUSIVE`` thì khác: giữ tới hết transaction, và chỉ
    là rủi ro BLOCKING khi có writer ĐỒNG THỜI trên cùng CSDL.

    Ca này giữ leg riêng như DEFENSE-IN-DEPTH: cô lập hai thao tác cấp bảng và
    giữ blast radius nhỏ nếu mô hình thực thi về sau đổi — không phải vì test
    dùng fixture chuẩn đang gặp nguy cơ tuần tự hôm nay.

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


# ---------------------------------------------------------------------------
# 8. NEO CHÉO — hợp đồng classifier phải được required check nhìn thấy
# ---------------------------------------------------------------------------
# Tệp test của classifier nằm ở `.github/scripts/tests/`, NGOÀI `Backend_FastAPI/`.
# Nó không thể tự canh dây nối của chính nó: một PR gỡ `classifier-contract` khỏi
# `pytest.needs` sẽ làm chính nó ngừng ảnh hưởng tới cổng, mà nó vẫn xanh.
#
# Tệp NÀY nằm ở Tier 5 nên nó chạy qua required check `pytest`. Đặt neo ở đây là
# đặt vào đúng chỗ mà việc gỡ dây nối sẽ ĐỎ.

JOB_CONTRACT = "classifier-contract"
TEP_CONTRACT = ".github/scripts/tests/test_pr_classifier.py"
DUONG_WF_SHADOW = GOC / ".github" / "workflows" / "pr-classifier.yml"

#: San cua `REQUIRED_SENTINELS`. Suy tu danh sach THAT (snapshot `7b02278c`,
#: 05-09-2026).
#: Chi duoc NANG. Ha san la mot sua doi phai nhin thay duoc trong diff.
SO_SENTINEL_TOI_THIEU = 67

#: Loi bat buoc — moi ten o day khoa MOT nguon quyet dinh rieng cua classifier.
LOI_SENTINEL = {
    "test_broad_unknown_backend_khong_rong_va_dung_ly_do",
    "test_broad_self_change_khong_rong_va_dung_ly_do",
    "test_broad_shared_test_surface_khong_rong_va_dung_ly_do",
    "test_broad_empty_plan_guard_khong_rong_va_dung_ly_do",
    "test_cli_tra_ma_khac_0_khi_block",
    "test_manifest_rong_bi_tu_choi_khong_phai_bootstrap",
    "test_selector_manifest_khong_khop_tep_nao_thi_do",
    "test_record_it_hon_changed_files_thi_block",
    "test_record_nhieu_hon_changed_files_thi_block",
    "test_duong_top_level_la_hoac_ra_broad_khong_phai_no_backend_impact",
    "test_moi_duong_trong_github_deu_la_self_ke_ca_dependabot",
    "test_tron_AN_TOAN_voi_CHUA_BIET_thi_BROAD_khong_duoc_im_lang",
    "test_be_mat_VAN_HANH_khong_khop_mien_thi_BROAD_khong_phai_thoi",
    "test_cli_THUC_SU_goi_kiem_dinh_danh",
    "test_dinh_danh_commit_khong_phai_merge_thi_nem",
}


def _khoi_on(wf: dict) -> dict:
    """YAML 1.1 ép `on:` thành khoá bool `True` — cùng họ với Norway problem.

    Đo thật: `list(yaml.safe_load(backend-test.yml))` cho
    `['name', True, 'concurrency', 'jobs']`. Đọc `wf["on"]` là `KeyError`.
    """
    if "on" in wf:
        return wf["on"]
    if True in wf:
        return wf[True]
    raise AssertionError("workflow không có khối `on:`")


def _than_khong_comment_shell(than: str) -> str:
    """Bỏ comment SHELL trong thân `run:` trước khi tìm chuỗi.

    Bài học 2 dưới đây nói về comment YAML. Còn một tầng nữa: `steps[].run` giữ
    NGUYÊN comment shell (`# ...`) nằm bên trong khối lệnh. Đo thật — đột biến
    N11 giữ đủ mọi chuỗi bị khoá nhưng dời chúng vào một dòng `#` rồi ép
    `RESULT="success"`; TOÀN BỘ lớp neo vẫn xanh trong khi cổng đã tê liệt
    (snapshot `7b02278c`, 05-09-2026).
    """
    ra = []
    for dong in than.splitlines():
        cat = dong.split("#", 1)[0]
        if cat.strip():
            ra.append(cat)
    return "\n".join(ra)


# Ba bài học đã trả giá khi dựng lớp neo này, giữ lại để đừng ai đi lại:
#
#   1. `yaml.dump()` MÃ HOÁ LẠI chuỗi shell — `yaml.dump(job).count('!= "success"')`
#      cho **0** trong khi tệp có ba lần. Đừng đếm trên bản dump.
#   2. Đọc VĂN BẢN THÔ thì trúng comment: chính comment giải thích
#      "KHÔNG so `== failure`" làm phép cấm tự đỏ. Lọc comment đầu dòng vẫn sót
#      comment cuối dòng (`key: value  # ...`), và một `!= "success"` nhét vào
#      comment cuối dòng đủ để bù số đếm cho một cổng đã bị tháo.
#   3. Đúng cách là đọc CẤU TRÚC — `steps[].run` giữ nguyên chuỗi gốc, comment
#      YAML không nằm trong đó, và phạm vi khoá được vào đúng bước cần xét.


def _co_exit1_tran_trong_khoi(than: str) -> bool:
    """`exit 1` phải đứng TRẦN bên trong khối `if … != "success"; then … fi`.

    Đo thật — đột biến N12 giữ nguyên phép so và vẫn có chuỗi `exit 1`,
    chỉ bọc nó thành `[ "${QLTS_GATE_STRICT:-0}" = "1" ] && exit 1`. Phép
    `"exit 1" in than` xanh, trong khi cổng chỉ đỏ khi ai đó nhớ bật biến.
    """
    trong = False
    for dong in than.splitlines():
        goc = dong.strip()
        if '!= "success"' in goc and goc.startswith("if "):
            trong = True
            continue
        if trong:
            if goc == "fi":
                trong = False
                continue
            if goc == "exit 1":
                return True
    return False


class TestNeoCheoHopDongClassifier:
    def test_job_classifier_contract_ton_tai(self, wf):
        assert JOB_CONTRACT in wf["jobs"], (
            "job %r biến mất khỏi backend-test.yml — hợp đồng classifier không "
            "còn được required check `pytest` gom vào." % JOB_CONTRACT
        )

    def test_job_goi_dung_tep_test_classifier(self, wf):
        # Phải đọc THÂN JOB, không đọc toàn tệp: một comment còn giữ đường dẫn
        # cũ ở đâu đó trong workflow sẽ làm phép tìm trên toàn tệp xanh giả.
        than = "\n".join(str(b.get("run", "")) for b in wf["jobs"][JOB_CONTRACT]["steps"])
        assert TEP_CONTRACT in than, (
            "job %r không còn gọi %r — cổng có thể đang chạy một tệp khác, hoặc "
            "không chạy gì." % (JOB_CONTRACT, TEP_CONTRACT)
        )

    def test_job_khong_continue_on_error(self, wf):
        job = wf["jobs"][JOB_CONTRACT]
        assert not job.get("continue-on-error"), (
            "`continue-on-error` biến job đỏ thành job xanh — cổng còn tên mà "
            "hết hiệu lực."
        )
        for buoc in job.get("steps", []):
            assert not buoc.get("continue-on-error"), (
                "bước %r bật continue-on-error" % buoc.get("name")
            )

    def test_job_khong_co_dieu_kien_khien_no_bi_skip(self, wf):
        """GitHub coi check `skipped` là THÀNH CÔNG.

        Đo được ngay trong kho: trên `c6c212f8`, `Weekly Audit Alarm` và
        `Node.js Dev-scope Advisories` đều `completed | conclusion=skipped`. Một
        `if:` sai trên job này biến cổng thành xanh giả, không phải đỏ.
        """
        job = wf["jobs"][JOB_CONTRACT]
        assert "if" not in job, (
            "job %r không được có `if:` — mọi điều kiện đều là một đường để nó "
            "bị skip, và check skipped KHÔNG làm PR đỏ." % JOB_CONTRACT
        )

    def test_aggregator_needs_chua_classifier_contract(self, wf):
        needs = wf["jobs"]["pytest"]["needs"]
        assert JOB_CONTRACT in needs, (
            "`pytest.needs` không còn %r — job vẫn chạy nhưng kết quả của nó "
            "không ảnh hưởng gì tới required check." % JOB_CONTRACT
        )

    def test_aggregator_that_su_doc_ket_qua_classifier_contract(self, wf):
        """Có trong `needs` mà không đọc `result` là fail-open câm."""
        than = "\n".join(str(b.get("run", "")) for b in wf["jobs"]["pytest"]["steps"])
        assert "needs.%s.result" % JOB_CONTRACT in than, (
            "aggregator `pytest` không đọc `needs.%s.result` — phụ thuộc có mặt "
            "nhưng kết quả bị bỏ qua." % JOB_CONTRACT
        )

    def test_aggregator_phai_la_if_always_tran(self, wf):
        """Không có `always()` thì job bị skip khi một phụ thuộc đỏ — mà GitHub
        coi check `skipped` là THÀNH CÔNG, nên cổng biến mất đúng lúc cần nhất.
        """
        assert wf["jobs"]["pytest"].get("if") == "always()", (
            "aggregator `pytest` phải là `if: always()` trần; mọi biến thể kiểu "
            "`always() && needs.x.result != 'skipped'` mở lại chính lỗ đó."
        )

    def test_needs_cua_aggregator_dung_bang_tap_ghim(self, wf):
        """Khoá `needs` bằng TẬP CỐ ĐỊNH, không phải phép `in`.

        Vòng kiểm fail-closed duyệt chính `job["needs"]`, nên **gỡ một tên khỏi
        `needs` là tự loại nó khỏi phạm vi kiểm** — đo thật: gỡ
        `session-survival` thì TOÀN BỘ lớp neo vẫn xanh trong khi cổng ấy hết
        hiệu lực (snapshot `7b02278c`, 05-09-2026).
        """
        assert set(wf["jobs"]["pytest"]["needs"]) == {
            "pytest-shard", "session-survival", JOB_CONTRACT}

    def test_khong_buoc_nao_cua_cac_job_gac_bi_vo_hieu(self, wf):
        """Cấm `if:` và `continue-on-error` ở CẤP BƯỚC của ba job cổng.

        Neo cũ chỉ soi job `classifier-contract`. Đo thật: thêm `if:` hoặc
        `continue-on-error` vào một **bước** của aggregator `pytest` thì TOÀN
        BỘ lớp neo vẫn xanh trong khi phép gom ấy không còn chạy (snapshot `7b02278c`, 05-09-2026).

        ⚠️ `pytest-shard` KHÔNG nằm trong phạm vi này: nó là matrix và các leg
        có `if: matrix.<cờ>` **theo thiết kế** (`coverage_script`,
        `visibility_guard`). Điều kiện của riêng bước guard đã bị khoá ở
        `test_step_goi_dung_script_va_dung_dieu_kien` +
        `test_step_khong_duoc_continue_on_error`. Kéo `pytest-shard` vào đây
        chỉ tạo một ca đỏ vì kỳ vọng sai — đã đo.
        """
        for ten in ("pytest", JOB_CONTRACT, "session-survival"):
            job = wf["jobs"][ten]
            assert not job.get("continue-on-error"), (
                "job %r bật continue-on-error ở CẤP JOB" % ten)
            for buoc in job.get("steps", []):
                assert "if" not in buoc, (
                    "job %r bước %r có `if:` — mọi điều kiện là một đường để bước "
                    "gác không chạy." % (ten, buoc.get("name"))
                )
                assert not buoc.get("continue-on-error"), (
                    "job %r bước %r bật continue-on-error" % (ten, buoc.get("name"))
                )

    def test_cong_sentinel_dung_HIEU_tap_khong_dung_giao(self, wf):
        """Phép so tập phải là HIỆU, không phải GIAO.

        Đột biến `missing = REQUIRED & got` vẫn "so tập hợp", vẫn có biến
        `missing`, nhưng biến cổng thành *"chỉ cần có ít nhất một sentinel"*.
        Bất biến này KHÔNG tự canh được từ tệp test của classifier — logic nằm
        trong heredoc của workflow. Đây là nơi duy nhất nhìn thấy nó.
        """
        than = _than_khong_comment_shell(
            "\n".join(str(b.get("run", ""))
                      for b in wf["jobs"][JOB_CONTRACT]["steps"]))
        assert "CAN - got" in than, "cổng sentinel phải dùng HIỆU tập `CAN - got`"
        assert "CAN & got" not in than, (
            "`CAN & got` biến cổng thành 'chỉ cần có ít nhất một sentinel'")
        assert "got - CAN" in than, "phải báo cả THỪA để bắt được ca ĐỔI TÊN"

    def test_moi_phu_thuoc_cua_aggregator_deu_duoc_kiem_fail_closed(self, wf):
        """Mỗi phụ thuộc phải có RIÊNG một bước, và bước ấy phải vừa so
        `!= "success"` vừa `exit 1`.

        ⚠️ Bản đầu của ca này đếm `count('!= "success"') >= len(needs)` trên
        **văn bản toàn tệp**. Ba đột biến đo được đã lọt qua:

        * giữ phép so nhưng đổi `exit 1` thành `echo ::warning` — cổng còn phép
          so, phép so không làm gì;
        * cho một bước kiểm `pytest-shard` HAI lần rồi xoá hẳn khối `if` của
          classifier — tổng đếm vẫn đủ;
        * bù một `!= "success"` vào **comment cuối dòng** — bộ lọc chỉ loại
          comment đầu dòng.

        Đọc theo CẤU TRÚC (`steps[].run`) chặn cả ba: comment YAML không nằm
        trong giá trị `run`, và phạm vi bị khoá vào đúng bước của từng phụ thuộc.
        """
        job = wf["jobs"]["pytest"]
        buoc = [(b, _than_khong_comment_shell(str(b["run"])))
                for b in job["steps"] if "run" in b]
        for ten in job["needs"]:
            moc = "needs.%s.result" % ten
            cua_no = [x for x in buoc if moc in x[1]]
            assert len(cua_no) == 1, (
                "phụ thuộc %r phải được đọc bởi ĐÚNG MỘT bước LỆNH THẬT, thấy "
                "%d — nhiều hơn một là đếm phồng, bằng không là không ai kiểm "
                "(comment shell đã bị loại trước khi đếm)." % (ten, len(cua_no))
            )
            than = cua_no[0][1]
            assert '!= "success"' in than, (
                "bước kiểm %r không so `!= \"success\"` — `== \"failure\"` để "
                "lọt cả `cancelled` lẫn `skipped`." % ten
            )
            assert _co_exit1_tran_trong_khoi(than), (
                "bước kiểm %r không có `exit 1` TRẦN bên trong khối "
                "`!= \"success\"` — `exit 1` đứng ngoài khối, hay bị bọc thêm một "
                "điều kiện (`[ \"$X\" = 1 ] && exit 1`), đều là cổng còn hình thức "
                "mà hết hiệu lực." % ten
            )
            assert '== "failure"' not in than and "== 'failure'" not in than, (
                "bước kiểm %r dùng `== failure`." % ten
            )

    # -- than TRONG cong: neo cu chi kiem day noi NGOAI ---------------------
    # Bon dot bien duoi day tung LOT het (snapshot `7b02278c`, 05-09-2026): rut gon
    # `REQUIRED_SENTINELS` kem viec xoa dung nhung ca ay; xoa nguyen buoc
    # "Manifest THAT"; bo tang `--collect-only`; bo `skipped` khoi `bad`.
    # Chung khong dong toi day noi nao ca — chung rut ruot chinh cai cong.

    def test_danh_sach_sentinel_khong_bi_rut_gon(self, wf):
        """Sàn số lượng + một lõi tên bắt buộc.

        `REQUIRED_SENTINELS` nằm ở workflow chứ không trong tệp test, để một PR
        không thể vừa xoá ca vừa xoá dòng hằng. Nhưng một PR **vẫn** sửa được
        cả hai tệp: đo thật — gỡ 4 tên `test_broad_*` khỏi hằng VÀ xoá 4 `def`
        tương ứng thì `thiếu=∅ thừa=∅`, hợp đồng xanh, bốn nguồn BROAD hết được
        canh. Neo này là nhân chứng THỨ BA, ở một cây tệp thứ ba.

        Sàn phải được NÂNG khi danh sách dài ra — nó suy từ danh sách thật, và
        hạ sàn là một sửa đổi phải nhìn thấy được trong diff.
        """
        than = "\n".join(str(b.get("run", ""))
                         for b in wf["jobs"][JOB_CONTRACT]["steps"])
        # Ten ca CO chua chu HOA (`..._AN_TOAN_...`, `..._THUC_SU_...`) — lop
        # ky tu chi-thuong da tung bo sot 4 ten va lam san bi dem thieu.
        ten = set(re.findall(r'"(test_[A-Za-z0-9_]+)"', than))
        assert len(ten) >= SO_SENTINEL_TOI_THIEU, (
            "REQUIRED_SENTINELS còn %d tên, sàn là %d — danh sách chỉ được DÀI "
            "ra." % (len(ten), SO_SENTINEL_TOI_THIEU)
        )
        thieu = sorted(LOI_SENTINEL - ten)
        assert not thieu, (
            "gỡ khỏi `REQUIRED_SENTINELS` những sentinel lõi: %s" % thieu)

    def test_buoc_kiem_manifest_THAT_van_con(self, wf):
        """Xoá nguyên bước "Manifest THẬT" thì mọi neo cũ vẫn xanh (đã đo).

        `test_job_goi_dung_tep_test_classifier` chỉ đòi chuỗi đường dẫn tệp test
        xuất hiện đâu đó trong job — bước hợp đồng vẫn cung cấp chuỗi ấy. Mất
        bước này là `domains.yml` THẬT hết được xác thực: selector trỏ tệp đã
        xoá, sai lược đồ, `domains:` rỗng — không ai bắt.
        """
        # ⚠️ PHẢI lọc comment trước khi tìm. Đột biến
        # `pass  # C.kiem_paths_manifest(m, moi_duong)` giữ nguyên chuỗi bị khoá
        # trong khi lời gọi đã chết — đo thật, nó lọt qua phép tìm văn bản thô.
        than = _than_khong_comment_shell(
            "\n".join(str(b.get("run", ""))
                      for b in wf["jobs"][JOB_CONTRACT]["steps"]))
        # `kiem_paths_manifest` là chiều XUÔI (`paths:` phải khớp đường có
        # thật). Thiếu nó thì một `paths:` gõ sai vẫn hợp lệ, khớp 0 đường, và
        # miền lặng lẽ ngừng bắt — an toàn nhưng câm.
        for can in ("kiem_selector_manifest", "kiem_paths_manifest",
                    "nap_manifest", "git", "ls-files",
                    ".github/scripts/domains.yml"):
            assert can in than, (
                "job %r không còn xác thực manifest THẬT (thiếu %r)."
                % (JOB_CONTRACT, can))

    def test_bon_tang_cua_cong_hop_dong_deu_con(self, wf):
        """Bốn tầng, không phải một. Hai tầng đã đo là CHỊU LỰC (gỡ ra thì cổng
        xanh trên đúng đầu vào hỏng): `collected == executed` và
        `failures+errors+skipped == 0`.

        * `--collect-only` là nguồn DUY NHẤT của `collected` — JUnit không tiết
          lộ deselect. Bỏ tầng này rồi đặt `collected = tests` là hằng-đúng.
        * `skipped` trong `bad`: JUnit vẫn ghi `<testcase>` cho ca skip, nên
          `got` không thiếu tên nào — `@pytest.mark.skip` trên một sentinel lọt
          trọn nếu `bad` chỉ cộng `failures + errors`.
        """
        than = _than_khong_comment_shell(
            "\n".join(str(b.get("run", ""))
                      for b in wf["jobs"][JOB_CONTRACT]["steps"]))
        for can, vi_sao in (
            ("--collect-only", "nguồn duy nhất của `collected`; bỏ đi thì phép "
                               "`collected != executed` thành hằng-sai"),
            ('"skipped"', "`bad` phải cộng cả skipped, nếu không `@skip` trên "
                          "một sentinel lọt trọn"),
            ("tests <= 0", "lớp phòng thủ thứ hai cho lượt 0 ca"),
        ):
            assert can in than, "cổng hợp đồng mất %r — %s" % (can, vi_sao)

    # -- workflow shadow: cac thuoc tinh CAP JOB / CAP `on:` ----------------

    def test_shadow_khong_co_dieu_kien_va_khong_bi_paths_loc(self):
        """`if: false` trên job, hoặc thêm `paths:`, đều làm shadow im lặng biến
        mất — và hai neo cũ chỉ đọc `steps`, nên chúng vẫn xanh (đã đo).
        """
        doc = yaml.safe_load(DUONG_WF_SHADOW.read_text(encoding="utf-8"))
        job = doc["jobs"]["shadow-plan"]
        assert "if" not in job, "job shadow-plan có `if:` — nó sẽ skipped im lặng"
        assert not job.get("continue-on-error")
        khoi = _khoi_on(doc)["pull_request"]
        assert "paths" not in khoi, (
            "shadow phải chạy trên MỌI PR. Có `paths:` thì đúng những PR nó cần "
            "quan sát nhất (chỉ sửa tài liệu, chỉ sửa frontend) lại không có "
            "kế hoạch nào để đối chiếu."
        )

    def test_shadow_ghim_permissions_va_timeout(self):
        """Hai thuộc tính cấp job, không neo nào cũ nhìn tới.

        Mất `permissions` ⇒ rơi về mặc định kho (có thể là write). Mất
        `timeout-minutes` ⇒ một bước treo giữ check tới trần 6 giờ của Actions:
        không đỏ, không xanh, chỉ đứng đó.
        """
        doc = yaml.safe_load(DUONG_WF_SHADOW.read_text(encoding="utf-8"))
        assert doc.get("permissions") == {"contents": "read"}
        assert doc["jobs"]["shadow-plan"].get("timeout-minutes") == 10

    def test_ten_artifact_duoc_dung_o_buoc_DAU_TIEN(self):
        """`OUT` phải được dựng trước MỌI bước có thể đỏ.

        Đo thật: khi `OUT=` còn nằm trong bước "Tính kế hoạch", một bước fetch
        đỏ ở trên làm bước ấy bị SKIP ⇒ `OUT` không bao giờ vào `$GITHUB_ENV` ⇒
        `name: ${{ env.OUT }}` rỗng ⇒ upload đỏ với "Artifact name is not
        valid", che mất lý do thật và **không còn bằng chứng nào**.
        `if: always()` không cứu được, vì chính CÁI TÊN phụ thuộc bước đã skip.
        """
        doc = yaml.safe_load(DUONG_WF_SHADOW.read_text(encoding="utf-8"))
        buoc = doc["jobs"]["shadow-plan"]["steps"]
        co_out = [i for i, b in enumerate(buoc) if "OUT=" in str(b.get("run", ""))]
        assert co_out == [0], (
            "bước dựng `OUT=` phải là bước ĐẦU TIÊN và duy nhất, đang ở %r"
            % co_out)
        assert "uses" not in buoc[0], "bước dựng tên không được phụ thuộc action nào"

    def test_workflow_shadow_truyen_dung_duong_manifest(self):
        """Workflow phải truyền `--manifest .github/scripts/domains.yml`.

        Sai đường manifest bị hiểu như bootstrap "manifest vắng ở base" ⇒
        classifier chạy với 0 miền mà không ai báo. Nay `nap_manifest_tai` bắt
        HEAD phải tồn tại, nhưng dây nối vẫn phải được canh ở đây.
        """
        doc = yaml.safe_load(DUONG_WF_SHADOW.read_text(encoding="utf-8"))
        than = "\n".join(str(b.get("run", ""))
                         for b in doc["jobs"]["shadow-plan"]["steps"])
        assert "--manifest .github/scripts/domains.yml" in than, (
            "workflow shadow không truyền đúng đường manifest."
        )

    def test_workflow_shadow_khong_tat_kiem_dinh_danh(self):
        """CI KHÔNG được truyền `--khong-kiem-dinh-danh`.

        Cờ ấy tồn tại cho việc chạy tay ngoài ngữ cảnh merge của PR. Nó mặc
        định TẮT (tức kiểm định danh mặc định BẬT), nhưng một cờ tồn tại là một
        cờ có thể bị bật — và bật nó thì classifier lại tin ba SHA mà không
        chứng minh gì. Neo này ở cây tệp khác với workflow, nên bật cờ là một
        sửa đổi hai tệp, nhìn thấy được.

        `--head-sha` cũng bắt buộc: thiếu nó thì không có parent2 để đối chiếu.
        """
        doc = yaml.safe_load(DUONG_WF_SHADOW.read_text(encoding="utf-8"))
        than = _than_khong_comment_shell(
            "\n".join(str(b.get("run", ""))
                      for b in doc["jobs"]["shadow-plan"]["steps"]))
        assert "--khong-kiem-dinh-danh" not in than, (
            "workflow đang TẮT kiểm định danh ba SHA — kế hoạch khi ấy nói về "
            "một cặp cây chưa ai chứng minh là của PR này."
        )
        for can in ("--head-sha", "--base-sha", "--merge-sha"):
            assert can in than, "workflow không truyền %s" % can

    def test_workflow_shadow_luu_bang_chung_ke_ca_khi_do(self):
        """Lượt BLOCK mới là lượt cần điều tra nhất.

        Thiếu `if: always()` thì bước upload bị skip khi bước tính đỏ, và lượt
        đó không để lại gì ngoài log. `if-no-files-found: error` biến "không có
        chẩn đoán" thành ĐỎ thay vì bỏ qua im lặng.
        """
        doc = yaml.safe_load(DUONG_WF_SHADOW.read_text(encoding="utf-8"))
        up = [b for b in doc["jobs"]["shadow-plan"]["steps"]
              if str(b.get("uses", "")).startswith("actions/upload-artifact")]
        assert len(up) == 1, "phải có đúng một bước upload"
        assert up[0].get("if") == "always()", (
            "bước upload phải `if: always()` — lượt BLOCK cũng phải để lại bằng chứng."
        )
        assert up[0]["with"].get("if-no-files-found") == "error"
        # Tên artifact là `${{ env.OUT }}`; ba thành phần định danh nằm ở bước
        # dựng `OUT=`. Phải soi ĐÚNG chỗ đó, không soi khoá `name:`.
        dung_out = [b for b in doc["jobs"]["shadow-plan"]["steps"]
                    if "OUT=" in str(b.get("run", ""))]
        assert len(dung_out) == 1, "phải có đúng một bước dựng OUT="
        # Phải soi CHÍNH DÒNG gán, không soi cả thân bước: thân bước còn có
        # `PR_NUMBER=…`, `RUN_ID=…`, `RUN_ATTEMPT=…` ở trên, nên đổi
        # `OUT="shadow-plan.json"` vẫn làm phép tìm trên thân xanh (đã đo).
        than = "\n".join(
            d for d in _than_khong_comment_shell(str(dung_out[0]["run"])).splitlines()
            if d.lstrip().startswith("OUT=")
        )
        assert than.strip(), "không tìm thấy dòng gán `OUT=`"
        for can in ("PR_NUMBER", "RUN_ID", "RUN_ATTEMPT"):
            assert can in than, (
                "tên artifact phải chứa %r — `upload-artifact@v4` từ chối tên "
                "trùng bằng HTTP 409, nên thiếu `RUN_ATTEMPT` là mọi lượt "
                "re-run đỏ ở bước upload, không chỉ mất bằng chứng." % can
            )
        assert str(up[0]["with"].get("name", "")).strip() == "${{ env.OUT }}", (
            "tên artifact phải LÀ `${{ env.OUT }}` — một tên cố định kèm theo là "
            "va chạm 409 giữa các lượt."
        )
        assert str(up[0]["with"].get("path", "")).strip() == "${{ env.OUT }}", (
            "đường tệp upload phải trùng tên đã dựng; lệch đi thì "
            "`if-no-files-found: error` đỏ mọi lượt."
        )
        assert int(up[0]["with"].get("retention-days", 0)) == 90, (
            "`retention-days` phải là 90 — mặc định của repo có thể ngắn hơn "
            "chu kỳ backtest, bằng chứng bay trước khi được đọc."
        )

    def test_paths_van_phu_duong_dan_cua_classifier(self, wf):
        """Cổng phải NHÌN THẤY thứ nó canh.

        Thiếu `.github/scripts/**` thì một PR chỉ sửa classifier hoặc manifest
        không kích hoạt workflow — required check báo "expected, not run", PR
        không merge được, và lối thoát tự nhiên là chạm bừa một tệp khác.
        """
        paths = _khoi_on(wf)["pull_request"]["paths"]
        for can in (".github/workflows/**", ".github/scripts/**"):
            assert can in paths, (
                "bộ lọc `paths` thiếu %r — thay đổi mà hợp đồng classifier sinh "
                "ra để chặn lại chính là thay đổi khiến workflow không chạy." % can
            )


# ---------------------------------------------------------------------------
# 9. Hình dạng job gác + siêu dữ liệu phân vùng Tier 2
# ---------------------------------------------------------------------------
# Mục 1–8 canh *nội dung* cổng: selector nào chạy, ai gom kết quả, hợp đồng
# classifier có đủ sentinel không. Mục này canh *hình dạng* của chính job gác —
# những thuộc tính mà khi mất đi, cổng vẫn tồn tại, vẫn có tên, và vẫn xanh.

DUONG_WF_ADMISSION = GOC / ".github" / "workflows" / "admission-contract-check.yml"
DUONG_PR_CLASSIFY = GOC / ".github" / "scripts" / "pr_classify.py"
TEN_WF_ADMISSION = ".github/workflows/admission-contract-check.yml"
JOB_SHARD = "pytest-shard"
TRAN_PHUT_SHARD = 75
HOP_DONG_PHAN_VUNG = "tier2-rbac-security-v1"
PHAN_VUNG_CAN = {"a", "c"}

#: SHA-256 của HỢP hai lát Tier 2, băm trên **tập đã sắp xếp**:
#:     json.dumps(sorted(set(2a) | set(2c)), separators=(",", ":"))
#: Vì băm trên HỢP chứ không trên từng lát, chuyển một selector từ 2a sang 2c
#: (hay ngược lại) KHÔNG đổi digest — cân lại tải là việc thường, không nên bắt
#: sửa hằng số. Nhưng bỏ / thêm / thay một selector thì đổi, và đó đúng là thứ
#: cần đỏ.
SHA_HOP_SELECTOR_TIER2 = (
    "08380c444af4faca35e4e139f5b41adb1a4876e0f4361e75b56de2151db9035e"
)


def _nap_pr_classify():
    """Nạp `pr_classify` — CHỈ để mượn loader YAML nghiêm ngặt của nó.

    ⚠️ `sys.modules[...] = mod` PHẢI đứng TRƯỚC `exec_module`. Module ấy dùng
    `from __future__ import annotations` + `@dataclass`, và dataclass giải chú
    thích kiểu qua `sys.modules[cls.__module__].__dict__`. Thiếu dòng ấy thì
    nạp module ném `AttributeError: 'NoneType' object has no attribute
    '__dict__'` — đã đo thật trên Python 3.12.
    """
    spec = importlib.util.spec_from_file_location(
        "_pr_classify_cho_test_visibility", DUONG_PR_CLASSIFY
    )
    assert spec and spec.loader, "không nạp được %s" % DUONG_PR_CLASSIFY
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def prc():
    return _nap_pr_classify()


def _cac_leg_phan_vung(cac_leg):
    """Tìm hai lát Tier 2 bằng SIÊU DỮ LIỆU, không bằng tên hiển thị."""
    return [l for l in cac_leg
            if str(l.get("partition_contract", "")) == HOP_DONG_PHAN_VUNG]


class TestWorkflowAdmissionTuNhinThay:
    """Cổng phải nhìn thấy chính thứ nó canh — ở CẢ HAI sự kiện.

    `admission-contract-check.yml` từng liệt kê chính nó trong
    `pull_request.paths` mà KHÔNG có trong `push.paths`. Hệ quả đo được: sửa
    chính cổng ấy rồi merge vào `main` thì nhánh `push:main` không kích hoạt gì
    — cổng không tự kiểm lại sau khi bị sửa. Đúng hình dạng
    `ci-allowlist-tep-khong-duoc-gac`, chỉ đổi chỗ đứng.
    """

    @pytest.fixture(scope="class")
    def on_adm(self, prc):
        """Đọc bằng loader NGHIÊM NGẶT, không `safe_load`.

        `safe_load` nuốt khoá trùng: một `paths:` thứ hai dán nhầm vào cùng
        block sẽ lặng lẽ THAY THẾ cái thứ nhất, và mọi phép đếm bên dưới khi
        ấy đang đếm một danh sách không phải danh sách đang có hiệu lực.
        """
        return _khoi_on(prc.yaml.load(
            DUONG_WF_ADMISSION.read_text(encoding="utf-8"),
            Loader=prc._LoaderNghiemNgat))

    @staticmethod
    def _phai_la_danh_sach_chuoi(paths, ten_su_kien):
        """`paths` dạng SCALAR làm `str.count` xanh giả.

        GitHub đòi `paths` là danh sách chuỗi (sequence of strings). Nếu ai đó viết
        ``paths: ".github/workflows/admission-contract-check.yml"`` thì YAML
        cho một `str`, và `"…yml".count("…yml")` vẫn bằng 1 — phép đếm bên
        dưới xanh trong khi lược đồ trigger đã sai. Chặn ở KIỂU, trước khi đếm.
        """
        assert type(paths) is list, (
            "`%s.paths` phải là DANH SÁCH, nhận %s (%r). `paths` dạng scalar "
            "làm mọi phép `.count()` bên dưới xanh giả."
            % (ten_su_kien, type(paths).__name__, paths)
        )
        assert all(type(p) is str for p in paths), (
            "`%s.paths` có phần tử không phải chuỗi: %r" % (
                ten_su_kien, [p for p in paths if type(p) is not str])
        )

    def test_tu_nhin_thay_o_pull_request(self, on_adm):
        paths = on_adm["pull_request"]["paths"]
        self._phai_la_danh_sach_chuoi(paths, "pull_request")
        assert paths.count(TEN_WF_ADMISSION) == 1, (
            "`pull_request.paths` phải chứa ĐÚNG MỘT lần %r — 0 lần thì sửa "
            "cổng không kích hoạt cổng; 2 lần là dấu hiệu sao chép nhầm."
            % TEN_WF_ADMISSION
        )

    def test_tu_nhin_thay_o_push(self, on_adm):
        paths = on_adm["push"]["paths"]
        self._phai_la_danh_sach_chuoi(paths, "push")
        assert paths.count(TEN_WF_ADMISSION) == 1, (
            "`push.paths` phải chứa ĐÚNG MỘT lần %r. Đây là vế từng THIẾU: "
            "PR có, push không ⇒ bản vá cổng merge vào `main` mà cổng không "
            "chạy lại lần nào." % TEN_WF_ADMISSION
        )


class TestHinhDangJobPytestShard:
    """Hai thuộc tính mà khi mất, job vẫn còn tên và vẫn xanh."""

    @pytest.fixture(scope="class")
    def job(self, wf):
        return wf["jobs"][JOB_SHARD]

    def test_shard_ghim_tran_thoi_gian(self, job):
        """Thiếu `timeout-minutes` ⇒ job kế thừa trần MẶC ĐỊNH 360 phút.

        Một leg treo khi ấy giữ required check `pytest` suốt sáu giờ ở trạng
        thái KHÔNG đỏ cũng KHÔNG xanh — không ai bị báo, PR không merge được,
        và cách thoát tự nhiên là bấm rerun chứ không phải đọc log.

        ⚠️ Phải `type(...) is int`, KHÔNG `isinstance`: `isinstance(True, int)`
        là True, nên `timeout-minutes: true` sẽ lọt. Và YAML `"75"` có nháy cho
        `str`, cũng phải đỏ.
        """
        gia_tri = job.get("timeout-minutes")
        assert type(gia_tri) is int, (
            "`%s.timeout-minutes` phải là số nguyên THẬT, nhận %r (%s). "
            "Thiếu hẳn ⇒ trần mặc định 360 phút."
            % (JOB_SHARD, gia_tri, type(gia_tri).__name__)
        )
        assert gia_tri == TRAN_PHUT_SHARD, (
            "`%s.timeout-minutes` phải là %d, đang là %d."
            % (JOB_SHARD, TRAN_PHUT_SHARD, gia_tri)
        )

    def test_shard_khong_continue_on_error(self, job):
        """`continue-on-error` biến job đỏ thành job xanh.

        ⚠️ Phạm vi có chủ ý: ca này chỉ canh `continue-on-error`, KHÔNG canh
        `if:`. `test_khong_buoc_nao_cua_cac_job_gac_bi_vo_hieu` cố tình loại
        `pytest-shard` khỏi phép cấm `if:` vì các leg matrix có
        `if: matrix.<cờ>` theo thiết kế. Hai ca vì thế không mâu thuẫn nhau.
        """
        assert not job.get("continue-on-error"), (
            "job %r bật `continue-on-error` ở CẤP JOB — mọi shard đỏ sẽ được "
            "báo là thành công." % JOB_SHARD
        )
        for buoc in job.get("steps", []):
            assert not buoc.get("continue-on-error"), (
                "bước %r của %r bật `continue-on-error`."
                % (buoc.get("name") or buoc.get("uses"), JOB_SHARD)
            )


class TestTenLegMatrixDuyNhat:
    """Tên leg đi thẳng vào tên check `pytest shard — ${{ matrix.tier }}`.

    Hai leg trùng tên sinh hai ô check không phân biệt được trên GitHub, và
    `_tier_cua` trả leg KHỚP ĐẦU TIÊN — nên bất biến "hai neo ở HAI tier khác
    nhau" mất nghĩa mà vẫn xanh. So sau NFKC + casefold vì `Tier 2A` và
    `Tier 2a` là hai chuỗi khác nhau với Python nhưng là cùng một thứ với mắt
    người đọc log.

    ⚠️ Khoảng trắng cũng phải chuẩn hoá. `"Tier 2a — X "` và `"Tier 2a — X"`
    khác nhau với `==`, mà trên GitHub là hai ô check TRÔNG y hệt nhau —
    người đọc log không có cách nào phân biệt. Chuẩn hoá bằng
    `" ".join(s.split())` để gộp cả khoảng trắng đầu/cuối lẫn khoảng trắng
    nội bộ dư.
    """

    def test_moi_ten_leg_khac_rong(self, cac_leg):
        for leg in cac_leg:
            ten = leg.get("tier")
            assert isinstance(ten, str) and ten.strip(), (
                "leg có `tier` rỗng hoặc không phải chuỗi: %r" % (ten,))
            assert ten == ten.strip(), (
                "tên leg có khoảng trắng thừa ở đầu/cuối: %r. Nó vô hình trên "
                "giao diện check nhưng làm mọi phép so tên trượt." % (ten,))

    def test_ten_leg_duy_nhat_sau_chuan_hoa(self, cac_leg):
        chuan = [" ".join(unicodedata.normalize("NFKC", str(l["tier"])).split())
                 .casefold()
                 for l in cac_leg]
        trung = sorted({t for t in chuan if chuan.count(t) > 1})
        assert not trung, (
            "tên leg TRÙNG sau NFKC + gộp khoảng trắng + casefold: %s — "
            "GitHub sẽ dựng hai check trông y hệt nhau và `_tier_cua` chỉ "
            "thấy cái đầu." % trung)


class TestSelectorThatDiQuaGuard:
    """Workflow THẬT phải đi lọt guard, không chỉ YAML tự chế.

    `TestSelectorTrungLapVaChongLan` chạy `phan_tich_selector` trên ba dòng
    YAML viết tay — nó chứng minh guard BẮT được lỗi, không chứng minh rằng
    `backend-test.yml` hiện tại còn qua được guard ấy. Hai điều khác nhau, và
    chỉ điều thứ hai mới hỏng khi ai đó sửa ma trận.
    """

    def test_workflow_that_qua_duoc_phan_tich_selector(self, guard):
        whole, nodeid = guard.phan_tich_selector(
            DUONG_WF.read_text(encoding="utf-8"))
        assert whole, "guard trả tập whole-file RỖNG — ma trận không còn selector nào"
        tong = len(whole) + sum(len(v) for v in nodeid.values())
        assert tong > 0
        # KHÔNG ghim 226/207: chúng là số ĐỘNG. Thứ cần khoá là "guard không
        # ném ngoại lệ và không trả tập rỗng".

    def test_guard_thay_dung_tap_tep_ma_fixture_thay(self, guard, cac_leg):
        """Buộc hai đường đọc ma trận phải đồng ý với nhau.

        `guard.phan_tich_selector` và fixture `cac_leg` là hai bản đọc độc lập
        của cùng một khối `matrix.include`. Nếu chúng lệch nhau thì một trong
        hai đang nhìn nhầm chỗ, và mọi phép kiểm dựa trên bản kia đều vô nghĩa.
        """
        whole, nodeid = guard.phan_tich_selector(
            DUONG_WF.read_text(encoding="utf-8"))
        tu_fixture = {x for leg in cac_leg for x in str(leg.get("tests", "")).split()}
        tu_guard = set(whole) | {x for v in nodeid.values() for x in v}
        assert tu_guard == tu_fixture, (
            "guard và fixture bất đồng: chỉ guard thấy %s; chỉ fixture thấy %s"
            % (sorted(tu_guard - tu_fixture)[:3], sorted(tu_fixture - tu_guard)[:3]))


class TestYamlThoQuaLoaderNghiemNgat:
    """`safe_load` NUỐT khoá trùng — im lặng giữ giá trị CUỐI.

    Đo thật: `yaml.safe_load("jobs:\\n  a:\\n    x: 1\\n    x: 2\\n")` trả
    `{'jobs': {'a': {'x': 2}}}`, không cảnh báo gì. Nghĩa là một `tests:` thứ
    hai dán nhầm vào cùng một leg sẽ lặng lẽ thay thế cái thứ nhất, và mọi
    phép kiểm đọc qua `safe_load` đều mù. Loader nghiêm ngặt của classifier
    từ chối ca đó, nên workflow phải qua được NÓ.
    """

    def test_backend_test_yml_qua_duoc_loader_nghiem_ngat(self, prc):
        prc.yaml.load(DUONG_WF.read_text(encoding="utf-8"),
                      Loader=prc._LoaderNghiemNgat)

    def test_loader_that_su_tu_choi_khoa_trung(self, prc):
        """Đối chứng: nếu loader không từ chối gì thì ca trên vô nghĩa."""
        with pytest.raises(prc.LoiManifest):
            prc.yaml.load("jobs:\n  a:\n    x: 1\n    x: 2\n",
                          Loader=prc._LoaderNghiemNgat)


class TestPhanVungTier2TheoSieuDuLieu:
    """Tìm hai lát Tier 2 bằng SIÊU DỮ LIỆU, không bằng tên hiển thị.

    Tên hiển thị là văn bản cho người đọc log — đổi chữ trong đó là việc
    thường. Ghim phép kiểm vào tên hiển thị thì một lần sửa mô tả làm phép
    lọc khớp 0 leg, và một phép kiểm chạy trên tập rỗng thì **xanh**. Siêu dữ
    liệu `partition_contract` / `partition_part` tồn tại chỉ để máy tìm.
    """

    def test_dung_hai_phan_a_va_c(self, cac_leg):
        legs = _cac_leg_phan_vung(cac_leg)
        assert len(legs) == 2, (
            "phải có ĐÚNG HAI leg mang `partition_contract: %s`, thấy %d — "
            "gỡ khỏi một lát, hoặc gắn cho lát thứ ba, đều làm hợp đồng phân "
            "hoạch mất nghĩa." % (HOP_DONG_PHAN_VUNG, len(legs)))
        phan = sorted(str(l.get("partition_part", "")) for l in legs)
        assert set(phan) == PHAN_VUNG_CAN and len(set(phan)) == 2, (
            "`partition_part` phải là đúng {'a','c'}, thấy %r" % phan)

    def test_hop_selector_hai_lat_dung_digest(self, cac_leg):
        """Digest băm trên HỢP đã sắp xếp ⇒ chuyển selector 2a↔2c không đổi.

        Sinh lại khi cố ý đổi tập selector Tier 2:

            python - <<'EOF'
            import hashlib, json, yaml
            wf = yaml.safe_load(open(".github/workflows/backend-test.yml", encoding="utf-8"))
            legs = wf["jobs"]["pytest-shard"]["strategy"]["matrix"]["include"]
            u = sorted({t for l in legs
                        if l.get("partition_contract") == "tier2-rbac-security-v1"
                        for t in str(l["tests"]).split()})
            print(hashlib.sha256(json.dumps(u, separators=(",", ":")).encode()).hexdigest())
            EOF
        """
        legs = _cac_leg_phan_vung(cac_leg)
        assert len(legs) == 2, "cần đúng hai lát trước khi băm; thấy %d" % len(legs)
        theo_phan = {str(l["partition_part"]): str(l["tests"]).split() for l in legs}
        a, c = theo_phan["a"], theo_phan["c"]
        assert not (set(a) & set(c)), (
            "hai lát GIAO NHAU: %s" % sorted(set(a) & set(c)))
        hop = sorted(set(a) | set(c))
        assert hop, "hợp hai lát RỖNG — mọi phép băm sau đây sẽ vô nghĩa"
        bam = hashlib.sha256(
            json.dumps(hop, separators=(",", ":")).encode("utf-8")).hexdigest()
        assert bam == SHA_HOP_SELECTOR_TIER2, (
            "tập selector Tier 2 đã đổi: digest %s, cần %s. Bỏ/thêm/thay một "
            "selector là đổi; chuyển giữa 2a và 2c thì KHÔNG."
            % (bam, SHA_HOP_SELECTOR_TIER2))
