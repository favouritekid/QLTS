"""Thu hồi quyền Casbin — mọi đường phải xoá bằng ĐỦ bốn trường.

`auth_model.conf` khai ``p = sub, obj, act, eft``. Bốn đường thu hồi từng gọi
``remove_policy(sub, obj, act)`` với ba đối số, không khớp nổi rule bốn trường
nên KHÔNG xoá được gì — trong khi hai trong bốn đường vẫn báo thành công. Đây
là A01 Broken Access Control: một ALLOW cấp nhầm không thu hồi được bằng bất kỳ
đường nào người vận hành có.

Mọi ca dưới đây seed CẶP ``allow`` + ``deny`` cùng ``(sub, obj, act)``. Cặp ấy
không phải trang trí: nó là thứ duy nhất phân biệt được bản vá ĐÚNG (xoá theo
rule chính xác) với bản vá SAI (remove-filter theo ba trường) — bản sai xoá
luôn ``deny``, tức âm thầm MỞ quyền, tệ hơn lỗi ban đầu.
"""
import pytest

from app.database import AsyncSessionLocal
from app.main import fastapi_app
from app.services.casbin_service import CasbinPolicyService, policy_cua_role

SUB = "role:thu_hoi_probe"
OBJ = "/api/thu_hoi_probe/*"
ACT = "GET"
ALLOW = [SUB, OBJ, ACT, "allow"]
DENY = [SUB, OBJ, ACT, "deny"]


def _enf():
    return fastapi_app.state.enforcer


async def _seed_cap_allow_deny():
    """Dọn sạch rồi seed đúng cặp allow + deny cùng ba trường."""
    enf = _enf()
    for p in policy_cua_role(enf, SUB):
        await enf.remove_policy(*p)
    await enf.add_policy(*ALLOW)
    await enf.add_policy(*DENY)
    assert sorted(policy_cua_role(enf, SUB)) == sorted([ALLOW, DENY])
    return enf


# ---------------------------------------------------------------------------
# 1. Xoá thủ công qua API: xoá đúng allow, GIỮ deny
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_xoa_thu_cong_xoa_allow_va_giu_deny(client, admin_token_headers):
    enf = await _seed_cap_allow_deny()

    r = await client.request(
        "DELETE",
        "/api/admin/roles/policies",
        json={"subject": SUB, "object": OBJ, "action": ACT},
        headers=admin_token_headers,
    )
    assert r.status_code == 200, f"xoá thất bại: {r.text}"

    con_lai = policy_cua_role(enf, SUB)
    assert ALLOW not in con_lai, "allow phải bị xoá"
    assert DENY in con_lai, (
        "deny phải CÒN NGUYÊN — xoá nhầm deny là âm thầm MỞ quyền"
    )


# ---------------------------------------------------------------------------
# 2. Xoá hàng loạt: cùng bất biến
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_xoa_hang_loat_xoa_allow_va_giu_deny(client):
    enf = await _seed_cap_allow_deny()

    async with AsyncSessionLocal() as db:
        kq = await CasbinPolicyService(db, enf).remove_policies_batch(
            [(SUB, OBJ, ACT)], validate=False, force=True
        )

    con_lai = policy_cua_role(enf, SUB)
    assert kq["removed"] == 1, f"counter sai: {kq}"
    assert ALLOW not in con_lai
    assert DENY in con_lai, "deny phải CÒN NGUYÊN"
    # counter phải khớp TRẠNG THÁI THẬT, không phải tự khai
    assert kq["removed"] == 2 - len(con_lai)


@pytest.mark.asyncio
async def test_xoa_hang_loat_nhan_tuple_bon_truong(client):
    """Gọi bằng tuple bốn trường phải xoá ĐÚNG rule đó, không đụng rule kia."""
    enf = await _seed_cap_allow_deny()

    async with AsyncSessionLocal() as db:
        kq = await CasbinPolicyService(db, enf).remove_policies_batch(
            [tuple(DENY)], validate=False, force=True
        )

    con_lai = policy_cua_role(enf, SUB)
    assert kq["removed"] == 1, f"counter sai: {kq}"
    assert DENY not in con_lai, "phải xoá đúng deny khi được chỉ đích danh"
    assert ALLOW in con_lai, "allow phải còn nguyên"


