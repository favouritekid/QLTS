"""Hợp đồng JSON của lỗi 409 "nghi trùng phiếu thu" — qua ASGI THẬT.

Vì sao phải đi qua app thật thay vì gọi thẳng handler: một handler đăng ký sai
chỗ (ví dụ trong ``lifespan``) vẫn chạy đúng khi được gọi trực tiếp, nên unit
test sẽ xanh trong khi client thật nhận về một thân lỗi khác hẳn. Bài học đó
đã trả giá một lần rồi (memory ``handler-wiring-needs-real-stack-test``).

Thân của một lỗi không đi qua ``response_model`` nào cả — không có ai rà hộ.
Nên ở đây khoá **exact JSON**: đúng tập khoá, đúng KIỂU (số tiền là chuỗi,
ngày là ISO hoặc null), và không có gì thừa lọt ra.
"""

import base64
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select

from app import models
from app.database import AsyncSessionLocal
from app.models.finance import (
    FeeTypeEnum,
    Invoice,
    InvoiceStatusEnum,
    Payment,
    PaymentMethod,
    RefundRequest,
    RefundStatusEnum,
)
from app.repositories.payment_repository import MAX_DUPLICATE_CANDIDATES
from app.security import get_password_hash
from tests.fixtures.constants import AuthURLs
from tests.fixtures.users import get_auth_headers
from app.services.fee_calculation_service import FeeCalculationService
from app.services.payment_service import PaymentService

pytestmark = pytest.mark.asyncio

_HALF = Decimal("1000000")
_WHEN = datetime(2026, 8, 5, 3, 0, tzinfo=timezone.utc)  # 10:00 giờ VN

KHOA_HOP_DONG = {"payment_id", "amount", "payment_date", "status", "invoice_number"}


@pytest_asyncio.fixture
async def fee_with_one_payment(seed_lead_dependencies: dict, admin_user_in_db: dict):
    """Một khoản phí, hai đợt, và MỘT phiếu đã ghi ở đợt 1.

    ``tests/api/`` không có fixture ``db`` — tự mở session và **commit**, vì
    client gọi API qua session khác.
    """
    seeded = seed_lead_dependencies
    admin_id = admin_user_in_db["id"]

    async with AsyncSessionLocal() as db:
        method = PaymentMethod(
            code="dupcontract_cash", name="Cash", is_online=False, is_active=True
        )
        db.add(method)

        maker = models.User(
            username="dupcontract_maker",
            email="dupcontract_maker@test.com",
            password_hash=get_password_hash("Maker123!"),
            role="officer",
            status="active",
            full_name="Dup Contract Maker",
            unit_id=seeded["unit_id"],
        )
        db.add(maker)
        await db.flush()

        lead = models.Lead(
            full_name="Dup Contract Student",
            phone="0901770001",
            source="test",
            unit_id=seeded["unit_id"],
            consultation_status_id=seeded["initial_status_id"],
        )
        db.add(lead)
        await db.flush()

        profile = models.AdmissionProfile(
            lead_id=lead.id, status="submitted", academic_year=2025, applied_rules={}
        )
        db.add(profile)
        await db.flush()

        fee, _ = await FeeCalculationService(db).calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.application,
            base_amount=_HALF * 2,
            academic_year=2025,
            user_id=admin_id,
            unit_id=seeded["unit_id"],
        )
        await db.flush()

        invoices = []
        for idx in (1, 2):
            inv = Invoice(
                fee_id=fee.id,
                invoice_number=f"INV-DUPCONTRACT-{idx}",
                installment_no=idx,
                amount=_HALF,
                status=InvoiceStatusEnum.issued.value,
                due_date=date.today() + timedelta(days=30 * idx),
            )
            db.add(inv)
            invoices.append(inv)
        await db.commit()

        cu, _ = await PaymentService(db).record_manual_payment(
            invoice_id=invoices[0].id,
            method_id=method.id,
            amount=_HALF,
            user_id=maker.id,
            unit_id=seeded["unit_id"],
            payment_date=_WHEN,
        )
        await db.commit()

        return {
            "fee_id": fee.id,
            "invoice_ids": [i.id for i in invoices],
            "method_id": method.id,
            "maker_id": maker.id,
            "phieu_cu_id": cu.id,
            "so_hoa_don_cu": invoices[0].invoice_number,
        }


