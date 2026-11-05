"""Quyền Casbin cho route cờ quyền giao diện của văn bản Hội đồng (Lần xét tuyển GĐ1, lượt F).

Revision ID: hdts20261105
Revises: hdts20261104
Create Date: 2026-11-05

``GET /api/admission-config/council-documents/quyen`` trả cờ quyền GIAO DIỆN của người gọi —
máy chủ đánh giá chính các cổng (Casbin + phạm vi / chỉ-admin ở ``deps.py``) của từng route
(``deps.quyen_van_ban_hoi_dong``). Admin qua wildcard ``/*``; manager cần MỘT dòng (route ĐỌC,
không lộ dữ liệu: chỉ cờ của chính người gọi). Officer / accountant / user KHÔNG có dòng nào —
giữ luật "không dòng nào của module" (``test_quyen_manager_trong_template_co_migration_cap``);
giao diện coi 403 ở route này là "mọi cờ tắt".

Production KHÔNG tự đồng bộ ``policy_templates.py`` ⇒ thiếu migration này thì manager nhận 403
thật ở route cờ (giao diện ẩn hết dù quyền đọc bộ vẫn còn) dù mọi test API xanh.

Cùng khuôn ``hdts20261103b``: MỘT câu ``DO`` (``alembic/env.py`` chạy AUTOCOMMIT) chèn
``WHERE NOT EXISTS`` rồi tự kiểm hậu điều kiện; ``v3`` (eft) BẮT BUỘC có giá trị — NULL làm
``load_policy()`` đổ. Downgrade xoá đúng các dòng mang ``template_id`` của migration này.
"""

from alembic import op

revision = "hdts20261105"
down_revision = "hdts20261104"
branch_labels = None
depends_on = None

TIEN_TO = "/api/admission-config/council-documents"
#: (v0, v1, v2, v3)
POLICIES = (("role:manager", TIEN_TO + "/quyen", "GET", "allow"),)
TEMPLATE_ID = "_hdts20261105_council_document_flags"


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
DO $hdtsf$
DECLARE n bigint;
BEGIN
{chen};
    {dem};
    IF n <> {so} THEN
        RAISE EXCEPTION USING MESSAGE = 'HDTSF: can ' || {so} || ' dong casbin, thay ' || n;
    END IF;
END
$hdtsf$
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
