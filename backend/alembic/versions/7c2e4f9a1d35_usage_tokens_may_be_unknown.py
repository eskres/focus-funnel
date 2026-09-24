"""usage tokens may be unknown

Revision ID: 7c2e4f9a1d35
Revises: bc1bdf980860
Create Date: 2026-09-24 09:00:00.000000

A provider whose stream reports no usage (stream_usage: none) still has its
calls recorded, with the tokens and the cost unknown.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '7c2e4f9a1d35'
down_revision: Union[str, Sequence[str], None] = 'bc1bdf980860'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('usage_events') as batch:
        batch.alter_column('prompt_tokens', existing_type=sa.Integer(), nullable=True)
        batch.alter_column('completion_tokens', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    """Downgrade schema. Records with unknown tokens are removed first."""
    op.execute(
        "DELETE FROM usage_events WHERE prompt_tokens IS NULL OR completion_tokens IS NULL"
    )
    with op.batch_alter_table('usage_events') as batch:
        batch.alter_column('prompt_tokens', existing_type=sa.Integer(), nullable=False)
        batch.alter_column('completion_tokens', existing_type=sa.Integer(), nullable=False)