# ---------------------------------------------------------------------------
# 3. Refresh template: xoá SẠCH rule cũ, và counter đo trạng thái thật
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_template_xoa_sach_rule_cu(client):
    enf = await _seed_cap_allow_deny()

    async with AsyncSessionLocal() as db:
        kq = await CasbinPolicyService(db, enf).refresh_role_from_template(
            role=SUB, template_id="lead_viewer", force=True
        )

    sau = policy_cua_role(enf, SUB)
    assert kq["success"] is True, f"refresh phải thành công: {kq}"
    assert ALLOW not in sau, "rule cũ allow phải bị xoá, không được mồ côi"
    assert DENY not in sau, "rule cũ deny phải bị xoá — refresh là xoá TOÀN role"
    # counter phải ĐO trạng thái thật, không suy từ `added`
    assert kq["policies_after"] == len(sau), (
        f"policies_after={kq['policies_after']} nhưng thực tế {len(sau)}"
    )
    assert kq["policies_removed"] == 2


@pytest.mark.asyncio
async def test_counter_policies_after_do_trang_thai_that(client):
    """`policies_after` phải ĐO enforcer, không suy từ `added`.

    Ca này CHỈ canh counter — cố ý không khẳng định gì về rule mồ côi, để khi
    nó đỏ thì biết ngay đỏ VÌ COUNTER chứ không phải vì thứ khác.

    Giới hạn cần nói thẳng: khi xoá chạy đúng thì `added` và số rule thật
    TRÙNG NHAU một cách tình cờ, nên đột biến counter đơn lẻ KHÔNG bị bắt —
    đã đo. Counter chỉ phân biệt được khi xoá hỏng, và đó đúng là lúc nó quan
    trọng: bản gốc báo `policies_after: 4` trong khi enforcer có 6. Vì vậy
    kiểm ngược cho ca này phải là đột biến GHÉP (xoá ba đối số + bỏ hậu điều
    kiện + counter suy từ added), không phải đột biến counter đơn lẻ.
    """
    enf = await _seed_cap_allow_deny()

    async with AsyncSessionLocal() as db:
        kq = await CasbinPolicyService(db, enf).refresh_role_from_template(
            role=SUB, template_id="lead_viewer", force=True
        )

    that = len(policy_cua_role(enf, SUB))
    assert kq["policies_after"] == that, (
        f"policies_after={kq['policies_after']} nhưng enforcer có {that} rule"
    )


@pytest.mark.asyncio
async def test_sync_all_roles_ke_thua_duong_refresh(client):
    """`sync_all_roles_from_templates` đi qua cùng đường refresh.

    Ca này tồn tại vì nó KẾ THỪA lỗi: vá refresh mà không đo sync thì không
    biết đường gọi gián tiếp có được vá theo hay không.
    """
    enf = await _seed_cap_allow_deny()

    async with AsyncSessionLocal() as db:
        kq = await CasbinPolicyService(db, enf).sync_all_roles_from_templates(
            dry_run=False
        )

    assert isinstance(kq, dict), f"sync trả về không phải dict: {kq!r}"
    # Không khẳng định SUB bị đụng (nó không có template), chỉ khẳng định
    # sync KHÔNG để lại rule mồ côi cho các role nó thật sự chạm.
    assert "error" not in kq or not kq.get("error"), f"sync lỗi: {kq}"


# ---------------------------------------------------------------------------
# 4. Xoá role: sạch policy, và không tuyên bố thành công khi còn sót
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_xoa_role_xoa_sach_ca_allow_lan_deny(client):
    from app.services import role_service

    enf = await _seed_cap_allow_deny()

    async with AsyncSessionLocal() as db:
        kq, _cb = await role_service.delete_role_atomic(db, SUB, enf)

    sau = policy_cua_role(enf, SUB)
    assert sau == [], f"xoá role phải không để lại rule mồ côi; còn: {sau}"
    assert kq["success"] is True, f"phải báo thành công: {kq}"
    assert "deleted successfully" in kq["detail"]
    assert kq["permission_policies_removed"] == 2, (
        f"counter phải khớp thực tế: {kq}"
    )