def _body(ctx: dict, *, invoice_idx: int = 1, phieu: str | None = None):
    body = {
        "invoice_id": ctx["invoice_ids"][invoice_idx],
        "method_id": ctx["method_id"],
        "amount": "1000000",
        "payment_date": "2026-08-05T03:00:00+00:00",
    }
    if phieu is not None:
        body["review_token"] = phieu
    return body


async def _ghi_qua_vong_xac_nhan(
    client: AsyncClient, headers: dict, ctx: dict, *, invoice_idx: int = 1
):
    """Bấm gửi; bị chặn thì lấy phiếu TỪ CHÍNH phản hồi rồi gửi lại.

    Đúng các bước giao diện làm. Ca kiểm không được tự dựng phiếu: làm thế là
    tự trao cho mình quyền mà giao diện không có, và ca sẽ xanh kể cả khi máy
    chủ quên cấp phiếu trong thân 409.
    """
    r = await client.post("/api/payments", json=_body(ctx, invoice_idx=invoice_idx), headers=headers)
    if r.status_code != 409:
        return r
    phieu = r.json()["review_token"]
    return await client.post(
        "/api/payments",
        json=_body(ctx, invoice_idx=invoice_idx, phieu=phieu),
        headers=headers,
    )


async def _dem_payment(fee_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(func.count(Payment.id))
                .join(Invoice, Payment.invoice_id == Invoice.id)
                .where(Invoice.fee_id == fee_id)
            )
        ).scalar() or 0


