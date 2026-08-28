#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cổng ĐỘ NHÌN THẤY của test: thứ vừa đụng vào phải được PHÂN LOẠI.

Vì sao cổng này tồn tại
=======================

``backend-test.yml`` chọn test bằng danh sách selector viết tay. Một tệp test
không có tên trong tier nào thì **không shard nào chạy nó**, mà required check
``pytest`` vẫn xanh — nó chỉ tổng hợp kết quả của những shard CÒN TỒN TẠI, nó
không biết có thứ gì vừa biến mất khỏi danh sách.

Đo trên ``ebe9311e``: 544 tệp ``test_*.py`` được theo dõi, 176 selector trỏ tới
157 tệp. 387 tệp đứng ngoài mọi tier. Trong 176 selector có 26 là *nodeid* —
chúng phủ 7 tệp một cách MỘT PHẦN, và đó là dạng mù nguy hiểm nhất vì tệp
"trông như" đã được gate.

Ca thật: ``tests/utils/test_file_helpers.py`` có 10 ca, đúng 1 ca nằm trong
Tier 5, và 9 ca còn lại đỏ nightly. PR gate xanh 100% trên tệp hỏng 9/10.

Cổng này KHÔNG ép 387 tệp cũ vào PR gate — làm thế là biến gate thành full
suite trá hình. Nó chỉ đòi: **thứ bạn vừa thêm hoặc vừa sửa phải được phân
loại**, và **độ phủ đang có không được âm thầm tụt xuống**.

Mô hình Record
==============

Với mỗi tệp test, dựng một ``Record`` ở base và ở head::

    Record = (exists, blob_oid, whole_selector, nodeid_selectors,
              ledger_entry, nightly_included)

Rồi áp đúng hai nhánh:

1. ``Record_base == Record_head`` → **grandfather**, xanh. Nợ cũ đứng yên thì
   không ai bị chặn: legacy NONE không ledger, legacy PARTIAL không ledger đều
   đi qua.

2. Khác một trường bất kỳ → trạng thái ở head **phải hợp lệ**:

   ============  =====================================================
   trạng thái    điều kiện
   ============  =====================================================
   WHOLE         không còn ledger entry
   PARTIAL       ledger ``partial`` · blob khớp · nodeids khớp CHÍNH XÁC
                 · ``nightly_included``
   NONE          ledger ``nightly-only`` · blob khớp · ``nightly_included``
   đã xoá        không selector, không ledger
   ============  =====================================================

``blob_oid`` chính là thứ trả lời "tệp có bị sửa không" — nhờ nó, guard không
cần đọc nội dung diff và cũng không cần ``--collect-only`` để đếm số ca. Thêm
ca thứ 11 vào một tệp ``partial`` làm đổi nội dung ⇒ đổi blob ⇒ Record đổi ⇒
phải khai báo lại. Bài toán "liệt kê hết ca trong tệp" được né hẳn.

⚠️ ``PARTIAL`` bắt buộc ``nightly_included``. Thiếu điều kiện này thì một lượt
thêm ``--ignore-glob`` vào nightly có thể nuốt trọn tệp trong khi ledger, blob
và nodeids đều còn khớp — và phần ngoài selector rơi khỏi CẢ HAI cổng mà không
gì đỏ. ``WHOLE`` không cần điều kiện ấy vì PR gate đã chạy trọn tệp.

Đọc gì, đọc từ đâu
==================

Mọi phép đọc lấy từ **cây Git tại SHA**, không lấy từ index hay working tree:
``git ls-tree`` để liệt kê, ``git show`` để đọc nội dung, ``git rev-parse
<SHA>:<path>`` để lấy blob. Trên sự kiện ``pull_request``, ``github.sha`` là
commit merge tổng hợp của PR — đúng cây sẽ được áp lên base — nên phép so là
``git diff BASE_SHA MERGE_SHA``, hai cây, KHÔNG cần merge-base và KHÔNG cần
lịch sử đầy đủ.

