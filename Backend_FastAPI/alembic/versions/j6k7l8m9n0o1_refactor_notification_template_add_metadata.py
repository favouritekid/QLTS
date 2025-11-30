"""refactor notification template add metadata fields

Revision ID: j6k7l8m9n0o1
Revises: i5j6k7l8m9n0
Create Date: 2025-11-30 11:00:00.000000

"""
from typing import Sequence, Union
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = 'j6k7l8m9n0o1'
down_revision: Union[str, None] = 'i5j6k7l8m9n0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def generate_template_code(name: str, existing_codes: set, template_id: int) -> str:
    """
    Generate unique template_code from name.

    Handles duplicate codes by appending template ID.
    Example: "Lead Assignment" -> "TPL_LEAD_ASSIGNMENT"
             If duplicate: "TPL_LEAD_ASSIGNMENT_123"

    Args:
        name: Template name
        existing_codes: Set of already generated codes
        template_id: Template ID for uniqueness

    Returns:
        Unique template code
    """
    # Convert to uppercase and replace spaces/special chars with underscore
    base_code = re.sub(r'[^A-Z0-9]+', '_', name.upper())
    base_code = f"TPL_{base_code}".strip('_')

    # If unique, return as-is
    if base_code not in existing_codes:
        return base_code

    # If duplicate, append template ID
    unique_code = f"{base_code}_{template_id}"
    return unique_code


def upgrade() -> None:
    """
    ✅ NOTIFICATION 2.0 - PHASE 1: Refactor notification_template table.

    Adds 4 new metadata fields to support:
        1. template_code: Code-based referencing (instead of ID)
        2. supported_channels: Filter templates by channel
        3. allowed_events: Filter templates by event
        4. template_type: Classify template types

    This migration safely handles existing data by:
        - Generating unique template_code from name
        - Setting default values for new fields
        - Handling duplicate codes gracefully
    """

    # Step 1: Add new columns with temporary nullable constraints
    op.add_column(
        'notification_template',
        sa.Column('template_code', sa.String(length=100), nullable=True,
                 comment='Template code (unique identifier for referencing)')
    )
    op.add_column(
        'notification_template',
        sa.Column('supported_channels', postgresql.JSON(astext_type=sa.Text()), nullable=True,
                 comment='Channels this template supports')
    )
    op.add_column(
        'notification_template',
        sa.Column('allowed_events', postgresql.JSON(astext_type=sa.Text()), nullable=True,
                 comment='Events this template is designed for (null = all events)')
    )
    op.add_column(
        'notification_template',
        sa.Column('template_type', sa.String(length=50), nullable=True,
                 comment='Template type: system, zalo_zns, email_html, sms')
    )

    # Step 2: Populate template_code for existing records
    # Use Python to generate codes safely handling duplicates
    connection = op.get_bind()

    # Fetch all existing templates
    result = connection.execute(text(
        "SELECT id, name FROM notification_template ORDER BY id"
    ))
    templates = result.fetchall()

    existing_codes = set()

    # Generate and update template_code for each template
    for template_id, name in templates:
        template_code = generate_template_code(name, existing_codes, template_id)
        existing_codes.add(template_code)

        connection.execute(
            text(
                "UPDATE notification_template "
                "SET template_code = :code "
                "WHERE id = :id"
            ),
            {"code": template_code, "id": template_id}
        )

    # Step 3: Populate default values for other new columns
    connection.execute(text(
        """
        UPDATE notification_template
        SET
            supported_channels = '["socket"]'::jsonb,
            template_type = 'system'
        WHERE supported_channels IS NULL
        """
    ))

    # Step 4: Alter columns to NOT NULL and add constraints
    op.alter_column(
        'notification_template',
        'template_code',
        nullable=False,
        existing_type=sa.String(length=100)
    )
    op.alter_column(
        'notification_template',
        'supported_channels',
        nullable=False,
        existing_type=postgresql.JSON(astext_type=sa.Text()),
        server_default='["socket"]'
    )
    op.alter_column(
        'notification_template',
        'template_type',
        nullable=False,
        existing_type=sa.String(length=50),
        server_default='system'
    )

    # Step 5: Create indexes for efficient querying
    op.create_index(
        op.f('ix_notification_template_template_code'),
        'notification_template',
        ['template_code'],
        unique=True
    )

    # Step 6: Create unique constraint on template_code
    op.create_unique_constraint(
        'uq_notification_template_code',
        'notification_template',
        ['template_code']
    )


def downgrade() -> None:
    """
    Rollback: Remove added metadata fields.
    """
    # Drop constraints and indexes
    op.drop_constraint('uq_notification_template_code', 'notification_template', type_='unique')
    op.drop_index(op.f('ix_notification_template_template_code'), table_name='notification_template')

    # Drop columns
    op.drop_column('notification_template', 'template_type')
    op.drop_column('notification_template', 'allowed_events')
    op.drop_column('notification_template', 'supported_channels')
    op.drop_column('notification_template', 'template_code')
