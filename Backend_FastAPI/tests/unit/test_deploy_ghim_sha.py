"""Deploy workflow phải deploy ĐÚNG commit sinh ra nó, không phải tip mới nhất.

Job `deploy` dừng ở `environment: production` chờ người duyệt. Giữa lúc run được
sinh và lúc có người bấm approve, `main` có thể đã nhận thêm commit. Bản trước
chạy `git pull --ff-only origin main` rồi chỉ `echo` ra SHA — nên một run mang
metadata của commit A vẫn lặng lẽ deploy commit B, và log không hề mâu thuẫn với
chính nó.

Phép kiểm ở đây không dừng ở việc grep vài chữ: nó **trích đúng khối `if` đã
ship** trong `deploy.yml` rồi thi hành bằng `sh`. Một khối được chép tay vào test
chỉ chứng minh giả định của người viết test, không chứng minh thứ chạy trên VPS.
"""

from __future__ import annotations

import shutil
import subprocess as _sp
from pathlib import Path

import pytest
import re


def _goc_repo() -> Path:
    for goc in Path(__file__).resolve().parents:
        if (goc / ".github" / "workflows").is_dir():
            return goc
    pytest.fail("không tìm thấy gốc repo (thiếu .github/workflows)")


_DEPLOY = _goc_repo() / ".github" / "workflows" / "deploy.yml"
_NOI_DUNG = _DEPLOY.read_text(encoding="utf-8")
_CO_SH = shutil.which("sh") is not None

_SHA_A = "a" * 40
_SHA_B = "b" * 40


def test_workflow_truyen_github_sha_sang_vps():
    """Thiếu `envs:` thì biến không sang tới VPS và cổng thành no-op câm lặng."""
    assert "SHA_MONG_DOI: ${{ github.sha }}" in _NOI_DUNG, "chưa khai github.sha ở env:"
    assert re.search(r"^\s*envs:\s*SHA_MONG_DOI\s*$", _NOI_DUNG, re.M), (
        "thiếu `envs: SHA_MONG_DOI` — appleboy/ssh-action chỉ chuyển biến được "
        "liệt kê ở đây; không có nó thì `$SHA_MONG_DOI` rỗng trên VPS"
    )


def _dong_lenh() -> list[str]:
    """Chỉ các dòng LỆNH, bỏ hết chú thích.

    Phép kiểm đầu tiên viết ra ở đây đã đỏ oan vì khớp trúng chữ
    `git pull --ff-only origin main` nằm trong một dòng `#` giải thích tại sao
    nhánh ấy bị bỏ. Một biểu thức khớp cả chú thích thì vừa báo động giả, vừa có
    thể im lặng khi lệnh thật được viết khác đi.
    """
    return [
        d for d in _NOI_DUNG.splitlines()
        if d.strip() and not d.lstrip().startswith("#")
    ]


def test_khong_con_pull_tron_theo_nhanh():
    """`git pull --ff-only origin main` là chính cái nhánh fail-open đã bỏ."""
    con_sot = [d for d in _dong_lenh() if "git pull --ff-only origin main" in d]
    assert not con_sot, (
        "vẫn còn `pull` trống theo nhánh — nó kéo tip mới nhất bất kể run này "
        f"được sinh cho commit nào: {con_sot}"
    )
    assert any('git merge --ff-only "$SHA_MONG_DOI"' in d for d in _dong_lenh()), (
        "phải ghim tường minh tới SHA của run"
    )


def _trich_khoi_cong() -> str:
    """Lấy nguyên văn khối `if` so SHA trong script đã ship."""
    m = re.search(
        r'^(\s*)if \[ "\$SHA_TIP" != "\$SHA_MONG_DOI" \]; then\n(.*?)^\1fi$',
        _NOI_DUNG,
        re.S | re.M,
    )
    assert m, "không tìm thấy khối `if` so SHA trong deploy.yml"
    khoi = m.group(0)
    # Bỏ thụt lề của YAML block scalar để `sh` đọc được.
    thut = len(m.group(1))
    return "\n".join(d[thut:] if d[:thut].strip() == "" else d for d in khoi.splitlines())


def _chay(khoi: str, tip: str, mong_doi: str):
    kich_ban = f'SHA_TIP={tip}\nSHA_MONG_DOI={mong_doi}\n{khoi}\nexit 0\n'
    return _sp.run(["sh", "-c", kich_ban], capture_output=True, text=True, timeout=60)


@pytest.mark.skipif(not _CO_SH, reason="cần `sh` để thi hành khối cổng đã ship")
def test_cong_sha_chan_that_khi_tip_lech():
    """Lệch ⇒ mã thoát khác 0, và nêu đích danh cả hai SHA."""
    ket = _chay(_trich_khoi_cong(), _SHA_B, _SHA_A)
    ra = (ket.stdout or "") + (ket.stderr or "")
    assert ket.returncode != 0, f"cổng KHÔNG chặn khi tip lệch (rc={ket.returncode}): {ra[:300]}"
    assert _SHA_A in ra and _SHA_B in ra, (
        f"thông báo phải nêu cả SHA thật lẫn SHA mong đợi, nhận: {ra[:300]}"
    )


@pytest.mark.skipif(not _CO_SH, reason="cần `sh` để thi hành khối cổng đã ship")
def test_cong_sha_cho_di_tiep_khi_trung_khop():
    """Kiểm chiều ngược: trùng khớp thì KHÔNG được chặn.

    Thiếu ca này thì một khối `exit 1` vô điều kiện vẫn làm ca trên xanh.
    """
    ket = _chay(_trich_khoi_cong(), _SHA_A, _SHA_A)
    assert ket.returncode == 0, (
        f"cổng chặn nhầm khi SHA trùng khớp (rc={ket.returncode}): "
        f"{((ket.stdout or '') + (ket.stderr or ''))[:300]}"
    )
