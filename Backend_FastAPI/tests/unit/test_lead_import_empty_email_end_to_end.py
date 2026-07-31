"""Chạy TRỌN ``import_leads_from_file_content`` với một dòng email trống.

Test ở ``test_lead_import_empty_cells.py`` kiểm helper và khoá cấu trúc — bắt được
regression ở chỗ đã sửa, nhưng KHÔNG chứng minh dòng thiếu email đi hết luồng và
tạo ra lead. Nếu mai kia có ai thêm một phép kiểm email ở tầng khác trong cùng
hàm này, những test kia vẫn xanh còn người dùng vẫn mất dòng.

Ở đây thay repository + tra cứu trạng thái bằng bản giả, nên chạy được không cần
cơ sở dữ liệu, mà vẫn đi qua đúng đoạn đọc file → làm sạch ô → dựng ``LeadCreate``
→ gom lô.
"""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import lead_service

pytestmark = pytest.mark.unit

CSV = (
    "full_name,email,phone,source,unit_id\n"
    "Có Email,co@example.com,0900000001,website,14\n"
    "Không Email,,0900000002,website,14\n"
)


class _RepoGia:
    """Repository giả: không đụng cơ sở dữ liệu, ghi lại thứ được chèn."""

    def __init__(self, *_a, **_kw):
        self.da_chen = []

    async def check_batch_email_conflict(self, *_a, **_kw):
        return set()

    async def check_batch_phone_conflict(self, *_a, **_kw):
        return set()

    async def bulk_insert_leads(self, batch):
        self.da_chen.extend(batch)
        return list(range(1, len(batch) + 1))

    async def register_phone_identities(self, *_a, **_kw):
        return None


@pytest.fixture
def repo_gia(monkeypatch):
    holder = {}

    def _factory(*a, **kw):
        repo = holder.get("repo") or _RepoGia()
        holder["repo"] = repo
        return repo

    monkeypatch.setattr(lead_service, "LeadRepository", _factory)
    return holder


async def _chay(db_gia):
    return await lead_service.import_leads_from_file_content(
        file_content=CSV.encode("utf-8"),
        filename="thu.csv",
        db=db_gia,
        default_unit_id=14,
        auto_assign_officer_id=None,
    )


@pytest.fixture
def db_gia():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.get = AsyncMock(return_value=None)

    # ``async with db.begin_nested()`` — AsyncMock trả coroutine chứ không phải
    # context manager, nên phải dựng tay.
    @asynccontextmanager
    async def _nested():
        yield None

    db.begin_nested = MagicMock(side_effect=lambda *a, **kw: _nested())
    return db


async def test_dong_thieu_email_van_tao_duoc_lead(repo_gia, db_gia):
    """Ca thật: 7/211 thí sinh không có email vẫn phải vào được hệ thống.

    ``Lead.email`` nullable, ``LeadCreate.email`` Optional, và 2425/2535 lead trên
    production không có email — nên dòng thiếu email là chuyện BÌNH THƯỜNG, không
    phải lỗi dữ liệu.
    """
    with patch.object(
        lead_service.StatusHelper, "get_initial_status",
        AsyncMock(return_value=SimpleNamespace(
            id="sts00", legacy_status="new", stage_id="stg00", name="Chưa tiếp cận"
        )),
    ), patch.object(
        lead_service, "calculate_lead_score", AsyncMock(return_value=20)
    ):
        res = await _chay(db_gia)

    ket_qua = res[0] if isinstance(res, tuple) else res
    assert ket_qua.successful_imports == 2, (
        f"dòng thiếu email bị loại: {ket_qua.errors}"
    )
    assert ket_qua.failed_imports == 0

    da_chen = repo_gia["repo"].da_chen
    assert len(da_chen) == 2
    # ``bulk_insert_leads`` nhận list DICT (pg_insert().values(...)), không phải model
    emails = [x.get("email") if isinstance(x, dict) else getattr(x, "email", None)
              for x in da_chen]
    assert emails[0] == "co@example.com"
    assert emails[1] is None, (
        f"email trống phải là None, đang là {emails[1]!r} — chuỗi 'nan' quay lại"
    )


