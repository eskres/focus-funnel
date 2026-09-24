"""keep proposals and user categories

Revision ID: 3f9d1b7e5a28
Revises: 5e8b2c0d4a17
Create Date: 2026-09-24 20:00:00.000000

Creates proposals and user_categories, adds messages.details and
conversations.held_proposal_id, and drops conversations.held_proposal. Held
proposals are not moved: their cards were never kept across a reload, and the
downgrade does not restore them either.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3f9d1b7e5a28'
down_revision: Union[str, Sequence[str], None] = '5e8b2c0d4a17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('proposals',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('from_position', sa.Integer(), nullable=False),
    sa.Column('to_position', sa.Integer(), nullable=False),
    sa.Column('raw_text', sa.Text(), nullable=False),
    sa.Column('parts', JSON, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_proposals_conversation_id_conversations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_proposals_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_proposals'))
    )
    op.create_index(op.f('ix_proposals_conversation_id'), 'proposals', ['conversation_id'], unique=False)

    op.create_table('user_categories',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_categories_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_categories')),
    sa.UniqueConstraint('user_id', 'name', name=op.f('uq_user_categories_user_id'))
    )

    with op.batch_alter_table('messages') as batch_op:
        batch_op.add_column(sa.Column('details', JSON, nullable=True))

    with op.batch_alter_table('conversations') as batch_op:
        batch_op.add_column(sa.Column('held_proposal_id', sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            op.f('fk_conversations_held_proposal_id_proposals'),
            'proposals', ['held_proposal_id'], ['id'], ondelete='SET NULL',
        )
        batch_op.drop_column('held_proposal')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('conversations') as batch_op:
        batch_op.add_column(sa.Column('held_proposal', JSON, nullable=True))
        batch_op.drop_constraint(
            op.f('fk_conversations_held_proposal_id_proposals'), type_='foreignkey'
        )
        batch_op.drop_column('held_proposal_id')

    with op.batch_alter_table('messages') as batch_op:
        batch_op.drop_column('details')

    op.drop_table('user_categories')
    op.drop_index(op.f('ix_proposals_conversation_id'), table_name='proposals')
    op.drop_table('proposals')
