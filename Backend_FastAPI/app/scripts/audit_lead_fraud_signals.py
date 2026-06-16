# app/scripts/audit_lead_fraud_signals.py
"""Giám sát tín hiệu gian lận của officer trên lead được phân phối tự động —
SĐT / nguồn / CTV. Read-only. Xem Documents/LEAD_ANTIFRAUD_PLAN.md §6.2.

Bối cảnh: officer có quyền sửa lead được-phân-cho-mình (PUT /api/leads/{id}).
3 vector:

  V1 (hoa hồng CTV khống) — officer gán referrer_id (CTV do CHÍNH mình quản lý)
     / đổi source sang 'referral' SAU khi lead đã auto-assign → CTV ăn hoa hồng
     khống. Tín hiệu MẠNH = có audit action='flagged' hoặc đổi source→referral
     trên lead mà CTV thuộc officer giữ lead. (referral-gốc, gán lúc tạo = bình
     thường, KHÔNG cờ.)
  V2 (bắt cóc SĐT) — officer đổi 'phone' nhiều lần; hoặc gom cùng 1 SĐT mới cho
     >1 lead (kéo khách về 1 số). Gom số = tín hiệu MẠNH.
  V3 (thổi nguồn) — officer đổi 'source' hàng loạt / sang 'referral' (thổi
     lead_score). Tín hiệu YẾU (chỉ để soát, không tính exit code).

Chạy:
    docker compose exec backend python -m app.scripts.audit_lead_fraud_signals
    # one-off: docker compose run --rm --no-deps backend \
    #     python -m app.scripts.audit_lead_fraud_signals

Exit code: 0 nếu không có tín hiệu MẠNH (V1 gán-sau / V2 gom số), 1 nếu có.
Dùng được làm cổng cron/alert hoặc chạy trước mỗi kỳ chốt hoa hồng.

SĐT được mask (app.utils.masking.mask_phone — chỉ hiện 4 số cuối) trong output.
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.utils.masking import mask_phone

# === Ngưỡng giám sát (quyết định mở — tinh chỉnh theo baseline, plan §10) ===
WINDOW_DAYS = 30          # cửa sổ đếm đổi SĐT
PHONE_CHANGE_THRESHOLD = 3  # officer đổi 'phone' >= N lần / cửa sổ → đáng chú ý


# V1: lead có referrer_id mà CTV do CHÍNH officer giữ lead quản lý, kèm dấu hiệu
# "gán sau" (audit flagged HOẶC từng đổi source→referral). source_at_create
# không có trong audit → dùng has_flag/source_changed_to_referral để phân biệt.
_V1_SQL = text(
    """
    SELECT l.id AS lead_id,
           uo.username AS officer,
           l.referrer_id AS ctv_id,
           l.source, l.validity_status, l.status,
           EXISTS (SELECT 1 FROM entity_audit_log a
                   WHERE a.entity_type='Lead' AND a.entity_id=l.id
                     AND a.action='flagged') AS has_flag,
           EXISTS (SELECT 1 FROM entity_audit_log a
                   WHERE a.entity_type='Lead' AND a.entity_id=l.id
                     AND a.action='updated'
                     AND a.changes->'source'->>'new'='referral') AS src_to_referral
    FROM lead l
    JOIN collaborator c ON c.id = l.referrer_id
    LEFT JOIN "user" uo ON uo.id = l.assigned_officer_id
    WHERE l.referrer_id IS NOT NULL AND l.deleted_at IS NULL
      AND (
        -- CTV thuộc officer ĐANG giữ lead (còn assigned)
        c.managed_by_officer_id = l.assigned_officer_id
        -- HOẶC lead từng bị cờ (soft-warn) — bắt cả case officer "rút ruột" rồi
        -- offering-change reset assigned_officer_id=NULL (so sánh '=NULL' luôn false).
        OR EXISTS (SELECT 1 FROM entity_audit_log a
                   WHERE a.entity_type='Lead' AND a.entity_id=l.id
                     AND a.action='flagged')
      )
    ORDER BY has_flag DESC, src_to_referral DESC, l.id
    """
)

# V1b: hoa hồng đã phát sinh cho CTV do MỘT officer quản lý (mất tiền thật).
# JOIN theo cr.collaborator_id (CTV THỰC nhận hoa hồng), KHÔNG theo l.referrer_id
# hiện tại — nếu không sẽ bỏ sót case officer gán CTV → commission fires → officer
# revert referrer về NULL/CTV khác (lúc đó l.referrer_id không còn khớp).
_V1_COMMISSION_SQL = text(
    """
    SELECT cr.lead_id, cr.collaborator_id, cr.amount, cr.status,
           cr.created_at::date AS d,
           c.managed_by_officer_id AS ctv_officer,
           l.assigned_officer_id AS lead_officer
    FROM commission_record cr
    JOIN collaborator c ON c.id = cr.collaborator_id
    LEFT JOIN lead l ON l.id = cr.lead_id
    WHERE c.managed_by_officer_id IS NOT NULL
    ORDER BY cr.created_at DESC
    """
)

# V2a: officer đổi 'phone' >= ngưỡng trong cửa sổ.
_V2_FREQ_SQL = text(
    """
    SELECT u.username,
           count(*) AS phone_changes,
           count(DISTINCT a.entity_id) AS leads_touched
    FROM entity_audit_log a
    JOIN "user" u ON u.id = a.actor_user_id
    WHERE a.entity_type='Lead' AND a.action='updated' AND a.changes ? 'phone'
      AND a.created_at >= now() - make_interval(days => :days)
    GROUP BY u.username
    HAVING count(*) >= :threshold
    ORDER BY phone_changes DESC
    """
)

# V2b: cùng 1 SĐT mới được gán cho >1 lead (gom khách về 1 số) — tín hiệu MẠNH.
_V2_FANIN_SQL = text(
    """
    SELECT a.changes->'phone'->>'new' AS new_phone,
           count(DISTINCT a.entity_id) AS n_leads,
           string_agg(DISTINCT u.username, ',') AS actors
    FROM entity_audit_log a
    JOIN "user" u ON u.id = a.actor_user_id
    WHERE a.entity_type='Lead' AND a.action='updated' AND a.changes ? 'phone'
      AND a.changes->'phone'->>'new' IS NOT NULL
    GROUP BY a.changes->'phone'->>'new'
    HAVING count(DISTINCT a.entity_id) > 1
    ORDER BY n_leads DESC
    """
)

# V3: officer đổi 'source' (đặc biệt sang 'referral').
_V3_SQL = text(
    """
    SELECT u.username,
           count(*) FILTER (
               WHERE a.changes->'source'->>'new'='referral'
           ) AS to_referral,
           count(*) AS source_changes
    FROM entity_audit_log a
    JOIN "user" u ON u.id = a.actor_user_id
    WHERE a.entity_type='Lead' AND a.action='updated' AND a.changes ? 'source'
    GROUP BY u.username
    HAVING count(*) > 0
    ORDER BY to_referral DESC, source_changes DESC
    """
)


async def audit() -> int:
    async with AsyncSessionLocal() as session:
        v1 = (await session.execute(_V1_SQL)).mappings().all()
        v1_comm = (await session.execute(_V1_COMMISSION_SQL)).mappings().all()
        v2_freq = (
            await session.execute(
                _V2_FREQ_SQL, {"days": WINDOW_DAYS, "threshold": PHONE_CHANGE_THRESHOLD}
            )
        ).mappings().all()
        v2_fanin = (await session.execute(_V2_FANIN_SQL)).mappings().all()
        v3 = (await session.execute(_V3_SQL)).mappings().all()

    strong = 0  # đếm tín hiệu MẠNH → exit code

    print("=" * 64)
    print("[V1] Hoa hồng CTV — lead có CTV do CHÍNH officer giữ lead quản lý")
    print("=" * 64)
    v1_suspicious = [r for r in v1 if r["has_flag"] or r["src_to_referral"]]
    v1_legit = [r for r in v1 if not (r["has_flag"] or r["src_to_referral"])]
    for r in v1:
        _susp = r["has_flag"] or r["src_to_referral"]
        tag = "[!] GÁN-SAU" if _susp else "ok(referral-gốc)"
        print(
            f"  lead#{r['lead_id']:<6} officer={r['officer'] or '-':<16} "
            f"ctv#{r['ctv_id']:<4} src={r['source']:<12} "
            f"validity={r['validity_status']:<10} "
            f"flag={r['has_flag']} src->ref={r['src_to_referral']}  {tag}"
        )
    print(
        f"  -> {len(v1_suspicious)} nghi vấn gán-sau / "
        f"{len(v1_legit)} referral-gốc / {len(v1)} tổng"
    )
    strong += len(v1_suspicious)

    if v1_comm:
        print("  ⛔ COMMISSION đã phát sinh cho nhóm này (kiểm tra mất tiền):")
        for r in v1_comm:
            print(
                f"     lead#{r['lead_id']} ctv#{r['collaborator_id']} "
                f"ctv_officer={r['ctv_officer']} lead_officer={r['lead_officer']} "
                f"amount={r['amount']} status={r['status']} {r['d']}"
            )
        strong += len(v1_comm)
    else:
        print("  (commission_record: 0 row liên quan)")

    print()
    print("=" * 64)
    print(
        f"[V2a] Officer đổi 'phone' >= {PHONE_CHANGE_THRESHOLD} lần "
        f"/ {WINDOW_DAYS} ngày"
    )
    print("=" * 64)
    if v2_freq:
        for r in v2_freq:
            print(
                f"  {r['username']:<18} phone_changes={r['phone_changes']:<4} "
                f"leads={r['leads_touched']}  (đáng chú ý — soát thủ công)"
            )
    else:
        print("  (không có)")

    print()
    print("=" * 64)
    print("[V2b] Gom NHIỀU lead về CÙNG 1 SĐT mới (tín hiệu MẠNH)")
    print("=" * 64)
    if v2_fanin:
        for r in v2_fanin:
            print(
                f"  [!] {mask_phone(r['new_phone'])}  n_leads={r['n_leads']} "
                f" actors={r['actors']}"
            )
        strong += len(v2_fanin)
    else:
        print("  (không có)")

    print()
    print("=" * 64)
    print("[V3] Officer đổi 'source' (→referral thổi điểm — tín hiệu yếu, để soát)")
    print("=" * 64)
    if v3:
        for r in v3:
            print(
                f"  {r['username']:<18} ->referral={r['to_referral']:<4} "
                f"total_source_changes={r['source_changes']}"
            )
    else:
        print("  (không có)")

    print()
    if strong == 0:
        print("[audit] OK — 0 tín hiệu MẠNH (V1 gán-sau / V2 gom số).")
        return 0
    print(f"[audit] FAIL — {strong} tín hiệu MẠNH cần điều tra thủ công.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(audit()))