Fail-closed
===========

Ledger vắng mặt ở base (lượt rollout đầu tiên) là hợp lệ và cho ``{}`` — nhưng
CHỈ khi ``git ls-tree`` xác nhận đường dẫn không có trong cây. Mọi lỗi Git hay
YAML khác đều làm cổng đỏ. Không bắt exception chung rồi trả ``{}``: đó đúng
dạng fail-open mà ``pip_audit_count.py`` đã vấp một lần.
"""

from __future__ import annotations

import fnmatch
import os
import posixpath
import re
import subprocess
import sys

try:
    import yaml
except ImportError:  # pragma: no cover - môi trường thiếu PyYAML
    print("::error::pytest_visibility_guard cần PyYAML", file=sys.stderr)
    raise

# Selector trong workflow tương đối với ``working-directory: Backend_FastAPI``.
GOC_BACKEND = "Backend_FastAPI"
DUONG_WORKFLOW = ".github/workflows/backend-test.yml"
DUONG_NIGHTLY = ".github/workflows/nightly-backend-pytest.yml"
DUONG_LEDGER_TUONG_DOI = "tests/VISIBILITY_LEDGER.yml"
DUONG_LEDGER = posixpath.join(GOC_BACKEND, DUONG_LEDGER_TUONG_DOI)
DUONG_SCRIPT_GUARD = ".github/scripts/pytest_visibility_guard.py"

TRANG_THAI_HOP_LE = ("partial", "nightly-only")
KHOA_LEDGER_HOP_LE = {"path", "status", "reason", "blob", "nodeids"}

_RE_TEST_PY = re.compile(r"(?:^|/)test_[^/]+\.py$")


class LoiCong(Exception):
    """Vi phạm khiến cổng đỏ. Thông điệp là thứ người đọc log sẽ thấy."""


# ---------------------------------------------------------------------------
# Lớp mỏng bọc Git — mọi phép đọc đều theo SHA
# ---------------------------------------------------------------------------


def _git(*doi_so: str, cho_phep_that_bai: bool = False) -> str:
    ket_qua = subprocess.run(
        ("git",) + doi_so,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if ket_qua.returncode != 0 and not cho_phep_that_bai:
        raise LoiCong(
            "git %s thoát %d: %s"
            % (" ".join(doi_so), ket_qua.returncode, ket_qua.stderr.strip())
        )
    return ket_qua.stdout


def duong_dan_co_trong_cay(sha: str, duong: str) -> bool:
    """``True`` khi ``duong`` tồn tại trong cây của ``sha``.

    Dùng ``ls-tree`` chứ không dùng ``git show`` rồi bắt lỗi: ``ls-tree`` trả 0
    và output RỖNG cho đường dẫn không có, nên "không tồn tại" phân biệt được
    rạch ròi với "Git hỏng". Nhập nhằng hai ca đó chính là cách fail-open lẻn
    vào.
    """
    return bool(_git("ls-tree", "--name-only", sha, "--", duong).strip())


def doc_blob(sha: str, duong: str) -> str:
    return _git("show", "%s:%s" % (sha, duong))


def blob_oid(sha: str, duong: str) -> str | None:
    if not duong_dan_co_trong_cay(sha, duong):
        return None
    return _git("rev-parse", "%s:%s" % (sha, duong)).strip()


def liet_ke_tep_test(sha: str) -> set[str]:
    """Tệp ``test_*.py`` dưới ``Backend_FastAPI/tests``, đường dẫn TƯƠNG ĐỐI."""
    thu_muc = posixpath.join(GOC_BACKEND, "tests")
    ra = _git("ls-tree", "-r", "--name-only", sha, "--", thu_muc)
    tep = set()
    for dong in ra.splitlines():
        dong = dong.strip()
        if dong and _RE_TEST_PY.search(dong):
            tep.add(posixpath.relpath(dong, GOC_BACKEND))
    return tep


# ---------------------------------------------------------------------------
# Đọc workflow
# ---------------------------------------------------------------------------


def _cac_leg_matrix(doc: dict) -> list[dict]:
    try:
        return doc["jobs"]["pytest-shard"]["strategy"]["matrix"]["include"]
    except (KeyError, TypeError) as loi:
        raise LoiCong("không đọc được matrix pytest-shard: %r" % (loi,))


def phan_tich_selector(noi_dung_wf: str) -> tuple[set[str], dict[str, set[str]]]:
    """Tách selector thành (tệp whole-file, {tệp: tập nodeid}).

    YAML đã gấp scalar ``>-`` thành một dòng, nên ``split()`` ở đây tái lập
    đúng cách bash nhận đối số.
    """
    doc = yaml.safe_load(noi_dung_wf)
    whole: set[str] = set()
    nodeid: dict[str, set[str]] = {}
    trung: list[str] = []
    da_thay: set[str] = set()

    for leg in _cac_leg_matrix(doc):
        for sel in str(leg.get("tests", "")).split():
            if sel in da_thay:
                trung.append(sel)
            da_thay.add(sel)
            if "::" in sel:
                tep = sel.split("::", 1)[0]
                nodeid.setdefault(tep, set()).add(sel)
            else:
                whole.add(sel)

    if trung:
        raise LoiCong(
            "selector TRÙNG LẶP (v1 không có cơ chế trùng chủ ý): %s"
            % ", ".join(sorted(set(trung)))
        )
    chong_lan = whole & set(nodeid)
    if chong_lan:
        raise LoiCong(
            "tệp vừa có whole-file vừa có nodeid — chọn một: %s"
            % ", ".join(sorted(chong_lan))
        )
    return whole, nodeid


def cac_ignore_glob_nightly(noi_dung_nightly: str) -> list[str]:
    """Lấy ``--ignore-glob`` từ NGUỒN CHUẨN là workflow nightly.

    Không hardcode danh sách ở đây: nếu nightly được sửa để bỏ qua thêm một
    tệp, guard phải thấy điều đó và đỏ khi tệp ấy đang dựa vào nightly để được
    nhìn thấy.
    """
    doc = yaml.safe_load(noi_dung_nightly)
    globs: list[str] = []
    for gia_tri in (doc.get("env") or {}).values():
        for phan in str(gia_tri).split():
            if phan.startswith("--ignore-glob="):
                globs.append(phan.split("=", 1)[1])
    return globs


def nightly_thu_thap(duong_tuong_doi: str, globs: list[str]) -> bool:
    return not any(fnmatch.fnmatch(duong_tuong_doi, g) for g in globs)


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


def doc_ledger(sha: str) -> dict[str, dict]:
    """Đọc ledger tại ``sha``. Vắng mặt ⇒ ``{}``; mọi lỗi khác ⇒ đỏ."""
    if not duong_dan_co_trong_cay(sha, DUONG_LEDGER):
        return {}
    tho = doc_blob(sha, DUONG_LEDGER)
    try:
        doc = yaml.safe_load(tho)
    except yaml.YAMLError as loi:
        raise LoiCong("ledger tại %s không phải YAML hợp lệ: %s" % (sha[:8], loi))
    if doc is None:
        return {}
    if not isinstance(doc, list):
        raise LoiCong(
            "ledger phải là DANH SÁCH các entry, nhận %s" % type(doc).__name__
        )

    ket: dict[str, dict] = {}
    for muc in doc:
        if not isinstance(muc, dict):
            raise LoiCong("entry ledger phải là ánh xạ, nhận %r" % (muc,))
        duong = muc.get("path")
        if duong in ket:
            raise LoiCong("ledger có path TRÙNG LẶP: %s" % duong)
        ket[duong] = muc
    return ket


def kiem_luoc_do_ledger(ledger: dict[str, dict], tep_test: set[str]) -> list[str]:
    """Kiểm lược đồ, fail-closed. Trả danh sách lỗi (rỗng = đạt)."""
    loi: list[str] = []
    for duong, muc in sorted(ledger.items()):
        nhan = "ledger[%s]" % duong

        thua = set(muc) - KHOA_LEDGER_HOP_LE
        if thua:
            loi.append("%s: khoá lạ %s" % (nhan, sorted(thua)))

        if not isinstance(duong, str) or not duong:
            loi.append("%s: path phải là chuỗi khác rỗng" % nhan)
            continue
        xau = duong.startswith("/") or ":" in duong or "\\" in duong
        if xau or ".." in duong.split("/"):
            loi.append("%s: path phải tương đối, không '..', không '\\'" % nhan)
            continue
        if not _RE_TEST_PY.search(duong):
            loi.append("%s: path phải là test_*.py" % nhan)
            continue
        if duong not in tep_test:
            loi.append("%s: path KHÔNG tồn tại trong cây (ledger chết)" % nhan)
            continue

        trang_thai = muc.get("status")
        if trang_thai not in TRANG_THAI_HOP_LE:
            loi.append(
                "%s: status phải thuộc %s, nhận %r"
                % (nhan, list(TRANG_THAI_HOP_LE), trang_thai)
            )

        ly_do = muc.get("reason")
        # Kiểm GIÁ TRỊ dùng được, không phải sự tồn tại của khoá: ``"   "``,
        # ``""``, ``None`` và sai kiểu đều phải trượt.
        if not isinstance(ly_do, str) or not ly_do.strip():
            loi.append("%s: reason phải là chuỗi khác rỗng sau strip()" % nhan)

        blob = muc.get("blob")
        if not isinstance(blob, str) or not re.fullmatch(r"[0-9a-f]{40}", blob or ""):
            loi.append("%s: blob phải là 40 ký tự hex" % nhan)

        nodeids = muc.get("nodeids")
        if trang_thai == "partial":
            if not isinstance(nodeids, list) or not nodeids:
                loi.append("%s: partial bắt buộc có ≥1 nodeid" % nhan)
            elif len(set(nodeids)) != len(nodeids):
                loi.append("%s: nodeids TRÙNG LẶP" % nhan)
            elif any(not isinstance(n, str) or "::" not in n for n in nodeids):
                loi.append("%s: mỗi nodeid phải là chuỗi chứa '::'" % nhan)
        elif trang_thai == "nightly-only" and "nodeids" in muc:
            # Kiểm SỰ TỒN TẠI của khoá, không kiểm tính truthy: `nodeids: []`,
            # `""` và `{}` đều falsy nên phép kiểm cũ cho chúng lọt, và mục
            # ledger khi ấy hứa một đằng (nightly-only) mà mang cấu trúc của
            # một đằng khác. Cùng họ với bẫy `"skip_reason" in dep`, chỉ ngược
            # chiều: ở đây khoá CÓ MẶT mới là vi phạm.
            loi.append("%s: nightly-only không được khai nodeids" % nhan)
    return loi


# ---------------------------------------------------------------------------
# Record + luật
# ---------------------------------------------------------------------------


def dung_record(sha: str, ledger: dict[str, dict], globs: list[str]) -> dict[str, dict]:
    noi_dung_wf = doc_blob(sha, DUONG_WORKFLOW)
    whole, nodeid = phan_tich_selector(noi_dung_wf)
    tep_test = liet_ke_tep_test(sha)

    moi_duong = tep_test | whole | set(nodeid) | set(ledger)
    ban_ghi: dict[str, dict] = {}
    for duong in moi_duong:
        ton_tai = duong in tep_test
        ban_ghi[duong] = {
            "exists": ton_tai,
            "blob_oid": (
                blob_oid(sha, posixpath.join(GOC_BACKEND, duong)) if ton_tai else None
            ),
            "whole_selector": duong in whole,
            "nodeid_selectors": frozenset(nodeid.get(duong, ())),
            "ledger_entry": ledger.get(duong),
            "nightly_included": nightly_thu_thap(duong, globs) if ton_tai else False,
        }
    return ban_ghi


def _trang_thai(rec: dict) -> str:
    if not rec["exists"]:
        return "ĐÃ XOÁ"
    if rec["whole_selector"]:
        return "WHOLE"
    if rec["nodeid_selectors"]:
        return "PARTIAL"
    return "NONE"


def kiem_trang_thai_head(duong: str, rec: dict) -> list[str]:
    """Trạng thái ở head có hợp lệ không. Trả danh sách lỗi."""
    loi: list[str] = []
    entry = rec["ledger_entry"]
    tt = _trang_thai(rec)

    if tt == "ĐÃ XOÁ":
        if rec["whole_selector"] or rec["nodeid_selectors"]:
            loi.append("%s: tệp đã xoá nhưng selector vẫn còn trong tier" % duong)
        if entry is not None:
            loi.append("%s: tệp đã xoá nhưng ledger entry vẫn còn" % duong)
        return loi

    if tt == "WHOLE":
        if entry is not None:
            loi.append(
                "%s: đã whole-file trong tier — ledger entry LỖI THỜI, phải xoá" % duong
            )
        return loi

    if tt == "PARTIAL":
        if entry is None:
            loi.append(
                "%s: chỉ có nodeid trong tier. Nodeid KHÔNG tính là whole-file "
                "coverage — hoặc thêm selector whole-file, hoặc khai ledger "
                "status: partial kèm reason/blob/nodeids." % duong
            )
            return loi
        if entry.get("status") != "partial":
            loi.append(
                "%s: trạng thái là PARTIAL nhưng ledger khai %r"
                % (duong, entry.get("status"))
            )
        if entry.get("blob") != rec["blob_oid"]:
            loi.append(
                "%s: nội dung tệp đã đổi (blob %s ≠ ledger %s) — waiver hết hiệu "
                "lực, xem lại rồi cập nhật ledger"
                % (duong, (rec["blob_oid"] or "—")[:12], str(entry.get("blob"))[:12])
            )
        khai = set(entry.get("nodeids") or ())
        thuc = set(rec["nodeid_selectors"])
        if khai != thuc:
            loi.append(
                "%s: tập nodeid lệch — tier thừa %s / thiếu %s so với ledger"
                % (duong, sorted(thuc - khai) or "∅", sorted(khai - thuc) or "∅")
            )
        if not rec["nightly_included"]:
            loi.append(
                "%s: PARTIAL nhưng nightly BỎ QUA tệp này ⇒ phần ngoài nodeid "
                "không còn cổng nào nhìn thấy" % duong
            )
        return loi

    # NONE
    if entry is None:
        loi.append(
            "%s: không selector nào và không có ledger entry. Thêm selector "
            "whole-file, hoặc khai ledger status: nightly-only kèm reason/blob." % duong
        )
        return loi
    if entry.get("status") != "nightly-only":
        loi.append(
            "%s: không có selector nào nhưng ledger khai %r"
            % (duong, entry.get("status"))
        )
    if entry.get("blob") != rec["blob_oid"]:
        loi.append(
            "%s: nội dung tệp đã đổi (blob %s ≠ ledger %s) — cập nhật ledger"
            % (duong, (rec["blob_oid"] or "—")[:12], str(entry.get("blob"))[:12])
        )
    if not rec["nightly_included"]:
        loi.append(
            "%s: khai nightly-only nhưng nightly BỎ QUA tệp này ⇒ không cổng "
            "nào chạy nó"
            % duong
        )
    return loi


def _chan_doan_mat_nodeid(duong: str, cu: dict | None, moi: dict) -> list[str]:
    """In riêng nodeid MẤT và nodeid THÊM.

    Quan hệ tập con không đủ: ``{A,B} → {B,C}`` không phải tập con nhưng A đã
    mất coverage. Phải so hai chiều.
    """
    if cu is None:
        return []
    mat = sorted(set(cu["nodeid_selectors"]) - set(moi["nodeid_selectors"]))
    them = sorted(set(moi["nodeid_selectors"]) - set(cu["nodeid_selectors"]))
    if not mat:
        return []
    dong = ["%s: MẤT coverage nodeid: %s" % (duong, ", ".join(mat))]
    if them:
        dong.append(
            "%s: (có thêm: %s — thêm KHÔNG bù cho mất)" % (duong, ", ".join(them))
        )
    return dong


def so_sanh(
    base: dict[str, dict], head: dict[str, dict]
) -> tuple[list[str], list[str]]:
    """Trả (lỗi, ghi chú chẩn đoán)."""
    loi: list[str] = []
    ghi_chu: list[str] = []
    for duong in sorted(set(base) | set(head)):
        rec_cu = base.get(duong)
        rec_moi = head.get(duong)
        if rec_moi is None:
            # Không còn xuất hiện ở head dưới bất kỳ dạng nào — đã xoá sạch.
            continue
        if rec_cu == rec_moi:
            continue  # grandfather: nợ cũ đứng yên thì không chặn ai
        ghi_chu.extend(_chan_doan_mat_nodeid(duong, rec_cu, rec_moi))
        if rec_cu is not None and _trang_thai(rec_cu) != _trang_thai(rec_moi):
            ghi_chu.append(
                "%s: %s → %s" % (duong, _trang_thai(rec_cu), _trang_thai(rec_moi))
            )
        loi.extend(kiem_trang_thai_head(duong, rec_moi))
    return loi, ghi_chu


# ---------------------------------------------------------------------------
# Điểm vào
# ---------------------------------------------------------------------------


def chay(base_sha: str, merge_sha: str) -> int:
    globs_head = cac_ignore_glob_nightly(doc_blob(merge_sha, DUONG_NIGHTLY))
    globs_base = cac_ignore_glob_nightly(doc_blob(base_sha, DUONG_NIGHTLY))

    ledger_head = doc_ledger(merge_sha)
    ledger_base = doc_ledger(base_sha)

    tep_head = liet_ke_tep_test(merge_sha)
    loi_luoc_do = kiem_luoc_do_ledger(ledger_head, tep_head)

    rec_base = dung_record(base_sha, ledger_base, globs_base)
    rec_head = dung_record(merge_sha, ledger_head, globs_head)
    loi_so_sanh, ghi_chu = so_sanh(rec_base, rec_head)

    tat_ca = loi_luoc_do + loi_so_sanh
    print(
        "cổng độ nhìn thấy của test — base=%s head=%s"
        % (base_sha[:8], merge_sha[:8])
    )
    print("  tệp test ở head            : %d" % len(tep_head))
    print("  entry ledger               : %d" % len(ledger_head))
    print("  ignore-glob nightly        : %s" % (globs_head or "—"))
    for d in ghi_chu:
        print("  ~ %s" % d)
    if not tat_ca:
        print("ĐẠT — mọi thay đổi đều đã được phân loại.")
        return 0
    for d in tat_ca:
        print("::error::%s" % d)
    print("ĐỎ — %d vi phạm." % len(tat_ca))
    return 1


def main(argv: list[str] | None = None) -> int:
    del argv
    base = os.environ.get("BASE_SHA", "").strip()
    head = os.environ.get("MERGE_SHA", "").strip()
    if not base or not head:
        print("::error::thiếu BASE_SHA hoặc MERGE_SHA", file=sys.stderr)
        return 2
    try:
        return chay(base, head)
    except LoiCong as loi:
        print("::error::%s" % loi, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
