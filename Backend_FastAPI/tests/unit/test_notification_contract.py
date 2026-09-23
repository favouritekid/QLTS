# tests/unit/test_notification_contract.py
"""
PR3: Notification architecture contract tests.

These tests enforce invariants established by PR1/PR2:
- Event catalog classification (user / broadcast_only / internal_future)
- Dispatcher single-path behavior (no registry fallback)
- Delete guard for active catalog events
- Cross-action dedup precedence
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.events import SystemEvents
from app.core.event_catalog import (
    EVENT_CATALOG,
    get_event,
    get_event_by_key,
    get_notifiable_events,
    get_active_events,
    render_dedup_key,
    render_link,
)


# =============================================================================
# A. Catalog classification invariants
# =============================================================================


class TestCatalogClassification:
    """Every SystemEvents member must exist in EVENT_CATALOG with correct classification."""

    def test_all_system_events_in_catalog(self):
        """Every SystemEvents enum member must have a catalog entry."""
        missing = [ev for ev in SystemEvents if ev not in EVENT_CATALOG]
        assert missing == [], f"SystemEvents missing from catalog: {[e.value for e in missing]}"

    def test_no_duplicate_event_keys(self):
        """Event keys must be unique (enforced by dict, but verify explicitly)."""
        keys = [ev.value for ev in EVENT_CATALOG]
        assert len(keys) == len(set(keys)), "Duplicate event keys in catalog"

    def test_user_events_have_required_fields(self):
        """User events must have display_name, default_resolver, default_channels."""
        for defn in get_notifiable_events():
            assert defn.display_name, f"{defn.event.value}: missing display_name"
            assert defn.default_resolver, f"{defn.event.value}: missing default_resolver"
            assert defn.default_channels, f"{defn.event.value}: missing default_channels"

    def test_broadcast_only_excluded_from_notifiable(self):
        """broadcast_only events must NOT appear in get_notifiable_events()."""
        notifiable_keys = {d.event for d in get_notifiable_events()}
        broadcast = [
            d for d in EVENT_CATALOG.values()
            if d.notification_class == "broadcast_only"
        ]
        assert len(broadcast) > 0, "No broadcast_only events in catalog"
        for d in broadcast:
            assert d.event not in notifiable_keys, (
                f"{d.event.value} is broadcast_only but appears in notifiable"
            )

    def test_internal_future_excluded_from_notifiable(self):
        """internal_future events must NOT appear in get_notifiable_events()."""
        notifiable_keys = {d.event for d in get_notifiable_events()}
        future = [
            d for d in EVENT_CATALOG.values()
            if d.notification_class == "internal_future"
        ]
        assert len(future) > 0, "No internal_future events in catalog"
        for d in future:
            assert d.event not in notifiable_keys, (
                f"{d.event.value} is internal_future but appears in notifiable"
            )

    def test_lead_updated_is_broadcast_only(self):
        """D1 decision: lead_updated must be broadcast_only."""
        defn = get_event(SystemEvents.LEAD_UPDATED)
        assert defn is not None
        assert defn.notification_class == "broadcast_only"

    def test_ctv_lead_converted_is_internal_future(self):
        """CTV10 decision: ctv_lead_converted must be internal_future."""
        defn = get_event(SystemEvents.CTV_LEAD_CONVERTED)
        assert defn is not None
        assert defn.notification_class == "internal_future"

    def test_payment_overdue_is_user_class(self):
        """PR 8: payment_overdue promoted to user class."""
        defn = get_event(SystemEvents.PAYMENT_OVERDUE)
        assert defn is not None
        assert defn.notification_class == "user"

    def test_get_event_by_key_returns_correct_definition(self):
        defn = get_event_by_key("lead_assigned")
        assert defn is not None
        assert defn.event == SystemEvents.LEAD_ASSIGNED

    def test_render_functions(self):
        key = render_dedup_key(SystemEvents.LEAD_ASSIGNED, {"lead_id": 1, "officer_id": 2})
        assert key == "lead:1:assigned:2"
        link = render_link(SystemEvents.LEAD_ASSIGNED, {"lead_id": 42})
        assert link == "/leads/42"

    def test_system_alert_link_requires_safe_relative_path(self):
        assert render_link(SystemEvents.SYSTEM_ALERT, {"action_url": "/maintenance-info"}) == "/maintenance-info"
        assert render_link(SystemEvents.SYSTEM_ALERT, {"action_url": "https://evil.example/phish"}) is None
        assert render_link(SystemEvents.SYSTEM_ALERT, {"action_url": "javascript:alert(1)"}) is None
        assert render_link(SystemEvents.SYSTEM_ALERT, {"action_url": "//evil.example/phish"}) is None

    def test_user_profile_updated_is_specific_users_only(self):
        defn = get_event(SystemEvents.USER_PROFILE_UPDATED)
        assert defn is not None
        assert defn.default_resolver == "specific_users"
        assert defn.allowed_resolvers == ("specific_users",)


# =============================================================================
# A-bis. Link guard — D8-11 (vị từ) + D8-17 (ingress)
# =============================================================================
#
# Hợp đồng: chỉ đường NỘI BỘ bắt đầu bằng ``/``, không ``//``, và SAU CHUẨN
# HOÁ vẫn nội bộ. Đầu vào không đạt ⇒ ``render_link`` trả ``None`` (không
# ném), còn router ingress ⇒ HTTP 400. KHÔNG vá đầu vào, KHÔNG bỏ lặng lẽ.

_BS = chr(92)  # backslash — viết tường minh để heredoc/editor không nuốt

# Mỗi phần tử: (chuỗi, vì sao nguy hiểm).
# Bốn nhóm, mỗi nhóm bị một MỆNH ĐỀ khác nhau của vị từ chặn — đột biến gỡ
# một mệnh đề chỉ làm nhóm tương ứng đỏ.
_LINK_NGOAI_MIEN = [
    # nhóm "scheme / authority" — đã đỏ từ trước bản vá
    ("https://evil.example/phish", "scheme tuyệt đối"),
    ("javascript:alert(1)", "scheme javascript"),
    ("//evil.example/phish", "protocol-relative"),
    ("relative/path", "không bắt đầu bằng /"),
    # nhóm "backslash" — trình duyệt coi \ như / với scheme đặc biệt
    ("/" + _BS + "evil.example/p", "slash + backslash ⇒ //evil.example"),
    ("/" + _BS + "/evil.example/p", "slash backslash slash"),
    (_BS + _BS + "evil.example/p", "hai backslash"),
    # nhóm "ký tự điều khiển ở GIỮA" — trình duyệt gỡ TAB/LF/CR rồi mới phân giải
    ("/\t/evil.example/p", "TAB giữa hai dấu /"),
    ("/\n/evil.example/p", "LF giữa hai dấu /"),
    ("/\r/evil.example/p", "CR giữa hai dấu /"),
    ("/\tevil", "TAB ngay sau /"),
    ("/x\ny\rz", "CR+LF giữa đường dẫn"),
    ("/\x00evil", "NUL giữa đường dẫn"),
    # ``chr(0x2028)`` thay vì ký tự thô: không nhúng ký tự vô hình vào mã nguồn.
    ("/normal/" + chr(0x2028) + "evil", "U+2028 — dấu kết dòng JavaScript"),
    # nhóm "dot-segment THÔ" — chỉ lộ ra sau khi khử ./..
    ("/..//evil.example/p", "khử dot-segment ⇒ //evil.example"),
    ("/./../..//evil.example", "chuỗi dot-segment ⇒ //evil.example"),
    ("/.//x", "đoạn một chấm ⇒ //x"),
    ("/a/..//x", "hai chấm giữa đường ⇒ //x"),
    # nhóm "dot-segment MÃ HOÁ %2e" — WHATWG coi %2e là dấu chấm, `urlsplit`
    # của Python thì KHÔNG. Đo bằng Node v20.20.2: cả bảy dạng dưới đây cho
    # `pathname === "//x"`, và `resolveSafeUrl` của #644 trả `null`.
    ("/%2e%2e//x", "%2e%2e ⇒ //x (WHATWG đo được)"),
    ("/%2E%2E//x", "%2E%2E hoa ⇒ //x"),
    ("/%2e%2E//x", "%2e%2E hoa-thường trộn ⇒ //x"),
    ("/.%2e//x", ".%2e ⇒ //x"),
    ("/%2e.//x", "%2e. ⇒ //x"),
    ("/%2e//x", "đoạn MỘT chấm mã hoá %2e ⇒ //x"),
    ("/%2E//x", "đoạn MỘT chấm mã hoá %2E ⇒ //x"),
    ("/a/%2e%2e//x", "%2e%2e giữa đường ⇒ //x"),
]

# Dương tính — PHẢI xanh dưới MỌI đột biến (positive control).
_LINK_NOI_BO_HOP_LE = [
    "/maintenance-info",
    "/leads/42",
    "/leads/42?stage=3&status=rejected,unqualified#top",
    "/admin/kpi-planning/holidays/status/2027",
    "/a/../b",                 # dot-segment KHỬ RA vẫn nội bộ ⇒ phải cho qua
    # ⚠️ KHÔNG được chặn oan: bốn dạng %2e dưới đây chuẩn hoá thành `/b` —
    # nội bộ hợp lệ. Ranh giới là "chuẩn hoá xong có thành `//` không",
    # KHÔNG phải "có chứa dấu chấm không".
    "/%2e%2e/b",
    "/%2E%2E/b",
    "/.%2e/b",
    "/%2e./b",
    "/%09/evil.example",       # %09 KHÔNG được trình duyệt giải mã ⇒ vẫn cùng origin
    "/a%2f%2fb",               # %2f KHÔNG được WHATWG giải mã ⇒ vẫn MỘT đoạn
    "/",
]


def _system_alert_endpoint():
    """Trả về ĐÚNG hàm FastAPI gọi cho ``POST /system/alert``.

    KHÔNG dùng ``system_module.create_system_alert``: trong tệp đó
    ``@limiter.limit`` bọc NGOÀI ``@router.post`` (thứ tự sai đã biết, có
    tên trong ``tests/security/ratelimit_wrong_order_allowlist.txt``), nên
    thuộc tính module trỏ tới bản ĐÃ BỌC còn route giữ bản gốc. Đo được:
    ``router.routes[0].endpoint is module.create_system_alert`` → False.
    Test phải chạy đúng thân hàm đang phục vụ, không phải vỏ bọc.
    """
    from app.routers.admin import system as system_module

    for route in system_module.router.routes:
        if getattr(route, "path", None) == "/system/alert":
            return route.endpoint
    raise AssertionError("Không tìm thấy route POST /system/alert")


class TestNotificationLinkGuard:
    """D8-11: vị từ link phải chặn mọi biến thể thoát origin."""

    @pytest.mark.parametrize("raw,ly_do", _LINK_NGOAI_MIEN)
    def test_render_link_tu_choi_duong_thoat_origin(self, raw, ly_do):
        """``render_link`` trả None cho mọi biến thể thoát origin."""
        assert render_link(SystemEvents.SYSTEM_ALERT, {"action_url": raw}) is None, (
            f"render_link nhận sai {raw!r} ({ly_do})"
        )

    @pytest.mark.parametrize("raw,ly_do", _LINK_NGOAI_MIEN)
    def test_vi_tu_tu_choi_duong_thoat_origin(self, raw, ly_do):
        """Cùng corpus, gọi thẳng vị từ — không qua Template/strip."""
        from app.core.event_catalog import _is_safe_relative_link

        assert _is_safe_relative_link(raw) is False, f"vị từ nhận sai {raw!r} ({ly_do})"

    def test_vi_tu_tu_choi_khoang_trang_bao_ngoai_thay_vi_tu_cat(self):
        """Vị từ KHÔNG tự ``strip()`` — kiểm chuỗi nào thì phát chuỗi ấy."""
        from app.core.event_catalog import _is_safe_relative_link

        assert _is_safe_relative_link(" /maintenance-info") is False
        assert _is_safe_relative_link("/maintenance-info ") is False
        assert _is_safe_relative_link("\t/maintenance-info\n") is False

    # --- POSITIVE CONTROL: phải XANH dưới mọi đột biến -------------------
    @pytest.mark.parametrize("raw", _LINK_NOI_BO_HOP_LE)
    def test_positive_control_duong_noi_bo_van_duoc_cho_qua(self, raw):
        """Chứng cứ chống 'guard đúng vì chặn hết mọi thứ'."""
        assert render_link(SystemEvents.SYSTEM_ALERT, {"action_url": raw}) == raw

    def test_gia_tri_luu_bang_dung_gia_tri_da_kiem(self):
        """Không có ca nào kiểm chuỗi A rồi phát chuỗi B.

        Dạng đã khử dot-segment (``/b``) KHÔNG được lưu; giá trị trả về là
        chính chuỗi gốc ``/a/../b`` — đúng quyết định nêu ở docstring của
        ``render_link``.
        """
        ra = render_link(SystemEvents.SYSTEM_ALERT, {"action_url": "/a/../b"})
        assert ra == "/a/../b"
        assert ra != "/b"


class TestSystemAlertActionUrlIngress:
    """D8-17: ``action_url`` thô còn đi qua socket + ``notification.data``.

    ``render_link`` chỉ gác cột ``notification.link``. Cùng chuỗi ấy còn
    được ``_emit_domain_event`` phát NGUYÊN payload tới mọi role room, và
    được dispatcher trộn vào ``notification.data``. Hàng rào phải đứng ở
    INGRESS thì mới đóng hết các nhánh.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("raw,ly_do", _LINK_NGOAI_MIEN)
    async def test_ingress_tra_400_va_khong_dispatch(self, raw, ly_do):
        from fastapi import HTTPException

        endpoint = _system_alert_endpoint()
        sd = AsyncMock()
        with patch("app.routers.admin.system.safe_dispatch", new=sd):
            with pytest.raises(HTTPException) as ei:
                await endpoint(
                    request=MagicMock(),
                    severity="warning",
                    message="bao tri",
                    action_url=raw,
                    db=AsyncMock(),
                    current_admin=MagicMock(id=1, username="admin"),
                )
        assert ei.value.status_code == 400, f"{raw!r} ({ly_do}) không bị chặn ở ingress"
        # Không dispatch ⇒ không có payload thô nào tới socket / notification.data
        sd.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ingress_cho_qua_dung_chuoi_da_kiem(self):
        """Positive control cho ingress: link nội bộ đi tiếp NGUYÊN VĂN."""
        endpoint = _system_alert_endpoint()
        sd = AsyncMock()
        with patch("app.routers.admin.system.safe_dispatch", new=sd):
            ket_qua = await endpoint(
                request=MagicMock(),
                severity="info",
                message="bao tri",
                action_url="/maintenance-info",
                db=AsyncMock(),
                current_admin=MagicMock(id=1, username="admin"),
            )
        assert ket_qua["success"] is True
        sd.assert_awaited_once()
        payload = sd.await_args.kwargs["payload"]
        assert payload["action_url"] == "/maintenance-info"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("vang_mat", [None, ""])
    async def test_ingress_khong_chan_khi_vang_action_url(self, vang_mat):
        """Positive control: vắng link KHÔNG phải lỗi (hợp đồng cũ giữ nguyên)."""
        endpoint = _system_alert_endpoint()
        sd = AsyncMock()
        with patch("app.routers.admin.system.safe_dispatch", new=sd):
            ket_qua = await endpoint(
                request=MagicMock(),
                severity="info",
                message="bao tri",
                action_url=vang_mat,
                db=AsyncMock(),
                current_admin=MagicMock(id=1, username="admin"),
            )
        assert ket_qua["success"] is True
        sd.assert_awaited_once()


