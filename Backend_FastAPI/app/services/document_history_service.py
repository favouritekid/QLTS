"""GĐ1b K2 — lịch sử từng giấy (đặc tả bản 3.6 §4.7). Chỉ đọc. Quyền + phạm vi ở ``deps.get_admission_for_document_history``."""
from __future__ import annotations

from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.utils.exceptions import ResourceNotFoundError


async def get_document_history(db: AsyncSession, profile_id: int, document_row_id: int) -> Dict[str, Any]:
    doc = (
        await db.execute(
            select(models.ProfileDocument)
            .where(models.ProfileDocument.id == document_row_id, models.ProfileDocument.profile_id == profile_id)
            .options(selectinload(models.ProfileDocument.document_type))
        )
    ).scalar_one_or_none()
    if doc is None or doc.category != "path":
        raise ResourceNotFoundError("Document not found")
    logs = (
        await db.execute(
            select(models.DocumentAuditLog)
            .where(models.DocumentAuditLog.profile_document_id == document_row_id)
            .order_by(models.DocumentAuditLog.created_at, models.DocumentAuditLog.id)
        )
    ).scalars().all()
    actor_ids = {l.actor_user_id for l in logs if l.actor_user_id is not None}
    names = {}
    if actor_ids:
        rows = (await db.execute(select(models.User.id, models.User.full_name, models.User.username).where(models.User.id.in_(actor_ids)))).all()
        names = {r.id: (r.full_name or r.username) for r in rows}
    evidence = (
        await db.execute(
            select(models.DocumentEvidenceFile)
            .where(models.DocumentEvidenceFile.profile_document_id == document_row_id)
            .order_by(models.DocumentEvidenceFile.verified_at, models.DocumentEvidenceFile.id)
        )
    ).scalars().all()
    entries = []
    for l in logs:
        x = l.extra_data or {}
        entries.append(
            {
                "id": l.id,
                "action": l.action,
                "at": l.created_at,
                "actor_user_id": l.actor_user_id,
                "actor_name": names.get(l.actor_user_id),
                "old_status": l.old_status,
                "new_status": l.new_status,
                "via": x.get("via"),
                "batch_id": x.get("batch_id"),
                "grant_id": x.get("grant_id"),
                "reason": l.reason,
                "declared_format": l.declared_format,
                "verified_format": l.verified_format,
                "unknown_submitter_ack": x.get("unknown_submitter_ack"),
                "file_sha256": x.get("file_sha256"),
            }
        )
    return {
        "document_row_id": doc.id,
        "document_type_code": doc.document_type.code if doc.document_type else None,
        "status": doc.status,
        "row_version": doc.row_version,
        "entries": entries,
        "evidence_files": [
            {
                "id": e.id,
                "verification_audit_id": e.verification_audit_id,
                "verified_at": e.verified_at,
                "verified_by_user_id": e.verified_by_user_id,
                "sha256": e.sha256,
                "file_missing": e.file_missing,
            }
            for e in evidence
        ],
    }
