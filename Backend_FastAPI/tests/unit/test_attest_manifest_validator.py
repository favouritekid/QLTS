"""Regression hẹp cho `scripts/kiem-manifest.mjs` — validator manifest attest.

Vì sao có tệp này
-----------------
`scripts/attest-frontend-runtime.sh` là cổng chứng minh container đang phục vụ
Chrome chạy đúng cây làm việc. Ở hình dạng standalone (stack smoke bắt buộc dùng
bản này), toàn bộ bằng chứng nằm ở manifest JSON nướng trong ảnh — nên MỘT lỗ
trong validator là một attestation xanh cho một ảnh có thể khác source, và mọi
kết luận của lượt smoke sau đó thành vô nghĩa.

Bản validator trước viết bằng `sed`, vừa PARSE vừa LỌC ĐỊNH DẠNG. Phần tử sai
định dạng bị loại khỏi danh sách TRƯỚC KHI được kiểm, nên nhánh "sai định dạng"
không bao giờ có gì để bắt. Biến thể tái hiện được trên chính manifest đang chạy:

    tep[0] = "x"  ·  so_tep 1277 → 1276  ·  van_tay tính lại trên 1276 dòng
    ⇒ RAW_ARRAY_LEN=1277, EXTRACTED_LEN=1276, N_BAD_SEEN=0, PASS

`test_bien_the_phan_tu_rac_bi_giau_khoi_sed` khoá đúng biến thể ấy.

Môi trường
----------
Cần `node`. Thiếu node thì test ĐỎ, không skip: một test tự bỏ qua chính là cái
lỗ mà tệp này sinh ra để chặn. CI chạy trên `ubuntu-latest` (có sẵn Node 20+);
chạy tại máy thì chạy trên host, không trong container backend (ảnh ấy không có
node).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest


def _goc_kho() -> Path:
    for goc in Path(__file__).resolve().parents:
        if (goc / "scripts" / "kiem-manifest.mjs").is_file():
            return goc
    pytest.fail("không tìm thấy scripts/kiem-manifest.mjs — sai gốc kho")


_GOC = _goc_kho()
_VALIDATOR = _GOC / "scripts" / "kiem-manifest.mjs"


def _node() -> str:
    duong = shutil.which("node")
    if not duong:
        pytest.fail(
            "thiếu `node` — validator manifest không chạy được. KHÔNG skip: một "
            "test tự bỏ qua ở đây làm cổng attest mất hiệu lực mà vẫn xanh."
        )
    return duong


def _bam(*dong: str) -> str:
    return hashlib.sha256("".join(d + "\n" for d in dong).encode()).hexdigest()


def _manifest_hop_le() -> dict:
    """Manifest nhỏ nhất còn hợp lệ: hai tệp + đúng một mục build-arg."""
    tep = [
        f"{'a' * 64}  src/app/page.tsx",
        f"{'b' * 64}  tailwind.config.ts",
        f"{'c' * 64}  __NEXT_PUBLIC_ARGS__",
    ]
    tep.sort()
    return {"schema": 2, "so_tep": len(tep), "van_tay": _bam(*tep), "tep": tep}


def _chay(tmp_path: Path, du_lieu, *, tho: str | None = None):
    p = tmp_path / "manifest.json"
    p.write_text(tho if tho is not None else json.dumps(du_lieu, indent=2), encoding="utf-8")
    return subprocess.run(
        [_node(), str(_VALIDATOR), str(p), "ca-kiem"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Ca thuận
# ---------------------------------------------------------------------------


def test_manifest_hop_le_thi_xanh_va_xuat_danh_sach(tmp_path):
    d = _manifest_hop_le()
    r = _chay(tmp_path, d)
    assert r.returncode == 0, r.stderr
    # Chỉ được xuất danh sách SAU KHI toàn bộ JSON hợp lệ, và phải xuất ĐỦ.
    assert r.stdout == "".join(t + "\n" for t in d["tep"])


# ---------------------------------------------------------------------------
# Ca nghịch — mỗi ca vi phạm ĐÚNG MỘT bất biến
# ---------------------------------------------------------------------------


def test_bien_the_phan_tu_rac_bi_giau_khoi_sed(tmp_path):
    """Biến thể đã tái hiện được trên manifest thật: phần tử rác + sổ sách khớp.

    `so_tep` và `van_tay` đều được tính lại trên tập ĐÃ LỌC, nên mọi phép kiểm
    số lượng và vân tay đều khớp. Chỉ một validator NHÌN THẤY phần tử rác mới
    bắt được.
    """
    d = _manifest_hop_le()
    d["tep"][0] = "x"
    con_lai = [t for t in d["tep"] if t != "x"]
    d["so_tep"] = len(con_lai)
    d["van_tay"] = _bam(*con_lai)

    r = _chay(tmp_path, d)
    assert r.returncode == 2, f"validator ĐỂ LỌT phần tử rác: rc={r.returncode}"
    assert "sai định dạng" in r.stderr
    assert r.stdout == "", "không được xuất danh sách khi manifest hỏng"


def test_phan_tu_khong_phai_chuoi_thi_do(tmp_path):
    d = _manifest_hop_le()
    d["tep"][0] = 12345
    r = _chay(tmp_path, d)
    assert r.returncode == 2
    assert "sai định dạng" in r.stderr


def test_schema_khac_2_thi_do(tmp_path):
    d = _manifest_hop_le()
    d["schema"] = 1
    r = _chay(tmp_path, d)
    assert r.returncode == 2
    assert "schema" in r.stderr


def test_so_tep_lech_thi_do(tmp_path):
    d = _manifest_hop_le()
    d["so_tep"] = d["so_tep"] + 1
    r = _chay(tmp_path, d)
    assert r.returncode == 2
    assert "tự mâu thuẫn" in r.stderr


def test_duong_dan_trung_thi_do(tmp_path):
    d = _manifest_hop_le()
    d["tep"] = [d["tep"][0], d["tep"][0].replace("a" * 64, "d" * 64)] + d["tep"][1:]
    d["so_tep"] = len(d["tep"])
    d["van_tay"] = _bam(*d["tep"])
    r = _chay(tmp_path, d)
    assert r.returncode == 2
    assert "TRÙNG" in r.stderr


def test_thieu_muc_build_arg_thi_do(tmp_path):
    """Thiếu `__NEXT_PUBLIC_ARGS__` = build arg không được attest.

    Đây là lỗ nguy hiểm nhất còn lại nếu bỏ qua: cùng source mà ảnh nướng
    `NEXT_PUBLIC_API_URL` khác vẫn PASS, tức trình duyệt gọi sang backend của
    stack khác trong khi cổng báo xanh.
    """
    d = _manifest_hop_le()
    d["tep"] = [t for t in d["tep"] if "__NEXT_PUBLIC_ARGS__" not in t]
    d["so_tep"] = len(d["tep"])
    d["van_tay"] = _bam(*d["tep"])
    r = _chay(tmp_path, d)
    assert r.returncode == 2
    assert "__NEXT_PUBLIC_ARGS__" in r.stderr


def test_hai_muc_build_arg_thi_do(tmp_path):
    d = _manifest_hop_le()
    args = [t for t in d["tep"] if "__NEXT_PUBLIC_ARGS__" in t][0]
    d["tep"] = d["tep"] + [args.replace("c" * 64, "e" * 64)]
    d["so_tep"] = len(d["tep"])
    d["van_tay"] = _bam(*d["tep"])
    r = _chay(tmp_path, d)
    assert r.returncode == 2
    # Trùng đường dẫn bắn trước — vẫn là DỪNG, và lý do vẫn đúng sự thật.
    assert "TRÙNG" in r.stderr or "__NEXT_PUBLIC_ARGS__" in r.stderr


def test_van_tay_sai_thi_do(tmp_path):
    d = _manifest_hop_le()
    d["van_tay"] = "0" * 64
    r = _chay(tmp_path, d)
    assert r.returncode == 2
    assert "van_tay" in r.stderr


def test_json_cut_thi_do(tmp_path):
    d = _manifest_hop_le()
    r = _chay(tmp_path, None, tho=json.dumps(d)[:80])
    assert r.returncode == 2
    assert "JSON không phân giải được" in r.stderr


def test_json_rong_thi_do(tmp_path):
    r = _chay(tmp_path, None, tho="")
    assert r.returncode == 2
    assert "rỗng" in r.stderr


def test_goc_json_la_mang_thi_do(tmp_path):
    r = _chay(tmp_path, None, tho="[1,2,3]")
    assert r.returncode == 2
    assert "không phải object" in r.stderr


def test_tep_khong_phai_mang_thi_do(tmp_path):
    d = _manifest_hop_le()
    d["tep"] = "khong-phai-mang"
    r = _chay(tmp_path, d)
    assert r.returncode == 2
    assert "không phải mảng" in r.stderr