class TestHopDong409:
    async def test_than_loi_dung_hop_dong_va_dung_kieu(
        self, client: AsyncClient, admin_token_headers: dict, fee_with_one_payment
    ):
        ctx = fee_with_one_payment
        r = await client.post(
            "/api/payments", json=_body(ctx), headers=admin_token_headers
        )
        assert r.status_code == 409, r.text
        body = r.json()

        assert set(body.keys()) == {
            "detail",
            "error_code",
            "duplicates",
            "duplicates_truncated",
            "duplicates_total",
            "review_token",
        }, f"khoá lạ trong thân lỗi: {sorted(body.keys())}"
        assert isinstance(body["detail"], str) and body["detail"]
        assert body["error_code"] == "PAYMENT_DUPLICATE_SUSPECTED"
        assert body["duplicates_truncated"] is False
        # TỔNG thật, không phải độ dài danh sách đã cắt.
        assert body["duplicates_total"] == len(body["duplicates"])
        # Phiếu xác nhận phải CÓ MẶT và mờ. Thiếu nó thì người ghi không có
        # đường nào ghi tiếp — hàng rào mềm biến thành hàng rào cứng, và đó là
        # một lỗi im lặng: 409 vẫn trông đúng.
        assert isinstance(body["review_token"], str) and body["review_token"]
        assert body["review_token"].count(".") == 1, "phiếu phải là <thân>.<chữ ký>"

        # Thân phiếu KHÔNG bí mật — nó là base64 có chữ ký, ai cũng giải mã
        # được, và điều đó nằm trong thiết kế: thứ được bảo vệ là tính TOÀN VẸN
        # (sửa một byte là chữ ký hỏng), không phải tính kín. Nhưng vì ai cũng
        # đọc được, cái nằm bên trong phải là tập tối thiểu. Ca này khoá đúng
        # tập đó — đặc biệt là KHÔNG có danh sách mã phiếu ứng viên: giao diện
        # chỉ được thấy phần hiển thị, còn phiếu thì nói về TOÀN BỘ tập.
        import base64
        import json

        phan_than = body["review_token"].split(".")[0]
        than = json.loads(
            base64.urlsafe_b64decode(phan_than + "=" * (-len(phan_than) % 4))
        )
        assert set(than.keys()) == {
            "flow", "uid", "unit", "fee", "inv", "amt", "when", "gv",
            "batch", "row", "exp", "jti",
        }, f"khoá lạ trong thân phiếu: {sorted(than.keys())}"
        assert than["fee"] == ctx["fee_id"]
        assert than["inv"] == ctx["invoice_ids"][1]
        assert than["flow"] == "manual"
        # `gv` là ảnh chụp `fee.duplicate_guard_version` — vế chống chen ngang.
        assert isinstance(than["gv"], int) and than["gv"] >= 1

        assert len(body["duplicates"]) == 1
        d = body["duplicates"][0]
        assert set(d.keys()) == KHOA_HOP_DONG, f"khoá lạ: {sorted(d.keys())}"
        assert d["payment_id"] == ctx["phieu_cu_id"]
        # Số tiền là CHUỖI — khớp quy ước Decimal→string của giao diện và
        # không mất chính xác qua JSON number.
        assert isinstance(d["amount"], str), type(d["amount"])
        assert Decimal(d["amount"]) == _HALF
        # Ngày là ISO-8601, đọc lại được — không phải một chuỗi tuỳ hứng.
        assert isinstance(d["payment_date"], str)
        assert datetime.fromisoformat(d["payment_date"]) == _WHEN
        assert d["status"] == "pending"
        assert d["invoice_number"] == ctx["so_hoa_don_cu"]

    async def test_409_khong_sinh_them_phieu(
        self, client: AsyncClient, admin_token_headers: dict, fee_with_one_payment
    ):
        """Cảnh báo phải là TỪ CHỐI, không phải ghi xong rồi mới kêu."""
        ctx = fee_with_one_payment
        truoc = await _dem_payment(ctx["fee_id"])
        r = await client.post(
            "/api/payments", json=_body(ctx), headers=admin_token_headers
        )
        assert r.status_code == 409, r.text
        assert await _dem_payment(ctx["fee_id"]) == truoc

    async def test_khong_ro_context_noi_bo(
        self, client: AsyncClient, admin_token_headers: dict, fee_with_one_payment
    ):
        """``context`` là chỗ chứa dữ liệu debug — không được đi ra."""
        ctx = fee_with_one_payment
        r = await client.post(
            "/api/payments", json=_body(ctx), headers=admin_token_headers
        )
        body = r.json()
        assert "context" not in body
        # Vài trường của Payment cố tình nằm NGOÀI danh sách trắng.
        for cam in ("created_by_id", "notes", "payer_account", "invoice_id"):
            assert cam not in body["duplicates"][0], cam

    async def test_vong_xac_nhan_day_du_thi_ghi_duoc_201(
        self, client: AsyncClient, admin_token_headers: dict, fee_with_one_payment
    ):
        """Khoá TOÀN chuỗi: 409 cấp phiếu → thân yêu cầu thật → ghi được.

        Thiếu một mắt (schema, router, chữ ký service, hay chính máy chủ quên
        cấp phiếu) thì vòng này không khép và ca trả 409 lần hai. Đây là ca duy
        nhất chứng minh tính năng dùng được thật — ca ở tầng service tự dựng
        tham số nên nó xanh kể cả khi giao diện gửi thiếu một trường.
        """
        ctx = fee_with_one_payment
        r = await _ghi_qua_vong_xac_nhan(client, admin_token_headers, ctx)
        assert r.status_code == 201, r.text

    async def test_khong_co_phieu_thi_chan(
        self, client: AsyncClient, admin_token_headers: dict, fee_with_one_payment
    ):
        """Không gửi phiếu ⇒ chặn. Fail-closed cho cả client cũ."""
        ctx = fee_with_one_payment
        body = _body(ctx)
        assert "review_token" not in body
        r = await client.post("/api/payments", json=body, headers=admin_token_headers)
        assert r.status_code == 409, r.text

    async def test_phieu_bi_sua_mot_ky_tu_thi_van_chan(
        self, client: AsyncClient, admin_token_headers: dict, fee_with_one_payment
    ):
        """Chữ ký phải là chữ ký thật, không phải một chuỗi trông giống.

        ⚠️ Đột biến phải đổi BYTE, không chỉ đổi KÝ TỰ.

        Bản trước sửa ký tự CUỐI: ``phieu[:-1] + ("A" if phieu[-1] != "A" else "B")``.
        Phần chữ ký là 32 byte mã hoá Base64URL không padding ⇒ 43 ký tự, và ký
        tự cuối chỉ mang 4 bit dữ liệu — 2 bit thấp là padding. Nên nó chỉ nhận
        16 giá trị (``048AEIMQUYcgkosw``), và khi nó là ``A`` thì đột biến đổi
        sang ``B``: hai ký tự ấy chung 4 bit cao nên GIẢI MÃ RA CÙNG 32 BYTE.
        Chữ ký vẫn hợp lệ, endpoint cấp phép ghi, ca kiểm đỏ.

        Đo trên 200.000 chữ ký ngẫu nhiên: 6,33% va chạm (lý thuyết 1/16 =
        6,25%), và chỉ xảy ra khi ký tự cuối là ``A``. Tức cứ ~16 lượt CI thì
        một lượt đỏ vì lý do không liên quan gì tới thứ ca này canh.

        Nay giải mã chữ ký, lật một bit của byte đầu, rồi mã hoá lại. Cách này
        đúng theo bản chất phép kiểm (toàn vẹn HMAC) và không phụ thuộc tính
        chất vị trí nào của Base64 — chính loại lý lẽ đã làm bản trước sai.
        """
        ctx = fee_with_one_payment
        r = await client.post("/api/payments", json=_body(ctx), headers=admin_token_headers)
        assert r.status_code == 409, r.text
        phieu = r.json()["review_token"]

        phan_than, phan_ky = phieu.split(".")
        raw_ky = base64.urlsafe_b64decode(phan_ky + "=" * (-len(phan_ky) % 4))
        raw_hong = bytes([raw_ky[0] ^ 0x01]) + raw_ky[1:]
        # Đột biến phải THẬT SỰ đổi byte — nếu không, ca kiểm không kiểm gì cả.
        assert raw_hong != raw_ky, "đột biến không đổi byte nào — ca kiểm vô nghĩa"
        hong = f"{phan_than}.{base64.urlsafe_b64encode(raw_hong).rstrip(b'=').decode()}"
        # Giữ đúng hợp đồng mà tên ca này khai: SỬA MỘT KÝ TỰ. Lật một bit chỉ
        # chạm đúng một ký tự Base64, vì mỗi bit thuộc về đúng một ký tự.
        assert len(hong) == len(phieu)
        assert sum(a != b for a, b in zip(hong, phieu)) == 1, "phải khác đúng một ký tự"

        truoc = await _dem_payment(ctx["fee_id"])
        r = await client.post(
            "/api/payments",
            json=_body(ctx, phieu=hong),
            headers=admin_token_headers,
        )
        assert r.status_code == 409, r.text
        assert await _dem_payment(ctx["fee_id"]) == truoc, "phiếu hỏng mà vẫn ghi"

    async def test_phieu_cu_HET_hieu_luc_khi_co_phieu_thu_moi_chen_vao(
        self, client: AsyncClient, admin_token_headers: dict, fee_with_one_payment
    ):
        """Ca then chốt của cả đợt thiết kế lại.

        Người ghi nhận cảnh báo cho tập {A}, rồi một phiếu B vào giữa lúc họ
        đang đọc. Phiếu xác nhận cũ chỉ nói về {A}, nên nó KHÔNG được mở đường
        cho một tập đã khác — và thứ bắt được điều đó là
        ``fee.duplicate_guard_version``, do trigger ở tầng cơ sở dữ liệu tăng.
        """
        ctx = fee_with_one_payment
        r = await client.post("/api/payments", json=_body(ctx), headers=admin_token_headers)
        assert r.status_code == 409, r.text
        phieu_cu = r.json()["review_token"]

        # B chen vào: ghi ở hoá đơn CÒN LẠI của cùng khoản phí, qua đúng vòng
        # xác nhận (nên bản thân nó hợp lệ).
        r = await _ghi_qua_vong_xac_nhan(client, admin_token_headers, ctx, invoice_idx=0)
        assert r.status_code == 201, r.text

        truoc = await _dem_payment(ctx["fee_id"])
        r = await client.post(
            "/api/payments",
            json=_body(ctx, phieu=phieu_cu),
            headers=admin_token_headers,
        )
        assert r.status_code == 409, "phiếu cấp cho tập CŨ vẫn mở được cửa"
        assert await _dem_payment(ctx["fee_id"]) == truoc
        # Và phải cấp phiếu MỚI, nếu không người ghi mắc kẹt trong vòng 409.
        assert r.json()["review_token"] != phieu_cu

    async def test_dung_lai_phieu_sau_khi_da_ghi_thanh_cong_KHONG_sinh_phieu_thu_hai(
        self, client: AsyncClient, admin_token_headers: dict, fee_with_one_payment
    ):
        """Replay: bấm hai lần, hoặc mạng lag rồi client gửi lại.

        Chính lần ghi thành công làm version nhích (trigger trên ``payment``),
        nên phiếu vừa dùng tự hết hiệu lực — không cần một sổ jti đã-dùng nào
        cả. Đây là lý do version được đặt ở tầng cơ sở dữ liệu chứ không phải
        một con số do ứng dụng tự quản.
        """
        ctx = fee_with_one_payment
        r = await client.post("/api/payments", json=_body(ctx), headers=admin_token_headers)
        assert r.status_code == 409, r.text
        phieu = r.json()["review_token"]

        r = await client.post(
            "/api/payments", json=_body(ctx, phieu=phieu), headers=admin_token_headers
        )
        assert r.status_code == 201, r.text
        sau_lan_dau = await _dem_payment(ctx["fee_id"])

        r = await client.post(
            "/api/payments", json=_body(ctx, phieu=phieu), headers=admin_token_headers
        )
        assert r.status_code == 409, "phiếu dùng lại vẫn ghi được ⇒ tiền vào hai lần"
        assert await _dem_payment(ctx["fee_id"]) == sau_lan_dau


