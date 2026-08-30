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
async def test_sync_all_roles_uy_nhiem_sang_refresh(client):
    """`sync_all_roles_from_templates` phải gọi refresh cho role CÓ DRIFT.

    Bản nháp trước khẳng định `await_count >= 0` — biểu thức LUÔN ĐÚNG, tức
    không canh gì cả; và nó chạy `dry_run=False` thật nên có thể đổi policy của
    role HỆ THỐNG trong DB test dùng chung.

    Nay dựng drift CHẮC CHẮN và CHỈ cho đúng một role (`role:officer`), rồi
    khẳng định refresh được gọi ĐÚNG MỘT LẦN với đúng đối số. Đây là ca canh
    DELEGATION: nếu sync tự dựng đường xoá riêng thay vì đi qua refresh, bản vá
    bốn trường không bảo vệ được nó — và không ca nào khác phát hiện.
    """
    from unittest.mock import AsyncMock, patch

    CO_DRIFT = "role:officer"

    async def _drift(role_name, template_id):
        co = role_name == CO_DRIFT
        return {
            "has_drift": co,
            "extra_in_db": [[CO_DRIFT, OBJ, ACT, "allow"]] if co else [],
            "missing_in_db": [],
        }

    enf = _enf()
    async with AsyncSessionLocal() as db:
        sv = CasbinPolicyService(db, enf)
        with patch.object(
            CasbinPolicyService, "detect_template_drift",
            new_callable=AsyncMock, side_effect=_drift,
        ), patch.object(
            CasbinPolicyService, "refresh_role_from_template",
            new_callable=AsyncMock,
        ) as refresh:
            refresh.return_value = {"success": True, "policies_removed": 1}
            await sv.sync_all_roles_from_templates(dry_run=False)

    refresh.assert_awaited_once_with(CO_DRIFT, "officer", force=True)


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


# ---------------------------------------------------------------------------
# 5. Nhánh THẤT BẠI phải fail-closed — mã đúng, không audit, không đổi trạng thái
# ---------------------------------------------------------------------------
#
# Mọi ca dưới đây khẳng định MÃ CHÍNH XÁC (409/CONFLICT), không phải
# `status >= 400`. Bản nháp trước dùng `>= 400` và cả ba ca đều xanh GIẢ: một
# ca sai URL nên nhận 404, hai ca kia nhận 500 vì một lỗi khác hẳn. Một phép
# kiểm không phân biệt được nguyên nhân thì không canh được gì.


@pytest.mark.asyncio
async def test_feature_toggle_con_policy_thi_409_va_khong_audit(
    client, admin_token_headers
):
    """Tắt feature mà còn policy chưa xoá -> 409 CONFLICT, KHÔNG ghi audit.

    Kể cả khi policy bị safety-check giữ (`blocked`): hệ quả với người dùng y
    hệt — policy VẪN CÒN nên feature VẪN CHƯA TẮT. Vì thế mock trả
    ``blocked == len(policies_tuples)``: nếu ai đó trừ `blocked` ra khỏi phép
    đếm thì `chua_xoa` về 0 và endpoint báo thành công — đúng đột biến cần bắt.

    Ca này phải ở tầng HTTP vì cổng trung thực nằm ở ROUTER, không ở service.
    """
    from unittest.mock import AsyncMock, patch

    from sqlalchemy import func, select

    from app import models
    from app.services.casbin_service import CasbinPolicyService

    async def _gia(policies, *a, **k):
        return {
            "removed": 0,
            "blocked": len(policies),
            "errors": [],
            "warnings": ["Blocked for safety"],
        }

    async with AsyncSessionLocal() as db:
        truoc = await db.scalar(
            select(func.count()).select_from(models.UserActivityLog)
        )

    with patch.object(
        CasbinPolicyService,
        "remove_policies_batch",
        new_callable=AsyncMock,
        side_effect=_gia,
    ) as gia:
        r = await client.post(
            "/api/admin/roles/role:officer/features/toggle",
            json={"feature_id": "view_leads", "enabled": False},
            headers=admin_token_headers,
        )

    gia.assert_awaited_once()
    assert r.status_code == 409, (
        f"phải 409 CONFLICT; nhận {r.status_code}: {r.text[:200]}"
    )
    assert r.json().get("error_code") == "CONFLICT", r.text[:200]

    async with AsyncSessionLocal() as db:
        sau = await db.scalar(
            select(func.count()).select_from(models.UserActivityLog)
        )
    assert sau == truoc, (
        "KHÔNG được ghi audit 'Disabled feature' khi feature chưa thật sự tắt"
    )


