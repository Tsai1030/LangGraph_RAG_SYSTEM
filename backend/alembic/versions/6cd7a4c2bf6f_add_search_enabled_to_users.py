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
    """Add search_enabled column to users — DIRECT ADD COLUMN.

    Why NOT batch_alter_table here:
        On SQLite, alembic's `batch_alter_table` recreates the table:
        CREATE TABLE _alembic_tmp_users → INSERT SELECT → DROP users →
        RENAME _alembic_tmp_users TO users.
        Foreign-key cascade chains pointing at users
        (conversations.user_id ON DELETE CASCADE →
         messages.conversation_id ON DELETE CASCADE →
         conversation_summaries.conversation_id ON DELETE CASCADE)
        fire during DROP users if foreign_keys=ON in that connection's
        session, nuking ALL chat data. Prod cutover hit this and lost
        52 conversations + 321 messages before we caught it.

    `op.add_column` (without batch) emits plain `ALTER TABLE users ADD
    COLUMN search_enabled BOOLEAN NOT NULL DEFAULT 0`. SQLite has
    supported this natively since 3.2 — column added in place, no
    other table touched, no cascade trigger.

    server_default is required to back-fill existing rows when adding a
    NOT NULL boolean — without it ADD COLUMN would fail on any DB that
    already has users.

    server_default=sa.false() emits the dialect-appropriate boolean literal:
    'false' on PostgreSQL, '0' on SQLite (both back-fill rows to False).
    Using sa.text('0') breaks on PostgreSQL ("type boolean but default
    expression is of type integer").
    """
    op.add_column(
        'users',
        sa.Column(
            'search_enabled',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    """Drop search_enabled column.

    SQLite native DROP COLUMN landed in 3.35 (2021); on older SQLite
    this falls back to batch_alter_table internally, which would
    re-introduce the cascade-delete risk this upgrade fixed. If you
    really need to roll back, prefer the pre-migration DB backup over
    running this — see SEARCH_INTEGRATION_PLAN.md §6.5.
    """
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('search_enabled')
