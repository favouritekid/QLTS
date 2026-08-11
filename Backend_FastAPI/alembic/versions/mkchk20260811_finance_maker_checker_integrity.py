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

# Dấu vết chủ sở hữu: chỉ những dòng mang marker này mới là do migration này
# tạo ra, và chỉ chúng được phép gỡ khi downgrade.
_MARKER = "mkchk20260811"


def upgrade() -> None:
    conn = op.get_bind()

    # ── 0. PREFLIGHT CASBIN: có DENY sẵn thì DỪNG, không âm thầm ghi đè ──
    #
    # Một dòng `deny` cùng (v0, v1, v2) là quyết định của ai đó, có thể là hàng
    # rào cố ý. Thêm `allow` bên cạnh nó là đổi nghĩa của policy mà không ai
    # thấy — và tuỳ thứ tự/effect của model, kết quả có thể là mở quyền. Fail
    # đóng: dừng deploy, để người ra quyết định gỡ deny một cách tường minh.
    for v0, v1, v2 in _POLICIES:
        co_deny = conn.execute(
            sa.text(
                """
                SELECT 1 FROM casbin_rule
                WHERE ptype = 'p'
                  AND v0 = CAST(:v0 AS varchar)
                  AND v1 = CAST(:v1 AS varchar)
                  AND v2 = CAST(:v2 AS varchar)
                  AND v3 = 'deny'
                LIMIT 1
                """
            ),
            {"v0": v0, "v1": v1, "v2": v2},
        ).first()
        if co_deny:
            raise RuntimeError(
                f"[{_MARKER}] Đã tồn tại policy DENY cho ({v0}, {v1}, {v2}). "
                "Migration này KHÔNG ghi đè: thêm allow bên cạnh một deny cố ý "
                "là đổi nghĩa hàng rào mà không ai thấy. Hãy gỡ dòng deny một "
                "cách tường minh rồi chạy lại."
            )

        # 🔴 `v3 IS NULL` cũng phải DỪNG, và vì một lý do nặng hơn deny.
        #
        # Adapter tuần tự hoá hàng ấy thành policy BA trường, còn model khai
        # bốn. Khi enforcer nạp phải nó, `enforce()` ném
        # `RuntimeError: invalid policy size` — tức toàn bộ authorization 500,
        # chứ không phải "thiếu một quyền". Và nó nổ kể cả khi dòng allow bốn
        # trường đã nằm ngay cạnh: thêm allow KHÔNG chữa được, vì dòng hỏng vẫn
        # còn đó.
        #
        # Nên migration không tự dọn (xoá/ghi đè một hàng policy là quyết định
        # về quyền, không phải dọn rác) mà dừng hẳn để người vận hành xử lý.
        co_null = conn.execute(
            sa.text(
                """
                SELECT count(*) FROM casbin_rule
                WHERE ptype = 'p'
                  AND v0 = CAST(:v0 AS varchar)
                  AND v1 = CAST(:v1 AS varchar)
                  AND v2 = CAST(:v2 AS varchar)
                  AND v3 IS NULL
                """
            ),
            {"v0": v0, "v1": v1, "v2": v2},
        ).scalar_one()
        if co_null:
            raise RuntimeError(
                f"[{_MARKER}] Có {co_null} dòng policy ({v0}, {v1}, {v2}) với "
                "v3 IS NULL — hình dạng BA trường mà adapter sẽ nạp vào một "
                "model bốn trường, và enforce() sẽ ném 'invalid policy size' "
                "(authorization 500 toàn hệ thống). Thêm allow bên cạnh KHÔNG "
                "chữa được.\n"
                "    Xử lý trước khi chạy lại, ví dụ:\n"
                "      UPDATE casbin_rule SET v3 = 'allow'\n"
                "       WHERE ptype='p' AND v0=%r AND v1=%r AND v2=%r "
                "AND v3 IS NULL;\n"
                "    (hoặc DELETE nếu dòng đó không còn dùng)"
                % (v0, v1, v2)
            )

    # ── 1. Casbin: idempotent theo ĐỦ BỐN TRƯỜNG, có provenance ──
    #
    # 🔴 So cả `v3`. Bản trước chỉ so (ptype, v0, v1, v2): nếu DB đã có đúng
    # route ấy với `v3 = NULL` (hình dạng cũ, không khớp matcher) thì
    # `WHERE NOT EXISTS` coi như "đã có", migration im lặng không thêm gì, và
    # manager VẪN 403 — đúng triệu chứng mà migration này sinh ra để chữa.
    #
    # `template_id` đánh dấu dòng do CHÍNH migration này tạo, để downgrade chỉ
    # gỡ đúng thứ mình đặt vào (xem `downgrade`).
    for v0, v1, v2 in _POLICIES:
        conn.execute(
            sa.text(
                """
                INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id)
                SELECT 'p', CAST(:v0 AS varchar), CAST(:v1 AS varchar),
                       CAST(:v2 AS varchar), 'allow', CAST(:marker AS varchar)
                WHERE NOT EXISTS (
                    SELECT 1 FROM casbin_rule
                    WHERE ptype = 'p'
                      AND v0 = CAST(:v0 AS varchar)
                      AND v1 = CAST(:v1 AS varchar)
                      AND v2 = CAST(:v2 AS varchar)
                      AND v3 = 'allow'
                )
                """
            ),
            {"v0": v0, "v1": v1, "v2": v2, "marker": _MARKER},
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

    # 🔴 CHỈ gỡ dòng do CHÍNH migration này đặt vào: khớp `template_id` và
    # `v3='allow'`. Bản trước xoá theo (v0, v1, v2) và do đó cuốn theo mọi
    # effect — kể cả một `deny` cố ý hoặc một `allow` đã có từ trước, những thứ
    # migration này chưa bao giờ sở hữu. Downgrade phải trả môi trường về đúng
    # trạng thái trước khi chạy, không nhiều hơn.
    for v0, v1, v2 in _POLICIES:
        conn.execute(
            sa.text(
                """
                DELETE FROM casbin_rule
                WHERE ptype = 'p'
                  AND v0 = CAST(:v0 AS varchar)
                  AND v1 = CAST(:v1 AS varchar)
                  AND v2 = CAST(:v2 AS varchar)
                  AND v3 = 'allow'
                  AND template_id = CAST(:marker AS varchar)
                """
            ),
            {"v0": v0, "v1": v1, "v2": v2, "marker": _MARKER},
        )
