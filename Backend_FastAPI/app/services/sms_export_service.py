# app/services/sms_export_service.py
"""
Business logic SMS export (PR-4): gate fail-closed (§8.4) → find-or-create
export batch idempotent per nhà mạng → sinh file Excel ở POST-COMMIT callback
(session MỚI, atomic staging→os.replace + fsync + sha256) → download (verify
sha256) → mark-handed-off (recipient + contact freq-cap + campaign status).

Tuân thủ kiến trúc QLTS: KHÔNG import fastapi; raise domain exception; service
chỉ `flush` (router commit). File sinh trong callback dùng `AsyncSessionLocal`
MỚI vì db gốc đã commit/đóng transaction — §8.3.
Xem SMS_MARKETING_MODULE_DESIGN.md §8 / §11.7.
"""
import hashlib
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.sms import SmsCampaign, SmsCampaignExportBatch
from app.repositories.sms_campaign_repository import SmsCampaignRepository
from app.repositories.sms_export_repository import SmsExportRepository
from app.schemas import sms as sms_schemas
from app.utils.exceptions import BusinessRuleViolation, ResourceNotFoundError
from app.utils.sms_export import (
    XLSX_MEDIA,
    build_carrier_workbook,
    render_export_message,
    sanitize_export_filename,
)
from app.utils.sms_render import has_link

log = logging.getLogger(__name__)

# Campaign đã build, được phép export (lần đầu 'ready'; re-export idempotent
# khi 'exported'). 'draft' = chưa build/stale; 'handed_off'/'closed' = khoá.
_EXPORTABLE_CAMPAIGN_STATUS = {"ready", "exported"}
# Batch ở các trạng thái này = CHƯA có file dùng được → (re)generate.
_REGENERATE_BATCH_STATUS = {"pending", "failed", "purged", "invalidated"}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _carrier_label(carrier_bucket: str) -> str:
    return (carrier_bucket or "unknown").replace("_", " ").strip().title()


def _build_group_label(
    group_ids: List[int], names: dict
) -> Tuple[Optional[int], Optional[str]]:
    """B2 nhãn nhóm cho file: 1 nhóm → (group_id, tên); ≥2 nhóm → (None,
    'A+B' hoặc 'A+B+N' với N = số nhóm còn lại)."""
    if not group_ids:
        return None, None
    ordered = sorted(group_ids)
    labels = [names.get(g) or f"Nhom{g}" for g in ordered]
    if len(ordered) == 1:
        return ordered[0], labels[0]
    if len(ordered) == 2:
        return None, f"{labels[0]}+{labels[1]}"
    return None, f"{labels[0]}+{labels[1]}+{len(ordered) - 2}"


