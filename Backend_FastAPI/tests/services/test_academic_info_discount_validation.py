"""Chặn CẤU HÌNH ưu đãi sai ở cấp ngành (``applied_discount_policy_ids``).

Cột là JSONB, không có khoá ngoại — nên một id gõ nhầm hoặc một chính sách đã bị
tắt nằm im trong cấu hình mà không ai biết. Lúc tính phí, engine lặng lẽ bỏ qua
và kế toán chỉ thấy "đã bật ưu đãi mà không giảm đồng nào". Bắt ngay tại chỗ cấu
hình thì người sửa được, còn bắt lúc tính tiền thì đã muộn.

Ca thật đã xảy ra trên prod: cả 3 chính sách bị tắt (26-07) trong khi cấu hình
ngành vẫn có thể trỏ tới chúng.

🔴 Dùng fixture ``db`` chứ KHÔNG tự mở ``AsyncSessionLocal``: fixture là thứ dựng
schema cho ``qlts_test``. Bản đầu tự mở session nên chỉ xanh khi có suite khác
chạy trước tạo bảng hộ — chạy riêng file này là ``UndefinedTableError``.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tuition_discount_policy import TuitionDiscountPolicy
from app.services.organization_service import _validate_discount_policy_ids
from app.utils.exceptions import BadRequest

pytestmark = pytest.mark.asyncio


async def _seed_policy(db: AsyncSession, *, code: str, is_active: bool) -> int:
    policy = TuitionDiscountPolicy(
        code=code[:50],
        name=f"Chính sách {code}",
        discount_type="amount",
        discount_value=Decimal("500000"),
        is_active=is_active,
        applicable_scope={},
        target_criteria={},
    )
    db.add(policy)
    await db.flush()
    return policy.id


async def test_danh_sach_rong_thi_khong_kiem_gi(db: AsyncSession):
    await _validate_discount_policy_ids(db, None)
    await _validate_discount_policy_ids(db, [])


async def test_chinh_sach_dang_hoat_dong_thi_gan_duoc(db: AsyncSession):
    pid = await _seed_policy(db, code="CFG_OK_1", is_active=True)
    await _validate_discount_policy_ids(db, [pid])


async def test_id_khong_ton_tai_bi_tu_choi(db: AsyncSession):
    with pytest.raises(BadRequest) as exc:
        await _validate_discount_policy_ids(db, [999_999_99])
    assert "không tồn tại" in str(exc.value)


async def test_chinh_sach_da_tat_khong_gan_duoc(db: AsyncSession):
    """Ca prod thật: chính sách bị vô hiệu hoá vẫn có thể bị gắn cho ngành, rồi
    nằm đó như một ưu đãi ma."""
    pid = await _seed_policy(db, code="CFG_OFF_1", is_active=False)
    with pytest.raises(BadRequest) as exc:
        await _validate_discount_policy_ids(db, [pid])
    assert "ngừng hoạt động" in str(exc.value)


async def test_id_trung_lap_bi_tu_choi(db: AsyncSession):
    """Trùng id = cùng một ưu đãi hai lần. Engine dedupe được, nhưng cấu hình
    trùng là dấu hiệu người nhập nhầm — báo còn hơn im lặng sửa hộ."""
    pid = await _seed_policy(db, code="CFG_DUP_1", is_active=True)
    with pytest.raises(BadRequest) as exc:
        await _validate_discount_policy_ids(db, [pid, pid])
    assert "trùng lặp" in str(exc.value)


async def test_bao_loi_liet_ke_du_moi_id_hong(db: AsyncSession):
    """Sửa cấu hình mà mỗi lần chỉ biết một id hỏng thì phải thử nhiều vòng."""
    ok = await _seed_policy(db, code="CFG_MIX_OK", is_active=True)
    with pytest.raises(BadRequest) as exc:
        await _validate_discount_policy_ids(db, [ok, 888_888_88, 777_777_77])
    message = str(exc.value)
    assert "88888888" in message and "77777777" in message
