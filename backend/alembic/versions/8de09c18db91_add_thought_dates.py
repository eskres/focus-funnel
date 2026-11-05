"""add thought dates

Revision ID: 8de09c18db91
Revises: 8a4d6f2b9c13
Create Date: 2026-11-05 09:00:00.000000

Adds a thought's optional date: starts_on, starts_at, ends_on, ends_at, and
time_zone, all nullable, kept as the user's wall time (thought-dates design
decision 1). On Postgres it also adds the partial index on (user_id,
starts_on) for dated thoughts. No backfill: existing thoughts have no date.
The downgrade drops the index and the columns; dates set since are lost.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8de09c18db91'
down_revision: Union[str, Sequence[str], None] = '8a4d6f2b9c13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX = 'ix_thoughts_user_id_starts_on'


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('thoughts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('starts_on', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('starts_at', sa.Time(), nullable=True))
        batch_op.add_column(sa.Column('ends_on', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('ends_at', sa.Time(), nullable=True))
        batch_op.add_column(sa.Column('time_zone', sa.Text(), nullable=True))
    if op.get_bind().dialect.name == 'postgresql':
        op.create_index(
            INDEX, 'thoughts', ['user_id', 'starts_on'], unique=False,
            postgresql_where=sa.text('starts_on IS NOT NULL'),
        )


def downgrade() -> None:
    """Downgrade schema."""
    if op.get_bind().dialect.name == 'postgresql':
        op.drop_index(INDEX, table_name='thoughts')
    with op.batch_alter_table('thoughts', schema=None) as batch_op:
        batch_op.drop_column('time_zone')
        batch_op.drop_column('ends_at')
        batch_op.drop_column('ends_on')
        batch_op.drop_column('starts_at')
        batch_op.drop_column('starts_on')