# Corpus lấy NGUYÊN VĂN từ hợp đồng frontend của PR #644
# (`frontend/src/lib/utils.ts::resolveSafeUrl` + `utils.test.ts`). Nếu #644
# đổi danh sách này thì BE phải đổi theo — hai tầng cùng một bất biến
# "đích không rời site", nên KHÔNG được lệch.
#
# Đo 22-09 bằng Node v20.20.2, nền `https://qlts.example/notifications`:
# cả năm chuỗi dưới đây cho `new URL(x, base).pathname === "//x"`.
_644_PHAI_TU_CHOI = ["/..//x", "/.//x", "/%2e%2e//x", "/%2E%2E//x", "/a/..//x"]
# ...và hai chuỗi này #644 CHO QUA (chuẩn hoá ra `/b`) ⇒ BE không được chặn oan.
_644_PHAI_CHO_QUA = ["/a/../b", "/%2e%2e/b"]


class TestBeKhopHopDongFrontend644:
    """Khoá BE ↔ `resolveSafeUrl` của #644 — cùng một bất biến, hai tầng.

    Vì sao cần: `urlsplit` của Python KHÔNG giải mã `%2e`, còn WHATWG URL
    (thứ trình duyệt thật dùng, và `resolveSafeUrl` đi qua `new URL`) thì
    COI `%2e` là dấu chấm. Bản vá đầu chỉ nhận diện dấu chấm THÔ nên BE cho
    qua `/%2e%2e//x` trong khi FE từ chối — đo được **8/21 ca lệch**.
    """

    @pytest.mark.parametrize("duong", _644_PHAI_TU_CHOI)
    def test_be_tu_choi_dung_nhung_gi_644_tu_choi(self, duong):
        assert render_link(SystemEvents.SYSTEM_ALERT, {"action_url": duong}) is None

    @pytest.mark.parametrize("duong", _644_PHAI_CHO_QUA)
    def test_be_khong_chan_oan_nhung_gi_644_cho_qua(self, duong):
        """Ranh giới là 'chuẩn hoá xong có thành `//` không', KHÔNG phải
        'có chứa dấu chấm không'. Luật sau sẽ chặn oan hai ca này."""
        assert render_link(SystemEvents.SYSTEM_ALERT, {"action_url": duong}) == duong


