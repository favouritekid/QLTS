"""``activity_service.log_activity`` trả MỘT ``UserActivityLog`` — khoá ở tầng HTTP.

Vì sao tệp này tồn tại
======================

PR #251 đổi ``log_activity`` từ ``Tuple[UserActivityLog, Callable]`` sang một
đối tượng, với lý do ghi trong docstring: *"all 17 callers discard tuple
(verified)"*. Phép "verified" ấy sai — 17 đường vẫn **unpack**:

* ``routers/admin/roles.py`` × 12, qua ``commit_and_log`` (``_, cb = log_result``)
* ``routers/admin/users.py`` × 4  (``_, log_callback = await …``)
* ``routers/profile.py``    × 1  (``_activity_log, activity_callback = await …``)

Hậu quả **hai dạng**, và một bộ test chỉ canh dạng đầu là canh hụt:

1. **HTTP 500** — 12 đường không có ``try/except`` quanh lời gọi audit.
2. **Nghiệp vụ THÀNH CÔNG nhưng audit MẤT** — 5 đường đặt audit trong
   ``try/except`` "best-effort". Người dùng thấy 200, dữ liệu đổi thật, còn
   ``user_activity_log`` không có hàng nào. Đây là dạng nguy hiểm hơn: không có
   gì đỏ, không có gì báo, chỉ là dấu vết kiểm toán lặng lẽ biến mất.

Test HTTP **đã tồn tại** và nightly **đã** làm 8 ca đỏ vì đúng lỗi này —
``test_admin_roles.py`` ×6, ``test_admin_users.py`` ×1, ``test_casbin_tracking.py``
×1. Lỗi ẩn lâu không phải vì thiếu test, mà vì **cả 8 ca đều nằm ngoài PR gate**:
không tệp nào trong số đó có tên trong một tier allowlist, nên mọi PR trước vẫn
xanh trong khi nightly đỏ đêm này qua đêm khác.

Vì thế chính tệp này phải nằm trong tier. Một bộ test đúng mà cổng không chạy thì
không khác gì không có.

Mỗi ca dưới đây khẳng định **hai** thứ: mã trạng thái ĐÚNG **và** hàng audit
CÓ THẬT trong DB. Bỏ vế thứ hai thì ca "best-effort" xanh trọn kể cả khi audit
không bao giờ được ghi.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app import models
from app.database import AsyncSessionLocal

pytestmark = pytest.mark.asyncio


async def _dem_audit(action: str) -> int:
    """Đếm hàng audit theo ``action``, đọc thẳng bảng bằng SESSION RIÊNG.

    Dùng ``AsyncSessionLocal`` mới cho mỗi lần đếm — đúng lối các test trong
    ``tests/api/``. Đọc lại qua session của chính request sẽ trả về đối tượng
    đang nằm trong identity map, nên một hàng chưa thật sự commit vẫn hiện ra
    như đã ghi.

    Đếm bằng ``func.count`` trên bảng thật thay vì tin giá trị router trả về:
    router bị chặn thì có trả về gì đâu mà tin.
    """
    async with AsyncSessionLocal() as session:
        row = await session.execute(
            select(func.count())
            .select_from(models.UserActivityLog)
            .where(models.UserActivityLog.action == action)
        )
        return int(row.scalar_one())


class TestKhongUnpackUserActivityLog:
    """Ba router, ba lối gọi khác nhau, cùng một giao ước."""

    async def test_them_policy_khong_500(
        self, client: AsyncClient, admin_token_headers: dict
    ):
        """``roles.py`` — đường KHÔNG có ``try/except`` ⇒ dạng lỗi 500.

        ``commit_and_log`` là điểm chung của 12 callsite trong ``roles.py``;
        một ca đi qua nó là đủ chứng minh helper không còn unpack. Các callsite
        còn lại khác nhau ở nghiệp vụ, không ở giao ước này.
        """
        truoc = await _dem_audit("add_policy")

        resp = await client.post(
            "/api/admin/roles/policies",
            headers=admin_token_headers,
            json={
                "subject": "test_role_activity_contract",
                "object": "/api/test-activity-contract",
                "action": "GET",
            },
        )

        assert resp.status_code in (200, 201), (
            "them policy phai thanh cong; 500 o day nghia la commit_and_log "
            f"lai unpack UserActivityLog. Nhan {resp.status_code}: {resp.text}"
        )
        sau = await _dem_audit("add_policy")
        assert sau == truoc + 1, (
            f"audit 'add_policy' phai tang dung 1 (truoc={truoc}, sau={sau})"
        )

    async def test_cap_nhat_profile_van_ghi_audit(
        self,
        client: AsyncClient,
        regular_user_token_headers: dict,
        regular_user_in_db: dict,
    ):
        """``profile.py`` — đường CÓ ``try/except`` ⇒ dạng "200 nhưng mất audit".

        Ca này là ca quan trọng nhất của tệp. Trước bản vá, ``PUT /api/profile``
        trả **200** và tên người dùng đổi thật, trong khi ``log_profile_activity``
        ném ``TypeError`` bị ``except Exception`` nuốt gọn. Một phép kiểm chỉ
        nhìn mã trạng thái sẽ **xanh** trên đúng cái bug này.
        """
        truoc = await _dem_audit("update_profile")

        resp = await client.put(
            "/api/profile",
            headers=regular_user_token_headers,
            data={"full_name": "Ten Moi Kiem Audit"},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["full_name"] == "Ten Moi Kiem Audit", (
            "nghiep vu phai thanh cong — neu khong, ca nay dang do vi ly do khac"
        )

        sau = await _dem_audit("update_profile")
        assert sau == truoc + 1, (
            "PUT tra 200 va ten DA doi, nhung khong co hang audit nao duoc ghi "
            f"(truoc={truoc}, sau={sau}). Day dung la dang loi ma `try/except` "
            "best-effort che mat: khong 500, khong canh bao, chi mat dau vet."
        )

    async def test_admin_tao_user_van_ghi_audit(
        self, client: AsyncClient, admin_token_headers: dict
    ):
        """``users.py`` — cũng là đường ``try/except``, khác helper với profile.

        Giữ riêng khỏi ca profile: hai tệp có hai bản ``log_admin_activity`` /
        ``log_profile_activity`` khác nhau, sửa một bản không chứng minh bản kia.
        """
        truoc = await _dem_audit("create_user")

        # ``data=`` chứ không ``json=``: endpoint khai bằng ``Form(...)`` nên
        # body JSON cho ra 422 "Field required" và ca này sẽ đỏ vì lý do khác.
        resp = await client.post(
            "/api/admin/users",
            headers=admin_token_headers,
            data={
                "username": "audit_contract_user",
                "email": "audit_contract_user@example.com",
                "password": "Test@12345678",  # >= 12 ky tu theo rang buoc schema
                "full_name": "Audit Contract User",
                "role": "user",
                "status": "active",
            },
        )

        assert resp.status_code in (200, 201), resp.text
        sau = await _dem_audit("create_user")
        assert sau == truoc + 1, (
            f"tao user tra {resp.status_code} nhung audit 'create_user' khong "
            f"duoc ghi (truoc={truoc}, sau={sau})"
        )


MAT_KHAU_F154 = "AdminDatLai!2026x"


async def _hang_dat_mat_khau(target_id: int) -> list:
    """Hàng nhật ký ``admin_set_password`` của người đích — session CSDL RIÊNG (xem ``_dem_audit``)."""
    async with AsyncSessionLocal() as session:
        return list(
            (
                await session.execute(
                    select(models.UserActivityLog).where(
                        models.UserActivityLog.action == "admin_set_password",
                        models.UserActivityLog.target_user_id == target_id,
                    )
                )
            ).scalars()
        )


class TestF154NhatKyDatMatKhau:
    """F154 T3 (owner 25-11 Q-A8): Quản trị đặt mật khẩu cho người khác ⇒ ĐÚNG MỘT hàng nhật ký, CÙNG giao dịch với
    việc đổi mật khẩu, nêu ĐÚNG người làm; không chứa mật khẩu hay hash. Trước bản vá: 0 hàng, structlog ghi cứng
    ``admin_user="admin"`` ⇒ không truy được ai đã đặt."""

    async def test_dat_mat_khau_ghi_dung_mot_hang_dung_nguoi_lam(
        self, client: AsyncClient, admin_token_headers: dict, admin_user_in_db: dict,
        regular_user_in_db: dict, test_redis_client,
    ):
        target = regular_user_in_db["id"]
        try:
            resp = await client.post(
                f"/api/admin/users/{target}/password",
                json={"new_password": MAT_KHAU_F154},
                headers=admin_token_headers,
            )
            assert resp.status_code == 200, resp.text

            hang = await _hang_dat_mat_khau(target)
            assert [(h.actor_id, h.target_user_id) for h in hang] == [(admin_user_in_db["id"], target)], (
                "phải có đúng MỘT hàng nhật ký, nêu đúng Quản trị đã làm"
            )
        finally:
            await test_redis_client.delete(f"user_blacklist:{target}")

    async def test_nhat_ky_khong_chua_mat_khau_hay_hash(
        self, client: AsyncClient, admin_token_headers: dict, regular_user_in_db: dict, test_redis_client,
    ):
        target = regular_user_in_db["id"]
        try:
            resp = await client.post(
                f"/api/admin/users/{target}/password",
                json={"new_password": MAT_KHAU_F154},
                headers=admin_token_headers,
            )
            assert resp.status_code == 200, resp.text

            hang = await _hang_dat_mat_khau(target)
            assert len(hang) == 1, f"tiền đề: có hàng nhật ký để soi ({len(hang)})"
            noi_dung = f"{hang[0].description} {hang[0].changes}"
            assert MAT_KHAU_F154 not in noi_dung and "$2b$" not in noi_dung, (
                f"nhật ký lộ mật khẩu / hash: {noi_dung}"
            )
        finally:
            await test_redis_client.delete(f"user_blacklist:{target}")

    async def test_dat_trung_mat_khau_cu_khong_ghi_nhat_ky(
        self, client: AsyncClient, admin_token_headers: dict, regular_user_in_db: dict,
    ):
        """K4b — không đổi gì (mật khẩu mới trùng mật khẩu cũ ⇒ 400) thì KHÔNG có hàng nhật ký mồ côi."""
        target = regular_user_in_db["id"]
        resp = await client.post(
            f"/api/admin/users/{target}/password",
            json={"new_password": regular_user_in_db["password"]},
            headers=admin_token_headers,
        )
        assert resp.status_code == 400, f"tiền đề: đặt trùng mật khẩu cũ phải bị từ chối: {resp.text}"

        assert await _hang_dat_mat_khau(target) == [], "không đổi gì mà có hàng nhật ký"


class TestGiaoUocOTangKieu:
    """Chặn ngay ở khai báo, trước khi ai đó chạy tới runtime.

    Ba ca trên đi qua HTTP nên chúng bắt được bug thật; ba ca dưới rẻ hơn nhiều
    và bắt được đúng lúc kiểu bị đổi ngược — trước khi một callsite mới nào đó
    học theo chữ ký sai.
    """

    async def test_log_activity_tra_mot_doi_tuong(self):
        import inspect

        from app.services import activity_service

        sig = inspect.signature(activity_service.log_activity)
        assert sig.return_annotation is not inspect.Signature.empty, (
            "log_activity phai khai kieu tra ve"
        )
        assert "Tuple" not in str(sig.return_annotation), (
            "log_activity KHONG duoc quay lai kieu tuple: %s" % sig.return_annotation
        )

    async def test_ba_helper_router_khong_khai_tuple(self):
        import inspect

        from app.routers import profile as profile_router
        from app.routers.admin import roles as roles_router
        from app.routers.admin import users as users_router

        for ten, fn in (
            ("roles.log_admin_activity", roles_router.log_admin_activity),
            ("users.log_admin_activity", users_router.log_admin_activity),
            ("profile.log_profile_activity", profile_router.log_profile_activity),
        ):
            ann = str(inspect.signature(fn).return_annotation)
            assert "Tuple" not in ann, (
                "%s khai kieu tuple (%s) trong khi activity_service tra mot doi "
                "tuong — hai nguon chuan cho cung mot cau hoi" % (ten, ann)
            )

    async def test_khong_con_callsite_nao_unpack(self):
        """Quét NGUỒN, không quét runtime.

        Ba ca HTTP ở trên mỗi ca chỉ đi qua MỘT callsite. Mười bảy đường thì
        không thể viết mười bảy ca HTTP mà không biến bộ test thành gánh nặng —
        nên phần còn lại canh bằng phép quét nguồn. Hai lớp bù cho nhau: quét
        nguồn bắt được diện rộng, ca HTTP chứng minh đường thật chạy được.
        """
        import inspect
        import re

        from app.routers import profile as profile_router
        from app.routers.admin import roles as roles_router
        from app.routers.admin import users as users_router

        # Bắt `a, b = await log_*activity(` và `_, cb = log_result` — hai hình
        # dạng unpack đã thật sự xuất hiện trong kho.
        mau = re.compile(
            r"^\s*[\w_]+\s*,\s*[\w_]+\s*=\s*(?:await\s+)?"
            r"(?:log_admin_activity|log_profile_activity|log_result)\b",
            re.M,
        )
        vi_pham = []
        for ten, mod in (
            ("routers/admin/roles.py", roles_router),
            ("routers/admin/users.py", users_router),
            ("routers/profile.py", profile_router),
        ):
            src = inspect.getsource(mod)
            for m in mau.finditer(src):
                dong = src[: m.start()].count("\n") + 1
                vi_pham.append("%s:%d — %s" % (ten, dong, m.group(0).strip()))

        assert not vi_pham, (
            "con callsite unpack ket qua log_activity thanh 2 bien:\n  "
            + "\n  ".join(vi_pham)
        )
