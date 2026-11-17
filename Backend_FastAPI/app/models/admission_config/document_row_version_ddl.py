"""GĐ1b — trigger tăng ``profile_document.row_version`` ở MỌI lệnh UPDATE (đặc tả bản 3.6 §4.3, §4.5).

Tầng chủ sở hữu bất biến "mọi lần đổi dòng giấy đều đổi phiên bản" = trigger CSDL: bắt mọi đường ghi, kể cả SQL tay và
các hàm dịch vụ viết sau. Mã ứng dụng KHÔNG tự gán ``row_version``; ghi có điều kiện ``WHERE id AND row_version``.

Bản này cho ``create_all()`` (CSDL test không chạy Alembic — khuôn ``council_config_lock_ddl``). Bản thật: migration
``gd1b20261117`` chép NGUYÊN câu; ``tests/unit/test_gd1b_models_khop_migration.py`` so hai bên sau khi chuẩn hoá
khoảng trắng. Migration KHÔNG import module này.

KHÔNG dùng ``%`` (``DDL()`` nội suy bằng ``%``) và KHÔNG dùng ``::`` (``text()`` hiểu ``:tên`` là tham số).
"""
from sqlalchemy import DDL, event

from app.models.base import Base

SQL_FN_ROW_VERSION = """
CREATE OR REPLACE FUNCTION profile_document_bump_row_version()
RETURNS TRIGGER AS $$
BEGIN
    NEW.row_version := OLD.row_version + 1;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

SQL_TRIGGER_ROW_VERSION = """
CREATE TRIGGER trg_profile_document_row_version
BEFORE UPDATE ON profile_document
FOR EACH ROW EXECUTE FUNCTION profile_document_bump_row_version()
"""

#: Thứ tự có ý nghĩa: hàm trước, trigger sau.
STATEMENTS = (SQL_FN_ROW_VERSION, SQL_TRIGGER_ROW_VERSION)


def _register():
    for statement in STATEMENTS:
        event.listen(Base.metadata, "after_create", DDL(statement).execute_if(dialect="postgresql"))


_register()
