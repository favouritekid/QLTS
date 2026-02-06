"""add MFA fields to user

Revision ID: z8e9f0g1h2i3
Revises: z7d8e9f0g1h2
Create Date: 2026-02-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'z8e9f0g1h2i3'
down_revision: Union[str, None] = 'z7d8e9f0g1h2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'user',
        sa.Column(
            'mfa_enabled',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Whether TOTP MFA is enabled for this user',
        ),
    )
    op.add_column(
        'user',
        sa.Column(
            'totp_secret_encrypted',
            sa.String(256),
            nullable=True,
            comment='Fernet-encrypted TOTP secret (base32)',
        ),
    )
    op.add_column(
        'user',
        sa.Column(
            'backup_codes_hashed',
            sa.Text(),
            nullable=True,
            comment='JSON array of bcrypt-hashed backup codes',
        ),
    )


def downgrade() -> None:
    op.drop_column('user', 'backup_codes_hashed')
    op.drop_column('user', 'totp_secret_encrypted')
    op.drop_column('user', 'mfa_enabled')
