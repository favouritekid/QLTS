# tests/integration/test_sms_retention.py
"""
Integration test §16.9 retention (SMS Phase 2 deep-engagement).

`cleanup_sms_interest_events_task` / `_purge_old_interest_events` dọn event
tracking chi tiết (`sms_landing_session` + `sms_program_view` cascade) cũ hơn
`SMS_INTEREST_EVENT_RETENTION_DAYS`, GIỮ aggregate `sms_contact_program_interest`
(data-minimization; profile lâu dài không đổi vì view quá cũ có recency≈0).

Chạy one-off container (CLAUDE.md).
"""
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import text

from app.config import settings
from app.database import AsyncSessionLocal
from app.tasks.sms_tasks import _purge_old_interest_events

API = "/api/sms"


async def _mk_contact(client, h, phone: str) -> int:
    r = await client.post(
        f"{API}/contacts",
        json={"full_name": "Retention QA", "phone": phone},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_retention_task_registered():
    """Task + beat entry + config key khớp — điểm tích hợp Celery beat THẬT
    (chống: đổi/xoá beat entry, hoặc typo tên config trong task body)."""
    from app.celery_app import celery_app
    from app.tasks import cleanup_sms_interest_events_task

    assert (
        cleanup_sms_interest_events_task.name
        == "cleanup_sms_interest_events_task"
    )
    assert isinstance(settings.SMS_INTEREST_EVENT_RETENTION_DAYS, int)
    entry = celery_app.conf.beat_schedule.get(
        "cleanup-sms-interest-events-daily"
    )
    assert entry is not None, "beat entry retention bị xoá/đổi tên"
    assert entry["task"] == "cleanup_sms_interest_events_task"


async def test_views_for_interest_windowed_excludes_old(
    client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies
):
    """`views_for_interest(since=cutoff)` CHỈ trả view trong cửa sổ retention →
    recompute aggregate KHÔNG đếm view ngoài cửa sổ, nên purge (§16.9) không làm
    tụt view_count/total_dwell khi contact tương tác lại (finding P2)."""
    from app.repositories.sms_engagement_repository import (
        SmsEngagementRepository,
    )

    h = admin_token_headers
    cid = await _mk_contact(client, h, "0987611002")
    now = datetime.now(timezone.utc)
    retention = settings.SMS_INTEREST_EVENT_RETENTION_DAYS
    cutoff = now - timedelta(days=retention)

    async with AsyncSessionLocal() as s:
        prog = (
            await s.execute(
                text("SELECT id FROM major_program ORDER BY id LIMIT 1")
            )
        ).scalar()
        assert prog is not None
        for tag, ts, dwell in (
            ("old", now - timedelta(days=retention + 30), 100),  # ngoài cửa sổ
            ("new", now - timedelta(days=5), 20),  # trong cửa sổ
        ):
            sid = (
                await s.execute(
                    text(
                        "INSERT INTO sms_landing_session (contact_id, "
                        "session_token_hash, started_at) VALUES (:c,:t,:ts) "
                        "RETURNING id"
                    ),
                    {"c": cid, "t": f"w_{tag}_{cid}", "ts": ts},
                )
            ).scalar()
            await s.execute(
                text(
                    "INSERT INTO sms_program_view (session_id, contact_id, "
                    "program_name_snapshot, major_program_id, dwell_seconds, "
                    "viewed_at) VALUES (:s,:c,:n,:p,:d,:ts)"
                ),
                {"s": sid, "c": cid, "n": "Ngành Y", "p": prog,
                 "d": dwell, "ts": ts},
            )
        await s.commit()

        views = await SmsEngagementRepository(s).views_for_interest(
            cid, prog, since=cutoff
        )
    # CHỈ view mới (in-window); view cũ >retention bị loại dù còn tồn tại (trước
    # purge) → recompute không đếm nó → purge nó cũng không đổi aggregate.
    assert len(views) == 1, "chỉ view trong cửa sổ retention"
    assert views[0][0] == 20, "phải là view mới (dwell=20), không phải view cũ"


async def test_purge_old_events_keeps_recent_and_aggregate(
    client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies
):
    """Session quá hạn + program_view (cascade) bị xoá; session trong hạn GIỮ;
    aggregate interest GIỮ (không cascade)."""
    h = admin_token_headers
    cid = await _mk_contact(client, h, "0987611001")
    retention = settings.SMS_INTEREST_EVENT_RETENTION_DAYS
    now = datetime.now(timezone.utc)
    old_at = now - timedelta(days=retention + 30)  # quá hạn
    new_at = now - timedelta(days=10)  # trong hạn

    async with AsyncSessionLocal() as s:
        prog = (
            await s.execute(
                text("SELECT id FROM major_program ORDER BY id LIMIT 1")
            )
        ).scalar()
        assert prog is not None, "cần 1 major_program seed cho FK interest"

        old_sid = (
            await s.execute(
                text(
                    "INSERT INTO sms_landing_session "
                    "(contact_id, session_token_hash, started_at) "
                    "VALUES (:c, :t, :ts) RETURNING id"
                ),
                {"c": cid, "t": f"h_old_{cid}", "ts": old_at},
            )
        ).scalar()
        new_sid = (
            await s.execute(
                text(
                    "INSERT INTO sms_landing_session "
                    "(contact_id, session_token_hash, started_at) "
                    "VALUES (:c, :t, :ts) RETURNING id"
                ),
                {"c": cid, "t": f"h_new_{cid}", "ts": new_at},
            )
        ).scalar()
        await s.execute(
            text(
                "INSERT INTO sms_program_view "
                "(session_id, contact_id, program_name_snapshot, "
                "major_program_id, viewed_at) VALUES (:s, :c, :n, :p, :ts)"
            ),
            {"s": old_sid, "c": cid, "n": "Ngành X", "p": prog, "ts": old_at},
        )
        await s.execute(
            text(
                "INSERT INTO sms_contact_program_interest "
                "(contact_id, major_program_id, view_count, interest_score) "
                "VALUES (:c, :p, 1, 0.5)"
            ),
            {"c": cid, "p": prog},
        )
        await s.commit()

    # Tiền-điều-kiện: view của session cũ TỒN TẠI trước purge → assert
    # old_view==0 sau purge mới chứng minh CASCADE thật (không phải chưa từng có).
    async with AsyncSessionLocal() as s:
        pre_view = (
            await s.execute(
                text(
                    "SELECT count(*) FROM sms_program_view WHERE session_id=:i"
                ),
                {"i": old_sid},
            )
        ).scalar()
    assert pre_view == 1, "seed program_view cho session cũ phải tồn tại"

    # Chạy ĐÚNG helper của task
    async with AsyncSessionLocal() as s:
        deleted = await _purge_old_interest_events(s, retention)
        await s.commit()
    assert deleted >= 1  # ít nhất session quá hạn

    async with AsyncSessionLocal() as s:
        old_sess = (
            await s.execute(
                text("SELECT count(*) FROM sms_landing_session WHERE id=:i"),
                {"i": old_sid},
            )
        ).scalar()
        old_view = (
            await s.execute(
                text(
                    "SELECT count(*) FROM sms_program_view WHERE session_id=:i"
                ),
                {"i": old_sid},
            )
        ).scalar()
        new_sess = (
            await s.execute(
                text("SELECT count(*) FROM sms_landing_session WHERE id=:i"),
                {"i": new_sid},
            )
        ).scalar()
        interest = (
            await s.execute(
                text(
                    "SELECT count(*) FROM sms_contact_program_interest "
                    "WHERE contact_id=:c"
                ),
                {"c": cid},
            )
        ).scalar()

    assert old_sess == 0, "session quá hạn phải bị xoá"
    assert old_view == 0, "program_view của session cũ phải cascade-xoá"
    assert new_sess == 1, "session trong hạn phải GIỮ"
    assert interest == 1, "aggregate interest phải GIỮ (không cascade)"
