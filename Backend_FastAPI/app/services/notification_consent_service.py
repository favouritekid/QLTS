# app/services/notification_consent_service.py
"""
Service layer for Notification Consent management.

Handles business logic for consent CRUD and bulk import.
No FastAPI imports — raises domain exceptions only.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.notification_consent_repository import NotificationConsentRepository
from app.repositories.notification_consent_history_repository import NotificationConsentHistoryRepository

log = structlog.get_logger(__name__)

# Required CSV columns for bulk import
_REQUIRED_CSV_COLS = {"channel", "source_type", "source_id", "consent_status"}


async def list_consents(
    db: AsyncSession,
    *,
    channel: Optional[str] = None,
    source_type: Optional[str] = None,
    consent_status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> Tuple[list, int]:
    """List consent records with optional filters."""
    repo = NotificationConsentRepository(db)
    return await repo.list_consents(
        channel=channel,
        source_type=source_type,
        consent_status=consent_status,
        skip=skip,
        limit=limit,
    )


async def upsert_consent(
    db: AsyncSession,
    *,
    data: Dict[str, Any],
    actor_id: int,
) -> Any:
    """
    Upsert a single consent record.

    Enriches data with timestamp fields based on consent_status.
    Caller must call db.commit() after.
    """
    repo = NotificationConsentRepository(db)

    now = datetime.now(timezone.utc)
    data["granted_by"] = actor_id

    if data.get("consent_status") == "granted":
        data["granted_at"] = now
        data["revoked_at"] = None
    elif data.get("consent_status") == "revoked":
        data["revoked_at"] = now

    return await repo.upsert_latest(data)


async def grant_implied_zalo_consent(
    db: AsyncSession,
    lead,
    *,
    actor_id: Optional[int] = None,
) -> None:
    """Grant Zalo ZNS consent for a newly-registered lead (implied consent).

    Rationale: lead đã chủ động cung cấp số điện thoại qua luồng đăng ký
    (mẫu giấy / form online / referral). Theo Nghị định 13/2023 Điều 17.2,
    xử lý DLCN "cần thiết cho việc thực hiện hợp đồng/yêu cầu của chủ thể
    dữ liệu" không yêu cầu consent tường minh riêng. Việc ghi nhận consent
    row ở đây có 2 tác dụng:

    1. **Audit trail**: lưu `consent_source=implied_by_registration` +
       notes trích xuất source/created_via để chứng minh basis nếu bị audit.
    2. **Opt-out mechanism**: nếu lead yêu cầu dừng Zalo, admin set
       `consent_status=revoked` qua /admin/notification-consents → channel
       gate tự block.

    Non-blocking: log + silent skip nếu thất bại. Caller phải không expect
    consent row tồn tại 100% (vẫn phải check qua is_consent_granted trong
    dispatcher).
    """
    if not getattr(lead, "phone", None):
        return  # No phone → no Zalo delivery possible anyway
    try:
        from app.utils.phone_helpers import to_zalo_phone

        normalized = to_zalo_phone(lead.phone)
        created_at = getattr(lead, "created_at", None)
        created_str = created_at.strftime("%Y-%m-%d") if created_at else "N/A"
        created_via = getattr(lead, "created_via", None) or "unknown"
        source = getattr(lead, "source", None) or "unknown"
        await upsert_consent(
            db,
            data={
                "channel": "zalo",
                "source_type": "lead",
                "source_id": lead.id,
                "normalized_phone": normalized,
                "consent_status": "granted",
                "consent_source": "implied_by_registration",
                "notes": (
                    f"Lead đăng ký {created_str} qua source={source} "
                    f"created_via={created_via}. NĐ 13/2023 Đ.17.2."
                ),
            },
            actor_id=actor_id or 0,
        )
    except Exception as e:
        # Never block lead creation on consent grant failure.
        log.warning(
            "grant_implied_zalo_consent failed, lead creation unblocked",
            lead_id=getattr(lead, "id", None),
            error=str(e),
        )


async def bulk_import_consents(
    db: AsyncSession,
    *,
    file_content: bytes,
    actor_id: int,
) -> Dict[str, Any]:
    """
    Parse CSV content and bulk-upsert consent records.

    Returns a structured result dict with processed/granted/revoked/skipped/errors.
    Caller must call db.commit() after.
    """
    # Decode
    try:
        text = file_content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))

    # Validate headers
    if not reader.fieldnames:
        return {
            "processed": 0, "granted": 0, "revoked": 0, "skipped": 0,
            "errors": [{"line": 0, "message": "Empty CSV or missing headers"}],
        }

    missing = _REQUIRED_CSV_COLS - set(reader.fieldnames)
    if missing:
        return {
            "processed": 0, "granted": 0, "revoked": 0, "skipped": 0,
            "errors": [{"line": 0, "message": f"Missing required columns: {', '.join(sorted(missing))}"}],
        }

    # Parse rows
    now = datetime.now(timezone.utc)
    rows: List[Dict[str, Any]] = []
    parse_errors: List[Dict[str, Any]] = []

    for i, row in enumerate(reader, start=2):
        try:
            source_id = int(row["source_id"])
        except (ValueError, TypeError):
            parse_errors.append({"line": i, "message": f"Invalid source_id: {row.get('source_id')}"})
            continue

        consent_status = row.get("consent_status", "granted").strip().lower()
        if consent_status not in ("granted", "revoked"):
            parse_errors.append({"line": i, "message": f"Invalid consent_status: {consent_status}"})
            continue

        data = {
            "channel": row["channel"].strip(),
            "source_type": row["source_type"].strip(),
            "source_id": source_id,
            "consent_status": consent_status,
            "consent_source": row.get("consent_source", "csv_import").strip() or "csv_import",
            "granted_by": actor_id,
            "notes": row.get("notes", "").strip() or None,
            "normalized_phone": row.get("normalized_phone", "").strip() or None,
            "normalized_email": row.get("normalized_email", "").strip() or None,
        }

        if consent_status == "granted":
            data["granted_at"] = now
        elif consent_status == "revoked":
            data["revoked_at"] = now

        rows.append(data)

    # Bulk upsert
    repo = NotificationConsentRepository(db)
    summary = await repo.bulk_upsert(rows)

    # Merge parse errors
    all_errors = parse_errors + summary.get("errors", [])

    return {
        "processed": summary["processed"],
        "granted": summary["granted"],
        "revoked": summary["revoked"],
        "skipped": summary["skipped"] + len(parse_errors),
        "errors": all_errors,
    }


async def list_entity_consent_history(
    db: AsyncSession,
    *,
    source_type: str,
    source_id: int,
    skip: int = 0,
    limit: int = 50,
) -> Tuple[list, int]:
    """List consent history for a given entity."""
    repo = NotificationConsentHistoryRepository(db)
    return await repo.list_for_entity(
        source_type=source_type,
        source_id=source_id,
        skip=skip,
        limit=limit,
    )


async def list_consent_history(
    db: AsyncSession,
    *,
    consent_id: int,
    skip: int = 0,
    limit: int = 50,
) -> Tuple[list, int]:
    """List history entries for a specific consent record."""
    repo = NotificationConsentHistoryRepository(db)
    return await repo.list_for_consent(
        consent_id=consent_id,
        skip=skip,
        limit=limit,
    )
