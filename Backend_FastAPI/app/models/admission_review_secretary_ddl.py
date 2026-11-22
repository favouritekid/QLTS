# app/models/admission_review_secretary_ddl.py
"""GĐ2-C C1 — trigger "chỉ thu hồi, không xoá" của bảng quyền Thư ký Hội đồng (thiết kế GĐ2-C §2.2).

Tầng chủ sở hữu bất biến = trigger CSDL (bắt mọi đường ghi, kể cả SQL tay):

* ``DELETE`` một dòng quyền ⇒ chặn (lịch sử ai từng là Thư ký phải còn — K4 dựa vào nó để chặn xoá tài khoản);
* ``UPDATE`` chỉ được làm ĐÚNG một việc: ghi thu hồi lần đầu (``revoked_at`` từ NULL sang có giá trị) và không đổi cột nào
  của lần gán (người, người gán, lúc gán, lý do). Thu hồi lần hai, sửa lý do, "mở lại" quyền đã thu hồi ⇒ chặn.
  Ba cột thu hồi phải đi cùng nhau — CHECK ``ck_review_secretary_grant_revoked_triple`` của bảng lo phần ấy.

Lỗi mang SQLSTATE :data:`SQLSTATE_SECRETARY_GRANT_IMMUTABLE` — dịch vụ không bao giờ chạm tới (dịch vụ chỉ ghi thu hồi
một lần, dưới khoá dòng); gặp mã này = có đường ghi sai ⇒ để 500 (fail-closed), không đổi thành câu dễ hiểu.

Bản cho ``create_all()`` (CSDL test không chạy Alembic — khuôn ``admission_quota_ddl``). Bản thật: migration
``gd2c20261122`` chép NGUYÊN câu; hai bản khoá bằng ``tests/unit/test_gd2c_c1_ddl_lockin.py``. KHÔNG dùng ``%`` (``DDL()``
nội suy bằng ``%``) và ``::`` (``text()`` của migration hiểu ``:tên`` là tham số).
"""
from sqlalchemy import DDL, event

from app.models.base import Base

#: SQLSTATE riêng (5 ký tự, lớp tự đặt). Đã kiểm còn trống trong ``app/`` + ``alembic/`` của nền này VÀ của GĐ2-B
#: (GĐ2-B dùng ``QLC01``–``QLC04``, ``QLC10``–``QLC12``).
SQLSTATE_SECRETARY_GRANT_IMMUTABLE = "QLC20"

SQL_FN_REVOKE_ONLY = """
CREATE OR REPLACE FUNCTION admission_review_secretary_grant_revoke_only()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'admission_review_secretary_grant: chi thu hoi, khong xoa'
            USING ERRCODE = 'QLC20';
    END IF;
    IF OLD.revoked_at IS NOT NULL
       OR NEW.revoked_at IS NULL
       OR NEW.id IS DISTINCT FROM OLD.id
       OR NEW.user_id IS DISTINCT FROM OLD.user_id
       OR NEW.granted_by_user_id IS DISTINCT FROM OLD.granted_by_user_id
       OR NEW.granted_at IS DISTINCT FROM OLD.granted_at
       OR NEW.reason IS DISTINCT FROM OLD.reason THEN
        RAISE EXCEPTION 'admission_review_secretary_grant: chi duoc ghi thu hoi mot lan, khong sua lan gan'
            USING ERRCODE = 'QLC20';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

SQL_TRIGGER_REVOKE_ONLY = """
CREATE TRIGGER trg_admission_review_secretary_grant_revoke_only
BEFORE UPDATE OR DELETE ON admission_review_secretary_grant
FOR EACH ROW EXECUTE FUNCTION admission_review_secretary_grant_revoke_only()
"""

#: Thứ tự có ý nghĩa: hàm trước, trigger sau.
STATEMENTS = (SQL_FN_REVOKE_ONLY, SQL_TRIGGER_REVOKE_ONLY)
#: Hàm hạ cấp phải gỡ (tên + kiểu tham số) — khoá bằng test so với câu ``CREATE OR REPLACE FUNCTION``.
FUNCTION_SIGNATURES = ("admission_review_secretary_grant_revoke_only()",)


def _register():
    """Gắn vào ``after_create`` của METADATA (mọi bảng đã có mặt). ``CREATE TRIGGER`` chạy lại được nhờ ĐÚNG helper của
    ``duplicate_guard_ddl`` (một nguồn); ``STATEMENTS`` giữ nguyên văn để khớp migration."""
    from app.models.finance.duplicate_guard_ddl import _lam_chay_lai_duoc

    for statement in STATEMENTS:
        event.listen(
            Base.metadata, "after_create", DDL(_lam_chay_lai_duoc(statement)).execute_if(dialect="postgresql")
        )


_register()
