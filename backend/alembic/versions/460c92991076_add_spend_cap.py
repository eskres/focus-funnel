"""add spend cap

Revision ID: 460c92991076
Revises: f160f49f7141
Create Date: 2026-11-06 10:00:00.000000

Adds the monthly spend cap to user_settings (stop-and-spend-cap design
decision 6): its unit, usd or tokens, and its amount. Both are nullable and
null means no cap, so every existing row gets no cap. The downgrade drops
both columns; saved caps are lost.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '460c92991076'
down_revision: Union[str, Sequence[str], None] = 'f160f49f7141'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cap_unit', sa.String(length=8), nullable=True))
        batch_op.add_column(sa.Column('cap_amount', sa.Numeric(precision=18, scale=6), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        batch_op.drop_column('cap_amount')
        batch_op.drop_column('cap_unit')