async def test_khong_dong_nao_mang_chuoi_nan(repo_gia, db_gia):
    """Không trường chuỗi nào được mang giá trị 'nan' vào cơ sở dữ liệu.

    🔴 Bản đầu của ca này PASS cả trên code chưa sửa, vì hai lẽ: CSV lúc đó không
    có cột ``education_level``/``location`` để mà kiểm, và trên code cũ dòng thiếu
    email bị loại từ vòng validate nên danh sách chèn chỉ còn dòng đầy đủ — không
    còn ô trống nào để lộ chuỗi "nan". Nay CSV có đủ hai cột đó và ca này khẳng
    định **cả hai dòng** đều được chèn.
    """
    with patch.object(
        lead_service.StatusHelper, "get_initial_status",
        AsyncMock(return_value=SimpleNamespace(
            id="sts00", legacy_status="new", stage_id="stg00", name="Chưa tiếp cận"
        )),
    ), patch.object(
        lead_service, "calculate_lead_score", AsyncMock(return_value=20)
    ):
        await _chay(db_gia)

    da_chen = repo_gia["repo"].da_chen
    assert len(da_chen) == 2, (
        f"phải chèn CẢ HAI dòng mới chạm được ô trống; đang chèn {len(da_chen)}"
    )
    for lead in da_chen:
        for truong in ("full_name", "email", "source", "education_level", "location"):
            gia_tri = lead.get(truong) if isinstance(lead, dict) else getattr(lead, truong, None)
            assert gia_tri != "nan", f"{truong} mang chuỗi 'nan'"

    # Dòng 2 để trống ba trường — chúng phải là None, không phải "nan" cũng không
    # phải chuỗi rỗng lửng lơ.
    dong_trong = da_chen[1]
    for truong in ("email", "education_level", "location"):
        gia_tri = (dong_trong.get(truong) if isinstance(dong_trong, dict)
                   else getattr(dong_trong, truong, None))
        assert gia_tri is None, f"{truong} phải là None, đang là {gia_tri!r}"


CSV_THIEU_BAT_BUOC = (
    "full_name,email,phone,source,unit_id\n"
    "Có Tên,a@example.com,0900000001,website,14\n"
    ",b@example.com,0900000002,website,14\n"        # full_name TRỐNG
    "Thiếu Nguồn,c@example.com,0900000003,,14\n"    # source TRỐNG
)


async def test_o_bat_buoc_trong_thi_bao_loi_chu_khong_tao_lead_ten_nan(repo_gia, db_gia):
    """ĐỔI HÀNH VI có chủ đích: ô bắt buộc trống nay báo lỗi dòng.

    Trước bản vá, ``full_name``/``source`` trống được ép thành chuỗi "nan" và
    **lọt qua validator** — hệ thống nhận về một lead tên "nan", nguồn "nan".
    Nhập được, nhưng nhập rác: cái tên đó rồi sẽ hiện trên màn hình officer và
    trong báo cáo nguồn tuyển sinh.

    Nay chúng thành chuỗi rỗng nên validator bắt được và người import biết dòng
    nào hỏng để sửa. Đây là ĐÁNH ĐỔI: hai dòng kiểu này chuyển từ "nhập được"
    sang "bị loại" — cố ý, và chỉ ảnh hưởng dòng đó chứ không hỏng cả file.
    """
    with patch.object(
        lead_service.StatusHelper, "get_initial_status",
        AsyncMock(return_value=SimpleNamespace(
            id="sts00", legacy_status="new", stage_id="stg00", name="Chưa tiếp cận"
        )),
    ), patch.object(
        lead_service, "calculate_lead_score", AsyncMock(return_value=20)
    ):
        res = await lead_service.import_leads_from_file_content(
            file_content=CSV_THIEU_BAT_BUOC.encode("utf-8"),
            filename="thieu.csv", db=db_gia,
            default_unit_id=14, auto_assign_officer_id=None,
        )

    kq = res[0] if isinstance(res, tuple) else res
    assert kq.successful_imports == 1, f"chỉ dòng đầy đủ được nhận: {kq.errors}"
    assert kq.failed_imports == 2

    loi = " ".join(e.error_message for e in kq.errors)
    assert "'nan'" not in loi, "ô trống vẫn bị ép thành chuỗi 'nan'"

    # Và tuyệt đối không có lead nào mang tên/nguồn "nan" lọt vào lô chèn.
    for lead in repo_gia["repo"].da_chen:
        for truong in ("full_name", "source"):
            gt = lead.get(truong) if isinstance(lead, dict) else getattr(lead, truong, None)
            assert gt != "nan", f"{truong} = 'nan' — rác lọt vào cơ sở dữ liệu"