class TestPayloadKhongDeGhiDe:
    """``public_payload`` là dữ liệu, không phải quyền ghi đè hợp đồng."""

    async def test_payload_khong_ghi_de_duoc_detail_va_error_code(self):
        """Client rẽ nhánh theo ``error_code`` — nó phải do máy chủ quyết.

        Nếu payload thắng, một lỗi mang khoá trùng tên sẽ đổi được mã lỗi mà
        giao diện dùng để phân biệt "nghi trùng" với mọi lỗi 409 khác.
        """
        from fastapi import Request

        from app.middleware.exception_handlers import base_app_exception_handler
        from app.utils.exceptions import PaymentDuplicateSuspected

        exc = PaymentDuplicateSuspected("thật", duplicates=[])
        exc.public_payload["detail"] = "giả"
        exc.public_payload["error_code"] = "GIA_MAO"

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/payments",
            "headers": [],
            "query_string": b"",
        }
        resp = await base_app_exception_handler(Request(scope), exc)
        import json

        body = json.loads(resp.body)
        assert body["detail"] == "thật"
        assert body["error_code"] == "PAYMENT_DUPLICATE_SUSPECTED"

    async def test_hai_lan_nem_khong_dung_chung_payload(self):
        """Payload phải riêng theo từng instance.

        Đặt mặc định ở cấp lớp là chia sẻ MỘT dict cho mọi lần ném — hai lỗi
        liên tiếp đắp dữ liệu của nhau, và người dùng thứ hai nhìn thấy danh
        sách phiếu của người thứ nhất.
        """
        from app.utils.exceptions import PaymentDuplicateSuspected

        a = PaymentDuplicateSuspected("a", duplicates=[{"payment_id": 1}])
        b = PaymentDuplicateSuspected("b", duplicates=[])

        assert a.public_payload["duplicates"] == [{"payment_id": 1}]
        assert b.public_payload["duplicates"] == []
        assert a.public_payload is not b.public_payload

    async def test_lỗi_thuong_khong_co_payload_cong_khai(self):
        """Mặc định là RỖNG — fail-closed.

        Một lỗi không chủ động khai báo dữ liệu công khai thì không được vô
        tình mang gì ra ngoài.
        """
        from app.utils.exceptions import ConflictError

        assert ConflictError("x").public_payload == {}


