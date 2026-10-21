"""Route upload tài liệu hồ sơ với ẢNH thật — HTTP → router → service → helper Pillow → đĩa.

Test sẵn có chỉ gửi PDF qua HTTP; ảnh JPEG/PNG chỉ được kiểm ở mức helper, nên nối dây giữa helper Pillow và
``shutil.copyfileobj`` (chép từ vị trí con trỏ HIỆN TẠI) chưa từng được đo qua route thật. Tệp này gửi ảnh qua
``POST /api/admissions/{id}/documents/{code}/upload`` và đo hành vi ra ngoài:

- ảnh hợp lệ: 200/201, đúng MỘT tệp mới = tệp CSDL trỏ tới, byte trên đĩa = byte gửi lên, tệp có sẵn không bị
  ghi đè hay xoá;
- ảnh hỏng / sai MIME / quá dung lượng / quá chiều: 400 đúng thông điệp và thư mục KHÔNG đổi gì.

``uploads/admissions/<id>`` sống suốt phiên pytest trong khi id hồ sơ được dùng lại sau mỗi lần dựng lại CSDL,
nên thư mục có thể chứa sẵn tệp của test khác. Vì thế so ẢNH CHỤP {đường dẫn: sha256} ngay trước và sau request,
không giả định thư mục rỗng. Mỗi ca CẮM SẴN một tệp mồi (nội dung ngẫu nhiên) trước request, để phép so luôn có
một tệp có sẵn mà việc ghi đè / xoá sẽ làm lộ ra — không phụ thuộc thư mục tình cờ còn tệp của test khác.
Thông điệp của phép so mang nhãn ``ANH_CHUP:`` để kiểm ngược đối chiếu được đúng chỗ bắt.
"""
from __future__ import annotations

import hashlib
import io
import os
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from tests.api.test_admission_doc_mutations_response_parity import (  # noqa: F401 — parity_config là fixture
    ADMISSIONS,
    _create_profile,
    _login,
    parity_config,
)


def _anh(fmt: str, size=(64, 48), color="green") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, fmt)
    return buf.getvalue()


def _nua_dau(b: bytes) -> bytes:
    return b[: len(b) // 2]


def _chup(pid: int) -> dict[Path, str]:
    """{đường dẫn: sha256 nội dung} của mọi tệp (kể cả tệp ẩn .staging.*) trong thư mục upload của hồ sơ."""
    d = Path("uploads") / "admissions" / str(pid)
    if not d.is_dir():
        return {}
    return {f: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(d.iterdir()) if f.is_file()}


async def _gui(client, cfg, admin_h, officer, suffix, ten, data, ct):
    """Trả (pid, response, ảnh chụp trước, tệp mồi). Người gọi PHẢI dọn tệp mồi (``finally``)."""
    prof = await _create_profile(client, admin_h, officer, cfg, suffix)
    oh = await _login(client, officer["username"], officer["password"])
    d = Path("uploads") / "admissions" / str(prof["id"])
    d.mkdir(parents=True, exist_ok=True)
    moi = d / ("moi_%s.bin" % uuid.uuid4().hex)
    moi.write_bytes(os.urandom(64))
    truoc = _chup(prof["id"])
    r = await client.post(
        f"{ADMISSIONS}/{prof['id']}/documents/{cfg['upload_doc_code']}/upload",
        headers=oh, files={"file": (ten, data, ct)}, data={"actual_submission_format": "photo"},
    )
    return prof["id"], r, truoc, moi


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt,ct,duoi", [("PNG", "image/png", ".png"), ("JPEG", "image/jpeg", ".jpg")])
async def test_http_anh_hop_le_ghi_dung_byte(client: AsyncClient, admin_token_headers, officer_user_in_db,
                                              parity_config, fmt, ct, duoi):
    data = _anh(fmt, size=(120, 90))
    pid, r, truoc, moi_cam = await _gui(client, parity_config, admin_token_headers, officer_user_in_db, "ok" + fmt,
                                        "a" + duoi, data, ct)
    try:
        assert r.status_code in (200, 201), r.text
        sau = _chup(pid)
        giu = {p: h for p, h in sau.items() if p in truoc}
        assert giu == truoc, "ANH_CHUP: tệp có sẵn bị ghi đè hoặc xoá: %s" % sorted(
            str(p) for p in truoc if giu.get(p) != truoc[p])
        moi = set(sau) - set(truoc)
        async with AsyncSessionLocal() as s:
            paths = (await s.execute(select(models.ProfileDocument.file_path).where(
                models.ProfileDocument.profile_id == pid, models.ProfileDocument.file_path.isnot(None)))).scalars().all()
        assert len(paths) == 1 and paths[0].endswith(duoi), paths
        p = Path(paths[0])
        assert moi == {p}, "đúng MỘT tệp mới, và là tệp CSDL trỏ tới (không sót .staging): %s vs %s" % (
            sorted(map(str, moi)), p)
        ghi = p.read_bytes()
        assert ghi == data, "BYTE_GHI_RA: trên đĩa %d byte, gửi lên %d byte" % (len(ghi), len(data))
        p.unlink()
    finally:
        moi_cam.unlink(missing_ok=True)


_CA_XAU = [
    ("png_cat_cut", _nua_dau(_anh("PNG", size=(64, 64))), "image/png", "Ảnh tải lên hỏng"),
    ("jpeg_rac", b"\xff\xd8\xff\xe0" + b"\x00" * 64, "image/jpeg", "Ảnh tải lên hỏng"),
    ("png_khai_jpeg", _anh("PNG"), "image/jpeg", "Content-Type"),
    ("text_plain", _anh("PNG"), "text/plain", "Invalid file type"),
    ("qua_10mb", b"\x89PNG\r\n\x1a\n" + b"\x00" * (10 * 1024 * 1024 - 7), "image/png", "File too large"),
    ("qua_chieu_10001", _anh("PNG", size=(10001, 1)), "image/png", "quá lớn"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("ten,data,ct,khop", _CA_XAU, ids=[c[0] for c in _CA_XAU])
async def test_http_anh_xau_tra_400_thu_muc_khong_doi(client: AsyncClient, admin_token_headers, officer_user_in_db,
                                                       parity_config, ten, data, ct, khop):
    pid, r, truoc, moi_cam = await _gui(client, parity_config, admin_token_headers, officer_user_in_db, "x" + ten,
                                        ten + ".png", data, ct)
    try:
        assert r.status_code == 400, (ten, r.status_code, r.text[:300])
        assert khop in r.text, (ten, r.text[:300])
        sau = _chup(pid)
        assert sau == truoc, "ANH_CHUP: %s bị từ chối mà thư mục vẫn đổi — thêm %s · đổi/xoá %s" % (
            ten, sorted(str(p) for p in set(sau) - set(truoc)), sorted(str(p) for p in truoc if sau.get(p) != truoc[p]))
    finally:
        moi_cam.unlink(missing_ok=True)
