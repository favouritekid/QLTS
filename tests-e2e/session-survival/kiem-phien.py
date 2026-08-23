#!/usr/bin/env python3
"""Cổng SỐNG SÓT PHIÊN — phiên pytest của một tệp test phải kết thúc bình thường.

Đo ba điều, theo TỪNG NODE, không đọc cú pháp và không phụ thuộc việc ai vá
bằng cách nào:

  1. không ``INTERNALERROR``;
  2. mã thoát thuộc {0, 1} — 0 = mọi test xanh, 1 = có test đỏ nhưng phiên bình
     thường. KHÔNG khoá cứng 1: chín lỗi cũ của tệp mục tiêu được sửa hết thì
     pytest trả 0, và một guard khoá cứng 1 sẽ đỏ ngay lúc mọi thứ tốt lên;
  3. số node THỰC THI bằng số node THU THẬP — và node sentinel chỉ định phải có
     kết quả ``passed``.

Vế 3 chính là chỗ cổng độ phủ của nightly còn thiếu: cổng ấy chứng minh node đã
được PHÂN LÁT, không chứng minh đã THỰC THI. shard-06 của run 32513696715 phân
lát 744 node, thực thi 737 — bảy test không bao giờ chạy mà cổng vẫn xanh.

## Chạy ở đâu

CI gọi nó qua job ``session-survival`` trong ``.github/workflows/backend-test.yml``,
và job gom ``pytest`` (required check) đòi job ấy phải success — nếu không thì
nó không thuộc cổng nào và PR gate vẫn xanh khi bất biến bị phá.

Nó là một JOB RIÊNG chứ không phải một node pytest, vì tiến trình cha phải nhẹ.
Khi nó nằm trong bộ test, cha là pytest đang giữ cả ứng dụng và cha + con vượt
trần bộ nhớ 1G của service ``backend``: đo tại máy được ``OSError: [Errno 12]
Cannot allocate memory`` ở 1/5 rồi 2/4 lượt, kể cả sau ``--noconftest`` và sau
khi dừng các dịch vụ dev. Tách ra thành script độc lập: 3/3 lượt ổn định.

Chạy tay, từ ``Backend_FastAPI``::

    python ../tests-e2e/session-survival/kiem-phien.py \
        tests/utils/test_file_helpers.py test_khong_ro_ri_stdlib

Tham số: ``<duong-dan-tep-test> [ten-node-sentinel]``.

Mã thoát: ``0`` đạt · ``1`` lệch · ``3`` KHÔNG ĐO ĐƯỢC (tiến trình con bị giết,
bị treo quá trần, không thu thập được node…). Không đo được thì báo, không suy
ra là đạt.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree

NL = chr(10)


# Hai lớp trần thời gian, vì đây là cổng REQUIRED:
#   - `timeout-minutes` cho job trong workflow;
#   - `subprocess.run(timeout=...)` ở đây, để lượt treo trả về mã 3 (KHÔNG ĐO
#     ĐƯỢC) thay vì giữ check tới trần mặc định của Actions;
#   - `--timeout=60` cho lượt CHẠY, để một test treo bị chính pytest cắt và
#     phiên vẫn kết thúc bình thường — đúng thứ cổng này đo.
# Hai trần này phải CỘNG LẠI còn biên so với `timeout-minutes` của job, kể cả
# sau khi trừ thời gian setup. Xem khối chú thích ở job `session-survival`.
TRAN_THU_THAP = 120
TRAN_CHAY = 300


def _chay(goc, tran, *doi_so):
    return subprocess.run(
        [sys.executable, "-m", "pytest", *doi_so, "--noconftest",
         "-p", "no:cacheprovider"],
        capture_output=True, text=True, cwd=str(goc), timeout=tran,
    )


def main(argv):
    if not 2 <= len(argv) <= 3:
        print(__doc__)
        return 3
    tep = Path(argv[1])
    sentinel = argv[2] if len(argv) == 3 else None
    goc = Path.cwd()
    if not (goc / tep).is_file():
        print("KHONG THAY %s (cwd=%s)" % (tep, goc))
        return 3

    try:
        thu_thap = _chay(goc, TRAN_THU_THAP, str(tep), "--collect-only", "-qq")
    except subprocess.TimeoutExpired:
        print("THU THAP TREO qua %ds — KHONG DO DUOC." % TRAN_THU_THAP)
        return 3
    if thu_thap.returncode != 0:
        print("KHONG THU THAP DUOC NODE (rc=%d)" % thu_thap.returncode)
        print(thu_thap.stdout[-800:])
        print(thu_thap.stderr[-800:])
        return 3
    node = [d for d in thu_thap.stdout.splitlines() if "::" in d]
    if len(node) < 2:
        print("Chi thay %d node — phep dem dang hong, khong phai tep dang rong."
              % len(node))
        return 3
    print("thu thap: %d node" % len(node))

    # Đường dẫn tạm DUY NHẤT mỗi lượt. Bản trước ghi ``.kiem-phien.xml`` cố
    # định trong worktree: bị kill giữa chừng thì tệp còn lại, và lượt sau đọc
    # nhầm báo cáo cũ rồi kết luận trên dữ liệu của lượt khác.
    thu_muc_tam = tempfile.mkdtemp(prefix="kiem-phien-")
    bao_cao = Path(thu_muc_tam) / "ket-qua.xml"
    try:
        try:
            kq = _chay(goc, TRAN_CHAY, str(tep), "-q", "--tb=long",
                       "--timeout=60", "--junitxml=" + str(bao_cao))
        except subprocess.TimeoutExpired:
            print("LUOT CHAY TREO qua %ds — KHONG DO DUOC." % TRAN_CHAY)
            return 3
        ra = kq.stdout + kq.stderr

        if kq.returncode in (-9, 137) or "Cannot allocate memory" in ra:
            print("TIEN TRINH CON BI GIET (rc=%d) — KHONG DO DUOC, khong ket"
                  " luan gi. Cap them bo nho roi chay lai." % kq.returncode)
            return 3
        if "INTERNALERROR" in ra:
            print("DO: phien pytest CHET giua chung." + NL + ra[-1500:])
            return 1
        # Chấp nhận CẢ 0 lẫn 1: 0 = mọi test xanh, 1 = có test đỏ nhưng phiên
        # bình thường. Khoá cứng 1 thì khi chín lỗi cũ được sửa hết, guard sẽ
        # đỏ — mâu thuẫn với chính tuyên bố "không khoá số lỗi".
        if kq.returncode not in (0, 1):
            print("DO: mong ma thoat 0 hoac 1, nhan %d (3 = INTERNALERROR,"
                  " 2 = ngat, 4 = loi dung lenh)." % kq.returncode)
            print(ra[-1200:])
            return 1
        if not bao_cao.is_file():
            print("KHONG DO DUOC: pytest khong ghi JUnit XML.")
            return 3

        goc_xml = ElementTree.parse(str(bao_cao)).getroot()
        ca = [
            tc
            for su in (goc_xml.iter("testsuite")
                       if goc_xml.tag != "testsuite" else [goc_xml])
            for tc in su.iter("testcase")
        ]
        if len(ca) != len(node):
            print("DO: thu thap %d node nhung JUnit chi ghi %d — phien dung"
                  " giua chung." % (len(node), len(ca)))
            return 1
        print("thuc thi: %d node — khop" % len(ca))

        if sentinel:
            khop = [tc for tc in ca if tc.get("name") == sentinel]
            if len(khop) != 1:
                print("DO: khong thay dung mot ban ghi cho sentinel %r (thay %d)"
                      % (sentinel, len(khop)))
                return 1
            hong = [c.tag for c in khop[0]
                    if c.tag in ("failure", "error", "skipped")]
            if hong:
                print("DO: sentinel %r khong PASSED (%s). No nam CUOI tep, nen"
                      " viec no hong nghia la phien khong song sot qua cac"
                      " traceback truoc do." % (sentinel, hong))
                return 1
            print("sentinel %r: passed" % sentinel)

        # KHÔNG khoá số ca đỏ: các lỗi cũ được sửa thì con số ấy phải giảm bình
        # thường, không được biến thành hồi quy giả.
        print("DAT")
        return 0
    finally:
        shutil.rmtree(thu_muc_tam, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
