# app/services/sms_campaign_service.py
"""
Business logic SMS campaign (PR-3): CRUD campaign + group, BUILD engine
(snapshot revisioned + fail-closed consent/suppression/freq filter + carrier
+ token HMAC/Fernet + render [QC]/optout + preflight measure + invalidate
revision cũ), preflight report, attestations.

Tuân thủ kiến trúc QLTS: KHÔNG import fastapi; raise domain exception; chỉ
`flush` (router commit). Build chạy dưới row lock campaign. Xem
SMS_MARKETING_MODULE_DESIGN.md §3/§6/§7/§8.
"""
import re
from datetime import datetime, timezone

from app.utils.tz import ensure_aware
from typing import List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import SMS_OPTOUT_INSTRUCTION_DEFAULT, settings
from app.models.sms import SmsCampaign, SmsContactGroup
from app.repositories.sms_campaign_repository import SmsCampaignRepository
from app.repositories.sms_contact_repository import SmsContactRepository
from app.schemas import sms as sms_schemas
from app.services.sms_export_service import campaign_state_allows_export
from app.utils.exceptions import (
    BusinessRuleViolation,
    ConflictError,
    DuplicateResourceError,
    ResourceNotFoundError,
    ValidationError,
)
from app.utils.sms_render import (
    assemble_skeleton,
    classify_carrier,
    find_unknown_vars,
    has_link,
    measure_skeleton,
    preview_message,
    skeleton_is_broken,
)
from app.utils.sms_token import (
    LINK_SENTINEL,
    compute_token_hash,
    encrypt_code,
    ensure_token_secrets_configured,
    generate_short_code,
)
from app.utils.sms_url import host_in_allowlist
from app.utils.text_helpers import strip_diacritics

# Status cho phép build lại (chưa bàn giao/đóng).
_REBUILDABLE = {"draft", "ready", "exported"}
_TOKEN_RETRY = 5  # số lần auto-retry khi token_hash collision (§6.1)


def _slugify(name: str) -> str:
    """Slug ASCII cho campaign code — dùng chung helper bỏ dấu (đừng chép lại
    vòng NFD; bản ở `sms_contact_service` đã gom về `text_helpers`)."""
    s = strip_diacritics(name).lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:50] or "campaign"


_aware = ensure_aware  # alias tới helper tz chung (bỏ bản sao logic)


