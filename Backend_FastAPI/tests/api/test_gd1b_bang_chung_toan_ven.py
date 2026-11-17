"""GĐ1b — toàn vẹn tệp bằng chứng lúc tải (Claude 18-11, sau hợp đồng bổ sung bản 5 B6).

* Không có khe giữa lúc băm và lúc trả: route đọc tệp MỘT lần, băm đúng các byte ấy, trả đúng các byte ấy. Ca kiểm thay nội
  dung tệp trên ổ NGAY SAU bước băm ⇒ thân phản hồi vẫn phải là đúng các byte đã băm.
* Trần kích thước (= trần tải lên của lõi, khoá bằng nhau): tệp trên ổ lớn hơn trần ⇒ 409 ``EVIDENCE_FILE_ALTERED`` kể cả
  khi băm khớp, KHÔNG đọc tệp vào bộ nhớ, không ghi nhật ký tải.

Tách khỏi ``test_gd1b_bang_chung_tai.py`` để mỗi lượt chạy (≤ 600 s) giữ dư địa. Mỗi ca kiểm MỘT bất biến; biến thể phá ở
``kiem-thu-phien-a/ma/gd1b_bc_e.json``. Dữ liệu giả.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from app.services import document_evidence_service as svc
from tests.api.test_admission_doc_mutations_response_parity import parity_config  # noqa: F401
from tests.api.test_gd1b_bang_chung_tai import (  # noqa: F401
    PDF,
    _bang_chung,
    _dat_co_bang_chung,
    _dem_tai,
    _dn,
    _ho_so_co_bang_chung,
    _sha,
    _url,
    gan_route_bang_chung,
)

pytestmark = pytest.mark.asyncio
GOC = Path(__file__).resolve().parents[2]


def _thay_noi_dung(duong_dan: str, noi_dung: bytes) -> None:
    """Ghi nội dung mới cho tệp trên ổ (tệp tạm rồi thay) và đọc lại để chắc đã ghi."""
    tam = duong_dan + ".tam"
    with open(tam, "wb") as f:
        f.write(noi_dung)
    os.replace(tam, duong_dan)
    assert open(duong_dan, "rb").read() == noi_dung, "HẠ TẦNG: chưa ghi được tệp"


# ---------------------------------------------------------------- một nguồn: trần kích thước = trần tải lên của lõi
async def test_tran_kich_thuoc_bang_chung_bang_tran_tai_len_cua_loi():
    """``MAX_FILE_SIZE`` là biến CỤC BỘ trong ``admission_service.upload_document`` (không import được) ⇒ đọc bằng AST và so
    với ``EVIDENCE_MAX_BYTES`` (CLAUDE.md §7: hai bản phải có test khoá bằng nhau)."""

    def _gia_tri(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            return _gia_tri(node.left) * _gia_tri(node.right)
        raise AssertionError(f"biểu thức trần không đọc được: {ast.unparse(node)}")

    cay = ast.parse((GOC / "app" / "services" / "admission_service.py").read_text(encoding="utf-8"))
    ham = [n for n in ast.walk(cay) if isinstance(n, ast.AsyncFunctionDef) and n.name == "upload_document"]
    assert len(ham) == 1, "không tìm thấy đúng một upload_document"
    gan = [
        n for n in ast.walk(ham[0])
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "MAX_FILE_SIZE" for t in n.targets)
    ]
    assert len(gan) == 1, "upload_document phải gán MAX_FILE_SIZE đúng một lần"
    assert _gia_tri(gan[0].value) == svc.EVIDENCE_MAX_BYTES


# ---------------------------------------------------------------- không có khe giữa lúc băm và lúc trả
async def test_tep_bi_thay_ngay_sau_khi_bam_than_phan_hoi_la_dung_cac_byte_da_bam(
    client, gan_route_bang_chung, monkeypatch, admin_token_headers, admin_user_in_db, manager_user_in_db,
    officer_user_in_db, parity_config,
):
    """Tệp > 1 MiB (băm khác thuật toán lúc duyệt ở tệp lớn cũng lộ ra ở đây). Bước băm bị chèn: băm xong thì GHI ĐÈ tệp trên
    ổ bằng nội dung khác ⇒ phản hồi vẫn phải là đúng các byte đã băm (khớp sha256 lúc duyệt)."""
    a = PDF + os.urandom((1 << 20) + 64)
    pid, d, ev, _ = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_khe_bam", a
    )
    khac = PDF + os.urandom(len(a) - len(PDF))
    bam_that = svc._sha256_bytes
    da_thay = []

    def _bam_roi_thay(data: bytes) -> str:
        kq = bam_that(data)
        _thay_noi_dung(ev.file_path, khac)
        da_thay.append(True)
        return kq

    monkeypatch.setattr(svc, "_sha256_bytes", _bam_roi_thay)
    r = await client.get(_url(pid, d.id, ev.id), headers=await _dn(client, manager_user_in_db))
    assert da_thay == [True] and open(ev.file_path, "rb").read() == khac, "tiền đề: tệp đã bị thay sau bước băm"
    assert r.status_code == 200, r.status_code
    assert r.content == a and _sha(r.content) == ev.sha256, "thân phản hồi phải là ĐÚNG các byte đã băm"


# ---------------------------------------------------------------- trần kích thước
async def _phinh_tep_qua_tran(ev) -> bytes:
    """Tệp trên ổ phình quá trần (giữ nguyên phần đầu) và sha256 đã ghi được đặt KHỚP nội dung mới ⇒ chỉ còn trần chặn."""
    lon = open(ev.file_path, "rb").read()
    lon = lon + b"\0" * (svc.EVIDENCE_MAX_BYTES + 1 - len(lon))
    _thay_noi_dung(ev.file_path, lon)
    assert os.path.getsize(ev.file_path) == svc.EVIDENCE_MAX_BYTES + 1
    await _dat_co_bang_chung(ev.id, f"sha256 = '{_sha(lon)}'")
    return lon


async def test_tep_tren_o_vuot_tran_thi_409_du_bam_khop_nhat_ky_khong_doi(
    client, gan_route_bang_chung, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db,
    parity_config,
):
    pid, d, ev, _ = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_tran"
    )
    await _phinh_tep_qua_tran(ev)
    r = await client.get(_url(pid, d.id, ev.id), headers=await _dn(client, manager_user_in_db))
    assert r.status_code == 409, r.status_code
    assert r.json()["error_code"] == "EVIDENCE_FILE_ALTERED"
    assert await _dem_tai(d.id) == (0, 0), "nhật ký tải không đổi"


async def test_tep_tren_o_vuot_tran_thi_khong_doc_tep_vao_bo_nho(
    client, gan_route_bang_chung, monkeypatch, admin_token_headers, admin_user_in_db, manager_user_in_db,
    officer_user_in_db, parity_config,
):
    """Phép đo kích thước đứng TRƯỚC lần đọc: vượt trần thì bước đọc không được gọi tới."""
    pid, d, ev, _ = await _ho_so_co_bang_chung(
        client, admin_user_in_db, officer_user_in_db, parity_config, admin_token_headers, "bc_tran_khong_doc"
    )
    await _phinh_tep_qua_tran(ev)
    doc_that = svc._read_bounded
    lan_doc = []

    def _do_doc(path, limit):
        lan_doc.append(path)
        return doc_that(path, limit)

    monkeypatch.setattr(svc, "_read_bounded", _do_doc)
    r = await client.get(_url(pid, d.id, ev.id), headers=await _dn(client, manager_user_in_db))
    assert r.status_code == 409, r.status_code
    assert lan_doc == [], "tệp vượt trần không được đọc"
