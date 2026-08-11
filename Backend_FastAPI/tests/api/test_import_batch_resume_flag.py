"""Cờ ``can_resume_commit`` — quyền mở đường "ghi tiếp các dòng nghi trùng".

Vì sao cờ này phải do MÁY CHỦ cấp, trong khi ``status`` và
``review_required_count`` đã nằm sẵn trong payload: hai trường đó cho giao diện
suy được "lô còn dòng chờ soát", nhưng **không** cho biết người đang xem có qua
được gate của route commit hay không. Suy nửa vời ở client nghĩa là vẽ một nút
mà máy chủ sẽ từ chối — và người dùng học được rằng nút trên màn này không đáng
tin.

Ba vế của cờ, ca dưới đây tách riêng từng vế để hỏng vế nào thì biết vế đó:

* lô còn ``preview`` (đã ``committed``/``void`` thì không còn gì để ghi tiếp);
* còn ít nhất một dòng ``duplicate_review_required``;
* người xem thuộc nhóm qua được ``require_finance_staff``.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal
from app.models.finance import (
    PaymentImportBatch,
    PaymentImportBatchStatusEnum,
    PaymentImportCommitStatusEnum,
    PaymentImportRow,
)

pytestmark = pytest.mark.asyncio

_TIEN = Decimal("2000000")


async def _lo(status: str, *, review_required: int, creator_id: int) -> int:
    """Một lô ở trạng thái cho trước, kèm đúng số dòng đang chờ soát."""
    async with AsyncSessionLocal() as db:
        b = PaymentImportBatch(
            academic_year=2026,
            semester_no=1,
            file_name=f"resume-{status}-{review_required}.xlsx",
            file_sha256=f"{abs(hash((status, review_required))) % 10**60:064d}",
            status=status,
            row_count=1,
            review_required_count=review_required,
            total_amount=_TIEN,
            created_by_id=creator_id,
        )
        db.add(b)
        await db.flush()
        db.add(
            PaymentImportRow(
                batch_id=b.id,
                row_no=1,
                raw={},
                validation_status="warned",
                commit_status=(
                    PaymentImportCommitStatusEnum.duplicate_review_required.value
                    if review_required
                    else PaymentImportCommitStatusEnum.pending.value
                ),
                amount=_TIEN,
            )
        )
        await db.commit()
        return b.id


@pytest_asyncio.fixture
async def accountant_headers(client: AsyncClient, setup_test_database) -> dict:
    """Persona THẬT chạy FIN-09.

    Ca dương bằng `admin` không thay thế được ca này: admin đi qua mọi gate nên
    nó chứng minh "cờ bật cho người có quyền tối đa", không chứng minh kế toán —
    người thực sự ngồi làm việc này — nhìn thấy nút.
    """
    # `create_user_with_role` nhận các phụ thuộc qua tham số (models,
    # get_password_hash, CasbinRule, app) — bỏ trống thì nó rơi vào `None` và
    # nổ ở `models.User`. Truyền đủ, đúng như conftest vẫn làm.
    from tests.fixtures.users import create_user_with_role, get_auth_headers
    from tests.fixtures.constants import AuthURLs
    from app import models as app_models
    from app.security import get_password_hash as _hash
    from casbin_async_sqlalchemy_adapter.adapter import CasbinRule as _CasbinRule
    # `fastapi_app`, KHÔNG phải `app`: `app` là wrapper Socket.IO và không có
    # `.state` — cùng lý do conftest import như vậy.
    from app.main import fastapi_app as _app

    info = await create_user_with_role(
        session_factory=AsyncSessionLocal,
        user_data={
            "username": "testaccountant_resume",
            "email": "accountant_resume@example.com",
            "password": "AccountantPass!123",
            "role": "accountant",
            "status": "active",
        },
        casbin_role="role:accountant",
        models=app_models,
        get_password_hash=_hash,
        CasbinRule=_CasbinRule,
        app=_app,
    )
    return await get_auth_headers(client, info, AuthURLs.LOGIN)


def _tim(items: list, batch_id: int) -> dict:
    for it in items:
        if it["id"] == batch_id:
            return it
    raise AssertionError(f"không thấy lô {batch_id} trong danh sách trả về")


class TestCoResumeCommit:
    # Dùng `admin` cho các ca dương: `list_batches` lọc theo unit-scope của
    # người xem, mà lô dựng trong ca test không gắn unit của manager — dùng
    # manager thì lô rơi ra ngoài danh sách và ca đỏ vì lý do chẳng liên quan
    # tới thứ nó định chứng minh. Vế quyền được canh riêng bằng ca officer.
    async def test_lo_preview_con_dong_cho_soat_thi_MO(
        self, client: AsyncClient, admin_token_headers, admin_user_in_db
    ):
        """Đủ ba vế ⇒ cờ bật, và `review_required_count` cũng phải đi ra cùng."""
        bid = await _lo("preview", review_required=1, creator_id=admin_user_in_db["id"])
        r = await client.get(
            "/api/payments/import/batches", headers=admin_token_headers
        )
        assert r.status_code == 200, r.text
        lo = _tim(r.json()["items"], bid)
        assert lo["can_resume_commit"] is True, (
            "lô preview còn dòng chờ soát phải mở được đường ghi tiếp — thiếu cờ "
            "này thì lô mắc kẹt sau khi người dùng rời màn hình"
        )
        assert lo["review_required_count"] == 1, (
            "số dòng chờ soát phải đi ra cùng cờ: giao diện cần nó để nói RÕ còn "
            "bao nhiêu dòng, thay vì một nút không kèm con số"
        )

    async def test_lo_preview_KHONG_con_dong_cho_soat_thi_DONG(
        self, client: AsyncClient, admin_token_headers, admin_user_in_db
    ):
        """Không còn gì để soát ⇒ không mời người dùng bấm."""
        bid = await _lo("preview", review_required=0, creator_id=admin_user_in_db["id"])
        r = await client.get(
            "/api/payments/import/batches", headers=admin_token_headers
        )
        lo = _tim(r.json()["items"], bid)
        assert lo["can_resume_commit"] is False

    async def test_lo_da_COMMITTED_thi_DONG(
        self, client: AsyncClient, admin_token_headers, admin_user_in_db
    ):
        """Lô đã đóng: `review_required_count` sót lại cũng không mở cửa.

        Ca này canh đúng lối tắt dễ viết nhất — chỉ kiểm counter mà quên kiểm
        trạng thái lô.
        """
        bid = await _lo(
            PaymentImportBatchStatusEnum.committed.value,
            review_required=1,
            creator_id=admin_user_in_db["id"],
        )
        r = await client.get(
            "/api/payments/import/batches", headers=admin_token_headers
        )
        lo = _tim(r.json()["items"], bid)
        assert lo["can_resume_commit"] is False, (
            "lô đã committed không còn đường ghi tiếp — mở nút ở đây là mời gọi "
            "một request mà route commit sẽ trả 409"
        )

    async def test_officer_KHONG_qua_gate_thi_DONG(
        self, client: AsyncClient, officer_token_headers, admin_user_in_db
    ):
        """Vế quyền — đây là vế giao diện KHÔNG tự suy được.

        Officer không qua `require_finance_staff`, nên dù lô đủ hai vế còn lại
        thì cờ vẫn phải tắt. Nếu ca này xanh mà cờ vẫn bật, giao diện sẽ vẽ một
        nút dẫn thẳng tới 403.
        """
        bid = await _lo("preview", review_required=1, creator_id=admin_user_in_db["id"])
        r = await client.get(
            "/api/payments/import/batches", headers=officer_token_headers
        )
        # Officer có thể bị chặn ngay ở route (403) — cũng là fail-closed hợp lệ.
        if r.status_code == 200:
            lo = _tim(r.json()["items"], bid)
            assert lo["can_resume_commit"] is False, (
                "officer không qua gate commit mà cờ vẫn bật"
            )
        else:
            assert r.status_code in (401, 403), r.status_code

    async def test_ACCOUNTANT_thay_co_VA_goi_duoc_commit(
        self, client: AsyncClient, accountant_headers, admin_user_in_db
    ):
        """Persona thật: kế toán phải vừa THẤY nút, vừa BẤM được.

        Hai vế phải đi cùng nhau. Chỉ kiểm cờ thì vẫn có thể vẽ ra một nút mà
        route commit từ chối; chỉ kiểm endpoint thì nút có thể không bao giờ
        hiện. Ca này đóng cả hai đầu bằng đúng một persona.
        """
        bid = await _lo("preview", review_required=1, creator_id=admin_user_in_db["id"])

        ds = await client.get(
            "/api/payments/import/batches", headers=accountant_headers
        )
        assert ds.status_code == 200, ds.text
        assert _tim(ds.json()["items"], bid)["can_resume_commit"] is True, (
            "kế toán — người thật sự chạy luồng này — không thấy đường ghi tiếp"
        )

        r = await client.post(
            f"/api/payments/import/{bid}/commit",
            headers=accountant_headers,
            json={"confirmed_rows": []},
        )
        assert r.status_code != 403, (
            f"cờ bật nhưng route commit từ chối kế toán (403) — nút sẽ dẫn vào "
            f"ngõ cụt. Body: {r.text[:300]}"
        )

    async def test_detail_tra_cung_co_voi_danh_sach(
        self, client: AsyncClient, admin_token_headers, admin_user_in_db
    ):
        """Hai endpoint phải nói CÙNG một câu.

        Giao diện mở lô từ danh sách rồi nạp lại chi tiết; hai nguồn lệch nhau
        thì nút hiện ở màn này lại biến mất ở màn kia mà không ai giải thích được.
        """
        bid = await _lo("preview", review_required=1, creator_id=admin_user_in_db["id"])
        ds = await client.get(
            "/api/payments/import/batches", headers=admin_token_headers
        )
        ct = await client.get(
            f"/api/payments/import/batches/{bid}", headers=admin_token_headers
        )
        assert ct.status_code == 200, ct.text
        assert (
            _tim(ds.json()["items"], bid)["can_resume_commit"]
            == ct.json()["can_resume_commit"]
            is True
        )