class TestCatDanhSachTrongThanLoi:
    async def test_toi_da_20_phan_tu_va_co_co_bao_bi_cat(
        self, client: AsyncClient, admin_token_headers: dict, fee_with_one_payment
    ):
        """Thân lỗi phải có kích thước hữu hạn.

        Xác nhận trùng là hợp lệ và phiếu chờ duyệt chưa giảm số dư, nên số
        phiếu giống nhau có thể tăng không giới hạn. Một thông báo lỗi không
        có trần là một thông báo lỗi có thể bị dùng làm vũ khí.
        """
        ctx = fee_with_one_payment
        # Đã có 1 phiếu từ fixture; thêm 20 nữa (xác nhận trùng) → 21.
        for _ in range(MAX_DUPLICATE_CANDIDATES):
            r = await _ghi_qua_vong_xac_nhan(client, admin_token_headers, ctx)
            assert r.status_code == 201, r.text

        r = await client.post(
            "/api/payments", json=_body(ctx), headers=admin_token_headers
        )
        assert r.status_code == 409, r.text
        body = r.json()
        assert len(body["duplicates"]) == MAX_DUPLICATE_CANDIDATES
        assert body["duplicates_truncated"] is True
        # Bị cắt thì câu chữ không được tuyên bố con số.
        assert "20" not in body["detail"], body["detail"]


