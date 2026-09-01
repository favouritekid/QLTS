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
import asyncio

import pytest

from app.database import AsyncSessionLocal
from app.main import fastapi_app
from app.services.casbin_service import (
    CasbinPolicyService,
    chuan_hoa_rule,
    policy_cua_role,
)

SUB = "role:thu_hoi_probe"
OBJ = "/api/thu_hoi_probe/*"
ACT = "GET"
ALLOW = [SUB, OBJ, ACT, "allow"]
DENY = [SUB, OBJ, ACT, "deny"]
# Đường request THẬT mà người dùng gõ, khác với `OBJ` là mẫu trong policy.
# `enforce` phải được hỏi bằng đường thật thì mới nói lên điều gì. Đã đo trên
# `auth_model.conf`: allow+deny -> False, chỉ còn allow -> True.
DUONG_THAT = "/api/thu_hoi_probe/1"


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
    hệt — policy VẪN CÒN nên feature VẪN CHƯA TẮT.

    Mock trả về ĐÚNG hình dạng thật của ``remove_policies_batch``: rule bị
    ``blocked`` thì vẫn nằm trong enforcer, nên nó phải có mặt trong
    ``con_song``. Nếu ai đó lọc `blocked` ra khỏi `con_song` thì cổng mở và
    endpoint báo thành công — đúng đột biến cần bắt.

    Mock KHÔNG được thiếu `con_song`/`an_toan`: thiếu thì router rơi về mặc
    định fail-closed và vẫn ra 409, nghĩa là ca kiểm xanh vì một lý do khác
    hẳn thứ nó định canh.

    Ca này phải ở tầng HTTP vì cổng trung thực nằm ở ROUTER, không ở service.
    """
    from unittest.mock import AsyncMock, patch

    from sqlalchemy import func, select

    from app import models
    from app.services.casbin_service import CasbinPolicyService

    async def _gia(policies, *a, **k):
        chuan = [chuan_hoa_rule(p) for p in policies]
        return {
            "removed": 0,
            "blocked": len(chuan),
            "errors": [],
            "warnings": ["Blocked for safety"],
            # bị chặn = chưa xoá = CÒN trong enforcer
            "con_song": chuan,
            "deny_chua_cham": [],
            "an_toan": True,
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


# ---------------------------------------------------------------------------
# 6. THẤT BẠI HỖN HỢP — xoá allow hụt thì TUYỆT ĐỐI không chạm deny
# ---------------------------------------------------------------------------
#
# Đây là lỗ hổng mà mục 5 KHÔNG bắt được. Mọi ca ở mục 5 cho MỌI lượt xoá đều
# hụt, nên vòng lặp phẳng "hụt rồi vẫn chạy tiếp" trông vô hại. Ca thật nguy
# hiểm là hỗn hợp: `allow` xoá hụt mà `deny` xoá được.
#
# Khi ấy hàm báo `success=False` — nghe như đã an toàn — nhưng trạng thái để
# lại là CHỈ CÒN ALLOW, tức quyền đi từ TỪ CHỐI sang CHO PHÉP. Đo trên enforcer
# thật: `policies_removed=1`, `remaining=[allow]`, `enforce=True`. Thất bại mà
# lại NỚI quyền thì nguy hiểm hơn hẳn không làm gì.
#
# Vì thế patch dưới đây phải BẤT ĐỐI XỨNG: `allow` luôn hụt, còn `deny` thì
# XOÁ ĐƯỢC THẬT nếu bị gọi. Nếu làm cho `deny` cũng hụt thì ca kiểm không phân
# biệt nổi "không chạm tới deny" với "có chạm mà không xoá nổi" — xanh giả.


def _patch_hut_non_deny(ghi_nhan):
    """allow (và mọi non-deny) xoá HỤT; deny thì xoá ĐƯỢC THẬT nếu bị gọi."""

    async def _gia(enforcer, rule):
        r = chuan_hoa_rule(rule)
        ghi_nhan.append(r)
        if r[3] == "deny":
            return await enforcer.remove_policy(*r)
        return False

    return _gia


def _khang_dinh_deny_nguyen_ven(enf, ghi_nhan, nhan):
    """Ba khẳng định độc lập cho cùng một bất biến, ở ba mức khác nhau."""
    con_lai = policy_cua_role(enf, SUB)
    # HỆ QUẢ trước, cơ chế sau. `enforce` là thứ người dùng thật sự chạm phải;
    # để nó nổ đầu tiên thì thông điệp lỗi nói thẳng ra rằng quyền vừa bị MỞ,
    # thay vì chỉ nói một hàng policy đã biến mất.
    assert enf.enforce(SUB, DUONG_THAT, ACT) is False, (
        f"{nhan}: enforce phải VẪN là False. True nghĩa là deny đã mất trong "
        f"khi allow còn sống — đúng cửa fail-open. Còn lại: {con_lai!r}"
    )
    assert DENY in con_lai, (
        f"{nhan}: deny bị xoá sau khi allow xoá hụt — quyền vừa được MỞ"
    )
    assert not any(r[3] == "deny" for r in ghi_nhan), (
        f"{nhan}: deny KHÔNG được chạm tới; đã gọi xoá với {ghi_nhan!r}"
    )


@pytest.mark.asyncio
async def test_refresh_hon_hop_khong_cham_deny(client):
    """refresh: allow xoá hụt -> dừng, deny nguyên vẹn, template không được áp."""
    from unittest.mock import AsyncMock, patch

    enf = await _seed_cap_allow_deny()
    goi = []

    async with AsyncSessionLocal() as db:
        sv = CasbinPolicyService(db, enf)
        with patch(
            "app.services.casbin_service.xoa_rule_chinh_xac",
            new_callable=AsyncMock,
            side_effect=_patch_hut_non_deny(goi),
        ):
            with patch.object(
                CasbinPolicyService, "apply_template_to_role",
                new_callable=AsyncMock,
            ) as ap:
                kq = await sv.refresh_role_from_template(
                    role=SUB, template_id="lead_viewer", force=True
                )

    _khang_dinh_deny_nguyen_ven(enf, goi, "refresh")
    assert kq["success"] is False, f"phải báo thất bại: {kq}"
    assert kq.get("an_toan") is False, (
        f"phải nêu rõ pha deny bị chặn, không chỉ 'thất bại chung': {kq}"
    )
    assert kq.get("policies_deny_chua_cham") == [DENY], (
        f"phải liệt kê đúng rule deny chưa bị chạm: {kq}"
    )
    ap.assert_not_awaited()


@pytest.mark.asyncio
async def test_xoa_role_hon_hop_khong_cham_deny(client):
    """delete_role_atomic: allow xoá hụt -> ConflictError, deny nguyên vẹn."""
    from unittest.mock import AsyncMock, patch

    from app.services import role_service
    from app.utils.exceptions import ConflictError

    enf = await _seed_cap_allow_deny()
    goi = []

    async with AsyncSessionLocal() as db:
        with patch(
            "app.services.casbin_service.xoa_rule_chinh_xac",
            new_callable=AsyncMock,
            side_effect=_patch_hut_non_deny(goi),
        ):
            with pytest.raises(ConflictError) as ex:
                await role_service.delete_role_atomic(db, SUB, enf)

    _khang_dinh_deny_nguyen_ven(enf, goi, "delete_role")
    assert "MỞ quyền" in str(ex.value), (
        f"thông điệp phải nói rõ vì sao deny không bị chạm: {ex.value}"
    )


@pytest.mark.asyncio
async def test_xoa_hang_loat_hon_hop_khong_cham_deny(client):
    """remove_policies_batch: cùng bất biến — đường thứ BA cùng root.

    Đường này không nằm trong hai chỗ được chỉ ra ban đầu, nhưng nó dùng đúng
    vòng lặp phẳng ấy và phục vụ cổng bật/tắt feature, nên bỏ sót nó là vá một
    nhánh còn ba.
    """
    from unittest.mock import AsyncMock, patch

    enf = await _seed_cap_allow_deny()
    goi = []

    async with AsyncSessionLocal() as db:
        with patch(
            "app.services.casbin_service.xoa_rule_chinh_xac",
            new_callable=AsyncMock,
            side_effect=_patch_hut_non_deny(goi),
        ):
            kq = await CasbinPolicyService(db, enf).remove_policies_batch(
                [ALLOW, DENY], validate=False, force=True
            )

    _khang_dinh_deny_nguyen_ven(enf, goi, "batch")
    assert kq["an_toan"] is False, f"phải báo pha deny bị chặn: {kq}"
    assert kq["removed"] == 0, f"không xoá được gì thì counter phải là 0: {kq}"
    assert kq["con_song"] == [ALLOW], f"phải đo đúng rule còn sống: {kq}"
    assert kq["deny_chua_cham"] == [DENY], f"phải liệt kê deny bị bỏ qua: {kq}"


@pytest.mark.asyncio
async def test_cong_do_enforcer_chu_khong_tin_gia_tri_tra_ve(client):
    """Handler báo ĐÃ XOÁ nhưng rule vẫn còn -> cổng VẪN phải chặn pha deny.

    Ca này phân biệt bản vá đang có với một bản vá trông rất giống: cổng dựng
    trên GIÁ TRỊ TRẢ VỀ của từng lượt xoá thay vì trên trạng thái enforcer.
    Bản ấy xanh ở mọi ca hỗn hợp khác, vì ở đó handler trả về đúng sự thật.

    Nó chỉ vỡ đúng ở đây: handler báo True trong khi rule còn sống. Đó không
    phải giả thuyết xa vời — `remove_policy` trả True theo bộ nhớ trong khi lượt
    ghi xuống adapter hỏng là đúng hình dạng ấy, và cả loạt lỗi trong tệp này
    đều sinh ra từ việc tin một giá trị trả về thay vì đo thứ nó nói về.

    Chú ý phần tương phản: `removed` nói 1, `con_song` nói vẫn còn. Cổng nghe
    theo `con_song`.
    """
    from unittest.mock import AsyncMock, patch

    enf = await _seed_cap_allow_deny()
    goi = []

    async def _noi_doi(enforcer, rule):
        r = chuan_hoa_rule(rule)
        goi.append(r)
        if r[3] == "deny":
            return await enforcer.remove_policy(*r)
        return True  # nói dối: báo đã xoá mà không hề xoá

    async with AsyncSessionLocal() as db:
        with patch(
            "app.services.casbin_service.xoa_rule_chinh_xac",
            new_callable=AsyncMock,
            side_effect=_noi_doi,
        ):
            kq = await CasbinPolicyService(db, enf).remove_policies_batch(
                [ALLOW, DENY], validate=False, force=True
            )

    _khang_dinh_deny_nguyen_ven(enf, goi, "handler nói dối")
    assert kq["removed"] == 1, f"counter đang chép lại lời nói dối: {kq}"
    assert kq["con_song"] == [ALLOW], (
        f"`con_song` phải ĐO enforcer, nên vẫn thấy allow: {kq}"
    )
    assert kq["an_toan"] is False, (
        f"cổng phải chặn vì allow còn sống, bất kể handler khai gì: {kq}"
    )


@pytest.mark.asyncio
async def test_feature_toggle_deny_chua_cham_thi_409(client, admin_token_headers):
    """Tầng HTTP: service báo `an_toan=False` -> phải 409, dù `con_song` rỗng.

    Hai trường này canh hai chuyện khác nhau. `con_song` nói "còn rule chưa
    xoá"; `an_toan` nói "nhóm rule mới bị xoá MỘT PHẦN, phần bỏ lại là deny".
    Một router chỉ nhìn `con_song` sẽ trả 200 cho đúng ca fail-open — nên ca
    này cố tình để `con_song` rỗng.
    """
    from unittest.mock import AsyncMock, patch

    from app.services.casbin_service import CasbinPolicyService

    async def _gia(policies, *a, **k):
        return {
            "removed": 1,
            "blocked": 0,
            "errors": ["DỪNG fail-closed"],
            "warnings": [],
            "con_song": [],
            "deny_chua_cham": [DENY],
            "an_toan": False,
        }

    with patch.object(
        CasbinPolicyService,
        "remove_policies_batch",
        new_callable=AsyncMock,
        side_effect=_gia,
    ):
        r = await client.post(
            "/api/admin/roles/role:officer/features/toggle",
            json={"feature_id": "view_leads", "enabled": False},
            headers=admin_token_headers,
        )

    assert r.status_code == 409, (
        f"phải 409 khi pha deny bị chặn; nhận {r.status_code}: {r.text[:200]}"
    )
    assert r.json().get("error_code") == "CONFLICT", r.text[:200]


# ---------------------------------------------------------------------------
# 7. RANH GIỚI model ↔ PostgreSQL — "vắng khỏi model" KHÔNG phải "đã thu hồi"
# ---------------------------------------------------------------------------
#
# Mục 6 đóng cửa fail-open TRONG BỘ NHỚ, nhưng chưa đóng ở ranh giới bền vững.
# PyCasbin gỡ rule khỏi model TRƯỚC rồi mới gọi adapter. Adapter hỏng thì hàm
# trả `False` mà model đã sạch. Đã đo trực tiếp trên PyCasbin:
#
#     remove_policy(allow) -> False
#     MODEL   = [deny]            <- mất allow
#     DURABLE = [allow, deny]     <- hàng còn nguyên
#
# Một cổng chỉ ĐO MODEL sẽ thấy "allow đã xong" rồi đi xoá `deny` — mà `deny`
# xoá được thật. Kết cục trong CSDL: chỉ còn `allow`. Sau reload hoặc trên
# worker khác, quyền mở lại, lần này BỀN VỮNG.
#
# Ca mục 6 `test_cong_do_enforcer_...` canh chiều NGƯỢC LẠI (handler trả True
# mà model còn rule). Hai chiều là hai lỗi khác nhau; chiều dưới đây mới là
# chiều PyCasbin thật sự đi.


@pytest.mark.asyncio
async def test_adapter_hong_model_sach_van_phai_chan_pha_deny(client):
    """Model sạch + handler trả False -> VẪN phải chặn pha deny."""
    from unittest.mock import AsyncMock, patch

    enf = await _seed_cap_allow_deny()
    goi = []
    # Mô phỏng hàng thật trong PostgreSQL, tách khỏi model bộ nhớ.
    ben_vung = {tuple(ALLOW), tuple(DENY)}

    async def _adapter_hong(enforcer, rule):
        r = chuan_hoa_rule(rule)
        goi.append(r)
        # PyCasbin gỡ khỏi model TRƯỚC, trong MỌI trường hợp.
        await enforcer.remove_policy(*r)
        if r[3] == "deny":
            ben_vung.discard(tuple(r))
            return True
        # non-deny: ghi xuống CSDL hỏng -> trả False, hàng CÒN NGUYÊN
        return False

    async with AsyncSessionLocal() as db:
        with patch(
            "app.services.casbin_service.xoa_rule_chinh_xac",
            new_callable=AsyncMock,
            side_effect=_adapter_hong,
        ):
            kq = await CasbinPolicyService(db, enf).remove_policies_batch(
                [ALLOW, DENY], validate=False, force=True
            )

    assert not any(r[3] == "deny" for r in goi), (
        f"deny KHÔNG được chạm tới khi allow chưa xác nhận thu hồi; "
        f"đã gọi xoá với {goi!r}"
    )
    assert kq["an_toan"] is False, (
        f"handler trả False là cách PyCasbin báo adapter hỏng — phải chặn, "
        f"bất kể model trông sạch: {kq}"
    )
    assert kq["con_song"] == [ALLOW], (
        f"allow phải bị xếp vào 'chưa xác nhận', không phải 'đã xoá': {kq}"
    )
    assert ben_vung == {tuple(ALLOW), tuple(DENY)}, (
        f"CSDL phải còn NGUYÊN cả cặp. Nếu chỉ còn allow thì sau reload quyền "
        f"mở lại và mở BỀN VỮNG. Hiện có: {ben_vung!r}"
    )


@pytest.mark.asyncio
async def test_pha_deny_that_bai_khong_duoc_bao_thanh_cong(client):
    """Pha 2 hỏng thì KHÔNG mở quyền, nhưng cũng KHÔNG được báo xong."""
    from unittest.mock import AsyncMock, patch

    enf = await _seed_cap_allow_deny()

    async def _deny_hong(enforcer, rule):
        r = chuan_hoa_rule(rule)
        await enforcer.remove_policy(*r)
        return r[3] != "deny"  # allow: xác nhận thật; deny: adapter hỏng

    async with AsyncSessionLocal() as db:
        with patch(
            "app.services.casbin_service.xoa_rule_chinh_xac",
            new_callable=AsyncMock,
            side_effect=_deny_hong,
        ):
            kq = await CasbinPolicyService(db, enf).remove_policies_batch(
                [ALLOW, DENY], validate=False, force=True
            )

    # Không có cửa fail-open: pha 1 sạch nên không còn allow nào để deny che.
    assert kq["an_toan"] is True, f"pha 1 sạch thì không có cửa mở: {kq}"
    # Nhưng việc CHƯA XONG, và người gọi phải thấy điều đó.
    assert kq["con_song"] == [DENY], (
        f"deny xoá hụt phải vào `con_song` để người gọi báo thất bại — "
        f"fail-closed không phải là lý do để tuyên bố thành công: {kq}"
    )


@pytest.mark.asyncio
async def test_rule_vang_san_la_idempotent_khong_chan_pha_deny(client):
    """Rule vốn đã vắng: không có gì để thu hồi, nên KHÔNG chặn pha sau."""
    enf = _enf()
    for p in policy_cua_role(enf, SUB):
        await enf.remove_policy(*p)
    await enf.add_policy(*DENY)  # chỉ deny, KHÔNG có allow
    assert policy_cua_role(enf, SUB) == [DENY]

    async with AsyncSessionLocal() as db:
        kq = await CasbinPolicyService(db, enf).remove_policies_batch(
            [ALLOW, DENY], validate=False, force=True
        )

    assert kq["vang_san"] == [ALLOW], (
        f"allow vắng sẵn phải xếp riêng, không phải thất bại: {kq}"
    )
    assert kq["con_song"] == [], f"không có gì chưa xác nhận: {kq}"
    assert kq["an_toan"] is True, (
        f"không có allow nào sống sót thì không có cửa mở để chặn: {kq}"
    )
    assert policy_cua_role(enf, SUB) == [], f"deny phải được xoá: {kq}"


@pytest.mark.asyncio
async def test_callback_nem_loi_thi_khong_cham_deny(client):
    """Handler ném lỗi cũng là 'chưa xác nhận' -> chặn pha deny."""
    from unittest.mock import AsyncMock, patch

    enf = await _seed_cap_allow_deny()
    goi = []

    async def _no(enforcer, rule):
        r = chuan_hoa_rule(rule)
        goi.append(r)
        raise RuntimeError("adapter mất kết nối giữa chừng")

    async with AsyncSessionLocal() as db:
        with patch(
            "app.services.casbin_service.xoa_rule_chinh_xac",
            new_callable=AsyncMock,
            side_effect=_no,
        ):
            kq = await CasbinPolicyService(db, enf).remove_policies_batch(
                [ALLOW, DENY], validate=False, force=True
            )

    _khang_dinh_deny_nguyen_ven(enf, goi, "handler ném lỗi")
    assert kq["an_toan"] is False, f"ném lỗi phải chặn pha deny: {kq}"
    assert kq["errors"], f"lỗi phải được nêu ra, không nuốt im lặng: {kq}"


@pytest.mark.asyncio
async def test_xoa_role_adapter_hong_model_sach_van_nem_conflict(client):
    """delete_role: model SẠCH mà chưa xác nhận -> vẫn phải ném ConflictError.

    Hậu điều kiện cũ chỉ đọc `policy_cua_role`, tức MODEL. Ca này dựng đúng
    hoàn cảnh nó mù: role CHỈ có `allow`, không có `deny`, nên cổng fail-open
    không kích hoạt (không có pha 2 để chặn); fake dọn sạch model rồi trả
    False. Đọc model thì thấy "role đã sạch" và báo `deleted successfully`,
    trong khi hàng `allow` vẫn nằm trong PostgreSQL.

    Khẳng định `policy_cua_role(...) == []` ở cuối là phần quan trọng: nó
    chứng minh guard KHÔNG dựa vào model, vì model đúng là rỗng thật.
    """
    from unittest.mock import AsyncMock, patch

    from app.services import role_service
    from app.utils.exceptions import ConflictError

    enf = _enf()
    for p in policy_cua_role(enf, SUB):
        await enf.remove_policy(*p)
    await enf.add_policy(*ALLOW)  # CHỈ allow — không có deny
    assert policy_cua_role(enf, SUB) == [ALLOW]

    async def _adapter_hong(enforcer, rule):
        await enforcer.remove_policy(*chuan_hoa_rule(rule))
        return False

    async with AsyncSessionLocal() as db:
        with patch(
            "app.services.casbin_service.xoa_rule_chinh_xac",
            new_callable=AsyncMock,
            side_effect=_adapter_hong,
        ):
            with pytest.raises(ConflictError) as ex:
                await role_service.delete_role_atomic(db, SUB, enf)

    assert "chưa xác nhận" in str(ex.value), (
        f"thông điệp phải phân biệt 'còn trong model' với 'chưa xác nhận thu "
        f"hồi': {ex.value}"
    )
    assert policy_cua_role(enf, SUB) == [], (
        "model ĐÚNG LÀ rỗng — nên guard không thể dựa vào model mà vẫn phải nổ"
    )


# ---------------------------------------------------------------------------
# 8. LƯỢT RETRY — model lệch CSDL là DI CHỨNG của chính lượt hỏng trước
# ---------------------------------------------------------------------------
#
# Mục 7 đóng lượt hỏng ĐẦU TIÊN. Nhưng lượt hỏng ấy để lại model và CSDL lệch
# nhau: PyCasbin đã gỡ `allow` khỏi model rồi mới gọi adapter, adapter hỏng nên
# hàng vẫn nằm trong CSDL. `refresh_role_from_template` và `delete_role_atomic`
# dựng danh sách rule TỪ MODEL, nên lượt RETRY chỉ nhìn thấy `deny`. Đo được:
#
#     lượt 1:  an_toan=False  MODEL=[deny]  DURABLE=[allow, deny]
#     lượt 2:  rules=[deny]   an_toan=True  MODEL=[]  DURABLE=[allow]
#
# Lượt hai "thành công" và mở quyền bền vững. Cùng root làm `vang_san` không an
# toàn: "vắng khỏi model" bị hiểu là idempotent, trong khi nó là di chứng.
#
# Cách đóng: đồng bộ model từ CSDL TRƯỚC mỗi thao tác nhóm, và trước cả lúc
# dựng danh sách. Đồng bộ hỏng thì dừng trước mọi mutation.


def _go_khoi_model_thoi(enf, r):
    """Gỡ rule khỏi MODEL, KHÔNG chạm adapter.

    Đúng hình dạng PyCasbin để lại khi ghi xuống CSDL thất bại — đã đo:
    `remove_policy` trả False, MODEL mất rule, DURABLE còn nguyên.
    """
    return enf.get_model().remove_policy("p", "p", list(r))


@pytest.mark.asyncio
async def test_hai_luot_retry_khong_xoa_deny_khi_allow_con_ben_vung(client):
    """Lượt 1 hỏng làm model quên allow; lượt 2 KHÔNG được vì thế mà xoá deny."""
    from unittest.mock import AsyncMock, patch

    enf = await _seed_cap_allow_deny()

    # ── LƯỢT 1: adapter hỏng với non-deny ──────────────────────────────────
    goi1 = []

    async def _luot1(enforcer, rule):
        r = chuan_hoa_rule(rule)
        goi1.append(r)
        _go_khoi_model_thoi(enforcer, r)
        return r[3] == "deny"  # deny xoá được; allow: adapter hỏng

    async with AsyncSessionLocal() as db:
        with patch(
            "app.services.casbin_service.xoa_rule_chinh_xac",
            new_callable=AsyncMock,
            side_effect=_luot1,
        ):
            kq1 = await CasbinPolicyService(db, enf).remove_policies_batch(
                [ALLOW, DENY], validate=False, force=True
            )

    assert kq1["an_toan"] is False, f"lượt 1 phải chặn: {kq1}"
    assert not any(r[3] == "deny" for r in goi1), "lượt 1 không được chạm deny"
    assert not enf.has_policy(*ALLOW), (
        "tiền đề của ca này: model PHẢI đã quên allow sau lượt hỏng. Nếu còn "
        "thì ca kiểm không dựng được cái bẫy nó định canh."
    )

    # ── LƯỢT 2: adapter hoạt động lại ──────────────────────────────────────
    goi2 = []

    async def _luot2(enforcer, rule):
        r = chuan_hoa_rule(rule)
        goi2.append(r)
        return await enforcer.remove_policy(*r)

    async with AsyncSessionLocal() as db:
        with patch(
            "app.services.casbin_service.xoa_rule_chinh_xac",
            new_callable=AsyncMock,
            side_effect=_luot2,
        ):
            kq2 = await CasbinPolicyService(db, enf).remove_policies_batch(
                [ALLOW, DENY], validate=False, force=True
            )

    assert goi2, "lượt 2 phải thật sự làm gì đó"
    assert goi2[0][3] != "deny", (
        f"lượt retry phải xử lý allow TRƯỚC deny. Thứ tự nhận được {goi2!r} "
        f"nghĩa là cổng đồng bộ đã không chạy."
    )
    assert kq2["vang_san"] == [], (
        f"allow KHÔNG được xếp 'vắng sẵn' — nó vắng trong model vì lượt trước "
        f"hỏng, chứ không phải vì CSDL đã sạch: {kq2}"
    )
    assert ALLOW in kq2["da_xoa"], f"allow phải được thu hồi thật: {kq2}"

    # Trạng thái BỀN VỮNG cuối cùng — đọc lại từ CSDL, không tin model.
    await enf.load_policy()
    assert policy_cua_role(enf, SUB) == [], (
        f"CSDL phải sạch. Còn đúng [allow] nghĩa là lượt retry vừa mở quyền "
        f"BỀN VỮNG. Hiện có: {policy_cua_role(enf, SUB)!r}"
    )


@pytest.mark.asyncio
async def test_hai_luot_retry_delete_role_thay_lai_allow_ben_vung(client):
    """delete_role dựng danh sách TỪ MODEL — retry phải thấy lại allow."""
    from unittest.mock import AsyncMock, patch

    from app.services import role_service
    from app.utils.exceptions import ConflictError

    enf = await _seed_cap_allow_deny()

    async def _luot1(enforcer, rule):
        r = chuan_hoa_rule(rule)
        _go_khoi_model_thoi(enforcer, r)
        return r[3] == "deny"

    async with AsyncSessionLocal() as db:
        with patch(
            "app.services.casbin_service.xoa_rule_chinh_xac",
            new_callable=AsyncMock,
            side_effect=_luot1,
        ):
            with pytest.raises(ConflictError):
                await role_service.delete_role_atomic(db, SUB, enf)

    assert not enf.has_policy(*ALLOW), "tiền đề: model đã quên allow"
    assert enf.has_policy(*DENY), "deny chưa bị chạm tới"

    # LƯỢT 2 — không patch gì cả, đường thật.
    async with AsyncSessionLocal() as db:
        await role_service.delete_role_atomic(db, SUB, enf)

    await enf.load_policy()
    assert policy_cua_role(enf, SUB) == [], (
        f"CSDL phải sạch sau retry. Nếu còn [allow] thì `role_has_policies` và "
        f"`policies_to_remove` vẫn đang đọc model lệch: "
        f"{policy_cua_role(enf, SUB)!r}"
    )


@pytest.mark.asyncio
async def test_hai_luot_feature_toggle_retry_khong_tra_200_gia(
    client, admin_token_headers
):
    """Retry của feature-toggle KHÔNG được trả 200 khi CSDL còn policy.

    Không mock service: cả hai lượt đi qua đường HTTP thật. Lượt 1 chỉ hỏng ở
    tầng adapter. Nếu thiếu cổng đồng bộ, lượt 2 thấy model trống, xếp mọi rule
    vào `vang_san`, và trả 200 cho một hàng `allow` vẫn nằm trong PostgreSQL.
    """
    from unittest.mock import AsyncMock, patch

    from app.casbin_config.policy_templates import FEATURE_MAP

    enf = _enf()
    rules = [
        [p["subject"].replace("{role}", SUB), p["object"], p["action"], "allow"]
        for p in FEATURE_MAP["view_leads"]["policies"]
    ]
    for p in policy_cua_role(enf, SUB):
        await enf.remove_policy(*p)
    for r in rules:
        await enf.add_policy(*r)
    assert sorted(policy_cua_role(enf, SUB)) == sorted(rules)

    async def _adapter_hong(enforcer, rule):
        r = chuan_hoa_rule(rule)
        _go_khoi_model_thoi(enforcer, r)
        return False

    with patch(
        "app.services.casbin_service.xoa_rule_chinh_xac",
        new_callable=AsyncMock,
        side_effect=_adapter_hong,
    ):
        r1 = await client.post(
            f"/api/admin/roles/{SUB}/features/toggle",
            json={"feature_id": "view_leads", "enabled": False},
            headers=admin_token_headers,
        )
    assert r1.status_code == 409, (
        f"lượt 1 phải 409; nhận {r1.status_code}: {r1.text[:200]}"
    )
    assert policy_cua_role(enf, SUB) == [], "tiền đề: model đã bị dọn trống"

    # LƯỢT 2 — đường thật, adapter hoạt động.
    r2 = await client.post(
        f"/api/admin/roles/{SUB}/features/toggle",
        json={"feature_id": "view_leads", "enabled": False},
        headers=admin_token_headers,
    )

    await enf.load_policy()
    con_lai = policy_cua_role(enf, SUB)
    assert con_lai == [], (
        f"CSDL phải sạch sau retry. HTTP trả {r2.status_code} trong khi còn "
        f"{con_lai!r} là 200 GIẢ — người vận hành tin feature đã tắt."
    )
    assert r2.status_code < 300, (
        f"lượt 2 phải thành công thật; nhận {r2.status_code}: {r2.text[:200]}"
    )


@pytest.mark.asyncio
async def test_dong_bo_that_bai_thi_khong_cham_rule_nao(client):
    """Không đọc được CSDL thì DỪNG trước mọi mutation, không đoán."""
    from unittest.mock import AsyncMock, patch

    enf = await _seed_cap_allow_deny()
    goi = []

    async def _ghi_nhan(enforcer, rule):
        goi.append(chuan_hoa_rule(rule))
        return True

    async with AsyncSessionLocal() as db:
        with patch.object(
            enf, "load_policy",
            new_callable=AsyncMock,
            side_effect=RuntimeError("mất kết nối CSDL"),
        ):
            with patch(
                "app.services.casbin_service.xoa_rule_chinh_xac",
                new_callable=AsyncMock,
                side_effect=_ghi_nhan,
            ):
                kq = await CasbinPolicyService(db, enf).remove_policies_batch(
                    [ALLOW, DENY], validate=False, force=True
                )

    assert goi == [], f"KHÔNG được chạm rule nào khi chưa đọc được CSDL: {goi!r}"
    assert kq["dong_bo"] is False, f"phải nêu rõ đồng bộ hỏng: {kq}"
    assert kq["an_toan"] is False, f"đồng bộ hỏng là fail-closed: {kq}"
    assert kq["con_song"] == [ALLOW, DENY], (
        f"chưa chạm gì thì MỌI rule đều còn 'chưa xác nhận thu hồi': {kq}"
    )
    assert any("đồng bộ" in e for e in kq["errors"]), (
        f"lý do phải tới được người vận hành, không nuốt im lặng: {kq}"
    )
    assert sorted(policy_cua_role(enf, SUB)) == sorted([ALLOW, DENY])


@pytest.mark.asyncio
async def test_hai_luot_retry_refresh_thay_lai_allow_ben_vung(client):
    """refresh cũng dựng danh sách TỪ MODEL — retry phải thấy lại allow.

    `refresh_role_from_template` tự đồng bộ rồi mới dựng `current_policies`, và
    truyền `da_dong_bo=True` nên helper KHÔNG đồng bộ lần nữa. Nghĩa là cổng
    của refresh là cổng DUY NHẤT trên đường này — bỏ nó thì không ai đỡ.
    """
    from unittest.mock import AsyncMock, patch

    enf = await _seed_cap_allow_deny()

    async def _luot1(enforcer, rule):
        r = chuan_hoa_rule(rule)
        _go_khoi_model_thoi(enforcer, r)
        return r[3] == "deny"

    async with AsyncSessionLocal() as db:
        sv = CasbinPolicyService(db, enf)
        with patch(
            "app.services.casbin_service.xoa_rule_chinh_xac",
            new_callable=AsyncMock,
            side_effect=_luot1,
        ):
            with patch.object(
                CasbinPolicyService, "apply_template_to_role",
                new_callable=AsyncMock,
            ):
                kq1 = await sv.refresh_role_from_template(
                    role=SUB, template_id="lead_viewer", force=True
                )

    assert kq1["success"] is False, f"lượt 1 phải thất bại: {kq1}"
    assert not enf.has_policy(*ALLOW), "tiền đề: model đã quên allow"

    goi2 = []

    async def _luot2(enforcer, rule):
        r = chuan_hoa_rule(rule)
        goi2.append(r)
        return await enforcer.remove_policy(*r)

    async with AsyncSessionLocal() as db:
        sv = CasbinPolicyService(db, enf)
        with patch(
            "app.services.casbin_service.xoa_rule_chinh_xac",
            new_callable=AsyncMock,
            side_effect=_luot2,
        ):
            with patch.object(
                CasbinPolicyService, "apply_template_to_role",
                new_callable=AsyncMock,
                return_value={"added": 0, "warnings": []},
            ):
                await sv.refresh_role_from_template(
                    role=SUB, template_id="lead_viewer", force=True
                )

    assert goi2, "lượt 2 phải thật sự làm gì đó"
    assert goi2[0][3] != "deny", (
        f"retry phải xử lý allow TRƯỚC deny; thứ tự {goi2!r} nghĩa là cổng "
        f"đồng bộ của refresh đã không chạy"
    )
    await enf.load_policy()
    assert policy_cua_role(enf, SUB) == [], (
        f"CSDL phải sạch sau retry; còn {policy_cua_role(enf, SUB)!r}"
    )


# ---------------------------------------------------------------------------
# 9. CẠNH TRANH — enforcer là đối tượng DÙNG CHUNG
# ---------------------------------------------------------------------------
#
# Mục 7 và 8 đóng các lỗi TUẦN TỰ. Nhưng `request.app.state.enforcer` là MỘT
# đối tượng cho mọi request, và không có lock thì hai coroutine đan nhau vẫn mở
# được quyền dù từng đường đã fail-closed:
#
#     xoá ĐƠN gỡ `allow` khỏi model rồi hỏng ở adapter;
#     thao tác NHÓM đang chạy song song thấy `allow` vắng -> xếp `vang_san`
#     -> đi tiếp và xoá `deny`.
#
#     group_result: an_toan=True   vang_san=[allow]
#     durable: [allow]             FAIL_OPEN
#
# Nhóm báo AN TOÀN trong khi PostgreSQL cuối cùng chỉ còn `allow`.
#
# Lịch trình dưới đây tái hiện đúng thứ tự ấy: T2 vào vùng tới hạn rồi nhường
# lượt cho T1. Barrier có TIMEOUT chứ không chờ vô hạn — chờ vô hạn thì khi lock
# hoạt động đúng, T1 bị chặn và ca kiểm sẽ TREO thay vì xanh.


@pytest.mark.asyncio
async def test_canh_tranh_xoa_don_khong_duoc_bien_allow_thanh_vang_san(client):
    """Xoá ĐƠN hỏng chen giữa thao tác NHÓM: deny phải KHÔNG bị chạm."""
    from unittest.mock import AsyncMock, patch

    from app.services import casbin_service

    enf = await _seed_cap_allow_deny()
    that_remove = enf.remove_policy
    that_sync = casbin_service.dong_bo_tu_nguon_ben_vung

    goi = []
    t2_vao_vung = asyncio.Event()
    t1_xong = asyncio.Event()

    async def _remove_gia(*rule):
        r = chuan_hoa_rule(list(rule))
        goi.append(r)
        if r[3] == "deny":
            return await that_remove(*rule)
        # non-deny: PyCasbin gỡ khỏi model TRƯỚC rồi adapter hỏng
        _go_khoi_model_thoi(enf, r)
        return False

    async def _sync_hook(enforcer):
        kq = await that_sync(enforcer)
        # Đã vào vùng tới hạn (nếu có lock thì đang GIỮ lock). Nhường lượt.
        t2_vao_vung.set()
        try:
            await asyncio.wait_for(t1_xong.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass  # có lock: T1 bị chặn — đúng như mong đợi
        return kq

    async def _xoa_don():
        """Đường xoá ĐƠN thật: đi qua `xoa_rule_chinh_xac`, chịu cùng lock."""
        await t2_vao_vung.wait()
        await casbin_service.xoa_rule_chinh_xac(enf, ALLOW)
        t1_xong.set()

    with patch.object(enf, "remove_policy", side_effect=_remove_gia):
        with patch(
            "app.services.casbin_service.dong_bo_tu_nguon_ben_vung",
            new_callable=AsyncMock,
            side_effect=_sync_hook,
        ):
            t1 = asyncio.create_task(_xoa_don(), name="T1-xoa-don")
            async with AsyncSessionLocal() as db:
                kq = await CasbinPolicyService(db, enf).remove_policies_batch(
                    [ALLOW, DENY], validate=False, force=True
                )
            await asyncio.wait_for(t1, timeout=5)

    assert not any(r[3] == "deny" for r in goi), (
        f"deny KHÔNG được chạm tới. Đã gọi xoá với {goi!r} — nghĩa là thao tác "
        f"nhóm đã coi `allow` là 'vắng sẵn' vì lượt xoá đơn vừa gỡ nó khỏi "
        f"model, rồi đi tiếp xoá deny."
    )
    assert kq["vang_san"] == [], (
        f"`allow` KHÔNG được xếp 'vắng sẵn': nó vắng vì một thao tác KHÁC đang "
        f"chạy dở, không phải vì CSDL đã sạch: {kq}"
    )
    assert kq["an_toan"] is False, f"pha deny phải bị chặn: {kq}"

    # Trạng thái BỀN VỮNG — hàng nào cũng phải còn, adapter đã hỏng cả lượt.
    await enf.load_policy()
    con_lai = sorted(policy_cua_role(enf, SUB))
    assert con_lai == sorted([ALLOW, DENY]), (
        f"CSDL phải còn NGUYÊN cả cặp. Chỉ còn [allow] nghĩa là quyền vừa mở "
        f"bền vững do đan lịch. Hiện có: {con_lai!r}"
    )


# ---------------------------------------------------------------------------
# 10. CẠNH TRANH TRÊN GROUPING — cùng lock, khác bảng
# ---------------------------------------------------------------------------
#
# Mục 9 đóng race trên policy `p`. Nhưng `g` (grouping) đi qua ĐÚNG cơ chế ấy:
# PyCasbin gỡ rule khỏi model TRƯỚC rồi mới `await adapter.remove_policy`. Cửa
# sổ giữa hai bước là chỗ một lượt reload chen vào, đọc CSDL còn hàng cũ, và
# ĐƯA ROLE TRỞ LẠI model.
#
# Lịch trình:
#   1. Thu hồi `user:999999 -> role:admin` khỏi model, đang chờ adapter.
#   2. Reload chen vào, đọc CSDL cũ, đưa role trở lại model.
#   3. Adapter thu hồi hoàn tất -> hàng trong CSDL biến mất.
#   4. Model VẪN CÒN role. API báo thu hồi thành công.
#
# Người vận hành thu hồi role, API nói xong, mà `enforce` vẫn cho qua cho tới
# lượt reload kế tiếp. Nếu sau đó có bất kỳ lượt ghi toàn-model nào
# (`save_policy`) thì role còn được ghi TRỞ LẠI CSDL — phục hồi bền vững.


@pytest.mark.asyncio
async def test_canh_tranh_grouping_reload_khong_duoc_phuc_hoi_role(client):
    """Reload chen giữa lúc gỡ grouping: role phải mất ở CẢ model LẪN CSDL."""
    from unittest.mock import patch

    from app.services import casbin_service
    from app.services.casbin_service import khoa_enforcer

    enf = _enf()
    USER = "user:999999"
    ROLE = "role:admin"

    for g in [list(x) for x in enf.get_grouping_policy()]:
        if g[0] == USER:
            await enf.remove_grouping_policy(*g)
    await enf.add_grouping_policy(USER, ROLE)
    assert [USER, ROLE] in [list(g) for g in enf.get_grouping_policy()]

    dang_trong_adapter = asyncio.Event()
    reload_xong = asyncio.Event()
    that_adapter_remove = enf.adapter.remove_policy

    async def _adapter_cham(sec, ptype, rule):
        # Tới đây thì model ĐÃ mất rule còn adapter chưa xong — đúng cửa sổ.
        if list(rule) == [USER, ROLE]:
            dang_trong_adapter.set()
            try:
                await asyncio.wait_for(reload_xong.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass  # có lock: reload bị chặn — đúng như mong đợi
        return await that_adapter_remove(sec, ptype, rule)

    async def _reload_chen_ngang():
        """Đúng thứ endpoint reload làm: nạp lại policy từ CSDL."""
        await dang_trong_adapter.wait()
        async with khoa_enforcer(enf):
            await enf.load_policy()
        reload_xong.set()

    with patch.object(enf.adapter, "remove_policy", side_effect=_adapter_cham):
        t2 = asyncio.create_task(_reload_chen_ngang(), name="T2-reload")
        async with AsyncSessionLocal() as db:
            so_go = await casbin_service.CasbinPolicyService(
                db, enf
            ).remove_user_roles(999999)
        await asyncio.wait_for(t2, timeout=5)

    assert so_go == 1, f"phải gỡ đúng 1 grouping: {so_go}"

    trong_model = [list(g) for g in enf.get_grouping_policy() if list(g)[0] == USER]
    assert trong_model == [], (
        f"role phải biến khỏi MODEL. Nếu còn thì `enforce` vẫn cho qua cho tới "
        f"lượt reload kế tiếp — API báo thu hồi xong mà quyền vẫn sống. "
        f"Hiện có: {trong_model!r}"
    )

    # Trạng thái BỀN VỮNG: đọc lại từ CSDL, không tin model.
    async with khoa_enforcer(enf):
        await enf.load_policy()
    trong_db = [list(g) for g in enf.get_grouping_policy() if list(g)[0] == USER]
    assert trong_db == [], f"role phải biến khỏi CSDL: {trong_db!r}"

    # Và một lượt ghi TOÀN MODEL sau đó cũng không được phục hồi role — đây là
    # bước 4 trong lịch trình: `save_policy()` lấy model rồi ghi đè cả bảng.
    async with khoa_enforcer(enf):
        await enf.save_policy()
        await enf.load_policy()
    sau_save = [list(g) for g in enf.get_grouping_policy() if list(g)[0] == USER]
    assert sau_save == [], (
        f"một lượt ghi toàn-model sau đó đã PHỤC HỒI role vào CSDL: {sau_save!r}"
    )
