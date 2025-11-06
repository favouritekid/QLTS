"""replace_user_session_indexes_with_partial_ones

Revision ID: bf0ce03e4900
Revises: a1b2c3d4e5f6
Create Date: 2025-11-05 08:42:26.699698

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bf0ce03e4900'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

disable_ddl_transaction = True


def upgrade() -> None:
    """
    Nâng cấp: Xóa các index cũ (nếu tồn tại) và tạo partial indexes mới
    """
    
    connection = op.get_bind()
    
    check_query = """
        SELECT indexname 
        FROM pg_indexes 
        WHERE tablename = 'user_session' 
        AND indexname = :index_name
    """
    
    # 1. Xóa ix_user_session_user_active nếu tồn tại
    result = connection.execute(sa.text(check_query), {"index_name": "ix_user_session_user_active"})
    if result.fetchone():
        op.drop_index("ix_user_session_user_active", table_name="user_session", postgresql_concurrently=True)
    
    # 2. Xóa ix_user_session_refresh_jti nếu tồn tại
    result = connection.execute(sa.text(check_query), {"index_name": "ix_user_session_refresh_jti"})
    if result.fetchone():
        op.drop_index(op.f("ix_user_session_refresh_jti"), table_name="user_session", postgresql_concurrently=True)

    # 3. Tạo partial index cho user queries
    result = connection.execute(sa.text(check_query), {"index_name": "ix_user_session_active_partial"})
    if not result.fetchone():
        op.create_index(
            "ix_user_session_active_partial",
            "user_session",
            ["user_id", "revoked_at", "expires_at"],
            unique=False,
            postgresql_where=sa.text("revoked_at IS NULL"),
            postgresql_concurrently=True,
        )

    # 4. Tạo UNIQUE partial index cho JTI
    result = connection.execute(sa.text(check_query), {"index_name": "ix_user_session_jti_unique_partial"})
    if not result.fetchone():
        op.create_index(
            "ix_user_session_jti_unique_partial",
            "user_session",
            ["refresh_jti"],
            unique=True,
            postgresql_where=sa.text("revoked_at IS NULL"),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    """
    Hạ cấp: Xóa partial indexes và tạo lại full indexes
    """
    
    connection = op.get_bind()
    
    check_query = """
        SELECT indexname 
        FROM pg_indexes 
        WHERE tablename = 'user_session' 
        AND indexname = :index_name
    """
    
    # 1. Xóa partial indexes
    result = connection.execute(sa.text(check_query), {"index_name": "ix_user_session_active_partial"})
    if result.fetchone():
        op.drop_index("ix_user_session_active_partial", table_name="user_session", postgresql_concurrently=True)
    
    result = connection.execute(sa.text(check_query), {"index_name": "ix_user_session_jti_unique_partial"})
    if result.fetchone():
        op.drop_index("ix_user_session_jti_unique_partial", table_name="user_session", postgresql_concurrently=True)

    # 2. Tạo lại full indexes cũ
    result = connection.execute(sa.text(check_query), {"index_name": "ix_user_session_user_active"})
    if not result.fetchone():
        op.create_index(
            "ix_user_session_user_active",
            "user_session",
            ["user_id", "revoked_at", "expires_at"],
            unique=False,
            postgresql_concurrently=True,
        )
    
    result = connection.execute(sa.text(check_query), {"index_name": "ix_user_session_refresh_jti"})
    if not result.fetchone():
        op.create_index(
            op.f("ix_user_session_refresh_jti"),
            "user_session",
            ["refresh_jti"],
            unique=True,
            postgresql_concurrently=True,
        )