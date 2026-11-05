"""add setup state

Revision ID: 4d7a1c9e2b60
Revises: 2bea7235fdf6
Create Date: 2026-11-05 12:00:00.000000

Adds the one-row setup_state table that tracks the first-run setup wizard.
The row is created here and nowhere else. An install that already has a user
counts as set up, so it never prints a setup token after the upgrade.
Downgrade drops the table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4d7a1c9e2b60'
down_revision: Union[str, Sequence[str], None] = '2bea7235fdf6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

users = sa.table('users', sa.column('id', sa.Uuid()))


def upgrade() -> None:
    """Upgrade schema."""
    setup_state = op.create_table(
        'setup_state',
        sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=True),
        sa.Column('token_created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('id = 1', name=op.f('ck_setup_state_single_row')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_setup_state')),
    )
    in_use = sa.exists(sa.select(users.c.id))
    op.execute(
        setup_state.insert().from_select(
            ['id', 'completed_at'],
            sa.select(
                sa.literal(1),
                sa.case((in_use, sa.func.current_timestamp()), else_=sa.null()),
            ),
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('setup_state')
