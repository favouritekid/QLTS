"""Finance maker-checker integrity: policy manager verify/reject + chặn self-reject.

Vá hai lỗ hổng CÙNG MỘT chủ đề — quyết định trên phiếu thu tay phải do người
KHÁC người ghi thực hiện — mà hôm nay đang hở ở hai đầu ngược nhau:

1. MANAGER KHÔNG VERIFY/REJECT ĐƯỢC (403).
   `policy_templates.py` cấp cho manager hai quyền này, nhưng KHÔNG migration
   nào đưa chúng vào `casbin_rule`: migration tháng 1 chỉ cấp cho accountant
   (`rbac20260131001`), migration tháng 6 chỉ thêm cho manager quyền ĐỌC danh
   sách/chi tiết payment (`fincollect_casbin_20260621`). Deploy chạy
   `alembic upgrade head` chứ KHÔNG chạy `scripts/sync_casbin_templates.py`,
   nên template không bao giờ tự tới được production. Hậu quả đo được trên dev:
   đơn vị chỉ có MỘT kế toán thì phiếu do người đó ghi không ai duyệt nổi —
   manager 403, kế toán còn lại khác đơn vị bị IDOR chặn, chỉ còn admin
   (wildcard `/*`). Luồng thu tay bế tắc.

2. MAKER TỰ TỪ CHỐI ĐƯỢC PHIẾU CỦA MÌNH.
   Ràng buộc `chk_payment_no_self_approval` chỉ nói về `verified_by_id`; tầng
   service cũng chỉ chặn self-verify. Nên `PUT /api/payments/{id}/reject` bởi
   chính người ghi trả 200 (tái hiện trên dev: payment #862, `created_by_id` =
   `rejected_by_id` = 4). Giao diện có ẩn nút, nhưng đó là chỉ dẫn cho người
   dùng chứ không phải hàng rào.

Vì sao gộp một migration: hai vế là hai nửa của cùng một bất biến. Tách ra thì
một môi trường có thể chạy nửa này mà thiếu nửa kia, và đúng khe đó là chỗ lỗi
vừa chui qua.

⚠️ CHECK constraint thêm ở dạng **NOT VALID**: dữ liệu cũ có thể đã chứa vi
phạm (dev có 1). NOT VALID chặn mọi hàng MỚI ngay lập tức mà không cần dọn lịch
sử trước — sửa lịch sử tiền bạc là quyết định nghiệp vụ, không phải việc của
migration. Migration chỉ ĐẾM và in ra. Sau khi nghiệp vụ xử lý xong, chạy tay:

    ALTER TABLE payment VALIDATE CONSTRAINT chk_payment_no_self_reject;

Revision ID: mkchk20260811
Revises: dbte20260803002
Create Date: 2026-08-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "mkchk20260811"
down_revision: Union[str, None] = "dbte20260803002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Đúng hai dòng còn thiếu so với MANAGER_TEMPLATE. Cố ý KHÔNG đồng bộ toàn bộ
# template ở đây: sync là thao tác xoá-rồi-ghi-lại toàn bộ policy của vai trò
# (`casbin_service.py`), nên nó vừa vượt phạm vi bản vá vừa xoá mất bằng chứng
# về những gì migration thật sự đã tạo ra.
_POLICIES: list[tuple[str, str, str]] = [
    ("role:manager", "/api/payments/{id}/verify", "PUT"),
    ("role:manager", "/api/payments/{id}/reject", "PUT"),
]

_CONSTRAINT = "chk_payment_no_self_reject"


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. Casbin: idempotent, khớp đúng hình dạng hàng mà enforcer đọc ──
    #
    # Bảng có cột v3 (effect). Các migration policy trước ghi 'allow', nên giữ
    # nguyên quy ước ấy — hàng lệch hình dạng sẽ không khớp matcher.
    for v0, v1, v2 in _POLICIES:
        conn.execute(
            sa.text(
                """
                INSERT INTO casbin_rule (ptype, v0, v1, v2, v3)
                SELECT 'p', CAST(:v0 AS varchar), CAST(:v1 AS varchar),
                       CAST(:v2 AS varchar), 'allow'
                WHERE NOT EXISTS (
                    SELECT 1 FROM casbin_rule
                    WHERE ptype = 'p'
                      AND v0 = CAST(:v0 AS varchar)
                      AND v1 = CAST(:v1 AS varchar)
                      AND v2 = CAST(:v2 AS varchar)
                )
                """
            ),
            {"v0": v0, "v1": v1, "v2": v2},
        )

    # ── 2. PREFLIGHT: đếm vi phạm lịch sử, KHÔNG tự sửa ──
    so_vi_pham = conn.execute(
        sa.text(
            """
            SELECT count(*) FROM payment
            WHERE rejected_by_id IS NOT NULL
              AND rejected_by_id = created_by_id
            """
        )
    ).scalar_one()

    if so_vi_pham:
        # In ra để người deploy thấy ngay, kèm câu lệnh tra cứu. Không raise:
        # chặn deploy vì dữ liệu lịch sử sẽ khiến bản vá KHÔNG bao giờ lên
        # được, tức là để ngỏ lỗ hổng cho hàng mới chỉ vì hàng cũ đã bẩn.
        print(
            f"[mkchk20260811] ⚠️  {so_vi_pham} phiếu thu đã bị CHÍNH người ghi "
            "từ chối (rejected_by_id = created_by_id).\n"
            "    Constraint được thêm ở dạng NOT VALID nên hàng MỚI đã bị chặn "
            "ngay, hàng cũ giữ nguyên để nghiệp vụ xử lý.\n"
            "    Tra cứu: SELECT id, invoice_id, amount, created_by_id, "
            "rejected_at FROM payment WHERE rejected_by_id = created_by_id;\n"
            "    Sau khi xử lý xong: ALTER TABLE payment VALIDATE CONSTRAINT "
            f"{_CONSTRAINT};"
        )

    # ── 3. CHECK constraint (NOT VALID) — đối xứng với self-approval ──
    #
    # `IF NOT EXISTS` không tồn tại cho ADD CONSTRAINT, nên kiểm qua catalog để
    # migration chạy lại được (môi trường đã có constraint do `create_all` của
    # test DB dựng từ model).
    da_co = conn.execute(
        sa.text(
            """
            SELECT 1 FROM pg_constraint
            WHERE conname = :ten AND conrelid = 'payment'::regclass
            """
        ),
        {"ten": _CONSTRAINT},
    ).first()

    if not da_co:
        op.execute(
            f"""
            ALTER TABLE payment
            ADD CONSTRAINT {_CONSTRAINT}
            CHECK (rejected_by_id IS NULL OR rejected_by_id != created_by_id)
            NOT VALID
            """
        )


def downgrade() -> None:
    conn = op.get_bind()

    op.execute(f"ALTER TABLE payment DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")

    for v0, v1, v2 in _POLICIES:
        conn.execute(
            sa.text(
                """
                DELETE FROM casbin_rule
                WHERE ptype = 'p'
                  AND v0 = CAST(:v0 AS varchar)
                  AND v1 = CAST(:v1 AS varchar)
                  AND v2 = CAST(:v2 AS varchar)
                """
            ),
            {"v0": v0, "v1": v1, "v2": v2},
        )
