"""add_search_enabled_to_users

Revision ID: 6cd7a4c2bf6f
Revises: c6ee55ce0d95
Create Date: 2026-05-18 14:33:14.836841

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6cd7a4c2bf6f'
down_revision: Union[str, Sequence[str], None] = 'c6ee55ce0d95'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add search_enabled column to users.

    server_default='0' is required to back-fill existing rows when adding a
    NOT NULL boolean — without it the migration would fail on any DB that
    already has users. New accounts get False by default; admin must
    explicitly grant access via PATCH /admin/users/{id}/search-permission.
    """
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'search_enabled',
                sa.Boolean(),
                nullable=False,
                server_default=sa.text('0'),
            )
        )


def downgrade() -> None:
    """Drop search_enabled column."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('search_enabled')
