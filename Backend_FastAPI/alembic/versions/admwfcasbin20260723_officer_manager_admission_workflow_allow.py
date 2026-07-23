"""seed casbin ALLOW còn thiếu: officer /withdraw + officer/manager v2 publish-result/waitlist

Vá drift đo được trên PROD 2026-07-23 (audit qua enforce() live): các endpoint
admission-workflow mới role-gated đã được thêm vào ``policy_templates.py`` (nguồn
sự thật) NHƯNG chỉ có nhánh ``deny`` (accountant) được seed vào ``casbin_rule``,
còn nhánh ``allow`` (officer/manager) thì KHÔNG một migration nào seed. Vì
``AUTO_SYNC_TEMPLATES=False`` ở prod (safety) nên enforcer prod chạy với policy
thiếu → officer bấm "Rút hồ sơ" bị **403** (Casbin default-deny), làm bế tắc quy
trình rút + hoàn học phí (officer BẮT BUỘC là maker để né deadlock refund unit 14 —
memory refund-approval-unit14-no-manager).

6 row cần có (5 đầu đã khai sẵn trong policy_templates.py — chỉ bù SEED; row 6 là
gap SÂU hơn, bổ sung CẢ template trong cùng PR này):
  1. role:officer  POST /api/admissions/{id}/withdraw                   (OFFICER_TEMPLATE)
  2. role:officer  GET  /api/v2/admissions/*/publish-result            (OFFICER_TEMPLATE)
  3. role:manager  POST /api/v2/admissions/*/publish-result            (MANAGER_TEMPLATE)
  4. role:manager  POST /api/v2/admissions/*/waitlist-promote          (MANAGER_TEMPLATE)
  5. role:manager  POST /api/v2/admissions/*/waitlist-reject           (MANAGER_TEMPLATE)
  6. role:manager  GET  /api/organization-units/tree-with-aggregation  (MANAGER_TEMPLATE — MỚI)

Row 6: trang admin "Organization Tree" (FE nav gate admin+manager) gọi endpoint trả
aggregation TOÀN TRƯỜNG (service `get_organization_tree_with_aggregation` KHÔNG scope
theo user). Mục tiêu = admin+manager allow, officer+accountant DENY.

⚠️ SỬA SAU CODE-REVIEW: KHÔNG phải "endpoint chưa có policy nào". Migration nền
`p2q3r4s5t6u7` (2024-11-19) ĐÃ seed `role:officer GET tree-with-aggregation` ("for
dropdowns"), `phase1_19b` backfill eft='allow'. ⇒ ở môi trường build-từ-migration
(CI/DR-rebuild), officer VÀ accountant (kế thừa officer) đang = allow = LỘ số liệu
toàn trường. Prod hiện DENY (cold-cutover ghi đè casbin, chưa từng có row officer
này). Để nhất quán MỌI môi trường theo FE nav, upgrade() vừa ADD manager (grant trên)
VỪA XÓA row officer legacy (bên dưới). KHÔNG dùng officer-DENY vì manager kế thừa
officer → deny-override sẽ chặn cả manager. Đã thêm manager vào MANAGER_TEMPLATE.

Không cần seed row allow cho manager /withdraw (manager kế thừa officer qua g-policy
``role:manager -> role:officer``) hay admin (wildcard ``/*``). Accountant kế thừa
officer nhưng đã có ``deny`` tường minh riêng cho từng object → deny-override giữ
tài chính KHÔNG rút/không publish/không waitlist (đúng nghiệp vụ).

Ghi WITH v3 (eft): mọi p-row đều mang eft; NULL eft làm ``load_policy`` crash ở lần
reload kế tiếp (memory casbin-insert-must-include-eft). Idempotent kiểu UPSERT
(UPDATE sửa eft drift TRƯỚC rồi mới INSERT nếu thiếu) — KHÔNG chỉ ``WHERE NOT
EXISTS`` vì row đã tồn tại với eft sai/NULL sẽ khiến INSERT bị bỏ qua mà policy vẫn
hỏng. Cùng khuôn với distpanelcasbin20260719 / enrolllettercasbin20260718.

⚠️ PROD đã được vá TAY (5 row INSERT + restart backend) ngày 2026-07-23 để khơi
thông vận hành ngay; migration này chỉ để VERSIONED + chống tái drift ở môi trường
mới (fresh CI/dev). Trên prod nó là no-op idempotent (row đã có, eft='allow' khớp).

Revision ID: admwfcasbin20260723
Revises: admderivedcols20260721
Create Date: 2026-07-23
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "admwfcasbin20260723"
down_revision = "admderivedcols20260721"
branch_labels = None
depends_on = None

# (subject, object, action) — eft luôn 'allow' cho block này.
_GRANTS = [
    ("role:officer", "/api/admissions/{id}/withdraw", "POST"),
    ("role:officer", "/api/v2/admissions/*/publish-result", "GET"),
    ("role:manager", "/api/v2/admissions/*/publish-result", "POST"),
    ("role:manager", "/api/v2/admissions/*/waitlist-promote", "POST"),
    ("role:manager", "/api/v2/admissions/*/waitlist-reject", "POST"),
    # Manager oversight — cây tổ chức + aggregation toàn trường (trang admin
    # "Organization Tree", FE nav gate admin+manager). Đây là gap SÂU hơn 5 cái
    # trên: trước 23-07 endpoint KHÔNG có trong policy_templates.py (nên chưa role
    # non-admin nào qua được), nay bổ sung vào MANAGER_TEMPLATE cùng PR này. Officer
    # CỐ Ý không cấp (service không scope theo user → không lộ số liệu toàn trường).
    ("role:manager", "/api/organization-units/tree-with-aggregation", "GET"),
]


def _upsert_allow(subject: str, obj: str, action: str) -> None:
    """Đảm bảo tồn tại ĐÚNG 1 row (subject, obj, action) với eft='allow'.

    UPDATE sửa drift eft TRƯỚC (row đã có nhưng eft sai/NULL sẽ khiến bước INSERT
    WHERE NOT EXISTS bỏ qua mà vẫn hỏng — memory casbin-insert-must-include-eft),
    rồi INSERT nếu thực sự chưa có.
    """
    op.execute(
        f"""
        UPDATE casbin_rule
        SET v3 = 'allow'
        WHERE ptype = 'p'
          AND v0 = '{subject}'
          AND v1 = '{obj}'
          AND v2 = '{action}'
          AND (v3 IS DISTINCT FROM 'allow')
        """
    )
    op.execute(
        f"""
        INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id)
        SELECT 'p', '{subject}', '{obj}', '{action}', 'allow', '_legacy'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p'
              AND v0 = '{subject}'
              AND v1 = '{obj}'
              AND v2 = '{action}'
        )
        """
    )


# Over-grant legacy cần XÓA để officer/accountant KHÔNG xem aggregation toàn trường
# (xem docstring — p2q3r4s5t6u7 seed row này). Xoá thẳng, KHÔNG dùng officer-DENY vì
# manager kế thừa officer sẽ dính deny-override. Prod: no-op (row chưa từng tồn tại).
_REVOKE = ("role:officer", "/api/organization-units/tree-with-aggregation", "GET")


def upgrade() -> None:
    for subject, obj, action in _GRANTS:
        _upsert_allow(subject, obj, action)
    subject, obj, action = _REVOKE
    op.execute(
        f"""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
          AND v0 = '{subject}'
          AND v1 = '{obj}'
          AND v2 = '{action}'
        """
    )


def downgrade() -> None:
    # Xoá 6 row allow migration này thêm. KHÔNG khôi phục row officer tree-agg
    # legacy (p2q3r4s5t6u7) — nó là over-grant/leak; nếu thật sự cần, chạy lại
    # semantics p2q3r4s5t6u7 thủ công. (Downgrade không-identity là house-style
    # đã chấp nhận — cùng khuôn distpanelcasbin/enrolllettercasbin.)
    for subject, obj, action in _GRANTS:
        op.execute(
            f"""
            DELETE FROM casbin_rule
            WHERE ptype = 'p'
              AND v0 = '{subject}'
              AND v1 = '{obj}'
              AND v2 = '{action}'
              AND v3 = 'allow'
            """
        )
