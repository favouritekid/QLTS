"""add casbin policy: officer ALLOW + accountant DENY /api/officer/distribution-panel

Bảng "điểm bận" (`GET /api/officer/distribution-panel`) giải trình cách engine
chia lead cho CẢ ĐƠN VỊ. Khác các widget officer khác (chỉ xem của mình), endpoint
này lộ TÊN + TẢI của toàn phòng tư vấn nên cần 2 row:

1. ``role:officer`` **allow** — officer là người dùng chính (xem vị trí của mình
   giữa cả phòng). role:manager kế thừa role:officer qua g-policy nên cũng được;
   role:admin đã có wildcard.
2. ``role:accountant`` **deny** — accountant CŨNG kế thừa role:officer
   (diamond inheritance), nên nếu chỉ thêm row allow ở trên thì Casbin sẽ cho
   accountant qua, chỉ còn dependency chặn. Dữ liệu nhân sự/tải của phòng tư vấn
   nằm ngoài phạm vi kế toán ⇒ deny tường minh ngay ở policy layer.
   (Cùng khuôn với consultacctdeny20260716.)

Ghi WITH v3 (eft) — mọi p-row hiện có đều mang eft; NULL eft làm Casbin
``load_policy`` crash ở lần reload kế tiếp (memory casbin-insert-must-include-eft).
Idempotent theo kiểu UPSERT (UPDATE sửa eft drift rồi mới INSERT nếu thiếu), KHÔNG
chỉ ``WHERE NOT EXISTS`` — vì row đã tồn tại với eft sai/NULL sẽ khiến INSERT bị bỏ
qua mà policy vẫn hỏng.

Revision ID: distpanelcasbin20260719
Revises: consultacctdeny20260716
Create Date: 2026-07-19
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "distpanelcasbin20260719"
down_revision = "consultacctdeny20260716"
branch_labels = None
depends_on = None

_OBJ = "/api/officer/distribution-panel"


def _upsert(subject: str, eft: str) -> None:
    """Đảm bảo tồn tại ĐÚNG 1 row (subject, _OBJ, GET) với eft mong muốn.

    Hai bước, vì `WHERE NOT EXISTS` một mình KHÔNG đủ idempotent: nếu môi trường
    đã có row cùng (ptype,v0,v1,v2) nhưng eft sai/NULL (drift do seed tay hoặc
    template cũ), INSERT sẽ bị bỏ qua và policy vẫn sai — đúng thứ mà
    memory casbin-insert-must-include-eft cảnh báo (NULL eft làm load_policy crash).
    → UPDATE sửa drift TRƯỚC, rồi INSERT nếu thực sự chưa có.
    """
    op.execute(
        f"""
        UPDATE casbin_rule
        SET v3 = '{eft}'
        WHERE ptype = 'p'
          AND v0 = '{subject}'
          AND v1 = '{_OBJ}'
          AND v2 = 'GET'
          AND (v3 IS DISTINCT FROM '{eft}')
        """
    )
    op.execute(
        f"""
        INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id)
        SELECT 'p', '{subject}', '{_OBJ}', 'GET', '{eft}', '_legacy'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p'
              AND v0 = '{subject}'
              AND v1 = '{_OBJ}'
              AND v2 = 'GET'
        )
        """
    )


def upgrade() -> None:
    # template_id='_legacy' khớp các row role:officer/role:accountant hiện có
    # → row mới không bị logic quản-lý-template coi là orphan.
    _upsert("role:officer", "allow")
    _upsert("role:accountant", "deny")


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
          AND v1 = '{_OBJ}'
          AND v2 = 'GET'
          AND v0 IN ('role:officer', 'role:accountant')
        """
    )