class SmsExportService:
    """Service export-batch lifecycle + sinh file + download + handoff."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SmsExportRepository(db)
        self.campaign_repo = SmsCampaignRepository(db)

    # ===============================================================
    # Serialize helpers (cờ thin-client + group label)
    # ===============================================================
    def _batch_out(
        self, b: SmsCampaignExportBatch, now: datetime
    ) -> sms_schemas.SmsExportBatchOut:
        is_expired = bool(
            b.expires_at is not None and _aware(b.expires_at) <= now
        )
        out = sms_schemas.SmsExportBatchOut.model_validate(b)
        out.is_expired = is_expired
        out.can_download = bool(
            b.status in ("generated", "handed_off")
            and b.invalidated_at is None
            and b.purged_at is None
            and not is_expired
        )
        out.can_mark_handed_off = bool(
            b.status == "generated"
            and b.invalidated_at is None
            and not is_expired
        )
        return out

    async def _resolve_group_label(
        self, campaign_id: int
    ) -> Tuple[Optional[int], Optional[str]]:
        gids = await self.campaign_repo.get_campaign_group_ids(campaign_id)
        names = await self.repo.get_group_names(gids)
        return _build_group_label(gids, names)

    # ===============================================================
    # Gate fail-closed (§8.4)
    # ===============================================================
    def _assert_exportable(self, campaign: SmsCampaign) -> None:
        if campaign.status == "draft":
            raise BusinessRuleViolation(
                detail="Campaign chưa Build (hoặc đã đổi nhóm/nội dung sau "
                "Build) — Build lại trước khi export."
            )
        if campaign.status not in _EXPORTABLE_CAMPAIGN_STATUS:
            raise BusinessRuleViolation(
                detail="Campaign đã bàn giao/đóng — không export lại; tạo "
                "campaign mới."
            )
        rev = campaign.build_revision
        if rev < 1:
            raise BusinessRuleViolation(detail="Campaign chưa Build.")
        # 3 attestation phải khớp build_revision hiện tại + có reference thật.
        missing: List[str] = []
        if campaign.consent_checked_build_revision != rev or not (
            campaign.consent_reference or ""
        ).strip():
            missing.append("xác nhận đã kiểm consent")
        if campaign.dnc_checked_build_revision != rev or not (
            campaign.dnc_reference or ""
        ).strip():
            missing.append("xác nhận đối soát DNC")
        if campaign.optout_channel_checked_build_revision != rev or not (
            campaign.optout_channel_reference or ""
        ).strip():
            missing.append("xác nhận kênh từ chối (SMS/điện thoại) hoạt động")
        if missing:
            raise BusinessRuleViolation(
                detail="Thiếu xác nhận cho bản build hiện tại: "
                + "; ".join(missing)
                + ". Ghi đủ 3 attestation (đúng revision) rồi export."
            )

    # ===============================================================
    # Prepare export — gate + find-or-create batch + post-commit callback
    # ===============================================================
    async def prepare_export(
        self, campaign_id: int, user
    ) -> Tuple[Optional[Callable], dict]:
        # Lock campaign (cùng lock build/attestation) → serialize export vs
        # rebuild/đổi nhóm; gate re-check chạy trên trạng thái nhất quán.
        campaign = await self.campaign_repo.get_campaign_for_update(campaign_id)
        if campaign is None:
            raise ResourceNotFoundError(detail="Không tìm thấy campaign")
        self._assert_exportable(campaign)
        rev = campaign.build_revision

        # Re-check fail-closed NGAY trước khi tạo batch (§8.4).
        if await self.repo.count_over_limit(campaign_id, rev) > 0:
            raise BusinessRuleViolation(
                detail="Còn người nhận vượt 1 segment (over_limit) — rút gọn "
                "template/dữ liệu rồi Build lại trước khi export."
            )
        lost = await self.repo.count_lost_consent(campaign_id, rev)
        supp = await self.repo.count_new_suppression(campaign_id, rev)
        if lost or supp:
            raise BusinessRuleViolation(
                detail=f"Phát hiện thay đổi kể từ lần Build: {lost} người mất "
                f"consent, {supp} người mới opt-out/DNC — Build lại để cập nhật "
                "snapshot trước khi export (fail-closed)."
            )
        carriers = await self.repo.counts_by_carrier_exportable(
            campaign_id, rev
        )
        if not carriers:
            raise BusinessRuleViolation(
                detail="Không có người nhận nào đủ điều kiện export (sau lọc "
                "consent/suppression/over-limit)."
            )

        group_id, group_label = await self._resolve_group_label(campaign_id)
        base_dir = settings.SMS_EXPORT_STORAGE_DIR
        to_generate: List[int] = []

        for carrier_bucket, count in carriers:
            file_name = sanitize_export_filename(
                group_label, campaign.name, _carrier_label(carrier_bucket)
            )
            storage_path = os.path.join(
                base_dir, str(campaign_id), str(rev), file_name
            )
            batch = await self.repo.get_batch_for_carrier_locked(
                campaign_id, rev, carrier_bucket
            )
            if batch is None:
                batch = await self.repo.create_batch(
                    {
                        "campaign_id": campaign_id,
                        "build_revision": rev,
                        "group_id": group_id,
                        "group_name_snapshot": group_label,
                        "carrier_bucket": carrier_bucket,
                        "recipient_count": count,
                        "file_name": file_name,
                        "storage_path": storage_path,
                        "status": "pending",
                    }
                )
                to_generate.append(batch.id)
            elif batch.status in _REGENERATE_BATCH_STATUS:
                # Re-export cùng revision sau lỗi/purge/invalidate → reset.
                batch.group_id = group_id
                batch.group_name_snapshot = group_label
                batch.recipient_count = count
                batch.file_name = file_name
                batch.storage_path = storage_path
                batch.status = "pending"
                batch.failure_reason = None
                batch.file_sha256 = None
                batch.file_size_bytes = None
                batch.generated_at = None
                batch.generated_by_id = None
                batch.purged_at = None
                batch.invalidated_at = None
                batch.expires_at = None
                to_generate.append(batch.id)
            # else status in ('generated','handed_off') → idempotent: giữ file
            # hiện có, không sinh lại/không đổi token.

        if campaign.status == "ready":
            campaign.status = "exported"
        await self.db.flush()

        meta = {
            "campaign_id": campaign_id,
            "build_revision": rev,
            "total_exportable": sum(c for _, c in carriers),
        }
        if not to_generate:
            return None, meta

        generated_by = getattr(user, "id", None)
        retention = settings.SMS_EXPORT_RETENTION_DAYS

        async def _post_commit() -> None:
            await self._generate_files(to_generate, generated_by, retention)

        return _post_commit, meta

    # ===============================================================
    # File generation (POST-COMMIT — session MỚI, §8.3)
    # ===============================================================
    async def _generate_files(
        self, batch_ids: List[int], generated_by: Optional[int], retention: int
    ) -> None:
        for batch_id in batch_ids:
            try:
                async with AsyncSessionLocal() as db:
                    await self._generate_one(
                        db, batch_id, generated_by, retention
                    )
                    await db.commit()
            except Exception:  # noqa: BLE001
                log.exception("SMS export sinh file batch %s lỗi", batch_id)
                await self._mark_failed_safe(batch_id)

    async def _generate_one(
        self,
        db: AsyncSession,
        batch_id: int,
        generated_by: Optional[int],
        retention: int,
    ) -> None:
        repo = SmsExportRepository(db)
        campaign_repo = SmsCampaignRepository(db)
        batch = await repo.get_batch_for_update(batch_id)
        if batch is None or batch.status != "pending":
            return  # đã xử lý / không còn pending (idempotent giữa caller)
        campaign = await campaign_repo.get_campaign(batch.campaign_id)
        if campaign is None:
            batch.status = "failed"
            batch.failure_reason = "Campaign không còn tồn tại."
            return
        link = has_link(campaign.sms_template)
        recipients = await repo.get_exportable_recipients(
            batch.campaign_id, batch.build_revision, batch.carrier_bucket
        )
        rows: List[Tuple[str, str]] = []
        for r in recipients:
            msg = render_export_message(
                r.rendered_message_skeleton,
                has_link=link,
                token_ciphertext=r.token_ciphertext,
                token_key_version=r.token_key_version,
            )
            if msg is None:
                batch.status = "failed"
                batch.failure_reason = (
                    "Không giải mã được link của ≥1 người nhận (kiểm tra "
                    "key-ring SMS) — không xuất file thiếu link."
                )
                return
            rows.append((r.phone_international_snapshot, msg))
        if not rows:
            batch.status = "failed"
            batch.failure_reason = (
                "Không còn người nhận đủ điều kiện cho nhà mạng này."
            )
            return

        content = build_carrier_workbook(rows)
        sha = hashlib.sha256(content).hexdigest()
        final_path = batch.storage_path
        os.makedirs(os.path.dirname(final_path), exist_ok=True)
        # Atomic: ghi staging cùng thư mục → fsync → os.replace (atomic kể cả
        # khi đích đã tồn tại; cùng filesystem nên rename nguyên tử).
        staging = os.path.join(
            os.path.dirname(final_path), f".staging.{uuid.uuid4().hex[:12]}.xlsx"
        )
        try:
            with open(staging, "wb") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(staging, final_path)
        except Exception:
            # Dọn staging dở rồi để caller đánh dấu failed.
            if os.path.exists(staging):
                try:
                    os.remove(staging)
                except OSError:
                    pass
            raise

        now = datetime.now(timezone.utc)
        batch.status = "generated"
        batch.recipient_count = len(rows)
        batch.file_sha256 = sha
        batch.file_size_bytes = len(content)
        batch.generated_by_id = generated_by
        batch.generated_at = now
        batch.expires_at = now + timedelta(days=retention)
        batch.failure_reason = None

    async def _mark_failed_safe(self, batch_id: int) -> None:
        """Đánh dấu batch 'failed' ở session riêng (best-effort) khi sinh file
        ném exception ngoài _generate_one (vd ghi đĩa lỗi)."""
        try:
            async with AsyncSessionLocal() as db:
                b = await SmsExportRepository(db).get_batch_for_update(batch_id)
                if b is not None and b.status == "pending":
                    b.status = "failed"
                    b.failure_reason = "Lỗi sinh/ghi file (xem log hệ thống)."
                    await db.commit()
        except Exception:  # noqa: BLE001
            log.exception(
                "SMS export đánh dấu failed batch %s lỗi", batch_id
            )

    # ===============================================================
    # Read: kết quả export + danh sách batch (GET)
    # ===============================================================
    async def get_export_result(
        self, campaign_id: int
    ) -> sms_schemas.SmsExportResult:
        # File sinh ở session callback KHÁC → expire instance cũ trong session
        # này để list_batches đọc trạng thái mới nhất (pending→generated).
        self.db.expire_all()
        campaign = await self.campaign_repo.get_campaign(campaign_id)
        if campaign is None:
            raise ResourceNotFoundError(detail="Không tìm thấy campaign")
        now = datetime.now(timezone.utc)
        batches = await self.repo.list_batches(
            campaign_id, campaign.build_revision
        )
        return sms_schemas.SmsExportResult(
            campaign_id=campaign_id,
            build_revision=campaign.build_revision,
            total_exportable=sum(b.recipient_count for b in batches),
            batches=[self._batch_out(b, now) for b in batches],
        )

    async def list_export_batches(
        self, campaign_id: int
    ) -> sms_schemas.SmsExportBatchList:
        campaign = await self.campaign_repo.get_campaign(campaign_id)
        if campaign is None:
            raise ResourceNotFoundError(detail="Không tìm thấy campaign")
        now = datetime.now(timezone.utc)
        batches = await self.repo.list_batches(
            campaign_id, campaign.build_revision
        )
        return sms_schemas.SmsExportBatchList(
            campaign_id=campaign_id,
            build_revision=campaign.build_revision,
            batches=[self._batch_out(b, now) for b in batches],
        )

    # ===============================================================
    # Download (verify sha256) — trả bytes cho router dựng Response
    # ===============================================================
    async def get_export_file(
        self, campaign_id: int, batch_id: int
    ) -> Tuple[bytes, str, str]:
        batch = await self.repo.get_batch(batch_id)
        if batch is None or batch.campaign_id != campaign_id:
            raise ResourceNotFoundError(detail="Không tìm thấy file export")
        now = datetime.now(timezone.utc)
        if batch.status not in ("generated", "handed_off"):
            raise BusinessRuleViolation(
                detail="File export chưa sẵn sàng (đang sinh hoặc đã lỗi) — "
                "thử export lại."
            )
        if batch.invalidated_at is not None:
            raise BusinessRuleViolation(
                detail="File export đã bị vô hiệu (dữ liệu thay đổi) — export "
                "lại bản hiện tại."
            )
        expired = batch.expires_at is not None and _aware(
            batch.expires_at
        ) <= now
        if batch.purged_at is not None or expired:
            raise BusinessRuleViolation(
                detail="File export đã hết hạn/đã dọn — export lại để tạo file "
                "mới."
            )
        if not batch.storage_path or not os.path.isfile(batch.storage_path):
            raise BusinessRuleViolation(
                detail="File export không còn trên hệ thống — export lại."
            )
        with open(batch.storage_path, "rb") as f:
            content = f.read()
        if (
            batch.file_sha256
            and hashlib.sha256(content).hexdigest() != batch.file_sha256
        ):
            raise BusinessRuleViolation(
                detail="File export sai checksum (có thể hỏng) — export lại."
            )
        return content, batch.file_name or "sms_export.xlsx", XLSX_MEDIA

    # ===============================================================
    # Mark handed-off — recipient + contact freq-cap + campaign status
    # ===============================================================
    async def mark_handed_off(
        self, campaign_id: int, batch_id: int, user
    ) -> sms_schemas.SmsExportBatchOut:
        batch = await self.repo.get_batch_for_update(batch_id)
        if batch is None or batch.campaign_id != campaign_id:
            raise ResourceNotFoundError(detail="Không tìm thấy file export")
        if batch.status == "handed_off":
            raise BusinessRuleViolation(
                detail="Batch này đã được đánh dấu bàn giao."
            )
        if batch.status != "generated":
            raise BusinessRuleViolation(
                detail="Chỉ đánh dấu bàn giao khi file đã sinh xong "
                "(generated)."
            )
        if batch.invalidated_at is not None:
            raise BusinessRuleViolation(
                detail="File đã bị vô hiệu — không thể bàn giao; export lại."
            )
        # Lock campaign → serialize đổi status vs build/export.
        campaign = await self.campaign_repo.get_campaign_for_update(campaign_id)
        if campaign is None:
            raise ResourceNotFoundError(detail="Không tìm thấy campaign")
        if batch.build_revision != campaign.build_revision:
            raise BusinessRuleViolation(
                detail="File thuộc bản build cũ — export lại bản hiện tại "
                "trước khi bàn giao."
            )

        now = datetime.now(timezone.utc)
        batch.status = "handed_off"
        batch.marked_handed_off_at = now
        # Neo handed_off lên recipient (chặn rebuild) + last_handed_off_at lên
        # contact (frequency-cap proxy cho campaign sau).
        contact_ids = await self.repo.mark_recipients_handed_off(
            campaign_id, batch.build_revision, batch.carrier_bucket, now
        )
        await self.repo.touch_contacts_handed_off(contact_ids, now)
        if campaign.handed_off_marked_at is None:
            campaign.handed_off_marked_at = now
        if campaign.status in ("ready", "exported"):
            campaign.status = "handed_off"
        await self.db.flush()
        # Tất cả batch của revision đã bàn giao → đóng campaign.
        if await self.repo.count_unhanded_batches(
            campaign_id, campaign.build_revision
        ) == 0:
            campaign.status = "closed"
            await self.db.flush()
        return self._batch_out(batch, now)
