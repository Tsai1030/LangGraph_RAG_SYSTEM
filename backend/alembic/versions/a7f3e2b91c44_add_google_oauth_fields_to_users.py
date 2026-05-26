"""add google oauth fields to users

Revision ID: a7f3e2b91c44
Revises: 6cd7a4c2bf6f
Create Date: 2026-05-26 10:00:00.000000

加 Google OAuth 綁定欄位 + 將 password_hash 改為 nullable
（因為純 Google 註冊的使用者沒有密碼）。

新欄位：
- google_sub: Google ID token 的 sub claim，是 Google 帳號的唯一識別。
  email 可被改，sub 不會。用來防 email 被盜改而接管帳號。UNIQUE NULL。
- avatar_url: 從 Google 拿到的頭像，純展示用，可選。

password_hash → nullable：
  既有密碼帳號不受影響（其值仍然存在）。新建立的純 Google 帳號則為 NULL。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7f3e2b91c44'
down_revision: Union[str, Sequence[str], None] = '6cd7a4c2bf6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # password_hash 改 nullable — 用 op.alter_column 直接下 ALTER TABLE
    # PG 原生支援 ALTER COLUMN ... DROP NOT NULL；SQLite 需要 batch_alter_table，
    # 但 6cd7a4c2bf6f 的 commit message 已經提過 batch 在 users 表的風險。
    # 這個 repo 已經 cutover 到 PostgreSQL（見 .env），所以直接走 PG path。
    op.alter_column('users', 'password_hash',
                    existing_type=sa.String(length=255),
                    nullable=True)

    op.add_column(
        'users',
        sa.Column('google_sub', sa.String(length=255), nullable=True),
    )
    op.create_unique_constraint('uq_users_google_sub', 'users', ['google_sub'])
    op.create_index('idx_users_google_sub', 'users', ['google_sub'], unique=False)

    op.add_column(
        'users',
        sa.Column('avatar_url', sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('users', 'avatar_url')
    op.drop_index('idx_users_google_sub', table_name='users')
    op.drop_constraint('uq_users_google_sub', 'users', type_='unique')
    op.drop_column('users', 'google_sub')

    # 把 password_hash 變回 NOT NULL 前要先確保沒 NULL；rollback 情境下使用者要自己處理。
    op.alter_column('users', 'password_hash',
                    existing_type=sa.String(length=255),
                    nullable=False)
