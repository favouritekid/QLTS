"""Quyền Casbin cho hai route ĐỌC mới của văn bản Hội đồng mà Quản lý dùng (vòng giao diện GĐ1).

Revision ID: hdts20261113
Revises: hdts20261112
Create Date: 2026-11-11

* ``GET …/sets/{set_id}/tai-ca-bo`` — tải cả bộ (đặc tả 3.6: quyền + phạm vi Y HỆT tải lẻ ⇒ Quản lý có dòng như
  ``…/sets/{set_id}/files/{thu_tu}``; phạm vi đơn vị ở ``deps.get_council_document_set_for_user``).
* ``GET …/nguoi-tao-bo`` — người tạo phân biệt của các bộ trong phạm vi (bộ lọc "Người tạo" của danh sách bộ —
  Quản lý xem được danh sách bộ đơn vị mình).

Admin qua wildcard ``/*``. Officer / accountant / user KHÔNG có dòng nào. Production KHÔNG tự đồng bộ
``policy_templates.py`` ⇒ thiếu migration này thì Quản lý nhận 403 THẬT ở hai route dù mọi test API xanh.

Cùng khuôn ``hdts20261105``: MỘT câu ``DO`` (``alembic/env.py`` chạy AUTOCOMMIT) chèn ``WHERE NOT EXISTS`` rồi tự kiểm
hậu điều kiện; ``v3`` (eft) BẮT BUỘC có giá trị — NULL làm ``load_policy()`` đổ. Downgrade xoá đúng các dòng mang
``template_id`` của migration này.
"""

from alembic import op

revision = "hdts20261113"
down_revision = "hdts20261112"
branch_labels = None
depends_on = None

TIEN_TO = "/api/admission-config/council-documents"
#: (v0, v1, v2, v3)
POLICIES = (
    ("role:manager", TIEN_TO + "/sets/{set_id}/tai-ca-bo", "GET", "allow"),
    ("role:manager", TIEN_TO + "/nguoi-tao-bo", "GET", "allow"),
)
TEMPLATE_ID = "_hdts20261113_council_document_vong_gd"


def _chen_policy_sql(v0, v1, v2, v3) -> str:
    return (
        "INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id, applied_at) "
        "SELECT 'p', '{v0}', '{v1}', '{v2}', '{v3}', '{tid}', now() "
        "WHERE NOT EXISTS (SELECT 1 FROM casbin_rule WHERE ptype = 'p' AND v0 = '{v0}' "
        "AND v1 = '{v1}' AND v2 = '{v2}' AND v3 = '{v3}')"
    ).format(v0=v0, v1=v1, v2=v2, v3=v3, tid=TEMPLATE_ID)


def _dem_policy_sql() -> str:
    dk = " OR ".join(
        "(v0 = '%s' AND v1 = '%s' AND v2 = '%s' AND v3 = '%s')" % p for p in POLICIES
    )
    return (
        "SELECT COUNT(DISTINCT (v0, v1, v2, v3)) INTO n FROM casbin_rule "
        "WHERE ptype = 'p' AND (%s)" % dk
    )


UPGRADE_DO_SQL = """
DO $hdtsg$
DECLARE n bigint;
BEGIN
{chen};
    {dem};
    IF n <> {so} THEN
        RAISE EXCEPTION USING MESSAGE = 'HDTSG: can ' || {so} || ' dong casbin, thay ' || n;
    END IF;
END
$hdtsg$
""".format(
    chen=";\n".join("    " + _chen_policy_sql(*p) for p in POLICIES),
    dem=_dem_policy_sql(),
    so=len(POLICIES),
)

DOWNGRADE_SQL = (
    "DELETE FROM casbin_rule WHERE ptype = 'p' AND template_id = '%s'" % TEMPLATE_ID
)


def upgrade() -> None:
    op.execute(UPGRADE_DO_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