class SmsCampaignService:
    """Service campaign CRUD + build + preflight + attestations."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SmsCampaignRepository(db)
        self.contact_repo = SmsContactRepository(db)

    # ===============================================================
    # Content validation (cross-field — cần config + candidate state)
    # ===============================================================
    def _host_allowed(self, url: str) -> bool:
        """Delegate sang util chung `host_in_allowlist` (PR-5) → 1 nguồn sự
        thật cho allowlist redirect (gồm vá backslash/charset host §6.2),
        tránh lệch giữa create-time và /r/-resolve."""
        return host_in_allowlist(url)

    def _validate_content(
        self,
        *,
        sms_template: str,
        landing_type: str,
        landing_url: Optional[str],
        landing_cta_url: Optional[str],
        landing_cta_label: Optional[str] = None,
    ) -> None:
        if LINK_SENTINEL in (sms_template or ""):
            raise ValidationError(
                detail="Template không được chứa chuỗi nội bộ "
                f"'{LINK_SENTINEL}'."
            )
        unknown = find_unknown_vars(sms_template)
        if unknown:
            raise ValidationError(
                detail="Biến template không hợp lệ: "
                + ", ".join("{" + v + "}" for v in sorted(unknown))
                + " (chỉ {name}/{full_name}/{link})"
            )
        if landing_type == "external":
            if not (landing_url and landing_url.strip()):
                raise ValidationError(
                    detail="landing_type=external cần landing_url"
                )
            if not has_link(sms_template):
                raise ValidationError(
                    detail="external + landing_url cần {link} trong template"
                )
        # Allowlist host cho mọi URL external (landing_url + CTA).
        if landing_type == "external" and not self._host_allowed(landing_url):
            raise ValidationError(
                detail="landing_url host không thuộc allowlist redirect"
            )
        if landing_cta_url and landing_cta_url.strip():
            if not self._host_allowed(landing_cta_url):
                raise ValidationError(
                    detail="landing_cta_url host không thuộc allowlist redirect"
                )
        # CTA cần CẢ nhãn lẫn URL, hoặc bỏ trống cả hai (chống CTA nửa vời).
        if bool((landing_cta_label or "").strip()) != bool(
            (landing_cta_url or "").strip()
        ):
            raise ValidationError(
                detail="CTA cần CẢ nhãn (landing_cta_label) lẫn URL "
                "(landing_cta_url), hoặc bỏ trống cả hai."
            )

    def _with_computed(
        self, campaign: SmsCampaign, group_count: Optional[int] = None
    ) -> SmsCampaign:
        # Luôn set cả 3 transient attr (kể cả None) để Pydantic from_attributes
        # không thiếu thuộc tính khi serialize SmsCampaignOut ở list.
        campaign.has_link = has_link(campaign.sms_template)
        campaign.group_count = group_count
        # Gọi thẳng vị từ của export_service → FE không tự suy diễn từ status,
        # và cờ hiển thị không thể lệch khỏi gate thật.
        campaign.can_export = campaign_state_allows_export(campaign)
        return campaign

    # ===============================================================
    # Measure/preview template (form soạn campaign — chưa recipient)
    # ===============================================================
    def _optout_violations(self, footer: str) -> List[str]:
        """3 luật optout NĐ91 (build gate + measure warning DÙNG CHUNG → không
        drift). Trả list mô tả vi phạm (rỗng = hợp lệ). `footer` đã strip."""
        violations: List[str] = []
        if not footer:
            violations.append(
                "Chưa cấu hình hướng dẫn từ chối (SMS_OPTOUT_INSTRUCTION) — "
                "bắt buộc footer từ chối NĐ91."
            )
            return violations
        if settings.APP_ENV == "production" and (
            footer == SMS_OPTOUT_INSTRUCTION_DEFAULT.strip()
            or re.search(r"[xX]{3,}", footer)
        ):
            violations.append(
                "SMS_OPTOUT_INSTRUCTION còn là placeholder (vd 'xxxx') — "
                "production phải đặt kênh từ chối SMS/điện thoại thật."
            )
        if len(footer) > 160:
            violations.append(
                "Hướng dẫn từ chối quá dài (>160 ký tự) — rút gọn để khớp bản "
                "ghi audit và tiết kiệm segment."
            )
        return violations

    def _resolve_optout_for_measure(self) -> Tuple[str, List[str], bool]:
        """Dùng CHUNG `_optout_violations` với build() (không drift) nhưng KHÔNG
        raise → measure vẫn đo được (footer placeholder cũng có độ dài); điều
        kiện build-sẽ-chặn trả dưới dạng warning + optout_ok=False."""
        footer = (settings.SMS_OPTOUT_INSTRUCTION or "").strip()
        violations = self._optout_violations(footer)
        warnings = [f"{v} (build sẽ bị chặn)" for v in violations]
        return footer, warnings, not violations

    def measure_template(
        self, template: str, *, sample_full_name: Optional[str] = None
    ) -> sms_schemas.SmsMeasureResult:
        """Đo skeleton = assemble_skeleton([QC]+body+optout, sentinel link) +
        measure_skeleton — CÙNG hàm build dùng → số khớp. Tên rỗng → NAME_FALLBACK.

        ⚠ Sentinel gate: `render_body` GỠ ÂM THẦM __SMS_LINK__ → preview trông
        'ổn' nhưng `_validate_content` (create/update) lại REJECT → drift. Vì vậy
        set `has_internal_sentinel` TRƯỚC khi assemble để FE cảnh báo lỗi-chặn-lưu
        (cùng tinh thần `unknown_vars`)."""
        unknown = sorted(find_unknown_vars(template))
        has_sentinel = LINK_SENTINEL in (template or "")
        link = has_link(template)
        footer, warnings, optout_ok = self._resolve_optout_for_measure()
        skeleton = assemble_skeleton(
            template, sample_full_name or "", optout_instruction=footer
        )
        encoding, length, segments, is_over = measure_skeleton(skeleton)
        if is_over:
            warnings.append(
                f"Tin vượt 1 đoạn ({segments} đoạn, {encoding}) — rút gọn nội "
                "dung để export không bị chặn."
            )
        return sms_schemas.SmsMeasureResult(
            encoding=encoding,
            length=length,
            segments=segments,
            is_over_limit=is_over,
            preview=preview_message(skeleton),
            has_link=link,
            unknown_vars=unknown,
            has_internal_sentinel=has_sentinel,
            optout_configured=optout_ok,
            warnings=warnings,
        )

    # ===============================================================
    # CRUD campaign
    # ===============================================================
    async def create_campaign(
        self, data: sms_schemas.SmsCampaignCreate, user
    ) -> SmsCampaign:
        self._validate_content(
            sms_template=data.sms_template,
            landing_type=data.landing_type,
            landing_url=data.landing_url,
            landing_cta_url=data.landing_cta_url,
            landing_cta_label=data.landing_cta_label,
        )
        code = (data.code or _slugify(data.name)).strip()
        if await self.repo.get_campaign_by_code(code) is not None:
            raise DuplicateResourceError(
                detail=f"Mã campaign '{code}' đã tồn tại"
            )
        fields = {
            "name": data.name.strip(),
            "code": code,
            "sms_template": data.sms_template,
            "landing_type": data.landing_type,
            "landing_url": data.landing_url,
            "landing_headline": data.landing_headline,
            "landing_body": data.landing_body,
            "landing_cta_label": data.landing_cta_label,
            "landing_cta_url": data.landing_cta_url,
            "frequency_cap_days": data.frequency_cap_days,
            "link_expires_at": data.link_expires_at,
            "created_by_id": getattr(user, "id", None),
        }
        try:
            campaign = await self.repo.create_campaign(fields)
        except IntegrityError:
            raise DuplicateResourceError(
                detail=f"Mã campaign '{code}' đã tồn tại"
            )
        return self._with_computed(campaign, group_count=0)

    async def get_campaign(self, campaign_id: int) -> SmsCampaign:
        campaign = await self.repo.get_campaign(campaign_id)
        if campaign is None:
            raise ResourceNotFoundError(detail="Không tìm thấy campaign")
        gids = await self.repo.get_campaign_group_ids(campaign_id)
        return self._with_computed(campaign, group_count=len(gids))

    async def list_campaigns(
        self,
        skip: int,
        limit: int,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Tuple[int, List[SmsCampaign]]:
        total, items = await self.repo.list_campaigns(
            skip=skip, limit=limit, status=status, search=search
        )
        counts = await self.repo.get_group_counts([c.id for c in items])
        for c in items:
            self._with_computed(c, group_count=counts.get(c.id, 0))
        return total, items

    async def list_campaign_groups(
        self, campaign_id: int
    ) -> Tuple[int, List[SmsContactGroup]]:
        """Danh sách nhóm ĐÃ GẮN vào campaign (kèm member_count) — cho FE
        liệt kê + bỏ nhóm. 404 nếu campaign không tồn tại."""
        campaign = await self.repo.get_campaign(campaign_id)
        if campaign is None:
            raise ResourceNotFoundError(detail="Không tìm thấy campaign")
        gids = await self.repo.get_campaign_group_ids(campaign_id)
        if not gids:
            return 0, []
        groups = await self.contact_repo.get_groups_by_ids(gids)
        counts = await self.contact_repo.count_members_by_group(gids)
        for g in groups:
            g.member_count = counts.get(g.id, 0)
        return len(groups), groups

    async def update_campaign(
        self, campaign_id: int, data: sms_schemas.SmsCampaignUpdate
    ) -> SmsCampaign:
        # Lock campaign row (cùng lock build) → serialize sửa template vs
        # build, tránh build snapshot bằng template cũ rồi update đổi mới (#1).
        campaign = await self.repo.get_campaign_for_update(campaign_id)
        if campaign is None:
            raise ResourceNotFoundError(detail="Không tìm thấy campaign")
        if campaign.status != "draft":
            raise BusinessRuleViolation(
                detail="Chỉ sửa campaign khi đang ở trạng thái draft"
            )
        await self._ensure_not_handed_off(campaign_id)
        patch = data.model_dump(exclude_unset=True)
        # Chặn explicit null cho cột NOT NULL.
        for f in ("name", "sms_template", "landing_type"):
            if f in patch and patch[f] is None:
                raise ValidationError(detail=f"Trường '{f}' không được null")
        # Validate trên candidate state (existing + patch).
        self._validate_content(
            sms_template=patch.get("sms_template", campaign.sms_template),
            landing_type=patch.get("landing_type", campaign.landing_type),
            landing_url=patch.get("landing_url", campaign.landing_url),
            landing_cta_url=patch.get(
                "landing_cta_url", campaign.landing_cta_url
            ),
            landing_cta_label=patch.get(
                "landing_cta_label", campaign.landing_cta_label
            ),
        )
        if "name" in patch and patch["name"]:
            patch["name"] = patch["name"].strip()
        for key, value in patch.items():
            setattr(campaign, key, value)
        await self.db.flush()
        await self.db.refresh(campaign)
        gids = await self.repo.get_campaign_group_ids(campaign_id)
        return self._with_computed(campaign, group_count=len(gids))

    # ===============================================================
    # Campaign ↔ group
    # ===============================================================
    async def _ensure_not_handed_off(self, campaign_id: int) -> None:
        """Chặn MỌI sửa audience/nội dung sau khi đã bàn giao ≥1 batch — giữ
        bất biến audit sau handoff (§232). build() reset-draft qua attach rồi
        PATCH sẽ lách nếu chỉ gate ở build; gate cả attach/detach/update."""
        if await self.repo.has_handed_off_recipients(campaign_id):
            raise BusinessRuleViolation(
                detail="Đã bàn giao ≥1 batch cho nhà mạng — KHÔNG sửa "
                "nhóm/nội dung; tạo campaign mới."
            )

    async def _mark_audience_changed(self, campaign: SmsCampaign) -> None:
        """Đổi nhóm sau khi ĐÃ build → snapshot recipient stale → reset
        status='draft' (buộc build lại; export PR-4 chặn vì draft, build kế
        tiếp tăng revision làm attestation cũ lệch). Fail-closed #3."""
        if campaign.status != "draft":
            campaign.status = "draft"
            await self.db.flush()
            # onupdate=func.now() expire updated_at → refresh trước serialize.
            await self.db.refresh(campaign)

    async def attach_group(
        self, campaign_id: int, group_id: int
    ) -> SmsCampaign:
        # Lock campaign row (CÙNG lock với build) → serialize đổi audience vs
        # build, tránh group chèn lọt khi build đang snapshot (#1 R2).
        campaign = await self.repo.get_campaign_for_update(campaign_id)
        if campaign is None:
            raise ResourceNotFoundError(detail="Không tìm thấy campaign")
        if campaign.status not in _REBUILDABLE:
            raise BusinessRuleViolation(
                detail="Campaign đã bàn giao/đóng — không đổi nhóm"
            )
        await self._ensure_not_handed_off(campaign_id)
        grp = await self.contact_repo.get_group(group_id)
        if grp is None:
            raise ResourceNotFoundError(detail="Không tìm thấy nhóm liên hệ")
        if not grp.is_active:
            raise BusinessRuleViolation(
                detail="Nhóm đã ngừng hoạt động — không thể chọn cho campaign"
            )
        if await self.repo.get_campaign_group(campaign_id, group_id):
            raise DuplicateResourceError(
                detail="Nhóm đã được chọn cho campaign"
            )
        try:
            await self.repo.create_campaign_group(campaign_id, group_id)
        except IntegrityError:
            raise DuplicateResourceError(
                detail="Nhóm đã được chọn cho campaign"
            )
        await self._mark_audience_changed(campaign)
        gids = await self.repo.get_campaign_group_ids(campaign_id)
        return self._with_computed(campaign, group_count=len(gids))

    async def detach_group(self, campaign_id: int, group_id: int) -> None:
        # Lock campaign row (cùng lock build) — serialize đổi audience (#1 R2).
        campaign = await self.repo.get_campaign_for_update(campaign_id)
        if campaign is None:
            raise ResourceNotFoundError(detail="Không tìm thấy campaign")
        if campaign.status not in _REBUILDABLE:
            raise BusinessRuleViolation(
                detail="Campaign đã bàn giao/đóng — không đổi nhóm"
            )
        await self._ensure_not_handed_off(campaign_id)
        cg = await self.repo.get_campaign_group(campaign_id, group_id)
        if cg is None:
            raise ResourceNotFoundError(
                detail="Nhóm không thuộc campaign này"
            )
        await self.repo.delete_campaign_group(cg)
        await self._mark_audience_changed(campaign)

    # ===============================================================
    # BUILD — snapshot revisioned + fail-closed + token + render
    # ===============================================================
    def _gen_token_triplet(
        self, seen_hashes: set
    ) -> Tuple[str, str, str]:
        """Sinh (token_hash, ciphertext, key_version). Tránh trùng hash
        trong cùng build (global trùng ~0 nhờ HMAC random; UNIQUE backstop)."""
        for _ in range(8):
            code = generate_short_code()
            token_hash = compute_token_hash(code)
            if token_hash in seen_hashes:
                continue
            ciphertext, key_version = encrypt_code(code)
            seen_hashes.add(token_hash)
            return token_hash, ciphertext, key_version
        raise BusinessRuleViolation(detail="Không sinh được token duy nhất")

    async def build(self, campaign_id: int, user) -> sms_schemas.SmsPreflightReport:
        campaign = await self.repo.get_campaign_for_update(campaign_id)
        if campaign is None:
            raise ResourceNotFoundError(detail="Không tìm thấy campaign")
        if campaign.status not in _REBUILDABLE:
            raise BusinessRuleViolation(
                detail="Campaign đã bàn giao/đóng — không build lại"
            )
        # Chặn rebuild sau PARTIAL handoff: campaign vẫn 'exported' nhưng đã
        # bàn giao ≥1 batch → recipient cũ active SONG SONG revision mới (vì
        # invalidate cố ý chừa dòng đã handoff) → trùng/lệch evidence (§232).
        if await self.repo.has_handed_off_recipients(campaign_id):
            raise BusinessRuleViolation(
                detail="Đã bàn giao ≥1 batch cho nhà mạng — KHÔNG build lại; "
                "tạo campaign mới để tránh trùng người nhận."
            )
        self._validate_content(
            sms_template=campaign.sms_template,
            landing_type=campaign.landing_type,
            landing_url=campaign.landing_url,
            landing_cta_url=campaign.landing_cta_url,
            landing_cta_label=campaign.landing_cta_label,
        )
        group_ids = await self.repo.get_campaign_group_ids(campaign_id)
        if not group_ids:
            raise BusinessRuleViolation(
                detail="Campaign chưa chọn nhóm nào để build"
            )
        # Re-check expiry lúc BUILD (schema chỉ validate create/update; campaign
        # tạo với expiry tương lai có thể đã quá hạn khi build). Chặn TRƯỚC
        # invalidate revision cũ / sinh token → không build link chết. R8 P2.
        if has_link(campaign.sms_template) and campaign.link_expires_at and (
            _aware(campaign.link_expires_at) <= datetime.now(timezone.utc)
        ):
            raise BusinessRuleViolation(
                detail="link_expires_at đã hết hạn — cập nhật thời hạn link "
                "trước khi build (tránh tạo link chết)."
            )

        new_revision = campaign.build_revision + 1
        await self.repo.invalidate_recipients_before(campaign_id, new_revision)
        # Rebuild → vô hiệu export batch revision CŨ (PR-4): file revision cũ
        # KHÔNG còn tải được (PII/consent lỗi thời) + status='invalidated' để
        # cleanup dọn. Import cục bộ tránh phụ thuộc vòng tại module-load.
        from app.repositories.sms_export_repository import SmsExportRepository

        await SmsExportRepository(self.db).invalidate_export_batches_before(
            campaign_id, new_revision
        )

        # Gom member → dedupe theo phone, gom group_ids đóng góp.
        members = await self.repo.get_members_of_groups(group_ids)
        by_phone: dict = {}
        for gid, contact in members:
            entry = by_phone.setdefault(
                contact.phone_normalized,
                {"contact": contact, "groups": set()},
            )
            entry["groups"].add(gid)

        if not by_phone:
            raise BusinessRuleViolation(
                detail="Các nhóm đã chọn không có liên hệ nào (hoặc nhóm đã "
                "ngừng hoạt động) — không có người nhận để build."
            )
        phones = list(by_phone.keys())
        optout_src = await self.repo.get_optout_source_map(phones)
        carrier_map = await self.repo.get_active_carrier_prefix_map()

        link = has_link(campaign.sms_template)
        # --- Compliance fail-closed (NĐ91) ---
        # [QC] LUÔN được chèn (assemble_skeleton); optout PHẢI cấu hình thật.
        # Cùng `_optout_violations` với measure preview → không drift; ≤160 khớp
        # cột optout_instruction_snapshot String(160) (audit KHỚP tin cuối).
        optout_instruction = (settings.SMS_OPTOUT_INSTRUCTION or "").strip()
        violations = self._optout_violations(optout_instruction)
        if violations:
            raise BusinessRuleViolation(detail=violations[0])
        # Token secret/keyring (prod) — chỉ cần khi có {link}.
        if link:
            ensure_token_secrets_configured()
        freq_days = (
            campaign.frequency_cap_days
            if campaign.frequency_cap_days is not None
            else settings.SMS_FREQUENCY_CAP_DAYS
        )
        now = datetime.now(timezone.utc)
        seen_hashes: set = set()
        rows: List[dict] = []

        for phone, entry in by_phone.items():
            contact = entry["contact"]
            carrier = classify_carrier(phone, carrier_map)
            # Fail-closed (ưu tiên consent > opt-out > frequency).
            reason: Optional[str] = None
            if contact.marketing_consent_status != "granted":
                reason = "no_consent"
            elif phone in optout_src:
                # external_suppression = DNC list (đối tác); còn lại = opt-out
                # do người dùng → excluded_reason phân biệt cho báo cáo/audit.
                reason = (
                    "dnc_suppressed"
                    if optout_src[phone] == "external_suppression"
                    else "opted_out"
                )
            elif (
                freq_days > 0
                and contact.last_handed_off_at is not None
                and (now - _aware(contact.last_handed_off_at)).days
                < freq_days
            ):
                reason = "frequency_capped"

            skeleton = assemble_skeleton(
                campaign.sms_template,
                contact.full_name,
                optout_instruction=optout_instruction,
            )
            encoding, length, segments, is_over = measure_skeleton(skeleton)
            if reason is None and is_over:
                reason = "over_limit"
            # Defensive drop-broken-row (§18.D): tin cuối còn placeholder lạ
            # hoặc sentinel-không-link → missing_data (trước khi sinh token).
            if reason is None and skeleton_is_broken(skeleton, has_link=link):
                reason = "missing_data"

            token_hash = token_ciphertext = token_key_version = None
            if link and reason is None:
                token_hash, token_ciphertext, token_key_version = (
                    self._gen_token_triplet(seen_hashes)
                )

            rows.append(
                {
                    "campaign_id": campaign_id,
                    "build_revision": new_revision,
                    "contact_id": contact.id,
                    "group_ids_snapshot": sorted(entry["groups"]),
                    "full_name_snapshot": contact.full_name,
                    "phone_normalized_snapshot": phone,
                    "phone_international_snapshot": contact.phone_international,
                    "note_snapshot": contact.note,
                    "carrier_bucket": carrier,
                    "token_hash": token_hash,
                    "token_ciphertext": token_ciphertext,
                    "token_key_version": token_key_version,
                    "rendered_message_skeleton": skeleton,
                    "message_length": length,
                    "encoding": encoding,
                    "segments": segments,
                    "is_over_limit": is_over,
                    "excluded_reason": reason,
                }
            )

        # Insert recipient + AUTO-RETRY token collision (committed HOẶC TOCTOU
        # concurrent) tối đa N lần (§6.1 "retry N lần"): Core insert TRONG
        # savepoint; IntegrityError (unique token_hash) → regenerate token có
        # link + thử lại; hết N → 409. Core insert nên savepoint rollback
        # sạch (không ORM instance lingering). #3 R4.
        for _attempt in range(_TOKEN_RETRY):
            try:
                async with self.db.begin_nested():
                    await self.repo.bulk_insert_recipients(rows)
                break
            except IntegrityError as exc:
                # CHỈ retry khi đụng UNIQUE token_hash; lỗi khác (FK / check /
                # phone-rev UNIQUE) KHÔNG phải collision → re-raise ngay.
                if "uq_sms_recipient_token_hash" not in str(
                    getattr(exc, "orig", exc)
                ):
                    raise
                for r in rows:
                    if r["token_hash"]:
                        th, ct, kv = self._gen_token_triplet(seen_hashes)
                        r["token_hash"] = th
                        r["token_ciphertext"] = ct
                        r["token_key_version"] = kv
        else:
            raise ConflictError(
                detail="Token collision không giải được sau retry — build lại."
            )

        campaign.build_revision = new_revision
        campaign.status = "ready"
        # Lưu ĐỦ footer (đã chặn >160 ở trên) → snapshot khớp tin cuối, audit
        # không bị cắt ngầm (P2-2 R7).
        campaign.optout_instruction_snapshot = optout_instruction or None
        await self.db.flush()
        return await self.preflight(campaign_id)

    # ===============================================================
    # Preflight report
    # ===============================================================
    async def preflight(
        self, campaign_id: int
    ) -> sms_schemas.SmsPreflightReport:
        campaign = await self.repo.get_campaign(campaign_id)
        if campaign is None:
            raise ResourceNotFoundError(detail="Không tìm thấy campaign")
        rev = campaign.build_revision
        link = has_link(campaign.sms_template)

        reason_counts = await self.repo.counts_by_excluded_reason(
            campaign_id, rev
        )
        total = sum(c for _, c in reason_counts)
        exportable = sum(c for r, c in reason_counts if r is None)
        excluded_by_reason = {
            r: c for r, c in reason_counts if r is not None
        }
        carrier_dist = await self.repo.counts_by_carrier_exportable(
            campaign_id, rev
        )
        over_rows = await self.repo.get_over_limit_rows(campaign_id, rev)
        over_limit = [
            sms_schemas.SmsOverLimitRow(
                phone_normalized=r.phone_normalized_snapshot,
                full_name=r.full_name_snapshot,
                encoding=r.encoding,
                length=r.message_length,
                segments=r.segments,
            )
            for r in over_rows
        ]

        warnings: List[str] = []
        if rev == 0:
            warnings.append("Chưa build — preflight trống.")
        if not link:
            warnings.append(
                "Template không có {link} → campaign này KHÔNG đo được click."
            )
        n_over = excluded_by_reason.get("over_limit", 0)
        if n_over:
            warnings.append(
                f"{n_over} recipient vượt 1 segment — EXPORT sẽ bị CHẶN cho "
                "tới khi rút gọn template/dữ liệu."
            )
        if n_over > len(over_limit):
            warnings.append(
                f"Danh sách over_limit chỉ hiển thị {len(over_limit)}/{n_over} "
                "(đã cắt) — sắp theo id."
            )

        # Stale: đã build (rev>0) nhưng đổi nhóm/nội dung sau đó (status=draft)
        # → số liệu & skeleton thuộc revision CŨ → báo rõ + KHÔNG show preview
        # cũ (tránh preview còn link khi has_link hiện tại đã =false). P2-1 R7.
        stale = campaign.status == "draft" and rev > 0
        if stale:
            warnings.append(
                "⚠ Có thay đổi nhóm/nội dung CHƯA build — số liệu & preview "
                f"thuộc revision {rev} CŨ; bấm Build lại để cập nhật."
            )

        # Preview ≤5 dòng tin cuối từ recipient exportable thực (§D6).
        if stale:
            preview: List[str] = []
        else:
            sample_skeletons = await self.repo.get_sample_skeletons(
                campaign_id, rev
            )
            preview = [preview_message(s) for s in sample_skeletons]

        return sms_schemas.SmsPreflightReport(
            campaign_id=campaign_id,
            build_revision=rev,
            status=campaign.status,
            has_link=link,
            total=total,
            exportable=exportable,
            excluded_by_reason=excluded_by_reason,
            carrier_distribution=carrier_dist,
            over_limit=over_limit,
            warnings=warnings,
            preview=preview,
        )

    # ===============================================================
    # Attestations (khớp build_revision hiện tại)
    # ===============================================================
    async def add_attestation(
        self, campaign_id: int, data: sms_schemas.SmsAttestationCreate, user
    ) -> SmsCampaign:
        campaign = await self.repo.get_campaign_for_update(campaign_id)
        if campaign is None:
            raise ResourceNotFoundError(detail="Không tìm thấy campaign")
        # CHỈ attest khi 'ready' (đã build, CHƯA export/bàn giao). Sau export
        # evidence đã đóng băng cho file đã sinh — cho sửa reference/actor/ts sẽ
        # khiến attestation lệch bằng chứng thực dùng; muốn đổi phải build lại.
        if campaign.status != "ready":
            raise BusinessRuleViolation(
                detail="Chỉ attest khi campaign ở trạng thái 'ready' (đã build, "
                "chưa export/bàn giao) — sau export evidence bị đóng băng."
            )
        now = datetime.now(timezone.utc)
        rev = campaign.build_revision
        uid = getattr(user, "id", None)
        if data.kind == "consent":
            campaign.consent_checked_at = now
            campaign.consent_checked_by_id = uid
            campaign.consent_reference = data.reference
            campaign.consent_checked_build_revision = rev
        elif data.kind == "dnc":
            campaign.dnc_checked_at = now
            campaign.dnc_checked_by_id = uid
            campaign.dnc_reference = data.reference
            campaign.dnc_checked_build_revision = rev
        else:  # optout_channel
            campaign.optout_channel_checked_at = now
            campaign.optout_channel_checked_by_id = uid
            campaign.optout_channel_reference = data.reference
            campaign.optout_channel_checked_build_revision = rev
        await self.db.flush()
        await self.db.refresh(campaign)
        gids = await self.repo.get_campaign_group_ids(campaign_id)
        return self._with_computed(campaign, group_count=len(gids))