class TestXemTruocDaGoFailClosed:
    """Đường XEM TRƯỚC đã gỡ — và phải gỡ theo kiểu KÊU THÀNH TIẾNG.

    Chỗ nguy hiểm không phải việc gỡ, mà là gỡ nửa vời. Hai tham số
    ``duplicate_amount``/``duplicate_date`` sống trên chính ``GET /api/payments``
    (đặt ở đó vì Casbin cấp quyền theo từng path, nên một path mới kéo theo
    policy + migration + test phân quyền). Xoá chúng khỏi chữ ký thì FastAPI
    IM LẶNG bỏ qua query lạ và trả 200 kèm danh sách phiếu thu THƯỜNG của khoản
    phí — một tập rộng hơn hẳn tập ứng viên trùng, mà client cũ sẽ vẽ ra thành
    "các phiếu nghi trùng" rồi cho người dùng bấm qua.

    Không có dòng đỏ nào để lần theo trong ca đó. Nên nó cần một ca riêng.
    """

    async def test_duplicate_amount_bi_tu_choi_410_KHONG_roi_sang_list(
        self, client: AsyncClient, admin_token_headers: dict, fee_with_one_payment
    ):
        ctx = fee_with_one_payment
        r = await client.get(
            f"/api/payments?fee_id={ctx['fee_id']}&duplicate_amount=1000000"
            "&duplicate_date=2026-08-05T03:00:00%2B00:00",
            headers=admin_token_headers,
        )
        assert r.status_code == 410, (
            f"đường xem trước phải trả 410, nhận {r.status_code}. Nếu là 200 "
            "thì tham số đang bị bỏ qua và client nhận danh sách phiếu thường "
            "dưới danh nghĩa 'nghi trùng'."
        )
        # Và tuyệt đối KHÔNG kèm dữ liệu phiếu nào.
        assert "items" not in r.text, "410 mà vẫn trả danh sách phiếu"

    async def test_chi_MOT_trong_hai_tham_so_cung_bi_tu_choi(
        self, client: AsyncClient, admin_token_headers: dict, fee_with_one_payment
    ):
        """Nửa bộ tham số cũng là client cũ, cũng phải nghe cùng một câu.

        Chấp nhận nửa bộ rồi rơi sang nhánh list là đúng cái ca fail-open ở
        trên, chỉ khác đường vào.
        """
        ctx = fee_with_one_payment
        for q in (
            f"fee_id={ctx['fee_id']}&duplicate_amount=1000000",
            f"fee_id={ctx['fee_id']}&duplicate_date=2026-08-05T03:00:00%2B00:00",
        ):
            r = await client.get(f"/api/payments?{q}", headers=admin_token_headers)
            assert r.status_code == 410, f"query `{q}` trả {r.status_code}"

    async def test_LIST_thuong_van_chay_binh_thuong(
        self, client: AsyncClient, admin_token_headers: dict, fee_with_one_payment
    ):
        """Chiều ngược lại: đừng chặn quá tay.

        Cùng endpoint còn phục vụ danh sách phiếu thu và hàng đợi chờ duyệt.
        Một phép chặn bắt nhầm ở đây sẽ làm hỏng hai màn hình không liên quan.
        """
        ctx = fee_with_one_payment
        r = await client.get(
            f"/api/payments?fee_id={ctx['fee_id']}", headers=admin_token_headers
        )
        assert r.status_code == 200, r.text
        assert r.json()["items"], "danh sách phiếu thu thường phải còn chạy"
