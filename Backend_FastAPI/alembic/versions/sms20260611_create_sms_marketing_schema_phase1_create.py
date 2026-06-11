"""sms marketing schema phase1 create

Revision ID: sms20260611_create
Revises: schoolkv01_20260610
Create Date: 2026-06-11 12:35:04.208115

⚠ HAND-CLEANED: autogenerate kéo theo drift KHÔNG liên quan (đòi drop
casbin_rule / trusted_device backups / _archived_*, đổi hàng trăm comment,
tạo lại index admission/notification...). ĐÃ XÓA toàn bộ drift — migration
này CHỈ tạo 12 bảng SMS Marketing Phase 1. Index đặc biệt giữ nguyên: GIN
group_ids_snapshot, partial-UNIQUE token_hash, composite (campaign_id,
build_revision, carrier_bucket), unique gửi-1-lần.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'sms20260611_create'
down_revision: Union[str, Sequence[str], None] = 'schoolkv01_20260610'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — chỉ tạo 12 bảng SMS Marketing Phase 1."""
    op.create_table('sms_prefix_carrier_rule',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('prefix', sa.String(length=4), nullable=False, comment="3 ký tự đầu gồm số 0, vd '032','086'"),
    sa.Column('carrier_code', sa.String(length=20), nullable=False, comment='viettel/vinaphone/mobifone/vietnamobile/gmobile'),
    sa.Column('carrier_name', sa.String(length=50), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('prefix')
    )
    op.create_table('sms_campaign',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='draft', nullable=False),
    sa.Column('frequency_cap_days', sa.Integer(), nullable=True, comment='NULL = dùng SMS_FREQUENCY_CAP_DAYS mặc định'),
    sa.Column('sms_template', sa.Text(), nullable=False, comment='chứa {name}/{full_name}/{link}'),
    sa.Column('landing_type', sa.String(length=20), server_default='qlts_hosted', nullable=False),
    sa.Column('landing_url', sa.Text(), nullable=True),
    sa.Column('landing_headline', sa.String(length=200), nullable=True),
    sa.Column('landing_body', sa.Text(), nullable=True, comment='plain text; KHÔNG render HTML (XSS)'),
    sa.Column('landing_cta_label', sa.String(length=100), nullable=True),
    sa.Column('landing_cta_url', sa.Text(), nullable=True),
    sa.Column('build_revision', sa.Integer(), server_default='0', nullable=False, comment='tăng sau mỗi build'),
    sa.Column('link_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('optout_instruction_snapshot', sa.String(length=160), nullable=True, comment='hướng dẫn từ chối qua SMS/điện thoại đã chèn vào tin cuối'),
    sa.Column('consent_checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('consent_checked_by_id', sa.Integer(), nullable=True),
    sa.Column('consent_reference', sa.String(length=512), nullable=True),
    sa.Column('consent_checked_build_revision', sa.Integer(), nullable=True),
    sa.Column('dnc_checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('dnc_checked_by_id', sa.Integer(), nullable=True),
    sa.Column('dnc_reference', sa.String(length=512), nullable=True, comment='nguồn/case/report đối soát thực tế'),
    sa.Column('dnc_checked_build_revision', sa.Integer(), nullable=True),
    sa.Column('optout_channel_checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('optout_channel_checked_by_id', sa.Integer(), nullable=True),
    sa.Column('optout_channel_reference', sa.String(length=512), nullable=True),
    sa.Column('optout_channel_checked_build_revision', sa.Integer(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('handed_off_marked_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("landing_type IN ('qlts_hosted','external')", name='chk_sms_campaign_landing_type'),
    sa.CheckConstraint("status IN ('draft','ready','exported','handed_off','closed')", name='chk_sms_campaign_status'),
    sa.CheckConstraint('build_revision >= 0', name='chk_sms_campaign_build_revision'),
    sa.ForeignKeyConstraint(['consent_checked_by_id'], ['user.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by_id'], ['user.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['dnc_checked_by_id'], ['user.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['optout_channel_checked_by_id'], ['user.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_index(op.f('ix_sms_campaign_created_by_id'), 'sms_campaign', ['created_by_id'], unique=False)
    op.create_table('sms_contact',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('full_name', sa.String(length=255), nullable=False),
    sa.Column('phone_raw', sa.String(length=32), nullable=True, comment='số gốc nhập'),
    sa.Column('phone_normalized', sa.String(length=20), nullable=False, comment='0xxxxxxxxx — duy nhất toàn hệ thống'),
    sa.Column('phone_international', sa.String(length=20), nullable=False, comment='84xxxxxxxxx (xuất Excel)'),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('source_label', sa.String(length=255), nullable=True, comment='nguồn liên hệ'),
    sa.Column('marketing_consent_status', sa.String(length=20), server_default='unknown', nullable=False, comment='unknown / granted / revoked'),
    sa.Column('marketing_consented_at', sa.DateTime(timezone=True), nullable=True, comment='thời điểm opt-in gần nhất'),
    sa.Column('marketing_consent_basis', sa.String(length=30), nullable=True, comment='explicit_form / signed_form / recorded_call / imported_proof'),
    sa.Column('marketing_consent_proof_ref', sa.String(length=512), nullable=True, comment='tham chiếu bằng chứng; KHÔNG chứa secret'),
    sa.Column('consent_disclosure_version', sa.String(length=50), nullable=True, comment='phiên bản câu chữ đã đồng ý'),
    sa.Column('last_handed_off_at', sa.DateTime(timezone=True), nullable=True, comment='lần gần nhất số này thuộc batch đã bàn giao (frequency-cap proxy)'),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("marketing_consent_basis IS NULL OR marketing_consent_basis IN ('explicit_form','signed_form','recorded_call','imported_proof')", name='chk_sms_contact_consent_basis'),
    sa.CheckConstraint("marketing_consent_status IN ('unknown','granted','revoked')", name='chk_sms_contact_consent_status'),
    sa.CheckConstraint("marketing_consent_status <> 'granted' OR (marketing_consented_at IS NOT NULL AND marketing_consent_basis IS NOT NULL AND marketing_consent_proof_ref IS NOT NULL AND consent_disclosure_version IS NOT NULL)", name='chk_sms_contact_granted_requires_proof'),
    sa.ForeignKeyConstraint(['created_by_id'], ['user.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('phone_normalized')
    )
    op.create_index(op.f('ix_sms_contact_created_by_id'), 'sms_contact', ['created_by_id'], unique=False)
    op.create_table('sms_contact_group',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('code', sa.String(length=50), nullable=False, comment='slug duy nhất'),
    sa.Column('group_type', sa.String(length=20), nullable=False, comment='parent / student / teacher / lead / custom'),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("group_type IN ('parent','student','teacher','lead','custom')", name='chk_sms_contact_group_type'),
    sa.ForeignKeyConstraint(['created_by_id'], ['user.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_index(op.f('ix_sms_contact_group_created_by_id'), 'sms_contact_group', ['created_by_id'], unique=False)
    op.create_table('sms_campaign_export_batch',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('campaign_id', sa.Integer(), nullable=False),
    sa.Column('build_revision', sa.Integer(), nullable=False),
    sa.Column('group_id', sa.Integer(), nullable=True, comment='NULL nếu export gộp nhiều nhóm (B2)'),
    sa.Column('group_name_snapshot', sa.String(length=200), nullable=True, comment='nhãn filename (B2)'),
    sa.Column('carrier_bucket', sa.String(length=20), nullable=False),
    sa.Column('recipient_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=True, comment='{Nhóm}-{Campaign}-{NhàMạng}.xlsx (set khi generated)'),
    sa.Column('storage_path', sa.String(length=512), nullable=True, comment='NGOÀI public webroot (§11.7)'),
    sa.Column('file_sha256', sa.String(length=64), nullable=True),
    sa.Column('file_size_bytes', sa.BigInteger(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('purged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
    sa.Column('failure_reason', sa.Text(), nullable=True, comment='lỗi tạo/ghi file đã sanitize'),
    sa.Column('invalidated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('generated_by_id', sa.Integer(), nullable=True),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('marked_handed_off_at', sa.DateTime(timezone=True), nullable=True, comment="bấm 'Đã bàn giao' per nhà mạng"),
    sa.CheckConstraint("status IN ('pending','generated','handed_off','failed','purged','invalidated')", name='chk_sms_export_batch_status'),
    sa.ForeignKeyConstraint(['campaign_id'], ['sms_campaign.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['generated_by_id'], ['user.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['group_id'], ['sms_contact_group.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('campaign_id', 'build_revision', 'carrier_bucket', name='uq_sms_export_campaign_rev_carrier')
    )
    op.create_index(op.f('ix_sms_campaign_export_batch_campaign_id'), 'sms_campaign_export_batch', ['campaign_id'], unique=False)
    op.create_table('sms_campaign_group',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('campaign_id', sa.Integer(), nullable=False),
    sa.Column('group_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['campaign_id'], ['sms_campaign.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['group_id'], ['sms_contact_group.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('campaign_id', 'group_id', name='uq_sms_campaign_group')
    )
    op.create_index(op.f('ix_sms_campaign_group_campaign_id'), 'sms_campaign_group', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_sms_campaign_group_group_id'), 'sms_campaign_group', ['group_id'], unique=False)
    op.create_table('sms_campaign_recipient',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('campaign_id', sa.Integer(), nullable=False),
    sa.Column('build_revision', sa.Integer(), nullable=False),
    sa.Column('contact_id', sa.Integer(), nullable=True, comment='snapshot giữ kể cả khi contact bị xoá'),
    sa.Column('group_ids_snapshot', postgresql.ARRAY(sa.Integer()), nullable=False, comment='nhóm đã chọn đóng góp contact này (report theo nhóm)'),
    sa.Column('full_name_snapshot', sa.String(length=255), nullable=False),
    sa.Column('phone_normalized_snapshot', sa.String(length=20), nullable=False, comment='0xxxxxxxxx'),
    sa.Column('phone_international_snapshot', sa.String(length=20), nullable=False, comment='84xxxxxxxxx (xuất Excel)'),
    sa.Column('note_snapshot', sa.Text(), nullable=True),
    sa.Column('carrier_bucket', sa.String(length=20), nullable=False, comment='viettel … unknown'),
    sa.Column('token_hash', sa.String(length=64), nullable=True, comment='HMAC-SHA256(code, SMS_TOKEN_HASH_SECRET); NULL nếu không có {link}'),
    sa.Column('token_ciphertext', sa.Text(), nullable=True, comment='Fernet ciphertext của code'),
    sa.Column('token_key_version', sa.String(length=32), nullable=True, comment='chọn key trong key-ring'),
    sa.Column('rendered_message_skeleton', sa.Text(), nullable=True, comment='tin cuối dùng sentinel cố định cho link; KHÔNG chứa raw code'),
    sa.Column('message_length', sa.Integer(), nullable=True),
    sa.Column('encoding', sa.String(length=8), nullable=True, comment='GSM7 / UCS2'),
    sa.Column('segments', sa.Integer(), nullable=True),
    sa.Column('is_over_limit', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('excluded_reason', sa.String(length=30), nullable=True, comment='no_consent/opted_out/dnc_suppressed/frequency_capped/over_limit/missing_data/NULL(=export)'),
    sa.Column('invalidated_at', sa.DateTime(timezone=True), nullable=True, comment='revision cũ chưa bàn giao bị vô hiệu khi rebuild'),
    sa.Column('handed_off_at', sa.DateTime(timezone=True), nullable=True, comment='set khi batch tương ứng được xác nhận bàn giao'),
    sa.Column('raw_click_count', sa.Integer(), server_default='0', nullable=False, comment='tổng click GỒM bot (audit)'),
    sa.Column('human_click_count', sa.Integer(), server_default='0', nullable=False, comment="click loại bot — 'đã click' hiển thị cho người dùng"),
    sa.Column('first_human_clicked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_human_clicked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("encoding IS NULL OR encoding IN ('GSM7','UCS2')", name='chk_sms_recipient_encoding'),
    sa.CheckConstraint("excluded_reason IS NULL OR excluded_reason IN ('no_consent','opted_out','dnc_suppressed','frequency_capped','over_limit','missing_data')", name='chk_sms_recipient_excluded_reason'),
    sa.CheckConstraint("(token_hash IS NULL AND token_ciphertext IS NULL AND token_key_version IS NULL) OR (token_hash IS NOT NULL AND token_ciphertext IS NOT NULL AND token_key_version IS NOT NULL)", name='chk_sms_recipient_token_triplet'),
    sa.ForeignKeyConstraint(['campaign_id'], ['sms_campaign.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['contact_id'], ['sms_contact.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sms_campaign_recipient_campaign_id'), 'sms_campaign_recipient', ['campaign_id'], unique=False)
    op.create_index('ix_sms_recipient_campaign_rev_carrier', 'sms_campaign_recipient', ['campaign_id', 'build_revision', 'carrier_bucket'], unique=False)
    op.create_index('ix_sms_recipient_group_ids_gin', 'sms_campaign_recipient', ['group_ids_snapshot'], unique=False, postgresql_using='gin')
    op.create_index('uq_sms_recipient_campaign_rev_phone', 'sms_campaign_recipient', ['campaign_id', 'build_revision', 'phone_normalized_snapshot'], unique=True)
    op.create_index('uq_sms_recipient_token_hash', 'sms_campaign_recipient', ['token_hash'], unique=True, postgresql_where=sa.text('token_hash IS NOT NULL'))
    op.create_table('sms_contact_group_member',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('group_id', sa.Integer(), nullable=False),
    sa.Column('contact_id', sa.Integer(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True, comment='ghi chú riêng trong nhóm này'),
    sa.Column('added_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['added_by_id'], ['user.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['contact_id'], ['sms_contact.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['group_id'], ['sms_contact_group.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('group_id', 'contact_id', name='uq_sms_group_member_group_contact')
    )
    op.create_index(op.f('ix_sms_contact_group_member_added_by_id'), 'sms_contact_group_member', ['added_by_id'], unique=False)
    op.create_index(op.f('ix_sms_contact_group_member_contact_id'), 'sms_contact_group_member', ['contact_id'], unique=False)
    op.create_index(op.f('ix_sms_contact_group_member_group_id'), 'sms_contact_group_member', ['group_id'], unique=False)
    op.create_table('sms_contact_import_batch',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('group_id', sa.Integer(), nullable=True, comment='nhóm đích; SET NULL khi xóa group (giữ audit import)'),
    sa.Column('file_name', sa.String(length=255), nullable=True),
    sa.Column('file_sha256', sa.String(length=64), nullable=True),
    sa.Column('source_label', sa.String(length=255), nullable=True),
    sa.Column('consent_basis', sa.String(length=30), nullable=True, comment='explicit_form / signed_form / recorded_call / imported_proof'),
    sa.Column('consent_disclosure_version', sa.String(length=50), nullable=True, comment='bắt buộc nếu lô tạo consent event'),
    sa.Column('consent_proof_ref', sa.String(length=512), nullable=True, comment='bắt buộc nếu lô tạo consent event'),
    sa.Column('consent_obtained_at', sa.DateTime(timezone=True), nullable=True, comment='bắt buộc nếu lô tạo consent event'),
    sa.Column('row_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('valid_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('invalid_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('duplicate_contact_count', sa.Integer(), server_default='0', nullable=False, comment='trùng phone trong CHÍNH file upload'),
    sa.Column('existing_member_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('inserted_contact_count', sa.Integer(), server_default='0', nullable=False, comment='contact mới tạo (phone chưa từng có)'),
    sa.Column('added_member_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('skipped_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('uploaded_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("consent_basis IS NULL OR consent_basis IN ('explicit_form','signed_form','recorded_call','imported_proof')", name='chk_sms_import_batch_consent_basis'),
    sa.CheckConstraint("row_count >= 0 AND valid_count >= 0 AND invalid_count >= 0 AND duplicate_contact_count >= 0 AND existing_member_count >= 0 AND inserted_contact_count >= 0 AND added_member_count >= 0 AND skipped_count >= 0", name='chk_sms_import_batch_counts_nonneg'),
    sa.CheckConstraint("row_count = valid_count + invalid_count + duplicate_contact_count", name='chk_sms_import_batch_row_total'),
    sa.CheckConstraint("skipped_count = invalid_count + duplicate_contact_count", name='chk_sms_import_batch_skipped_total'),
    sa.CheckConstraint("added_member_count + existing_member_count = valid_count", name='chk_sms_import_batch_member_total'),
    sa.CheckConstraint("inserted_contact_count <= valid_count", name='chk_sms_import_batch_inserted_le_valid'),
    sa.ForeignKeyConstraint(['group_id'], ['sms_contact_group.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['uploaded_by_id'], ['user.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sms_contact_import_batch_group_id'), 'sms_contact_import_batch', ['group_id'], unique=False)
    op.create_index(op.f('ix_sms_contact_import_batch_uploaded_by_id'), 'sms_contact_import_batch', ['uploaded_by_id'], unique=False)
    op.create_table('sms_opt_out',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('phone_normalized', sa.String(length=20), nullable=False, comment='khóa toàn cục'),
    sa.Column('source', sa.String(length=30), nullable=False, comment='landing_optout/manual/sms_reply/phone_call/external_suppression'),
    sa.Column('campaign_id', sa.Integer(), nullable=True, comment='campaign dẫn tới opt-out'),
    sa.Column('contact_id', sa.Integer(), nullable=True),
    sa.Column('revoked_by_id', sa.Integer(), nullable=True, comment='ai ghi (manual)'),
    sa.Column('source_reference', sa.String(length=512), nullable=True, comment='provider ticket/file/call reference'),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False, comment='thời điểm nhận từ chối/nguồn suppression'),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("source IN ('landing_optout','manual','sms_reply','phone_call','external_suppression')", name='chk_sms_opt_out_source'),
    sa.ForeignKeyConstraint(['campaign_id'], ['sms_campaign.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['contact_id'], ['sms_contact.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['revoked_by_id'], ['user.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('phone_normalized')
    )
    op.create_table('sms_click_event',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('recipient_id', sa.Integer(), nullable=False),
    sa.Column('campaign_id', sa.Integer(), nullable=False, comment='denormalize query nhanh'),
    sa.Column('contact_id', sa.Integer(), nullable=True),
    sa.Column('clicked_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('ip_hash', sa.String(length=64), nullable=True, comment='HMAC-SHA256(ip, SMS_IP_HASH_SECRET); KHÔNG lưu IP thô/prefix'),
    sa.Column('user_agent', sa.String(length=512), nullable=True),
    sa.Column('is_suspected_bot', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('bot_reason', sa.String(length=50), nullable=True, comment='known_scanner_ua / prefetch_head / instant_after_send'),
    sa.ForeignKeyConstraint(['campaign_id'], ['sms_campaign.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['contact_id'], ['sms_contact.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['recipient_id'], ['sms_campaign_recipient.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sms_click_event_campaign_id'), 'sms_click_event', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_sms_click_event_clicked_at'), 'sms_click_event', ['clicked_at'], unique=False)
    op.create_index(op.f('ix_sms_click_event_recipient_id'), 'sms_click_event', ['recipient_id'], unique=False)
    op.create_table('sms_marketing_consent_event',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('contact_id', sa.Integer(), nullable=True, comment='SET NULL (KHÔNG cascade): ledger phải sống sót khi xóa contact'),
    sa.Column('phone_normalized_snapshot', sa.String(length=20), nullable=False, comment='bằng chứng vẫn đọc được nếu contact đổi/xóa'),
    sa.Column('event_type', sa.String(length=20), nullable=False),
    sa.Column('basis', sa.String(length=30), nullable=False, comment='explicit_form / signed_form / recorded_call / imported_proof'),
    sa.Column('disclosure_version', sa.String(length=50), nullable=False, comment='nội dung đồng ý áp dụng'),
    sa.Column('proof_reference', sa.String(length=512), nullable=False, comment='tham chiếu artifact bên ngoài hoặc object private'),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False, comment='thời điểm sự kiện thực'),
    sa.Column('recorded_by_id', sa.Integer(), nullable=True),
    sa.Column('import_batch_id', sa.Integer(), nullable=True),
    sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='metadata tối thiểu, không chứa secret/PII thừa'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("basis IN ('explicit_form','signed_form','recorded_call','imported_proof')", name='chk_sms_consent_event_basis'),
    sa.CheckConstraint("event_type IN ('granted','revoked')", name='chk_sms_consent_event_type'),
    sa.ForeignKeyConstraint(['contact_id'], ['sms_contact.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['import_batch_id'], ['sms_contact_import_batch.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['recorded_by_id'], ['user.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sms_marketing_consent_event_contact_id'), 'sms_marketing_consent_event', ['contact_id'], unique=False)


def downgrade() -> None:
    """Downgrade — drop 12 bảng SMS theo thứ tự FK-safe (con trước cha).

    PG tự drop index/constraint kèm bảng nên không cần drop_index riêng.
    """
    op.drop_table('sms_marketing_consent_event')
    op.drop_table('sms_click_event')
    op.drop_table('sms_opt_out')
    op.drop_table('sms_contact_group_member')
    op.drop_table('sms_contact_import_batch')
    op.drop_table('sms_campaign_recipient')
    op.drop_table('sms_campaign_group')
    op.drop_table('sms_campaign_export_batch')
    op.drop_table('sms_contact_group')
    op.drop_table('sms_contact')
    op.drop_table('sms_campaign')
    op.drop_table('sms_prefix_carrier_rule')
