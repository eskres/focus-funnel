"""add thought additions and similarity baselines

Revision ID: 0162bb890895
Revises: 2bea7235fdf6
Create Date: 2026-11-05 02:44:10.248621

Creates thought_additions, one row per addition to a saved thought with the
fields it had before, so undo can restore them. Adds similarity_p95,
similarity_p99, and baseline_thoughts to search_indexes for the
similar-thought check's cut-offs. No backfill: baselines are measured on the
next rebuild or on growth. The downgrade drops both.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0162bb890895'
down_revision: Union[str, Sequence[str], None] = '2bea7235fdf6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('thought_additions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('thought_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('proposal_id', sa.Uuid(), nullable=False),
    sa.Column('from_position', sa.Integer(), nullable=False),
    sa.Column('to_position', sa.Integer(), nullable=False),
    sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('after_updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('before', JSON, nullable=False),
    sa.Column('undone_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['proposal_id'], ['proposals.id'], name=op.f('fk_thought_additions_proposal_id_proposals'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['thought_id'], ['thoughts.id'], name=op.f('fk_thought_additions_thought_id_thoughts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_thought_additions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_thought_additions'))
    )
    op.create_index(op.f('ix_thought_additions_thought_id'), 'thought_additions', ['thought_id'], unique=False)

    with op.batch_alter_table('search_indexes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('similarity_p95', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('similarity_p99', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('baseline_thoughts', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('search_indexes', schema=None) as batch_op:
        batch_op.drop_column('baseline_thoughts')
        batch_op.drop_column('similarity_p99')
        batch_op.drop_column('similarity_p95')

    op.drop_index(op.f('ix_thought_additions_thought_id'), table_name='thought_additions')
    op.drop_table('thought_additions')
