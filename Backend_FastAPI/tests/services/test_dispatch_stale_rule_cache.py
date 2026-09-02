# tests/services/test_dispatch_stale_rule_cache.py
# -*- coding: utf-8 -*-
"""Hồi quy: cấu hình rule cũ trong cache ⇒ dispatch phá giao dịch của người gọi.

Sự cố gốc, trình tự đo bằng SQL echo (không suy đoán)::

    SAVEPOINT sa_savepoint_3                      <- lead_service.py:1363
      INSERT INTO notification ... RETURNING id     -> id 1
      INSERT INTO notification_delivery (rule_id=1)
          X notification_delivery_rule_id_fkey      (rule 1 không còn trong DB)
    ROLLBACK TO SAVEPOINT sa_savepoint_3          <- notification id 1 biến mất
      step=1 browser: "Failed to create delivery rows", strict=False -> ĐI TIẾP
      step=2 email:   PendingRollbackError
    lead_service.py:1375 "Dispatch failed, business data preserved"  <- BÁO SAI

`notification_id_fkey` mà sổ nightly ghi nhận chỉ là triệu chứng tầng hai; lỗi
nguyên phát là `rule_id`. Cấu hình mang `rule_id` chết đến từ cache Redis của
`notification_rule_loader` (TTL 3600) — đã đo: trong cả lượt dispatch hỏng chỉ
có ĐÚNG MỘT truy vấn `FROM notification_rule`, và nó hỏi một event khác.

Bốn bất biến bị phá cùng lúc. Mỗi ca dưới đây gác ĐÚNG MỘT cái::

    BT1  cấu hình đem đi dispatch phải là cấu hình ĐANG CÓ trong CSDL
    BT2  một INSERT hỏng chỉ được huỷ savepoint của CHÍNH NÓ; phiên phải
         còn dùng được ngay sau đó
    BT3  dispatch KHÔNG được rollback giao dịch của người gọi
    BT4  không được để lại hàng nửa vời (notification không có delivery)

⚠️ ĐỪNG dùng "toàn vẹn tham chiếu lúc nghỉ" làm khẳng định: chính FK đã ép nó,
nên `LEFT JOIN notification_rule ... WHERE r.id IS NULL` không bao giờ khác 0
kể cả khi gỡ sạch guard. Thứ KHÔNG ràng buộc nào canh — và vì thế đáng khẳng
định — là `notification` mồ côi, số hàng tuyệt đối, và phiên còn sống.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.events import SystemEvents
from app.database import AsyncSessionLocal, safe_redis_get, safe_redis_set
from app.services import lead_service
from app.services import notification_dispatcher as nd
from app.services.notification_rule_loader import (
    RULE_CACHE_PREFIX,
    get_rule_for_event,
    invalidate_rule_cache,
)

pytestmark = pytest.mark.asyncio

TIEU_DE_CACHE = "TIÊU ĐỀ BẢN CŨ (chỉ còn trong cache)"
TIEU_DE_DB = "TIÊU ĐỀ BẢN MỚI (đang có trong CSDL)"

SU_KIEN = SystemEvents.LEAD_ASSIGNED


# =============================================================================
# HELPER
# =============================================================================


class MockLeadIn:
    """Bản sao tối giản của `schemas.LeadCreate`.

    Giữ y hình mẫu ở `test_create_lead_referral.py` để không đẻ ra quy ước
    thứ hai cho cùng một việc.
    """

    def __init__(self, phone: str, unit_id: int, assigned_officer_id: int = None):
        self.phone = phone
        self.phone2 = None
        self.email = None
        self.unit_id = unit_id
        self.source = "website"
        self.assigned_officer_id = assigned_officer_id
        self.referrer_id = None

    def model_dump(self, **kwargs):
        data = {
            "full_name": f"Lead {self.phone}",
            "phone": self.phone,
            "source": self.source,
            "unit_id": self.unit_id,
        }
        if self.assigned_officer_id is not None:
            data["assigned_officer_id"] = self.assigned_officer_id
        return data


async def _tao_rule(
    db: AsyncSession,
    *,
    tieu_de: str,
    event: SystemEvents = SU_KIEN,
    kenh: tuple = ("browser",),
) -> models.NotificationRule:
    """Dựng MỘT rule đang bật kèm N action, commit ngay.

    Dùng resolver `specific_users` vì nó KHÔNG truy vấn CSDL — người nhận đến
    thẳng từ `payload["user_ids"]`. Nhờ vậy số người nhận là hằng số của ca
    test, không phải hệ quả của seed đơn vị/vai trò.
    """
    rule = models.NotificationRule(
        event=event.value,
        title_template=tieu_de,
        message_template="Nội dung kiểm thử lead $lead_id",
        notification_type="info",
        recipient_config={"resolver_type": "specific_users", "params": {}},
        condition=None,
        enabled=True,
    )
    db.add(rule)
    await db.flush()
    for step, ch in enumerate(kenh, start=1):
        db.add(
            models.NotificationAction(
                rule_id=rule.id, step=step, channel=ch,
                content_mode="inherit_default",
            )
        )
    await db.commit()
    await db.refresh(rule)
    return rule


async def _nap_cache(
    db: AsyncSession, rule: models.NotificationRule, event: SystemEvents = SU_KIEN
) -> int:
    """Ghi THẲNG khoá Redis đúng hình dạng mã cũ sinh ra, trả về `rule_id`.

    CỐ Ý không đi qua `get_rule_for_event`: sau bản vá, loader không còn ghi
    cache nữa, nên nếu tiền đề phụ thuộc vào loader thì ca test sẽ tự vô hiệu
    hoá chính nó. Ghi thẳng khoá cho ta đúng cảnh cần đo — *một khoá cũ vẫn
    còn nằm trong Redis* (do tiến trình khác, do bản deploy trước, do TTL
    3600 chưa hết) — và bắt loader phải phớt lờ nó.

    Hình dạng payload lấy nguyên từ mã trước khi vá (`_cache_rule_config`):
    id/event/title_template/message_template/notification_type/link_template/
    actions/recipient_config/condition. Chú ý nó KHÔNG có `enabled` — đó
    chính là một trong những lý do cache này không đáng tin.
    """
    actions = (
        await db.execute(
            select(models.NotificationAction)
            .where(models.NotificationAction.rule_id == rule.id)
            .order_by(models.NotificationAction.step)
        )
    ).scalars().all()
    rule_data = {
        "id": rule.id,
        "event": rule.event,
        "title_template": rule.title_template,
        "message_template": rule.message_template,
        "notification_type": rule.notification_type,
        "link_template": rule.link_template,
        "actions": [
            {
                "step": a.step, "channel": a.channel,
                "delay_minutes": a.delay_minutes,
                "template_code": a.template_code, "config": a.config,
                "recipient_config": a.recipient_config,
                "content_mode": a.content_mode,
                "content_override": a.content_override,
                "branch_key": a.branch_key,
            }
            for a in actions
        ],
        "recipient_config": rule.recipient_config,
        "condition": rule.condition,
    }
    await safe_redis_set(
        f"{RULE_CACHE_PREFIX}{event.value}", json.dumps(rule_data), ex=3600
    )

    raw = await safe_redis_get(f"{RULE_CACHE_PREFIX}{event.value}")
    assert raw, (
        "Tiền đề hỏng: không ghi được khoá cache ⇒ ca test không chứng minh "
        "được gì. (Phép chống xanh giả, không phải khẳng định chính.)"
    )
    return json.loads(raw)["id"]


async def _xoa_rule_giu_nguyen_cache(
    db: AsyncSession, rule_id: int, event: SystemEvents = SU_KIEN
) -> None:
    """Xoá hàng rule mà CỐ Ý bỏ qua `invalidate_rule_cache`.

    Đúng hình dạng của một đường sửa rule quên gọi callback, của một
    migration `DELETE FROM notification_rule`, hoặc của một tiến trình khác đã
    cache trước khi hàng bị xoá.
    """
    await db.execute(
        delete(models.NotificationRule).where(models.NotificationRule.id == rule_id)
    )
    await db.commit()

    con_lai = await db.scalar(
        select(func.count()).select_from(models.NotificationRule)
        .where(models.NotificationRule.id == rule_id)
    )
    assert con_lai == 0, "Tiền đề hỏng: rule chưa bị xoá thật"

    raw = await safe_redis_get(f"{RULE_CACHE_PREFIX}{event.value}")
    assert raw, (
        "Tiền đề hỏng: cache đã tự bay ⇒ ca test không còn đo cảnh 'cache cũ'"
    )


def _hook_xoa_rule_truoc_khi_ghi_delivery(monkeypatch, rule_id: int) -> dict:
    """Xoá rule ở MỘT PHIÊN KHÁC ngay trước lần ghi delivery đầu tiên.

    Đây KHÔNG phải mock CSDL: hàm thật vẫn chạy, INSERT thật, FK thật, lỗi
    thật. Hook chỉ quyết định THỜI ĐIỂM một lệnh DELETE thật (phiên độc lập,
    commit thật) đáp xuống — mô phỏng đúng cảnh "admin xoá rule giữa request".

    Dùng cảnh TOCTOU thay vì cache bẩn là CÓ CHỦ Ý: bản vá BT1 (đọc rule từ
    CSDL) KHÔNG đóng được cửa sổ này, nên những ca dùng hook vẫn còn gác
    BT2/BT3/BT4 sau khi BT1 đã vá. Nếu dùng cache bẩn, ca sẽ tự sụp thành ca
    BT1 và guard biến mất.
    """
    that = nd._create_deliveries_for_action
    trang_thai = {"da_xoa": False, "so_lan_goi": 0}

    async def _bao_boc(**kwargs):
        trang_thai["so_lan_goi"] += 1
        if kwargs.get("rule_id") == rule_id and not trang_thai["da_xoa"]:
            async with AsyncSessionLocal() as phien_khac:
                # lock_timeout: nếu phiên chính đang giữ KEY SHARE trên hàng
                # rule thì DELETE sẽ TREO. Thà đỏ vì timeout còn hơn treo cả bộ.
                await phien_khac.execute(text("SET LOCAL lock_timeout = '5s'"))
                await phien_khac.execute(
                    delete(models.NotificationRule)
                    .where(models.NotificationRule.id == rule_id)
                )
                await phien_khac.commit()
            trang_thai["da_xoa"] = True
        return await that(**kwargs)

    monkeypatch.setattr(nd, "_create_deliveries_for_action", _bao_boc)
    return trang_thai


def _cam_tac_dung_phu(monkeypatch, *, ket_qua_kenh=None) -> dict:
    """Chặn mọi tác dụng phụ ngoài CSDL và GHI LẠI thứ callback định làm.

    `ket_qua_kenh` cho phép một ca ép kết quả gửi kênh (ai `sent`, ai `failed`)
    một cách tất định. Mặc định giữ nguyên hành vi cũ nên các ca sẵn có không
    đổi. `send_channel`/`recipient_ids` là hai mốc ĐO ĐƯỢC chứng minh callback
    đã chạy tới bước 8a — không có chúng thì "cache rỗng" và "callback không
    chạy" trông giống hệt nhau.
    """
    ghi = {"ids_enqueue": [], "domain_emit": 0,
           "send_channel": 0, "recipient_ids": None}

    async def _emit(*a, **k):
        ghi["domain_emit"] += 1

    async def _gui(**kwargs):
        ghi["send_channel"] += 1
        # ĐO thứ tự thật của `browser_recipients` — ca BT11 cần nó để chứng
        # minh hai thứ tự KHÁC nhau, thay vì chỉ giả định.
        ghi["recipient_ids"] = list(kwargs.get("recipient_ids") or [])
        return ("browser", ket_qua_kenh if ket_qua_kenh is not None else
                MagicMock(sent_count=1, failed_ids=[], error_message=""), None)

    monkeypatch.setattr(nd, "_emit_domain_event", _emit)
    monkeypatch.setattr(nd, "_send_via_channel", _gui)

    from app.tasks import delivery_tasks

    tac_vu = MagicMock()
    tac_vu.apply_async.side_effect = (
        lambda args, **k: ghi["ids_enqueue"].append(args[0])
    )
    monkeypatch.setattr(delivery_tasks, "execute_notification_delivery", tac_vu)
    return ghi


async def _dem(db: AsyncSession, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


async def _dem_notification_mo_coi(db: AsyncSession) -> int:
    """Số hàng `notification` KHÔNG có `notification_delivery` đi kèm.

    Không ràng buộc nào của CSDL canh quan hệ này — đây mới là hình dạng "mồ
    côi" thật, khác hẳn phép LEFT JOIN theo FK (vốn luôn ra 0 nhờ chính FK).
    """
    return await db.scalar(
        text(
            "SELECT count(*) FROM notification n "
            "LEFT JOIN notification_delivery d ON d.notification_id = n.id "
            "WHERE d.id IS NULL"
        )
    )


async def _khang_dinh_phien_con_dung_duoc(db: AsyncSession, nhan: str) -> None:
    """BT2 — phiên phải còn ghi/đọc được NGAY SAU sự cố.

    Đọc + ghi + commit + đọc lại ở PHIÊN KHÁC. Chỉ `SELECT 1` là chưa đủ:
    `PendingRollbackError` chặn cả đọc lẫn ghi, nhưng một phiên "sống nửa vời"
    chỉ lộ ra ở bước commit.

    Ghi vào `notification_template` — bảng KHÔNG nằm trong phép đếm nào của
    các ca, nên phép thăm dò không làm nhiễu khẳng định chính.
    """
    await db.execute(select(1))
    ma = f"TPL_PROBE_{nhan}_{datetime.now(timezone.utc).timestamp()}"
    db.add(
        models.NotificationTemplate(
            name=f"probe {nhan}", template_code=ma,
            title_template="probe", message_template="probe",
            template_type="system",
        )
    )
    await db.commit()
    async with AsyncSessionLocal() as phien_moi:
        found = await phien_moi.scalar(
            select(func.count()).select_from(models.NotificationTemplate)
            .where(models.NotificationTemplate.template_code == ma)
        )
    assert found == 1, (
        f"BT2 vỡ ({nhan}): phiên KHÔNG dùng được sau sự cố dispatch — "
        "dispatch đã huỷ giao dịch của người gọi thay vì chỉ huỷ phần của nó."
    )


def _payload(officer_id: int, admin_id: int, lead_id: int) -> dict:
    return {
        "user_ids": [officer_id],
        "lead_id": lead_id,
        "lead_name": "Kiểm thử",
        "actor_id": admin_id,
    }


# =============================================================================
# BT1 — cấu hình phải là cấu hình ĐANG CÓ trong CSDL
# =============================================================================


async def test_bt1_rule_da_xoa_thi_loader_khong_duoc_tra_ban_cache(
    db: AsyncSession, clear_redis_keys, admin_user: models.User,
):
    """Xoá rule, bỏ qua invalidate ⇒ loader PHẢI trả `None` (fail-closed).

    Ca này KHÔNG chèn hàng nào nên giao dịch không thể hỏng ⇒ nếu nó đỏ thì
    chỉ có đúng một nghĩa: loader tin cache thay vì tin CSDL.
    """
    rule = await _tao_rule(db, tieu_de=TIEU_DE_CACHE)
    rule_id_cache = await _nap_cache(db, rule)
    assert rule_id_cache == rule.id

    await _xoa_rule_giu_nguyen_cache(db, rule.id)

    config = await get_rule_for_event(db, SU_KIEN)
    assert config is None, (
        "BT1 vỡ: loader trả cấu hình từ cache cho một rule KHÔNG còn trong "
        f"CSDL (rule_id={rule_id_cache}). Mọi delivery sinh ra sau đó mang "
        "rule_id chết và làm vỡ FK giữa giao dịch của người gọi."
    )


async def test_bt1_rule_sua_tai_cho_thi_loader_phai_tra_noi_dung_moi(
    db: AsyncSession, clear_redis_keys, admin_user: models.User,
):
    """Sửa rule TẠI CHỖ (giữ nguyên `id`) ⇒ loader phải trả nội dung mới.

    Đây là ca giết bản vá "đặt cho có". Một bản vá chỉ kiểm *`rule_id` có còn
    tồn tại không* rồi mới tin cache sẽ XANH ở ca xoá phía trên — nhưng ở đây
    `id` vẫn sống nguyên, chỉ NỘI DUNG đã đổi, nên nó phát đi tiêu đề cũ và ĐỎ.

    Cảnh này với tới được ở production: cache không mang `updated_at`, không
    mang `version`, và cũng không mang cả `enabled` — nên nó không có cách nào
    tự chứng minh mình còn đồng bộ với `NotificationRule` + `NotificationAction`
    + `NotificationTemplate`.
    """
    rule = await _tao_rule(db, tieu_de=TIEU_DE_CACHE)
    rule_id_cache = await _nap_cache(db, rule)
    assert rule_id_cache == rule.id

    # Sửa tại chỗ, CỐ Ý bỏ qua invalidate — đúng thứ đang được gác.
    rule.title_template = TIEU_DE_DB
    await db.commit()

    raw = await safe_redis_get(f"{RULE_CACHE_PREFIX}{SU_KIEN.value}")
    assert raw and json.loads(raw)["title_template"] == TIEU_DE_CACHE, (
        "Tiền đề hỏng: cache không còn giữ nội dung CŨ ⇒ ca test vô nghĩa"
    )

    config = await get_rule_for_event(db, SU_KIEN)
    assert config is not None, "BT1 vỡ: có rule đang bật trong CSDL mà loader trả None"
    assert config.rule_id == rule.id
    assert config.title_template == TIEU_DE_DB, (
        "BT1 vỡ: NỘI DUNG vẫn đến từ cache. Kiểm tra sự tồn tại của `rule_id` "
        "là CHƯA ĐỦ — cùng một id nhưng rule/action/template đã đổi thì cache "
        "vẫn cũ."
    )


# =============================================================================
# BT2 — phạm vi rollback và sự sống sót của phiên
# =============================================================================


async def test_bt2_delivery_hong_thi_phien_nguoi_goi_van_dung_duoc(
    db: AsyncSession, clear_redis_keys, monkeypatch,
    admin_user: models.User, officer_user: models.User,
):
    """`strict=False`: delivery hỏng FK thật ⇒ phiên người gọi phải còn ghi được.

    Lỗi FK được ép bằng TOCTOU thật (xoá rule ở phiên khác, đã commit, ngay
    trước lần ghi delivery đầu tiên) — KHÔNG mock phiên, KHÔNG mock repository,
    KHÔNG cache bẩn. Vì thế ca này còn nguyên giá trị SAU KHI BT1 đã vá.
    """
    _cam_tac_dung_phu(monkeypatch)
    rule = await _tao_rule(db, tieu_de=TIEU_DE_DB, kenh=("browser", "email"))
    await invalidate_rule_cache(SU_KIEN.value)
    hook = _hook_xoa_rule_truoc_khi_ghi_delivery(monkeypatch, rule.id)

    try:
        await nd.dispatch(
            db=db, event=SU_KIEN,
            payload=_payload(officer_user.id, admin_user.id, 777),
            dedupe_key="bt2:777",
            rooms=[f"user_room_{officer_user.id}"],
            strict=False,
        )
    except Exception:
        # Bản vá có thể chọn để ngoại lệ thoát ra hay không — ca này KHÔNG gác
        # điều đó. Nó gác đúng một thứ: phiên còn dùng được.
        pass

    assert hook["da_xoa"] is True, "Tiền đề hỏng: DELETE đồng thời không xảy ra"
    await _khang_dinh_phien_con_dung_duoc(db, "bt2")


# =============================================================================
# BT3 — dispatch không được rollback giao dịch của người gọi
# =============================================================================


async def test_bt3_create_lead_van_commit_duoc_khi_rule_cache_da_chet(
    db: AsyncSession, clear_redis_keys, monkeypatch,
    seeded_dependencies: dict, admin_user: models.User, officer_user: models.User,
):
    """Đường THẬT của sự cố: `create_lead` → savepoint dòng 1363 → dispatch.

    CỐ Ý chỉ dựng rule cho `lead_assigned` và KHÔNG dựng cho `lead_created`:
    đường `lead_created` fail-closed im lặng, nên MỌI hàng notification còn
    lại trong CSDL đều thuộc `lead_assigned`. Không có mẹo này thì phép đếm
    tuyệt đối mất nghĩa.
    """
    _cam_tac_dung_phu(monkeypatch)
    # `lead_service.py:887` import tác vụ này TRONG hàm từ `..celery_utils`,
    # nên phải patch ở module nguồn — patch trên `lead_service` là no-op câm.
    from app import celery_utils

    monkeypatch.setattr(
        celery_utils, "process_automatic_lead_assignment_task", MagicMock()
    )

    rule = await _tao_rule(db, tieu_de=TIEU_DE_CACHE)
    await _nap_cache(db, rule)
    await _xoa_rule_giu_nguyen_cache(db, rule.id)

    lead_in = MockLeadIn(
        phone="0800000031",
        unit_id=seeded_dependencies["unit_id"],
        assigned_officer_id=officer_user.id,  # ⇒ nhánh gán trực tiếp, dòng 1361
    )
    lead, cb = await lead_service.create_lead(db, lead_in, created_by=admin_user)
    await db.commit()
    if cb:
        await cb()

    # Đọc lại ở PHIÊN KHÁC — không tin identity map của phiên đang chạy.
    async with AsyncSessionLocal() as phien_moi:
        con = await phien_moi.scalar(
            select(models.Lead).where(models.Lead.phone == "0800000031")
        )
    assert con is not None, (
        "BT3 vỡ: dữ liệu nghiệp vụ KHÔNG commit được. dispatch đã huỷ giao dịch "
        "của người gọi (rollback sai tầng, hoặc phiên bị đầu độc), trong khi "
        "lead_service vẫn ghi log 'business data preserved'."
    )
    assert con.assigned_officer_id == officer_user.id


# =============================================================================
# BT4 — không để lại hàng nửa vời
# =============================================================================


async def test_bt4_khong_de_lai_notification_mo_coi(
    db: AsyncSession, clear_redis_keys, monkeypatch,
    admin_user: models.User, officer_user: models.User,
):
    """Delivery hỏng ⇒ không được để lại `notification` không có delivery.

    Hai kênh là BẮT BUỘC: rule một action thì "đi tiếp sau lỗi" không có gì
    để đi tiếp, và ca sẽ xanh mà chẳng gác gì.
    """
    _cam_tac_dung_phu(monkeypatch)
    rule = await _tao_rule(db, tieu_de=TIEU_DE_DB, kenh=("browser", "email"))
    await invalidate_rule_cache(SU_KIEN.value)
    hook = _hook_xoa_rule_truoc_khi_ghi_delivery(monkeypatch, rule.id)

    try:
        await nd.dispatch(
            db=db, event=SU_KIEN,
            payload=_payload(officer_user.id, admin_user.id, 778),
            dedupe_key="bt4:778",
            rooms=[f"user_room_{officer_user.id}"],
            strict=False,
        )
    except Exception:
        pass
    try:
        await db.commit()
    except Exception:
        await db.rollback()

    assert hook["da_xoa"] is True, "Tiền đề hỏng: DELETE đồng thời không xảy ra"
    mo_coi = await _dem_notification_mo_coi(db)
    assert mo_coi == 0, (
        f"BT4 vỡ: còn {mo_coi} hàng notification KHÔNG có delivery đi kèm — "
        "chuông đỏ trong inbox mà không đường nào giao, và không dấu vết "
        "kiểm toán nào giải thích."
    )


async def test_bt4_safe_dispatch_giu_nghiep_vu_da_commit(
    db: AsyncSession, clear_redis_keys, monkeypatch,
    seeded_dependencies: dict, admin_user: models.User, officer_user: models.User,
):
    """`safe_dispatch`: nghiệp vụ ĐÃ commit không được đảo, phiên còn dùng được.

    Khác ba ca trên ở chỗ `safe_dispatch` TỰ SỞ HỮU commit và rollback của
    phiên — nên nó là tầng DUY NHẤT được phép gọi `db.rollback()`.
    """
    _cam_tac_dung_phu(monkeypatch)
    lead = models.Lead(
        full_name="Đã commit trước", phone="0805000041", source="website",
        unit_id=seeded_dependencies["unit_id"],
        consultation_status_id=seeded_dependencies["initial_status_id"],
        pipeline_stage_id=seeded_dependencies["stage_id"],
    )
    db.add(lead)
    await db.commit()
    lead_id = lead.id

    rule = await _tao_rule(db, tieu_de=TIEU_DE_DB, kenh=("browser", "email"))
    await invalidate_rule_cache(SU_KIEN.value)
    _hook_xoa_rule_truoc_khi_ghi_delivery(monkeypatch, rule.id)

    ids = await nd.safe_dispatch(
        db=db, event=SU_KIEN,
        payload=_payload(officer_user.id, admin_user.id, lead_id),
        dedupe_key="bt4:safe",
        rooms=[f"user_room_{officer_user.id}"],
    )

    assert ids == [], "safe_dispatch phải trả [] khi ghi hỏng, không được ném"
    async with AsyncSessionLocal() as phien_moi:
        assert await phien_moi.get(models.Lead, lead_id) is not None, (
            "safe_dispatch đã đảo cả dữ liệu nghiệp vụ đã commit trước đó"
        )
    assert await _dem_notification_mo_coi(db) == 0
    await _khang_dinh_phien_con_dung_duoc(db, "bt4safe")


# =============================================================================
# BT3 (pha CHA) — hỏng khi tạo Notification cha phải huỷ cả sự kiện
# =============================================================================


async def test_bt3_hong_pha_notification_cha_khong_duoc_nuot_nghiep_vu(
    db: AsyncSession, clear_redis_keys, monkeypatch,
    seeded_dependencies: dict, admin_user: models.User,
):
    """Pha tạo `Notification` CHA hỏng ⇒ huỷ sự kiện, giữ nguyên nghiệp vụ.

    Ép lỗi bằng FK THẬT trên `notification.user_id`: resolver `specific_users`
    trả thẳng ID từ payload nên một ID không tồn tại đi trọn đường tới INSERT
    rồi vỡ ở khoá ngoại. Không mock repository, không mock phiên.

    Ca này gác nhánh mà ba ca trên KHÔNG chạm tới: ở chúng, hàng cha được tạo
    THÀNH CÔNG và chỉ delivery mới hỏng. Không có ca này thì việc gỡ bỏ
    `db.rollback()` khỏi `_bulk_create_notifications` không có phép nào nhìn
    thấy — và đó chính là dòng đã nuốt dữ liệu nghiệp vụ của người gọi.

    Dữ liệu nghiệp vụ CỐ Ý chỉ `flush` chứ không `commit` trước khi dispatch:
    một `db.rollback()` sai tầng sẽ xoá đúng thứ đó, còn rollback theo savepoint
    thì không.
    """
    _cam_tac_dung_phu(monkeypatch)
    ID_KHONG_TON_TAI = 9_999_991

    rule = await _tao_rule(db, tieu_de=TIEU_DE_DB)
    await invalidate_rule_cache(SU_KIEN.value)
    assert rule.id is not None

    lead = models.Lead(
        full_name="Nghiệp vụ phải sống", phone="0805000061", source="website",
        unit_id=seeded_dependencies["unit_id"],
        consultation_status_id=seeded_dependencies["initial_status_id"],
        pipeline_stage_id=seeded_dependencies["stage_id"],
    )
    db.add(lead)
    await db.flush()  # CHƯA commit — đây là thứ rollback sai tầng sẽ nuốt
    lead_id = lead.id

    try:
        ids, _ = await nd.dispatch(
            db=db, event=SU_KIEN,
            payload=_payload(ID_KHONG_TON_TAI, admin_user.id, lead_id),
            dedupe_key="bt3:cha",
            rooms=[f"user_room_{ID_KHONG_TON_TAI}"],
            strict=False,
        )
        assert ids == [], (
            "Pha cha hỏng mà dispatch vẫn trả về ID notification — những ID ấy "
            "trỏ vào hàng không tồn tại."
        )
    except Exception:
        # Bản vá có thể chọn để ngoại lệ thoát ra; ca này không gác điều đó.
        pass

    await db.commit()

    async with AsyncSessionLocal() as phien_moi:
        con = await phien_moi.get(models.Lead, lead_id)
    assert con is not None, (
        "BT3 vỡ: hỏng ở pha tạo Notification cha đã nuốt luôn dữ liệu nghiệp vụ "
        "CHƯA commit của người gọi — đúng hành vi của `db.rollback()` gọi từ "
        "tầng không sở hữu giao dịch."
    )
    assert await _dem(db, models.Notification) == 0
    assert await _dem(db, models.NotificationDelivery) == 0


# =============================================================================
# BT5 — pha tạo Notification cha phải all-or-nothing trên TOÀN BỘ chunk
# =============================================================================


async def test_bt5_hong_chunk_thu_hai_khong_duoc_de_lai_chunk_dau(
    db: AsyncSession, clear_redis_keys, monkeypatch,
    seeded_dependencies: dict, admin_user: models.User, officer_user: models.User,
):
    """Chunk 2 hỏng ⇒ chunk 1 KHÔNG được sống sót.

    `_bulk_create_notifications` chèn theo lô `BULK_INSERT_CHUNK_SIZE = 100`.
    Nếu ranh giới giao dịch đặt ở CẤP CHUNK thì nó cho một bảo đảm sai: chunk 1
    release thành công, chunk 2 hỏng, ngoại lệ bay lên `dispatch`, `dispatch`
    bắt rồi `return` NGAY — trước khối dọn hàng mồ côi — nên hàng của chunk 1
    vẫn nằm trong giao dịch ngoài và được router commit.

    Ép chunk nhỏ bằng cách sửa hằng số ở cấp module (`dispatch` đọc nó lúc
    chạy), rẻ hơn nhiều so với seed 100+ user thật, và vẫn đi đúng đường mã.

    Bất biến DUY NHẤT của ca này: pha cha là all-or-nothing. Dữ liệu nghiệp vụ
    được `flush` mà CHƯA commit để phân biệt "rollback đúng phạm vi savepoint"
    với "rollback nuốt cả giao dịch của người gọi".
    """
    _cam_tac_dung_phu(monkeypatch)
    monkeypatch.setattr(nd, "BULK_INSERT_CHUNK_SIZE", 2)
    ID_KHONG_TON_TAI = 9_999_993

    rule = await _tao_rule(db, tieu_de=TIEU_DE_DB)
    await invalidate_rule_cache(SU_KIEN.value)
    assert rule.id is not None

    lead = models.Lead(
        full_name="Nghiệp vụ phải sống (chunk)", phone="0805000071", source="website",
        unit_id=seeded_dependencies["unit_id"],
        consultation_status_id=seeded_dependencies["initial_status_id"],
        pipeline_stage_id=seeded_dependencies["stage_id"],
    )
    db.add(lead)
    await db.flush()
    lead_id = lead.id

    # sorted() ⇒ hai ID thật vào chunk 1, ID không tồn tại rơi xuống chunk 2.
    nguoi_nhan = sorted({admin_user.id, officer_user.id, ID_KHONG_TON_TAI})
    assert nguoi_nhan[-1] == ID_KHONG_TON_TAI, "Tiền đề hỏng: ID giả không ở chunk cuối"

    try:
        ids, _ = await nd.dispatch(
            db=db, event=SU_KIEN,
            payload={
                "user_ids": nguoi_nhan, "lead_id": lead_id,
                "lead_name": "Kiểm thử", "actor_id": admin_user.id,
            },
            dedupe_key="bt5:chunk",
            rooms=[f"user_room_{admin_user.id}"],
            strict=False,
        )
        assert ids == [], "Pha cha hỏng mà dispatch vẫn trả ID notification"
    except Exception:
        pass

    await db.commit()

    con_lai = await _dem(db, models.Notification)
    assert con_lai == 0, (
        f"Ranh giới giao dịch đặt SAI CẤP: còn {con_lai} hàng notification của "
        "chunk đầu được commit trong khi chunk sau đã hỏng. Pha tạo Notification "
        "cha phải all-or-nothing trên TOÀN BỘ vòng lặp chunk."
    )
    assert await _dem(db, models.NotificationDelivery) == 0
    async with AsyncSessionLocal() as phien_moi:
        assert await phien_moi.get(models.Lead, lead_id) is not None, (
            "Savepoint cấp sự kiện đã cuộn vượt phạm vi và nuốt cả dữ liệu nghiệp vụ"
        )


# =============================================================================
# BT6 — không được ghi notification của người này vào inbox cache người kia
# =============================================================================


async def test_bt6_khong_ghi_notification_cua_nguoi_khac_vao_inbox_cache(
    db: AsyncSession, clear_redis_keys, monkeypatch, test_redis_client,
    admin_user: models.User, officer_user: models.User,
):
    """Hỏng MỘT PHẦN ⇒ cặp `user_id ↔ notification_id` vẫn phải đúng.

    Dựng hai action CÙNG kênh `browser` với tập người nhận RỜI NHAU (dedup
    chéo-action giữ nguyên cả hai vì không giao nhau):

        step 1  `specific_users`  -> officer  (ID LỚN hơn)
        step 2  `all_admins`      -> admin    (ID NHỎ hơn)

    `inbox_user_ids` được `sorted()` nên thứ tự là [admin, officer] và
    `notification_ids` là [n_admin, n_officer]. Hook xoá rule ngay trước lần
    ghi delivery của step 2 ⇒ step 1 (officer) ghi được, step 2 (admin) hỏng ⇒
    `n_admin` thành mồ côi và bị dọn.

    Nếu bản vá thu gọn RIÊNG `notification_ids` rồi vẫn `zip()` với
    `inbox_user_ids` nguyên vẹn thì cặp lệch một bậc: (admin, n_officer) —
    và ID notification của officer bị đẩy vào `user_inbox:{admin}`.

    Khẳng định là BẤT BIẾN chứ không phải ID cụ thể: mọi ID nằm trong
    `user_inbox:{u}` phải thuộc về đúng `u`. Nhờ vậy ca không vỡ nếu resolver
    `all_admins` trả thêm một admin khác.
    """
    _cam_tac_dung_phu(monkeypatch)

    rule = models.NotificationRule(
        event=SU_KIEN.value,
        title_template=TIEU_DE_DB,
        message_template="Nội dung kiểm thử lead $lead_id",
        notification_type="info",
        recipient_config={"resolver_type": "specific_users", "params": {}},
        condition=None,
        enabled=True,
    )
    db.add(rule)
    await db.flush()
    db.add(models.NotificationAction(
        rule_id=rule.id, step=1, channel="browser",
        content_mode="inherit_default",
        recipient_config={"resolver_type": "specific_users", "params": {}},
    ))
    db.add(models.NotificationAction(
        rule_id=rule.id, step=2, channel="browser",
        content_mode="inherit_default",
        recipient_config={"resolver_type": "all_admins", "params": {}},
    ))
    await db.commit()
    await db.refresh(rule)
    await invalidate_rule_cache(SU_KIEN.value)

    assert admin_user.id < officer_user.id, (
        "Tiền đề hỏng: ca này cần người sống sót nằm SAU trong thứ tự sắp xếp, "
        "nếu không thì phép ghép lệch lại đúng một cách tình cờ"
    )

    # Tiêm lỗi ở ĐÚNG mối nối, không xoá rule: xoá rule ở phiên khác sẽ vấp
    # khoá hàng do phiên chính đang giữ (đo được: `LockNotAvailableError` sau
    # 5 giây), và nó làm HỎNG CẢ HAI action nên không còn cảnh hỏng-một-phần.
    # Cơ chế gây lỗi không phải thứ ca này canh — cặp `user ↔ notification`
    # mới là thứ được canh; nên tiêm sạch và tất định là đúng chỗ.
    trang_thai = {"so_lan": 0, "da_hong_step2": False}
    that = nd._create_deliveries_for_action

    async def _bao_boc(**kwargs):
        trang_thai["so_lan"] += 1
        if kwargs["action"].step == 2:
            trang_thai["da_hong_step2"] = True
            raise RuntimeError("tiêm lỗi: delivery của step 2 hỏng")
        return await that(**kwargs)

    monkeypatch.setattr(nd, "_create_deliveries_for_action", _bao_boc)

    # KHÔNG bọc try/except: nuốt ngoại lệ ở đây làm ca xanh giả khi callback
    # không chạy hoặc khi bước nạp cache bị gỡ hẳn. Nếu `dispatch` ném thì ca
    # PHẢI đỏ — đó là thông tin, không phải nhiễu.
    ids, cb = await nd.dispatch(
        db=db, event=SU_KIEN,
        payload={
            "user_ids": [officer_user.id], "lead_id": 606,
            "lead_name": "Kiểm thử", "actor_id": admin_user.id,
        },
        dedupe_key="bt6:606",
        rooms=[f"user_room_{officer_user.id}"],
        strict=False,
    )
    await db.commit()
    assert cb is not None, "dispatch phải trả callback post-commit"
    await cb()

    assert trang_thai["da_hong_step2"] is True, (
        "Tiền đề hỏng: step 2 chưa từng được gọi ⇒ không có hỏng-một-phần"
    )
    con_lai = await _dem(db, models.Notification)
    assert con_lai == 1, (
        f"Tiền đề hỏng: mong đúng MỘT hàng notification sống sót, đo được "
        f"{con_lai}. Không có hỏng-MỘT-PHẦN thì phép ghép không thể lệch và ca "
        "này không chứng minh gì."
    )

    # BẤT BIẾN: mọi ID trong inbox cache của u phải là notification CỦA u.
    vi_pham = []
    for u in (admin_user.id, officer_user.id):
        for raw in await test_redis_client.lrange(f"user_inbox:{u}", 0, -1):
            n = await db.get(models.Notification, int(raw))
            if n is not None and n.user_id != u:
                vi_pham.append((u, int(raw), n.user_id))
    assert not vi_pham, (
        "Rò dữ liệu chéo người dùng: ID notification bị ghi vào inbox cache của "
        f"người KHÁC — (cache_cua, notification_id, chu_so_huu_that) = {vi_pham!r}. "
        "Nguyên nhân là ghép cặp theo VỊ TRÍ sau khi một danh sách đã bị thu gọn."
    )

    # KHẲNG ĐỊNH DƯƠNG — bắt buộc, nếu không thì gỡ HẲN bước nạp cache cũng
    # làm ca này xanh (không có cache thì không có cache sai).
    n_song = (
        await db.execute(select(models.Notification))
    ).scalars().all()
    assert len(n_song) == 1
    chu = n_song[0].user_id
    cache_chu = await test_redis_client.lrange(f"user_inbox:{chu}", 0, -1)
    assert str(n_song[0].id) in cache_chu, (
        f"Notification sống sót (id={n_song[0].id}, của user {chu}) KHÔNG vào "
        f"cache inbox của chính chủ. Cache đọc được: {cache_chu!r}. Một bản vá "
        "chỉ 'không ghi sai' mà cũng không ghi đúng thì đã phá tính năng."
    )
    assert ids == [n_song[0].id], (
        f"dispatch phải trả đúng ID còn sống, đo được {ids!r}"
    )


# =============================================================================
# BT7 — hàng rào cuối: hydrate inbox phải lọc theo chủ quyền
# =============================================================================


async def test_bt7_hydrate_inbox_khong_duoc_tin_redis_lam_bang_chu_quyen(
    db: AsyncSession, clear_redis_keys, test_redis_client,
    admin_user: models.User, officer_user: models.User,
):
    """Cache bị đầu độc ⇒ đường đọc vẫn KHÔNG được trả hàng của người khác.

    Đây là hàng rào ĐỘC LẬP với bản vá ở đường ghi. Kể cả khi một ID lọt vào
    `user_inbox:{u1}` — do lỗi ghép cặp, do sửa tay, do một khoá cũ còn sót —
    thì `get_user_notifications` vẫn phải lọc theo `user_id`. Redis không được
    là nguồn chứng minh chủ quyền.

    Chú ý: nhánh cache MISS ngay bên dưới trong cùng hàm đã lọc đúng qua
    `get_filtered(user_id=...)`. Lỗ hổng chỉ nằm ở nhánh cache HIT — nên ca này
    BẮT BUỘC phải làm cho cache HIT.
    """
    from app.services import notification_service

    cua_officer = models.Notification(
        user_id=officer_user.id, type="info",
        title="BÍ MẬT CỦA OFFICER", message="Không ai khác được đọc",
        is_read=False,
    )
    db.add(cua_officer)
    await db.commit()
    await db.refresh(cua_officer)

    # Đầu độc cache của admin bằng ID THẬT của officer.
    await test_redis_client.lpush(f"user_inbox:{admin_user.id}", str(cua_officer.id))
    assert await test_redis_client.lrange(f"user_inbox:{admin_user.id}", 0, -1), (
        "Tiền đề hỏng: không seed được cache ⇒ ca sẽ đi nhánh MISS và không đo gì"
    )

    _, _, ket_qua = await notification_service.get_user_notifications(
        db=db, user_id=admin_user.id, skip=0, limit=50, unread_only=False,
    )

    chu_so_huu = {n.user_id for n in ket_qua}
    assert officer_user.id not in chu_so_huu, (
        f"A01: admin (id={admin_user.id}) đọc được notification của officer "
        f"(id={officer_user.id}) chỉ vì ID ấy nằm trong cache Redis của mình. "
        "Đường hydrate phải ràng buộc `Notification.user_id`, không được tin cache."
    )
    assert cua_officer.id not in {n.id for n in ket_qua}


# =============================================================================
# BT8 — log helper chỉ được nói điều ĐO ĐƯỢC
# =============================================================================


@pytest.mark.parametrize(
    "con_song,muc_ky_vong,cum_tu_bat_buoc",
    [
        (True, "warning", "remains active"),
        (False, "error", "requires rollback"),
    ],
    ids=["phien-con-active", "phien-can-rollback"],
)
async def test_bt8_log_dispatch_failure_khong_khang_dinh_dieu_chua_do(
    con_song: bool, muc_ky_vong: str, cum_tu_bat_buoc: str,
):
    """`Session.is_active` KHÔNG chứng minh một hàng nghiệp vụ còn tồn tại.

    Nó chỉ chứng minh giao dịch không ở trạng thái bắt buộc phải rollback. Câu
    "business data preserved" vì thế là SUY LUẬN, không phải phép đo — dù nó
    đúng trong phần lớn trường hợp. Helper chỉ được phát ngôn điều đo được, và
    phải nói rõ rằng tính bền của dữ liệu nghiệp vụ KHÔNG được khẳng định.

    Canh cả MỨC log lẫn NỘI DUNG, ở cả hai nhánh — một ca chỉ kiểm "helper có
    được gọi không" sẽ xanh kể cả khi thông điệp quay lại nói sai.
    """
    phien = MagicMock()
    phien.sync_session.is_active = con_song
    ghi_log = MagicMock()

    ket = nd.log_dispatch_failure(
        phien, RuntimeError("boom"), logger=ghi_log, lead_id=123,
    )
    assert ket is con_song

    goi = getattr(ghi_log, muc_ky_vong)
    khong_goi = getattr(ghi_log, "error" if muc_ky_vong == "warning" else "warning")
    assert goi.called, f"phải log ở mức `{muc_ky_vong}`"
    assert not khong_goi.called, "không được log ở mức còn lại"

    thong_diep = " ".join(str(a) for a in goi.call_args.args)
    assert cum_tu_bat_buoc in thong_diep, (
        f"thông điệp phải nêu trạng thái ĐO ĐƯỢC (`{cum_tu_bat_buoc}`); "
        f"thực tế: {thong_diep!r}"
    )
    assert "preserved" not in thong_diep or "NOT asserted" in thong_diep, (
        "không được khẳng định dữ liệu nghiệp vụ đã được bảo toàn — "
        f"đó là suy luận, không phải phép đo. Thông điệp: {thong_diep!r}"
    )


# =============================================================================
# BT9/BT10/BT11 — quan hệ chủ quyền KHÔNG được dựng từ thứ tự danh sách
# =============================================================================


class _KetQuaDaoHang:
    """Bọc kết quả THẬT, chỉ đảo thứ tự các HÀNG mà `fetchall()` trả về.

    Không giả lập CSDL: lệnh INSERT đã chạy thật, FK thật, id thật. Vật này
    mô phỏng đúng MỘT điều — CSDL trả các hàng `RETURNING` theo thứ tự khác
    thứ tự trong `VALUES`. Chuẩn SQL không hứa thứ tự ấy.
    """

    def __init__(self, hang):
        self._hang = list(hang)

    def fetchall(self):
        return list(self._hang)

    def __getattr__(self, ten):
        # fail-LOUD: nếu mã sản phẩm đổi cách tiêu thụ kết quả, ta muốn biết
        # ngay chứ không muốn một ca test âm thầm ngừng đo.
        raise AssertionError(
            f"`bulk_create` gọi `result.{ten}` — vật bọc này chỉ hiểu "
            "`fetchall()`. Cập nhật vật bọc, ĐỪNG bỏ ca test."
        )


def _hook_dao_thu_tu_returning(monkeypatch, db) -> dict:
    """Đảo thứ tự HÀNG `RETURNING` của lệnh INSERT vào bảng `notification`.

    Đặt ở `db.execute` chứ KHÔNG bọc `NotificationRepository.bulk_create`.
    Đây là khác biệt quyết định: sau bản vá, CHÍNH `bulk_create` là nơi ràng
    buộc `user_id` với `id`. Bọc bên NGOÀI nó là đảo những cặp ĐÃ tự mô tả —
    vô hại theo định nghĩa — nên một đột biến bên TRONG (`RETURNING id` rồi
    `zip` với `[v["user_id"] for v in values]`, vẫn giữ nguyên kiểu trả về và
    vẫn qua cổng fail-closed độ dài) sẽ KHÔNG bị bắt. Ở tầng này thì bị.
    """
    from sqlalchemy.sql.dml import Insert

    that = db.execute
    trang_thai = {"so_lan_dao": 0, "so_hang_dao": 0}

    async def _bao_boc(statement, *a, **k):
        ket = await that(statement, *a, **k)
        bang = getattr(statement, "table", None)
        if not isinstance(statement, Insert) or bang is None:
            return ket
        if bang.name != models.Notification.__tablename__:
            return ket
        hang = list(ket.fetchall())
        if len(hang) < 2:
            # Đảo một danh sách < 2 phần tử là phép đồng nhất — KHÔNG đếm, để
            # phép kiểm tiền đề bắt được ca vô nghĩa.
            return _KetQuaDaoHang(hang)
        trang_thai["so_lan_dao"] += 1
        trang_thai["so_hang_dao"] = len(hang)
        return _KetQuaDaoHang(reversed(hang))

    monkeypatch.setattr(db, "execute", _bao_boc)
    return trang_thai


async def _cap_delivery_notification(db: AsyncSession):
    """Trả `[(delivery.user_id, notification.user_id, delivery.id), ...]`."""
    rows = (await db.execute(text(
        "SELECT d.user_id, n.user_id, d.id "
        "FROM notification_delivery d "
        "JOIN notification n ON n.id = d.notification_id"
    ))).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


async def test_bt9_thu_tu_returning_dao_van_phai_ghep_dung_chu(
    db: AsyncSession, clear_redis_keys, monkeypatch,
    admin_user: models.User, officer_user: models.User,
):
    """`RETURNING` trả ngược thứ tự ⇒ quan hệ chủ quyền vẫn phải đúng.

    Bất biến DUY NHẤT: với MỌI hàng `notification_delivery` có
    `notification_id`, phải có `delivery.user_id == notification.user_id`.

    Không có bảo đảm hình thức nào rằng `INSERT ... VALUES (…),(…) RETURNING`
    trả về theo thứ tự đầu vào. Ca này ép đúng cảnh ấy thay vì chờ CSDL tình
    cờ đảo.
    """
    _cam_tac_dung_phu(monkeypatch)

    await _tao_rule(db, tieu_de=TIEU_DE_DB)
    await invalidate_rule_cache(SU_KIEN.value)

    nguoi_nhan = sorted({admin_user.id, officer_user.id})
    assert len(nguoi_nhan) == 2, "Tiền đề hỏng: cần ĐÚNG hai người nhận khác nhau"

    # Đặt hook SAU khi đã dựng xong rule: nó chặn `db.execute`, và ta chỉ muốn
    # nó chạm đúng lệnh INSERT vào `notification` của lượt dispatch.
    hook = _hook_dao_thu_tu_returning(monkeypatch, db)

    _, cb = await nd.dispatch(
        db=db, event=SU_KIEN,
        payload={
            "user_ids": nguoi_nhan, "lead_id": 909,
            "lead_name": "Kiểm thử", "actor_id": admin_user.id,
        },
        dedupe_key="bt9:909",
        rooms=[f"user_room_{nguoi_nhan[0]}"],
        strict=False,
    )
    await db.commit()
    assert cb is not None
    await cb()

    assert hook["so_lan_dao"] == 1, (
        "Tiền đề hỏng: không lần INSERT nào vào `notification` bị đảo ⇒ ca này "
        f"không đo gì (so_lan_dao={hook['so_lan_dao']})"
    )
    assert hook["so_hang_dao"] == 2, (
        f"Tiền đề hỏng: đảo {hook['so_hang_dao']} hàng là phép đồng nhất"
    )

    cap = await _cap_delivery_notification(db)
    assert len(cap) == 2, f"Tiền đề hỏng: mong 2 delivery có cha, đo được {len(cap)}"
    lech = [(du, nu, did) for du, nu, did in cap if du != nu]
    assert not lech, (
        "Quan hệ chủ quyền bị ghép lệch: (delivery.user_id, notification.user_id, "
        f"delivery.id) = {lech!r}. Bản đồ user↔notification đang dựa vào THỨ TỰ "
        "của `RETURNING`, thứ không có bảo đảm hình thức nào."
    )


async def test_bt10_cache_inbox_dung_chu_va_du_nguoi(
    db: AsyncSession, clear_redis_keys, monkeypatch, test_redis_client,
    admin_user: models.User, officer_user: models.User,
):
    """Cache inbox: đúng chủ VÀ đủ người — hai vế của cùng một bất biến.

    Khẳng định PHỦ ĐỊNH ("không có ID sai chủ") một mình là chưa đủ: gỡ hẳn
    bước nạp cache cũng thoả nó. Nên ca này khẳng định luôn chiều DƯƠNG —
    mỗi người nhận hợp lệ phải có ĐÚNG notification của mình trong cache.
    """
    ghi = _cam_tac_dung_phu(monkeypatch)

    await _tao_rule(db, tieu_de=TIEU_DE_DB)
    await invalidate_rule_cache(SU_KIEN.value)

    nguoi_nhan = sorted({admin_user.id, officer_user.id})
    _hook_dao_thu_tu_returning(monkeypatch, db)

    _, cb = await nd.dispatch(
        db=db, event=SU_KIEN,
        payload={
            "user_ids": nguoi_nhan, "lead_id": 910,
            "lead_name": "Kiểm thử", "actor_id": admin_user.id,
        },
        dedupe_key="bt10:910",
        rooms=[f"user_room_{nguoi_nhan[0]}"],
        strict=False,
    )
    await db.commit()
    assert cb is not None
    await cb()

    # Callback đã chạy QUA bước nạp cache: bước 7.5 nằm GIỮA hai mốc này.
    # Không có hai mốc ấy thì "cache rỗng" và "callback không chạy" trông
    # giống hệt nhau — `_prepend_to_inbox_cache` nuốt mọi lỗi của chính nó.
    assert ghi["domain_emit"] == 1, "callback chưa tới bước phát domain event"
    assert ghi["send_channel"] == 1, "callback thoát sớm, chưa tới bước 8a"

    async with AsyncSessionLocal() as phien_moi:
        cua_ai = dict((await phien_moi.execute(text(
            "SELECT user_id, id FROM notification"
        ))).fetchall())
    assert set(cua_ai) == set(nguoi_nhan), (
        f"Tiền đề hỏng: mong notification cho {nguoi_nhan}, đo được {sorted(cua_ai)}"
    )

    for u in nguoi_nhan:
        cache = await test_redis_client.lrange(f"user_inbox:{u}", 0, -1)
        # chiều DƯƠNG
        assert str(cua_ai[u]) in cache, (
            f"user {u} KHÔNG có notification của mình (id={cua_ai[u]}) trong "
            f"cache inbox. Cache đọc được: {cache!r}"
        )
        # chiều PHỦ ĐỊNH
        la = [x for x in cache if int(x) != cua_ai[u]]
        assert not la, (
            f"cache inbox của user {u} chứa ID KHÔNG thuộc về mình: {la!r}"
        )


async def test_bt11_trang_thai_delivery_phai_bam_dung_nguoi(
    db: AsyncSession, clear_redis_keys, monkeypatch,
    admin_user: models.User, officer_user: models.User,
):
    """`sent`/`failed` phải rơi vào delivery của ĐÚNG người.

    Dựng hai action cùng kênh `browser` với người nhận RỜI NHAU và THỨ TỰ
    NGƯỢC nhau, để `browser_recipients` (đã `sorted()`) khác thứ tự
    `browser_del_ids` (nối theo thứ tự action):

        step 1  `specific_users`  -> officer  (id LỚN)   => delivery đầu tiên
        step 2  `all_admins`      -> admin    (id NHỎ)   => delivery thứ hai

    ⇒ recipients = [admin, officer] nhưng del_ids = [d_officer, d_admin].
    Ghép theo vị trí sẽ đánh `failed` của admin lên delivery của officer.

    Đọc lại bằng PHIÊN MỚI vì trạng thái được ghi ở một session riêng.
    """
    assert admin_user.id < officer_user.id, (
        "Tiền đề hỏng: ca này cần admin có id NHỎ hơn officer, nếu không hai "
        "thứ tự trùng nhau và phép ghép lệch không lộ ra"
    )
    # Một người THẤT BẠI, một người THÀNH CÔNG — tất định. `error_message`
    # phải là chuỗi THẬT: nó rơi thẳng vào cột Text `error_reason`, và cả khối
    # bước 8a nằm trong `except Exception` nên một MagicMock ở đó sẽ bị nuốt
    # im lặng, để cả hai hàng ở `queued` và ca test xanh vì lý do sai.
    ghi = _cam_tac_dung_phu(monkeypatch, ket_qua_kenh=MagicMock(
        sent_count=1,
        failed_ids=[admin_user.id],
        error_message="tiêm lỗi kênh",
    ))

    rule = models.NotificationRule(
        event=SU_KIEN.value,
        title_template=TIEU_DE_DB,
        message_template="Nội dung kiểm thử lead $lead_id",
        notification_type="info",
        recipient_config={"resolver_type": "specific_users", "params": {}},
        condition=None,
        enabled=True,
    )
    db.add(rule)
    await db.flush()
    db.add(models.NotificationAction(
        rule_id=rule.id, step=1, channel="browser",
        content_mode="inherit_default",
        recipient_config={"resolver_type": "specific_users", "params": {}},
    ))
    db.add(models.NotificationAction(
        rule_id=rule.id, step=2, channel="browser",
        content_mode="inherit_default",
        recipient_config={"resolver_type": "all_admins", "params": {}},
    ))
    await db.commit()
    await invalidate_rule_cache(SU_KIEN.value)

    _, cb = await nd.dispatch(
        db=db, event=SU_KIEN,
        payload={
            "user_ids": [officer_user.id], "lead_id": 911,
            "lead_name": "Kiểm thử", "actor_id": admin_user.id,
        },
        dedupe_key="bt11:911",
        rooms=[f"user_room_{officer_user.id}"],
        strict=False,
    )
    await db.commit()
    assert cb is not None
    await cb()

    async with AsyncSessionLocal() as phien_moi:
        rows = (await phien_moi.execute(text(
            "SELECT user_id, status FROM notification_delivery "
            "WHERE channel = 'browser' ORDER BY id"
        ))).fetchall()
    trang_thai = {r[0]: r[1] for r in rows}

    assert set(trang_thai) == {admin_user.id, officer_user.id}, (
        f"Tiền đề hỏng: mong delivery browser cho cả hai người, đo được "
        f"{trang_thai!r}"
    )

    # ── TIỀN ĐỀ CHỐNG-TỰ-ĐÚNG: hai thứ tự phải THẬT SỰ khác nhau ──────────
    # Không có phép này thì ca test có thể xanh vì ghép-theo-vị-trí và
    # ghép-theo-bản-đồ tình cờ cho cùng kết quả.
    thu_tu_ghi = [r[0] for r in rows]            # ≈ `browser_del_ids`
    thu_tu_gui = ghi["recipient_ids"]            # = `browser_recipients`
    assert thu_tu_ghi == [officer_user.id, admin_user.id], (
        f"Tiền đề hỏng: thứ tự GHI delivery không như thiết kế: {thu_tu_ghi!r}"
    )
    assert thu_tu_gui == [admin_user.id, officer_user.id], (
        f"Tiền đề hỏng: `browser_recipients` không được sắp xếp: {thu_tu_gui!r}"
    )
    assert thu_tu_gui != thu_tu_ghi, (
        "Tiền đề hỏng: hai thứ tự TRÙNG nhau ⇒ ghép theo vị trí và ghép theo "
        "bản đồ cho cùng kết quả, ca này không chứng minh gì."
    )
    assert trang_thai[admin_user.id] == "failed", (
        f"admin (id={admin_user.id}) được kênh báo THẤT BẠI nhưng delivery của "
        f"anh ta mang status {trang_thai[admin_user.id]!r}. Trạng thái đang bị "
        "ghép theo VỊ TRÍ giữa `browser_recipients` (đã sorted) và "
        "`browser_del_ids` (theo thứ tự action) — hai thứ tự khác nhau."
    )
    assert trang_thai[officer_user.id] == "sent", (
        f"officer (id={officer_user.id}) gửi THÀNH CÔNG nhưng delivery mang "
        f"status {trang_thai[officer_user.id]!r} — nhận nhầm kết quả của người khác."
    )
    assert ghi["domain_emit"] >= 0


async def test_bt12_returning_hut_hang_phai_huy_ca_su_kien(
    db: AsyncSession, clear_redis_keys, monkeypatch,
    seeded_dependencies: dict, admin_user: models.User, officer_user: models.User,
):
    """`RETURNING` trả THIẾU hàng ⇒ huỷ cả sự kiện, không ghi bó nửa vời.

    Bản đồ `user_id → notification_id` dựng từ kết quả trả về. Nếu kết quả hụt
    một hàng thì bản đồ mất phần tử một cách IM LẶNG: người nhận ấy có hàng
    `notification` trong CSDL nhưng không ai biết id của nó, nên không delivery
    nào, không cache nào, và khối dọn mồ côi cũng không thấy nó.

    Hàng rào fail-closed trong `_bulk_create_notifications` phải ném ra để
    `dispatch` huỷ cả sự kiện. Không có ca này thì hàng rào ấy là một dòng
    không phép kiểm nào canh.
    """
    from app.repositories.notification_repository import NotificationRepository

    _cam_tac_dung_phu(monkeypatch)
    that = NotificationRepository.bulk_create
    trang_thai = {"so_lan": 0}

    async def _bao_boc(self, values):
        cap = await that(self, values)
        trang_thai["so_lan"] += 1
        return cap[:-1]  # hụt ĐÚNG một hàng

    monkeypatch.setattr(NotificationRepository, "bulk_create", _bao_boc)

    await _tao_rule(db, tieu_de=TIEU_DE_DB)
    await invalidate_rule_cache(SU_KIEN.value)

    lead = models.Lead(
        full_name="Nghiệp vụ phải sống (hụt hàng)", phone="0805000081",
        source="website", unit_id=seeded_dependencies["unit_id"],
        consultation_status_id=seeded_dependencies["initial_status_id"],
        pipeline_stage_id=seeded_dependencies["stage_id"],
    )
    db.add(lead)
    await db.flush()
    lead_id = lead.id

    ids, _ = await nd.dispatch(
        db=db, event=SU_KIEN,
        payload={
            "user_ids": sorted({admin_user.id, officer_user.id}),
            "lead_id": lead_id, "lead_name": "Kiểm thử",
            "actor_id": admin_user.id,
        },
        dedupe_key="bt12:hut",
        rooms=[f"user_room_{admin_user.id}"],
        strict=False,
    )
    await db.commit()

    assert trang_thai["so_lan"] == 1, "Tiền đề hỏng: hook không chạy"
    assert ids == [], (
        f"Kết quả trả về hụt hàng mà dispatch vẫn báo {ids!r} notification"
    )
    assert await _dem(db, models.Notification) == 0, (
        "Bó nửa vời được commit: có hàng notification mà bản đồ chủ quyền "
        "không dựng đủ ⇒ hàng ấy vĩnh viễn không ai giao và không ai dọn."
    )
    assert await _dem(db, models.NotificationDelivery) == 0
    async with AsyncSessionLocal() as phien_moi:
        assert await phien_moi.get(models.Lead, lead_id) is not None, (
            "Huỷ sự kiện đã cuộn vượt phạm vi và nuốt cả dữ liệu nghiệp vụ"
        )