class TestSystemAlertIngressQuaHTTP:
    """Cùng bất biến với ``TestSystemAlertActionUrlIngress`` nhưng đi qua
    ĐÚNG đường người dùng đi: ASGI → middleware → router (CLAUDE.md §10).

    Ca ở tầng hàm không chứng minh route đã gắn, prefix đúng, hay
    ``HTTPException`` thật sự ra mã 400 sau middleware. Ca này chứng minh.
    Đường dẫn lấy TỪ CHÍNH ``fastapi_app.routes`` — không gõ tay, nên đổi
    prefix là ca này theo, không xanh giả.
    """

    @staticmethod
    def _duong_dan(app) -> str:
        duong = [
            r.path for r in app.routes
            if getattr(r, "name", None) == "create_system_alert"
        ]
        assert len(duong) == 1, f"mong đúng 1 route create_system_alert, thấy {duong}"
        return duong[0]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("raw,ly_do", _LINK_NGOAI_MIEN)
    async def test_http_400_va_khong_dispatch(self, raw, ly_do):
        from httpx import ASGITransport, AsyncClient

        from app import database
        from app.core.deps import check_permission
        from app.main import fastapi_app

        duong = self._duong_dan(fastapi_app)
        fastapi_app.dependency_overrides[database.get_db] = lambda: AsyncMock()
        fastapi_app.dependency_overrides[check_permission] = lambda: MagicMock(
            id=1, username="admin"
        )
        sd = AsyncMock()
        try:
            with patch("app.routers.admin.system.safe_dispatch", new=sd):
                async with AsyncClient(
                    transport=ASGITransport(app=fastapi_app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        duong,
                        params={
                            "severity": "warning",
                            "message": "bao tri",
                            "action_url": raw,
                        },
                    )
        finally:
            fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 400, (
            f"{raw!r} ({ly_do}) → HTTP {resp.status_code}, mong 400"
        )
        # Bất biến thứ hai của ca này: KHÔNG một lượt dispatch nào ⇒ không có
        # chuỗi thô nào tới socket / ``notification.data``.
        assert sd.await_count == 0

    @pytest.mark.asyncio
    async def test_http_positive_control_201_va_co_dispatch(self):
        """Phải XANH dưới mọi đột biến — chứng cứ guard không chặn tất."""
        from httpx import ASGITransport, AsyncClient

        from app import database
        from app.core.deps import check_permission
        from app.main import fastapi_app

        duong = self._duong_dan(fastapi_app)
        fastapi_app.dependency_overrides[database.get_db] = lambda: AsyncMock()
        fastapi_app.dependency_overrides[check_permission] = lambda: MagicMock(
            id=1, username="admin"
        )
        sd = AsyncMock()
        try:
            with patch("app.routers.admin.system.safe_dispatch", new=sd):
                async with AsyncClient(
                    transport=ASGITransport(app=fastapi_app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        duong,
                        params={
                            "severity": "info",
                            "message": "bao tri",
                            "action_url": "/maintenance-info",
                        },
                    )
        finally:
            fastapi_app.dependency_overrides.clear()

        assert resp.status_code == 201
        assert sd.await_count == 1
        assert sd.await_args.kwargs["payload"]["action_url"] == "/maintenance-info"


# =============================================================================
# B. Dispatcher invariants (unit-level, mocked DB)
# =============================================================================


class TestDispatcherInvariants:
    """Dispatcher single-path behavior — no registry fallback."""

    @pytest.mark.asyncio
    async def test_missing_rule_does_not_fallback(self):
        """User event with no enabled DB rule → fail-closed, empty result."""
        from app.services.notification_dispatcher import dispatch

        mock_defn = MagicMock()
        mock_defn.notification_class = "user"
        mock_defn.retired = False

        db = AsyncMock()
        db.flush = AsyncMock()

        with patch("app.services.notification_dispatcher.get_event", return_value=mock_defn), \
             patch("app.services.notification_dispatcher.get_rule_for_event", new=AsyncMock(return_value=None)), \
             patch("app.services.notification_dispatcher._emit_domain_event", new=AsyncMock()):
            ids, cb = await dispatch(db, SystemEvents.LEAD_ASSIGNED, {"lead_id": 1, "actor_id": 2})
            assert ids == [], "Missing rule must not produce notifications"
            assert cb is not None, "Callback must exist for domain event"

    @pytest.mark.asyncio
    async def test_broadcast_event_dispatches_domain_only(self):
        """broadcast_only event → domain event only, no DB rule lookup."""
        from app.services.notification_dispatcher import dispatch

        db = AsyncMock()
        mock_rule_loader = AsyncMock()

        with patch("app.services.notification_dispatcher.get_rule_for_event", mock_rule_loader), \
             patch("app.services.notification_dispatcher._emit_domain_event", new=AsyncMock()):
            ids, cb = await dispatch(db, SystemEvents.LEAD_UPDATED, {
                "lead_id": 1, "actor_id": 2, "updated_fields": [],
            })
            assert ids == []
            assert mock_rule_loader.call_count == 0, "broadcast_only must not query DB rules"

    @pytest.mark.asyncio
    async def test_internal_future_event_dispatches_domain_only(self):
        """internal_future event → domain event only, no DB rule lookup."""
        from app.services.notification_dispatcher import dispatch

        db = AsyncMock()
        mock_rule_loader = AsyncMock()

        with patch("app.services.notification_dispatcher.get_rule_for_event", mock_rule_loader), \
             patch("app.services.notification_dispatcher._emit_domain_event", new=AsyncMock()):
            ids, cb = await dispatch(db, SystemEvents.CTV_LEAD_CONVERTED, {
                "lead_id": 1, "collaborator_id": 2, "new_status": "contacted",
                "actor_id": 3,
            })
            assert ids == []
            assert mock_rule_loader.call_count == 0, "internal_future must not query DB rules"

    @pytest.mark.asyncio
    async def test_cross_action_dedup_lower_step_wins(self):
        """When same user appears in multiple actions for same channel, lower step wins.

        Step 1 (browser) and Step 2 (browser) both resolve [10, 20].
        After cross-action dedup, Step 2 should get 0 users.
        Verified by tracking per-step user_ids passed to _create_deliveries_for_action.
        """
        from app.services.notification_dispatcher import dispatch

        config = MagicMock()
        config.channel_values = ["browser"]
        config.rule_id = 1
        config.condition = None
        config.render_title.return_value = "Title"
        config.render_message.return_value = "Message"
        config.group = MagicMock(value="lead")

        action1 = MagicMock(step=1, channel="browser", delay_minutes=0,
                            template_code=None, config=None, recipient_config=None,
                            content_mode=None, content_override=None, branch_key="g1_browser")
        action2 = MagicMock(step=2, channel="browser", delay_minutes=0,
                            template_code=None, config=None, recipient_config=None,
                            content_mode=None, content_override=None, branch_key="g2_browser")
        config.actions = [action1, action2]
        config.resolver = MagicMock()
        config.resolver.resolve_users = AsyncMock(return_value=[10, 20])

        mock_defn = MagicMock()
        mock_defn.notification_class = "user"
        mock_defn.retired = False

        db = AsyncMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
        # ``dispatch`` mở savepoint cấp sự kiện quanh pha tạo Notification
        # cha (`async with db.begin_nested()`). `AsyncMock()` gọi ra một
        # coroutine chứ không phải async context manager, nên `db` giả phải
        # được trang bị. `__aexit__` trả False để KHÔNG nuốt ngoại lệ —
        # nuốt sẽ làm mọi ca trong tệp này xanh giả.
        _sp = MagicMock()
        _sp.__aenter__ = AsyncMock(return_value=_sp)
        _sp.__aexit__ = AsyncMock(return_value=False)
        db.begin_nested = MagicMock(return_value=_sp)

        # Track per-step delivery calls to verify dedup
        delivery_calls = []

        async def track_deliveries(db, event, action, user_ids, **kwargs):
            delivery_calls.append({"step": action.step, "user_ids": list(user_ids)})
            return [1000 + i for i in range(len(user_ids))]

        with patch("app.services.notification_dispatcher.get_event", return_value=mock_defn), \
             patch("app.services.notification_dispatcher.get_rule_for_event", new=AsyncMock(return_value=config)), \
             patch("app.services.notification_dispatcher.render_dedup_key", return_value=None), \
             patch("app.services.notification_dispatcher.render_link", return_value="/test"), \
             patch("app.services.notification_dispatcher.notification_preference_service") as mock_pref, \
             patch("app.services.notification_dispatcher.safe_redis_set", new=AsyncMock(return_value=True)), \
             patch("app.services.notification_dispatcher.safe_redis_incr", new=AsyncMock(return_value=1)), \
             patch("app.services.notification_dispatcher.safe_redis_expire", new=AsyncMock()), \
             patch("app.services.notification_dispatcher._bulk_create_notifications",
                   # Trả `{user_id: notification_id}` — quan hệ chủ quyền
                   # nay đến từ `RETURNING user_id, id`, không từ vị trí.
                   new=AsyncMock(return_value={10: 101, 20: 102})), \
             patch("app.services.notification_dispatcher._create_deliveries_for_action", track_deliveries), \
             patch("app.services.notification_dispatcher._resolve_action_templates", new=AsyncMock(return_value={})), \
             patch("app.services.notification_dispatcher._build_action_snapshot", return_value={}), \
             patch("app.services.notification_dispatcher._emit_domain_event", new=AsyncMock()), \
             patch("app.services.notification_dispatcher._extract_source_from_payload", return_value=("lead", 1)):
            mock_pref.filter_users_by_group = AsyncMock(side_effect=lambda db, user_ids, group, channel: user_ids)

            ids, cb = await dispatch(
                db, SystemEvents.LEAD_ASSIGNED,
                {"lead_id": 1, "officer_id": 10, "actor_id": 99},
                skip_preference_check=True,
            )

            # Step 1 gets [10, 20], Step 2 gets [] (deduped by cross-action dedup)
            assert len(ids) == 2, f"Expected 2 notifications (step 1 only), got {len(ids)}"

            step1_calls = [c for c in delivery_calls if c["step"] == 1]
            step2_calls = [c for c in delivery_calls if c["step"] == 2]

            assert len(step1_calls) == 1, "Step 1 should have 1 delivery call"
            assert sorted(step1_calls[0]["user_ids"]) == [10, 20], \
                f"Step 1 should deliver to [10, 20], got {step1_calls[0]['user_ids']}"

            # Step 2: either no call (empty users skipped) or called with empty list
            if step2_calls:
                assert step2_calls[0]["user_ids"] == [], \
                    f"Step 2 should be deduped (0 users), got {step2_calls[0]['user_ids']}"


# =============================================================================
# C. Delete guard invariants
# =============================================================================


class TestDeleteGuard:
    """Active catalog events cannot be hard-deleted."""

    @pytest.mark.asyncio
    async def test_cannot_delete_active_user_event_rule(self):
        """Deleting a rule for an active user event must raise BusinessRuleViolation."""
        from app.services.notification_rule_crud_service import delete_rule
        from app.utils.exceptions import BusinessRuleViolation

        mock_rule = MagicMock()
        mock_rule.event = "lead_assigned"
        mock_rule.id = 1

        db = AsyncMock()

        with pytest.raises(BusinessRuleViolation, match="Cannot delete rule"):
            await delete_rule(db, mock_rule)

    @pytest.mark.asyncio
    async def test_can_delete_orphan_event_rule(self):
        """Deleting a rule for an event not in catalog is allowed."""
        from app.services.notification_rule_crud_service import delete_rule

        mock_rule = MagicMock()
        mock_rule.event = "some_removed_event_not_in_catalog"
        mock_rule.id = 999
        mock_rule.template_id = None

        db = AsyncMock()
        mock_repo = MagicMock()
        mock_repo.delete_rule = AsyncMock()

        with patch("app.services.notification_rule_crud_service.NotificationRuleRepository", return_value=mock_repo):
            result, cb = await delete_rule(db, mock_rule)
            assert result is None
            mock_repo.delete_rule.assert_called_once()


# =============================================================================
# D. Dispatcher must not import from notification_registry
# =============================================================================


class TestNoRegistryDependency:
    """Dispatcher must not depend on notification_registry at runtime."""

    def test_dispatcher_has_no_registry_import(self):
        """notification_dispatcher.py must not import get_event_config or has_rule_override."""
        import inspect
        from app.services import notification_dispatcher
        source = inspect.getsource(notification_dispatcher)
        assert "get_event_config" not in source, "Dispatcher still imports get_event_config"
        assert "has_rule_override_for_event" not in source, "Dispatcher still imports has_rule_override"


# =============================================================================
# E. Sync contract tests
# =============================================================================


class TestSyncContract:
    """sync_notification_rules must be idempotent and complete."""

    @pytest.mark.asyncio
    async def test_sync_creates_missing_rules(self):
        """Fresh DB → sync creates one rule per user event."""
        from app.scripts.sync_notification_rules import sync_notification_rules
        from app.core.event_catalog import get_notifiable_events

        expected_user_count = len(get_notifiable_events())
        user_keys = {d.event.value for d in get_notifiable_events()}

        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # First query: existing rules → empty
                result.fetchall.return_value = []
            else:
                # Re-check query: all rules now exist (sync just created them)
                result.fetchall.return_value = [(k,) for k in user_keys]
            return result

        db.execute = mock_execute

        result = await sync_notification_rules(db)

        assert result["created"] == expected_user_count, (
            f"Sync should create {expected_user_count} rules, created {result['created']}"
        )
        assert result["skipped"] == 0
        assert result["missing_user_rules"] == 0

    @pytest.mark.asyncio
    async def test_sync_is_idempotent(self):
        """Running sync twice → second run creates 0, skips all."""
        from app.scripts.sync_notification_rules import sync_notification_rules
        from app.core.event_catalog import get_notifiable_events

        user_events = get_notifiable_events()
        existing_keys = [(ev.event.value,) for ev in user_events]

        db = AsyncMock()
        # Simulate all rules already exist
        mock_result = MagicMock()
        mock_result.fetchall.return_value = existing_keys
        db.execute = AsyncMock(return_value=mock_result)
        db.commit = AsyncMock()

        result = await sync_notification_rules(db)

        assert result["created"] == 0, "Idempotent sync should create 0"
        assert result["skipped"] == len(user_events)
        assert result["missing_user_rules"] == 0

    def test_sync_cli_exit_code_logic(self):
        """Script must exit non-zero when missing_user_rules > 0."""
        # Verify the exit logic exists in the main() function
        import inspect
        from app.scripts import sync_notification_rules as mod
        source = inspect.getsource(mod.main)
        assert "sys.exit(1)" in source, "main() must sys.exit(1) on missing rules"
        assert "missing_user_rules" in source

    @pytest.mark.asyncio
    async def test_can_delete_retired_event_rule(self):
        """Retired events (retired=True) should be deletable."""
        from app.services.notification_rule_crud_service import delete_rule

        mock_rule = MagicMock()
        mock_rule.event = "lead_assigned"
        mock_rule.id = 1
        mock_rule.template_id = None

        mock_defn = MagicMock()
        mock_defn.retired = True

        db = AsyncMock()
        mock_repo = MagicMock()
        mock_repo.delete_rule = AsyncMock()

        # Patch at catalog module level (delete_rule imports locally)
        with patch("app.core.event_catalog.get_event_by_key", return_value=mock_defn), \
             patch("app.services.notification_rule_crud_service.NotificationRuleRepository", return_value=mock_repo):
            result, cb = await delete_rule(db, mock_rule)
            assert result is None
            mock_repo.delete_rule.assert_called_once()


# =============================================================================
# F. User events must have real dispatch callers in production code
# =============================================================================


class TestUserEventsHaveDispatchCallers:
    """Every notification_class=user event must be dispatched somewhere in app/."""

    # Events dispatched via event=SystemEvents.XXX in app/routers/, app/services/, app/tasks/
    # Built by scanning: grep -rn "event=SystemEvents\." app/routers/ app/services/ app/tasks/
    _DISPATCHED_EVENTS = frozenset({
        "lead_assigned", "lead_assignment_failed", "lead_reassigned",
        "lead_status_changed", "lead_created", "lead_deleted",
        "lead_restored", "lead_imported", "lead_updated",
        "consultation_created", "consultation_updated",
        "consultation_deleted", "consultation_reminder",
        "application_created", "application_status_changed", "application_deleted",
        "application_fee_paid", "application_survey_due",
        "payment_received", "payment_verified",
        "payment_rejected",
        "fee_fully_paid", "invoice_issued", "payment_overdue",
        # Đổi ngành có khấu trừ phiếu thu. AWAITING dispatch từ hook
        # admission_service._reprice_on_resubmit_if_major_change (sau reprice);
        # CONFIRMED dispatch từ fee_calculation_service.confirm_major_change.
        "major_change_awaiting_confirmation", "major_change_confirmed",
        # refund_processed stays internal_future (no refund router yet)
        "ctv_claim_submitted", "ctv_claim_approved", "ctv_claim_rejected",
        "ctv_approved", "ctv_suspended", "ctv_commission_created",
        "ctv_attribution_expiring", "ctv_attribution_expired", "ctv_weekly_summary",
        "system_alert", "system_announcement", "user_role_changed",
        "user_deactivated", "user_profile_updated", "pipeline_config_updated",
        "officer_availability_changed", "suspicious_login",
        "holiday_calendar_incomplete",
        # fix/notification-alert-flood (2026-06-01): admin-only operational
        # health alert. Dispatched from app/tasks/delivery_tasks.py
        # ``check_notification_alerts`` (replaced the SYSTEM_ALERT fan-out).
        "notification_health_alert",
        # PR-Audit-1: dispatched from zalo_bot_link_service.verify_and_link
        # post_commit closure when chat_id displacement happens.
        "zalo_bot_link_displaced",
        # ADM-023+028 (2026-04-29): magic-link hardening events.
        # 24h/6h reminders fire from app/tasks/admission_tasks.py
        # ``check_admission_confirmation_reminders_task``. hard_locked
        # fires from app/services/admission_service.py
        # ``verify_and_confirm`` when attempt_count crosses
        # HARD_LOCK_THRESHOLD (=30).
        "admission_confirmation_reminder_24h",
        "admission_confirmation_reminder_6h",
        "admission_confirmation_hard_locked",
        # T11 source-aware decision (Wave 5, 2026-05-16). Dispatched at
        # runtime from app/services/admission_state_service.py::transition()
        # which resolves the event from
        # TRANSITION_PAIR_TO_EVENT[("waitlisted", "rejected")] and calls
        # dispatch_event(event=event, ...). The literal enum lives in that
        # module's _DISPATCH_ANCHORS docstring (the call reads `event=event`),
        # so the plain `event=SystemEvents.` grep finds it there. Distinct
        # from the 12 B2.1 milestones still on _PENDING_DISPATCH_EVENTS: this
        # T11 pair edge post-dates that frozen set, has a live caller today,
        # and was tripping the contract test as an un-listed user event.
        "admission_waitlist_rejected",
        # Q9 #07 Phase E priority overrides — dispatched via literal
        # dispatch_event(event=SystemEvents.X, ...) in
        # app/services/priority_override_service.py:
        #   - PRIORITY_KV_OVERRIDDEN    → override_kv            (Wave 2, ~L484)
        #   - PRIORITY_OBJECT_VERIFIED  → verify_object_evidence (Wave 3, ~L790)
        #   - PRIORITY_OBJECT_REJECTED  → reject_object_evidence (Wave 3, ~L918)
        # (all 2026-05-19). Real callers → belong here, not on the pending list.
        "priority_kv_overridden",
        "priority_object_verified",
        "priority_object_rejected",
    })

    # Events that have a catalog entry + are notification_class="user" but
    # do NOT yet have a dispatch caller in production code. The test below
    # subtracts this set from the "missing dispatch" assertion so it stays
    # honest — the assertion only excuses pending events that are
    # explicitly enumerated here, with a removal gate per entry. This is
    # NOT a permanent extension to `_DISPATCHED_EVENTS`; that whitelist
    # may only contain events with real callers in `app/`.
    #
    # Removal gate per cluster:
    # - admission_* (12): remove in #16 when
    #   `app/services/admission_state_service.py::transition()` calls
    #   `dispatch_event()` (B2.3). The coverage script
    #   (`app/scripts/check_notification_event_coverage.py`) reports
    #   ``no-dispatch-site`` for these 12 events today; once #16 lands
    #   the script goes green and these entries must be removed (the
    #   `test_pending_dispatch_events_locked` test below pins the count
    #   so the cleanup cannot be skipped).
    _PENDING_DISPATCH_EVENTS = frozenset({
        # B2.1 (2026-05-02) — admission cold-cutover refactor.
        # Catalog + group + seed defaults shipped here; dispatch sites
        # land in #16. Tracked separately from `_DISPATCHED_EVENTS` so
        # this contract test stays honest about the multi-PR wave.
        "admission_profile_submitted",
        "admission_revision_requested",
        "admission_resubmitted",
        "admission_result_published",
        "admission_decision_admitted",
        "admission_decision_waitlisted",
        "admission_decision_rejected",
        "admission_waitlist_promoted",
        "admission_confirmed",
        "admission_enrolled",
        "admission_withdrawn",
        "admission_rolled_back",
    })

    def test_user_events_have_dispatch_in_codebase(self):
        """Every active user event must have a dispatch caller OR be on the
        explicit pending list with a removal gate."""
        excused = self._DISPATCHED_EVENTS | self._PENDING_DISPATCH_EVENTS
        missing = []
        for defn in get_notifiable_events():
            if defn.event.value not in excused:
                missing.append(defn.event.value)
        assert not missing, (
            f"User events with no dispatch caller in production code: {missing}. "
            "Either add a dispatch call, demote to internal_future, or — for "
            "an event whose dispatch site is shipping in a follow-up PR — "
            "list it in `_PENDING_DISPATCH_EVENTS` with a removal gate."
        )

    def test_dispatched_set_covers_all_user_events(self):
        """Cross-check: every user event is either dispatched or pending.

        Same union as above, just framed from the catalog side so a regression
        in either direction (event added without wiring; whitelist entry
        deleted while caller still exists) is visible.
        """
        excused = self._DISPATCHED_EVENTS | self._PENDING_DISPATCH_EVENTS
        user_keys = {d.event.value for d in get_notifiable_events()}
        missing = user_keys - excused
        assert not missing, f"User events missing from dispatched/pending sets: {missing}"

    def test_pending_dispatch_events_disjoint_from_dispatched(self):
        """An event lives on exactly one list: real callers in
        `_DISPATCHED_EVENTS`, pending in `_PENDING_DISPATCH_EVENTS`."""
        overlap = self._DISPATCHED_EVENTS & self._PENDING_DISPATCH_EVENTS
        assert not overlap, (
            f"Events appear in BOTH dispatched and pending sets: {overlap}. "
            f"When a pending event gains a real dispatch site, remove it from "
            f"`_PENDING_DISPATCH_EVENTS` rather than adding it to "
            f"`_DISPATCHED_EVENTS`."
        )

    def test_pending_dispatch_events_locked_to_b2_1_admission_set(self):
        """Lock the pending set to exactly the 12 B2.1 events. Adding more
        (or forgetting to remove some after #16 ships) will fail loudly."""
        assert self._PENDING_DISPATCH_EVENTS == frozenset({
            "admission_profile_submitted",
            "admission_revision_requested",
            "admission_resubmitted",
            "admission_result_published",
            "admission_decision_admitted",
            "admission_decision_waitlisted",
            "admission_decision_rejected",
            "admission_waitlist_promoted",
            "admission_confirmed",
            "admission_enrolled",
            "admission_withdrawn",
            "admission_rolled_back",
        }), (
            "_PENDING_DISPATCH_EVENTS must be exactly the 12 B2.1 admission "
            "milestone events. If #16 has shipped, remove the 12 entries from "
            "_PENDING_DISPATCH_EVENTS (they should now appear via the live "
            "dispatch grep, not the pending list)."
        )


# =============================================================================
# G. Catalog DB Parity (unit-level with mocked DB)
# =============================================================================


class TestCatalogDBParity:
    """Invariants between catalog and DB rule state."""

    @pytest.mark.asyncio
    async def test_all_user_events_have_db_rule(self):
        """Sync ensures every user event has a DB rule. Verify via sync contract."""
        from app.scripts.sync_notification_rules import sync_notification_rules

        user_events = get_notifiable_events()
        existing_keys = [(d.event.value,) for d in user_events]

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = existing_keys
        db.execute = AsyncMock(return_value=mock_result)
        db.commit = AsyncMock()

        result = await sync_notification_rules(db)
        assert result["missing_user_rules"] == 0, (
            f"After sync, {result['missing_user_rules']} user events still missing rules"
        )

    def test_internal_future_events_have_no_rules_in_sync(self):
        """Sync must NOT create rules for internal_future events."""
        notifiable_keys = {d.event.value for d in get_notifiable_events()}
        future_events = [
            d for d in EVENT_CATALOG.values()
            if d.notification_class == "internal_future"
        ]
        for d in future_events:
            assert d.event.value not in notifiable_keys, (
                f"{d.event.value} is internal_future but in notifiable → sync would create rule"
            )

    @pytest.mark.asyncio
    async def test_no_orphan_rules_if_catalog_complete(self):
        """If DB rules only contain catalog events, orphan count = 0."""
        from app.scripts.sync_notification_rules import sync_notification_rules

        user_keys = [(d.event.value,) for d in get_notifiable_events()]

        db = AsyncMock()

        async def mock_exec(stmt):
            r = MagicMock()
            r.fetchall.return_value = user_keys
            return r

        db.execute = mock_exec
        db.commit = AsyncMock()

        result = await sync_notification_rules(db)
        assert result["orphan_rules"] == 0

    def test_no_enabled_rules_for_retired_events(self):
        """No catalog events are currently retired (baseline check)."""
        retired = [d for d in EVENT_CATALOG.values() if d.retired]
        assert len(retired) == 0, (
            f"Retired events found: {[d.event.value for d in retired]}. "
            "If intentional, add invariant test for 'no enabled DB rules for retired'."
        )


# =============================================================================
# H. Dedup template validation
# =============================================================================


class TestDedupTemplates:
    """Dedup key templates must use valid event variables."""

    def test_dedup_templates_use_valid_variables(self):
        """Every ${var} in dedup_key_template must be a declared event variable."""
        import re
        issues = []
        for defn in EVENT_CATALOG.values():
            if not defn.dedup_key_template:
                continue
            var_names = {v.name for v in defn.variables} if defn.variables else set()
            # Extract ${var} or $var patterns
            template_vars = set(re.findall(r'\$\{?(\w+)\}?', defn.dedup_key_template))
            invalid = template_vars - var_names
            if invalid:
                issues.append(
                    f"{defn.event.value}: dedup template uses {invalid} "
                    f"but event only declares {var_names}"
                )
        assert not issues, "Dedup templates reference undeclared variables:\n" + "\n".join(issues)

    def test_dedup_templates_unique_per_event(self):
        """No two events should share the exact same dedup_key_template pattern."""
        templates = {}
        dupes = []
        for defn in EVENT_CATALOG.values():
            if not defn.dedup_key_template:
                continue
            if defn.dedup_key_template in templates:
                dupes.append(
                    f"'{defn.dedup_key_template}' shared by "
                    f"{templates[defn.dedup_key_template]} and {defn.event.value}"
                )
            else:
                templates[defn.dedup_key_template] = defn.event.value
        assert not dupes, "Duplicate dedup templates:\n" + "\n".join(dupes)


# =============================================================================
# I. Retired event dispatch behavior
# =============================================================================


class TestRetiredEventDispatch:
    """Retired events must not dispatch notifications."""

    @pytest.mark.asyncio
    async def test_retired_event_does_not_dispatch(self):
        """A retired event must return empty + domain-only callback."""
        from app.services.notification_dispatcher import dispatch

        # Create a mock retired event definition
        mock_defn = MagicMock()
        mock_defn.retired = True
        mock_defn.notification_class = "user"

        db = AsyncMock()

        with patch("app.services.notification_dispatcher.get_event", return_value=mock_defn), \
             patch("app.services.notification_dispatcher._emit_domain_event", new=AsyncMock()):
            ids, cb = await dispatch(db, SystemEvents.LEAD_ASSIGNED, {"lead_id": 1})
            assert ids == [], "Retired event must not create notifications"
            assert cb is not None, "Domain event callback must exist"
