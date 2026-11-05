"""add thought status

Revision ID: f160f49f7141
Revises: 4d7a1c9e2b60
Create Date: 2026-11-05 15:00:00.000000

Adds a thought's status, open or done, and the time of its last status
change (thought-status design decision 3). Every existing thought becomes
open with no change time. The check constraint is added in batch mode, so
SQLite rebuilds the table. The downgrade drops the constraint and both
columns; statuses set since are lost.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f160f49f7141'
down_revision: Union[str, Sequence[str], None] = '4d7a1c9e2b60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('thoughts', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('status', sa.Text(), server_default='open', nullable=False)
        )
        batch_op.add_column(
            sa.Column('status_changed_at', sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_check_constraint(
            op.f('ck_thoughts_status'), "status IN ('open', 'done')"
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('thoughts', schema=None) as batch_op:
        batch_op.drop_constraint(op.f('ck_thoughts_status'), type_='check')
        batch_op.drop_column('status_changed_at')
        batch_op.drop_column('status')
