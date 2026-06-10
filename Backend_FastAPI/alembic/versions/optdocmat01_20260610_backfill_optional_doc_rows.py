"""Backfill: materialize ProfileDocument row cho optional doc thiếu row.

Revision ID: optdocmat01_20260610
Revises: resetcasbin01
Create Date: 2026-06-10

Bug: officer bấm "Xác nhận bản giấy vừa nhận" cho tài liệu TÙY CHỌN
(``is_mandatory=false``, vd ``giay_xac_nhan_cu_tru`` / ``giay_kham_suc_khoe``)
→ 404 ``Document code '...' not found in profile documents``.

Gốc: lúc tạo hồ sơ (``initialize_documents_for_profile``) và lúc re-resolve
(``add_path_documents_delta``) chỉ materialize ``ProfileDocument`` row cho
``mandatory_docs``, KHÔNG cho optional doc. Nhưng GET response (sau PR #394)
dựng ``documents_checklist`` từ TOÀN BỘ ``applied_rules.doc_configs`` keyset →
optional doc hiện nút thao tác nhưng không có row để cập nhật → 404
(``mark_paper_submitted``) hoặc no-op thầm lặng (``upload``). Service đã sửa
gốc (truyền full doc_configs keyset ở cả 2 điểm); migration này vá các hồ sơ
LỊCH SỬ đã tạo trước fix.

- Predicate CHẶT: chỉ INSERT cho ``doc_configs`` key CHƯA có row
  ``category='path'`` (NOT EXISTS guard) → tôn trọng ``uq_profile_document_path``.
- Idempotent: chạy lại = no-op (NOT EXISTS lọc hết row đã có).
- Row mới: ``status='missing'``, ``category='path'``, không file/paper → trung
  tính. Optional row KHÔNG ảnh hưởng submit/completion (``_validate_documents``
  + ``document_stats`` lọc theo ``mandatory_docs``).
- Downgrade: no-op — không phân biệt được row do migration tạo vs row 'missing'
  hợp lệ; xoá là rủi ro. Forward-only.
- Scope đã verify prod 2026-06-10: 15 hồ sơ draft × 2 optional doc = 30 row.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "optdocmat01_20260610"
down_revision = "resetcasbin01"
branch_labels = None
depends_on = None


# INSERT 1 row category='path' status='missing' cho mỗi doc_configs key đang
# thiếu row. CROSS JOIN LATERAL bung keyset; JOIN config_document_type ánh xạ
# code→id; NOT EXISTS chặn trùng (idempotent + không vi phạm partial-unique).
_BACKFILL_SQL = """
INSERT INTO profile_document
    (profile_id, document_type_id, category, status, created_at, updated_at)
SELECT ap.id, cdt.id, 'path', 'missing', now(), now()
FROM admission_profile ap
CROSS JOIN LATERAL jsonb_object_keys(ap.applied_rules->'doc_configs') AS k(code)
JOIN config_document_type cdt ON cdt.code = k.code
WHERE ap.applied_rules ? 'doc_configs'
  -- ``?`` chỉ kiểm tra KEY tồn tại; nếu value là JSON null / array / scalar,
  -- jsonb_object_keys() sẽ NÉM "cannot call jsonb_object_keys on a non-object"
  -- và làm hỏng CẢ migration. Guard kiểu để bỏ qua row dị thường (legacy / sửa
  -- tay) thay vì crash. Dry-run prod 2026-06-10: 0 row dính, nhưng vá phòng xa.
  AND jsonb_typeof(ap.applied_rules -> 'doc_configs') = 'object'
  AND NOT EXISTS (
      SELECT 1 FROM profile_document pd
      WHERE pd.profile_id = ap.id
        AND pd.document_type_id = cdt.id
        AND pd.category = 'path'
  );
"""


def upgrade() -> None:
    op.get_bind().execute(sa.text(_BACKFILL_SQL))


def downgrade() -> None:
    # No-op: row 'missing' do migration tạo không phân biệt được với row 'missing'
    # hợp lệ → không xoá. Forward-only.
    pass
