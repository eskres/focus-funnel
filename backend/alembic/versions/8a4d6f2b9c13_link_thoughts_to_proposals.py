"""link thoughts to proposals

Revision ID: 8a4d6f2b9c13
Revises: 3f9d1b7e5a28
Create Date: 2026-09-25 08:00:36.841314

Adds thoughts.proposal_id, then fills it from each proposal's saved parts. A
part whose thought is gone is skipped. The downgrade drops the column.
"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8a4d6f2b9c13'
down_revision: Union[str, Sequence[str], None] = '3f9d1b7e5a28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

proposals = sa.table(
    'proposals',
    sa.column('id', sa.Uuid()),
    sa.column('user_id', sa.Uuid()),
    sa.column('parts', sa.JSON()),
)
thoughts = sa.table(
    'thoughts',
    sa.column('id', sa.Uuid()),
    sa.column('user_id', sa.Uuid()),
    sa.column('proposal_id', sa.Uuid()),
)


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('thoughts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('proposal_id', sa.Uuid(), nullable=True))
        batch_op.create_index(batch_op.f('ix_thoughts_proposal_id'), ['proposal_id'], unique=False)
        batch_op.create_foreign_key(batch_op.f('fk_thoughts_proposal_id_proposals'), 'proposals', ['proposal_id'], ['id'], ondelete='SET NULL')

    # In Python rather than SQL, so it reads the JSON list the same way on
    # SQLite and Postgres. An update that matches no thought changes nothing.
    bind = op.get_bind()
    for row in bind.execute(sa.select(proposals.c.id, proposals.c.user_id, proposals.c.parts)):
        for part in row.parts or []:
            thought_id = part.get('thought_id')
            if not thought_id:
                continue
            bind.execute(
                thoughts.update()
                .where(thoughts.c.id == uuid.UUID(thought_id), thoughts.c.user_id == row.user_id)
                .values(proposal_id=row.id)
            )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('thoughts', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_thoughts_proposal_id_proposals'), type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_thoughts_proposal_id'))
        batch_op.drop_column('proposal_id')
