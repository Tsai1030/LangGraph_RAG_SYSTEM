"""split input/output tokens for accurate cost estimate

Revision ID: c6ee55ce0d95
Revises: 9431d4e5169d
Create Date: 2026-05-07 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c6ee55ce0d95'
down_revision: Union[str, Sequence[str], None] = '9431d4e5169d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add input_tokens / output_tokens columns to messages table.

    token_count (total = input + output) 保留供 timeseries 圖表彙總用；
    新欄位 input_tokens / output_tokens 用於精準成本計算（input 與 output 單價差 6 倍）。
    """
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('input_tokens', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('output_tokens', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Drop input_tokens / output_tokens columns."""
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_column('output_tokens')
        batch_op.drop_column('input_tokens')