@pytest.mark.asyncio
async def test_xoa_role_that_bai_service_nem_va_giu_nguyen_trang_thai(client):
    """Tầng SERVICE: xoá thất bại -> ném ConflictError, KHÔNG đụng gì.

    Hậu điều kiện chạy TRƯỚC mọi mutation DB/grouping, nên khi nó đỏ thì
    policy còn nguyên VÀ grouping còn nguyên. Grouping là chốt khoá THỨ TỰ:
    thay đổi trên enforcer không rollback được, nên dời phép kiểm xuống sau là
    để lại trạng thái nửa vời.
    """
    from unittest.mock import AsyncMock, patch

    from app.services import role_service
    from app.utils.exceptions import ConflictError

    enf = await _seed_cap_allow_deny()
    # Subject PHẢI đúng dạng `user:<số nguyên>`: STEP 3b chỉ nhận
    # `group[0].startswith("user:")` rồi `int(...)`, nên một subject tuỳ ý
    # (ví dụ "user_probe_thu_hoi") bị BỎ QUA hoàn toàn — chốt khoá thứ tự khi
    # ấy vô hiệu, và đột biến "kiểm muộn" không bị bắt. Đã đo đúng như vậy.
    USER = "user:999999"
    for g in list(enf.get_grouping_policy()):
        if g[0] == USER:
            await enf.remove_grouping_policy(*g)
    await enf.add_grouping_policy(USER, SUB)

    async with AsyncSessionLocal() as db:
        with patch(
            "app.services.casbin_service.xoa_rule_chinh_xac",
            new_callable=AsyncMock,
            return_value=False,
        ):
            with pytest.raises(ConflictError):
                await role_service.delete_role_atomic(db, SUB, enf)

    assert sorted(policy_cua_role(enf, SUB)) == sorted([ALLOW, DENY]), (
        "policy phải còn NGUYÊN khi xoá thất bại"
    )
    assert [USER, SUB] in [list(g) for g in enf.get_grouping_policy()], (
        "grouping phải còn NGUYÊN — hậu điều kiện phải chạy TRƯỚC mutation "
        "grouping, vì thay đổi trên enforcer không rollback được"
    )


@pytest.mark.asyncio
async def test_xoa_role_that_bai_http_tra_409_khong_phai_500(
    client, admin_token_headers
):
    """Tầng HTTP: xoá thất bại -> ĐÚNG 409, không phải 500.

    Router từng bắt mọi `Exception` rồi biến cả ConflictError thành 500. Với
    A01 đó là mất thông tin: "không xoá được vì còn policy" (409, người vận
    hành xử lý được) khác hẳn "lỗi bất ngờ" (500, chỉ biết thử lại).
    """
    from unittest.mock import AsyncMock, patch

    enf = await _seed_cap_allow_deny()

    with patch(
        "app.services.casbin_service.xoa_rule_chinh_xac",
        new_callable=AsyncMock,
        return_value=False,
    ):
        r = await client.delete(
            f"/api/admin/roles/{SUB}", headers=admin_token_headers
        )

    assert r.status_code == 409, f"phải 409; nhận {r.status_code}: {r.text[:200]}"
    assert "deleted successfully" not in r.text
    assert sorted(policy_cua_role(enf, SUB)) == sorted([ALLOW, DENY])


@pytest.mark.asyncio
async def test_xoa_role_thanh_cong_http_2xx_va_callback_khong_no(
    client, admin_token_headers
):
    """Đường THÀNH CÔNG: HTTP 2xx, role biến mất, callback chạy không TypeError.

    Ca này khoá bản vá logging: `_post_commit` chạy SAU `db.commit()`, nên một
    `TypeError` ở dòng log biến endpoint thành 500 cho một việc ĐÃ XẢY RA.
    """
    enf = await _seed_cap_allow_deny()

    r = await client.delete(
        f"/api/admin/roles/{SUB}", headers=admin_token_headers
    )

    assert r.status_code < 300, f"phải 2xx; nhận {r.status_code}: {r.text[:300]}"
    assert policy_cua_role(enf, SUB) == [], "role phải thật sự biến mất"


@pytest.mark.asyncio
async def test_refresh_that_bai_khong_ap_template(client):
    """Xoá thất bại -> KHÔNG được áp template đè lên trạng thái chưa dọn."""
    from unittest.mock import AsyncMock, patch

    enf = await _seed_cap_allow_deny()

    async with AsyncSessionLocal() as db:
        sv = CasbinPolicyService(db, enf)
        with patch(
            "app.services.casbin_service.xoa_rule_chinh_xac",
            new_callable=AsyncMock,
            return_value=False,
        ):
            with patch.object(
                CasbinPolicyService, "apply_template_to_role",
                new_callable=AsyncMock,
            ) as ap:
                kq = await sv.refresh_role_from_template(
                    role=SUB, template_id="lead_viewer", force=True
                )

    assert kq["success"] is False, f"phải báo thất bại: {kq}"
    assert kq.get("policies_xoa_that_bai"), "phải nêu rõ rule nào không xoá được"
    ap.assert_not_awaited()
