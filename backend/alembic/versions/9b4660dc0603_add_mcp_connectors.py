"""add mcp connectors

Revision ID: 9b4660dc0603
Revises: 0162bb890895
Create Date: 2026-11-04 23:44:11.988249

Adds the connectors, conversation_connectors, and tool_actions tables and
users.connector_warning_accepted_at. The downgrade drops them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9b4660dc0603'
down_revision: Union[str, Sequence[str], None] = '0162bb890895'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('connectors',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('operator_key', sa.String(length=64), nullable=True),
    sa.Column('url', sa.String(length=2048), nullable=True),
    sa.Column('auth_kind', sa.String(length=16), nullable=False),
    sa.Column('auth_header', sa.String(length=255), nullable=True),
    sa.Column('auth_ciphertext', sa.LargeBinary(), nullable=True),
    sa.Column('auth_nonce', sa.LargeBinary(), nullable=True),
    sa.Column('auth_key_version', sa.Integer(), nullable=True),
    sa.Column('auth_last4', sa.String(length=4), nullable=True),
    sa.Column('tools', JSON, nullable=False),
    sa.Column('tools_listed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('tool_settings', JSON, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_connectors_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_connectors')),
    sa.UniqueConstraint('user_id', 'name', name=op.f('uq_connectors_user_id'))
    )
    op.create_table('conversation_connectors',
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('connector_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['connector_id'], ['connectors.id'], name=op.f('fk_conversation_connectors_connector_id_connectors'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_conversation_connectors_conversation_id_conversations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('conversation_id', 'connector_id', name=op.f('pk_conversation_connectors'))
    )
    with op.batch_alter_table('conversation_connectors', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_conversation_connectors_connector_id'), ['connector_id'], unique=False)

    op.create_table('tool_actions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('connector_id', sa.Uuid(), nullable=True),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('connector_name', sa.String(length=64), nullable=False),
    sa.Column('tool', sa.String(length=255), nullable=False),
    sa.Column('arguments', JSON, nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('result', sa.Text(), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['connector_id'], ['connectors.id'], name=op.f('fk_tool_actions_connector_id_connectors'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_tool_actions_conversation_id_conversations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_tool_actions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tool_actions'))
    )
    with op.batch_alter_table('tool_actions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tool_actions_connector_id'), ['connector_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tool_actions_conversation_id'), ['conversation_id'], unique=False)

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('connector_warning_accepted_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('connector_warning_accepted_at')

    with op.batch_alter_table('tool_actions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tool_actions_conversation_id'))
        batch_op.drop_index(batch_op.f('ix_tool_actions_connector_id'))

    op.drop_table('tool_actions')
    with op.batch_alter_table('conversation_connectors', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_conversation_connectors_connector_id'))

    op.drop_table('conversation_connectors')
    op.drop_table('connectors')
