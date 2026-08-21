#!/usr/bin/env python3
"""Chia bộ pytest backend thành N lát, và CHỨNG MINH các lát phủ hết + không trùng.

Vì sao tệp này tồn tại
======================

``Nightly Backend Pytest`` chạy toàn bộ 8.652 test trong MỘT job tuần tự. Đo
được trên run ``32287527969`` (19-08-2026): 18:29:53 → 19:58:22, tức **88,5
phút cho 9%** của bộ test. Ngoại suy: **~5–6 giờ** một lượt. Trần
``timeout-minutes: 90`` cắt job giữa chừng, nên GitHub ghi ``cancelled``.

Đây không phải sự cố mới. **88/88 lượt gần nhất đều KHÔNG thành công**
(87 ``cancelled`` + 1 ``failure``), lượt cũ nhất còn thấy được là 24-05-2026 —
đúng ngày workflow ra đời. Nó **chưa từng chạy xong lần nào**, nên suốt ba
tháng nó không phải lưới an toàn mà chỉ là một ô xanh không ai đọc.

Vì sao không giải bằng cách tăng timeout hay xdist
--------------------------------------------------

* **Tăng timeout** không đổi gì: một lượt 6 giờ vẫn là 6 giờ, và ai đọc kết quả
  vào sáng hôm sau thì đọc kết quả của mã hôm kia.
* **xdist dùng chung một DB** thì các worker giẫm lên nhau: bộ này DROP/CREATE
  schema ``qlts_test`` trong fixture ``setup_test_database``, và nhiều lát đụng
  cùng bảng. Chia theo job — mỗi job một cặp Postgres+Redis RIÊNG do GitHub
  dựng — mới là cô lập thật.

Bất biến mà tệp này canh
========================

Chia lát bằng danh sách viết tay là đúng cái bẫy đã có sẵn trong kho: một tệp
test không có tên trong tier nào thì **không shard nào chạy nó**, mà required
check **vẫn xanh**. Nên ở đây:

1. Danh sách lát được **SINH RA** từ chính ``pytest --collect-only``, không ai
   gõ tay.
2. Sau khi các lát chạy xong, ``verify`` đối chiếu **hợp của các lát** với
   **bản kiểm kê gốc**: thiếu một node id ⇒ ĐỎ; một node id nằm ở hai lát ⇒ ĐỎ.

Điểm 2 là phần không được bỏ. Không có nó, điểm 1 vẫn có thể lặng lẽ đánh rơi
một tệp (lỗi glob, tệp mới thêm sau lúc kiểm kê, một lát chết lúc collect) và
tổng thể vẫn xanh.

Lệnh
====

    plan   --collected <tệp> --shards N --out <tệp json>
    verify --collected <tệp> --shard-dir <thư mục>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Dict, List, Sequence, Tuple

# Hệ số chi phí theo thư mục — đơn vị là "giây trên mỗi test", ước lượng từ đo
# thật: 88,5 phút cho ~800 test trong ``tests/api/`` = 6,6 s/test. Các nhóm còn
# lại suy theo độ nặng của fixture (api/integration dựng cả stack HTTP + DB;
# unit gần như thuần Python).
#
# ⚠️ Đây là số ƯỚC LƯỢNG, không phải số đo cho từng thư mục. Nó chỉ dùng để
# CÂN các lát cho đều; nó **không** ảnh hưởng tới tính đúng đắn — dù cân lệch
# thì mọi test vẫn chạy, chỉ là một lát lâu hơn. Khi đã có một lượt xanh, thay
# bảng này bằng thời gian đo thật từ artifact junit-xml.
_CHI_PHI_MAC_DINH = 1.0
CHI_PHI_THU_MUC: Dict[str, float] = {
    "tests/api": 6.6,
    "tests/integration": 6.6,
    "tests/security": 3.0,
    "tests/services": 2.5,
    "tests/repositories": 2.0,
    "tests/middleware": 1.0,
    "tests/tasks": 1.0,
    "tests/utils": 1.0,
    "tests/unit": 0.6,
}


def _chuan_hoa(duong_dan: str) -> str:
    """Đưa mọi đường dẫn về dạng dấu gạch chéo xuôi.

    Runner là Linux nhưng người phát triển chạy Windows; một ``\\`` lọt vào so
    sánh chuỗi sẽ làm ``verify`` đỏ vì lý do chẳng liên quan gì tới độ phủ.
    """
    return duong_dan.replace("\\", "/").strip()


def doc_node_ids(duong_dan: str) -> List[str]:
    """Đọc danh sách node id từ đầu ra ``pytest --collect-only -q``.

    Chỉ nhận dòng có ``::`` — đầu ra của pytest còn kèm dòng tổng kết
    ("123 tests collected in 4.5s"), dòng cảnh báo, và dòng trắng. Lọc theo
    ``::`` là tiêu chí ổn định nhất mà không phải bám vào định dạng bản in.
    """
    ket_qua: List[str] = []
    with open(duong_dan, "r", encoding="utf-8", errors="replace") as fh:
        for dong in fh:
            dong = _chuan_hoa(dong)
            if "::" in dong and dong.startswith("tests/"):
                ket_qua.append(dong)
    return ket_qua


def _tep_cua(node_id: str) -> str:
    return node_id.split("::", 1)[0]


def _chi_phi_tep(tep: str, so_test: int) -> float:
    for tien_to, he_so in CHI_PHI_THU_MUC.items():
        if tep.startswith(tien_to + "/"):
            return so_test * he_so
    return so_test * _CHI_PHI_MAC_DINH


def chia_lat(node_ids: Sequence[str], so_lat: int) -> List[List[str]]:
    """Chia theo TỆP (không theo node id) bằng LPT greedy.

    Chia theo tệp chứ không theo từng test: nhiều tệp có fixture phạm vi module
    và dữ liệu dùng chung, cắt đôi một tệp là tự chuốc lấy lỗi phụ thuộc thứ tự
    mà chỉ hiện ra ở một lát.

    LPT (longest processing time first): xếp tệp nặng nhất trước, mỗi tệp rơi
    vào lát đang NHẸ NHẤT. Tất định hoàn toàn — sắp xếp có khoá phụ là đường
    dẫn, nên cùng đầu vào luôn cho cùng kết quả, kể cả khi hai tệp bằng điểm.
    """
    if so_lat < 1:
        raise ValueError("so_lat phai >= 1")

    theo_tep: Dict[str, int] = defaultdict(int)
    for nid in node_ids:
        theo_tep[_tep_cua(nid)] += 1

    if not theo_tep:
        raise ValueError("khong thu duoc node id nao — kiem ke rong")

    xep_hang: List[Tuple[float, str]] = sorted(
        ((_chi_phi_tep(tep, n), tep) for tep, n in theo_tep.items()),
        key=lambda x: (-x[0], x[1]),
    )

    lat: List[List[str]] = [[] for _ in range(so_lat)]
    tai: List[float] = [0.0] * so_lat
    for chi_phi, tep in xep_hang:
        # Khoá phụ ``i`` để hai lát cùng tải luôn chọn lát chỉ số nhỏ hơn —
        # nếu không, thứ tự phụ thuộc cách cài đặt ``min`` và kết quả hết tất định.
        i = min(range(so_lat), key=lambda k: (tai[k], k))
        lat[i].append(tep)
        tai[i] += chi_phi

    return [sorted(x) for x in lat]


def lenh_plan(args: argparse.Namespace) -> int:
    node_ids = doc_node_ids(args.collected)
    lat = chia_lat(node_ids, args.shards)

    rong = [i for i, x in enumerate(lat) if not x]
    if rong:
        # Nhiều lát hơn số tệp: một lát rỗng chạy ``pytest`` không đối số ⇒ quét
        # cả kho ⇒ TRÙNG với mọi lát khác. Dừng ngay, đừng để verify bắt sau.
        print(
            "LOI: lat rong o chi so %s — giam --shards xuong <= so tep (%d)"
            % (rong, len({_tep_cua(n) for n in node_ids})),
            file=sys.stderr,
        )
        return 1

    ma_tran = [
        {"index": i + 1, "name": "shard-%02d" % (i + 1), "tests": " ".join(tep_list)}
        for i, tep_list in enumerate(lat)
    ]

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(ma_tran, fh, ensure_ascii=False)

    tong_tep = sum(len(x) for x in lat)
    print("kiem ke: %d node id, %d tep" % (len(node_ids), tong_tep))
    for muc in ma_tran:
        so_tep = len(muc["tests"].split())
        print("  %s: %d tep" % (muc["name"], so_tep))
    return 0


def lenh_verify(args: argparse.Namespace) -> int:
    """Đối chiếu hợp của các lát với bản kiểm kê gốc.

    Trả 0 chỉ khi: hợp == kiểm kê, và không node id nào xuất hiện ở hai lát.
    """
    goc = set(doc_node_ids(args.collected))
    if not goc:
        print("LOI: ban kiem ke goc RONG", file=sys.stderr)
        return 1

    tep_lat = sorted(
        os.path.join(args.shard_dir, t)
        for t in os.listdir(args.shard_dir)
        if t.endswith(".txt")
    )
    if not tep_lat:
        print("LOI: khong thay tep ket qua lat nao trong %s" % args.shard_dir, file=sys.stderr)
        return 1

    thay_o: Dict[str, List[str]] = defaultdict(list)
    for duong in tep_lat:
        ten = os.path.basename(duong)
        for nid in doc_node_ids(duong):
            thay_o[nid].append(ten)

    hop = set(thay_o)
    thieu = sorted(goc - hop)
    thua = sorted(hop - goc)
    trung = sorted(n for n, v in thay_o.items() if len(v) > 1)

    print("kiem ke goc : %d node id" % len(goc))
    print("hop cac lat : %d node id (tu %d lat)" % (len(hop), len(tep_lat)))

    loi = 0
    if thieu:
        loi += 1
        print("\nLOI: %d node id KHONG lat nao chay:" % len(thieu), file=sys.stderr)
        for n in thieu[:25]:
            print("   - %s" % n, file=sys.stderr)
        if len(thieu) > 25:
            print("   ... va %d node id nua" % (len(thieu) - 25), file=sys.stderr)
    if trung:
        loi += 1
        print("\nLOI: %d node id chay o NHIEU lat:" % len(trung), file=sys.stderr)
        for n in trung[:25]:
            print("   - %s  (%s)" % (n, ", ".join(thay_o[n])), file=sys.stderr)
    if thua:
        # Không phải lỗi chí mạng nhưng luôn đáng ngờ: lát thu được thứ không
        # có trong kiểm kê nghĩa là hai lần collect cho kết quả khác nhau.
        loi += 1
        print("\nLOI: %d node id co o lat nhung KHONG co trong kiem ke goc:" % len(thua), file=sys.stderr)
        for n in thua[:25]:
            print("   - %s" % n, file=sys.stderr)

    if loi:
        return 1
    print("\nDAT: cac lat phu HET kiem ke va KHONG trung nhau.")
    return 0


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="lenh", required=True)

    p_plan = sub.add_parser("plan", help="sinh ma tran lat tu ban kiem ke")
    p_plan.add_argument("--collected", required=True)
    p_plan.add_argument("--shards", type=int, required=True)
    p_plan.add_argument("--out", required=True)
    p_plan.set_defaults(func=lenh_plan)

    p_ver = sub.add_parser("verify", help="doi chieu do phu + khong trung")
    p_ver.add_argument("--collected", required=True)
    p_ver.add_argument("--shard-dir", required=True)
    p_ver.set_defaults(func=lenh_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
