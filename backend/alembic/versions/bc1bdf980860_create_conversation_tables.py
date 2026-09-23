"""create conversation tables

Revision ID: bc1bdf980860
Revises: bf3f5a046190
Create Date: 2026-09-23 21:10:25.899444

Creates conversations, messages, usage_events, chat_models, and
user_settings. There are no users yet, so no data is migrated. A local
database that ran the gate prototype's overrides migration must be reset,
because Alembic cannot find that revision.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'bc1bdf980860'
down_revision: Union[str, Sequence[str], None] = 'bf3f5a046190'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('chat_models',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('provider_id', sa.String(length=64), nullable=False),
    sa.Column('model', sa.Text(), nullable=False),
    sa.Column('reasoning_effort', sa.String(length=16), nullable=True),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_chat_models_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_chat_models')),
    sa.UniqueConstraint('user_id', 'provider_id', 'model', name=op.f('uq_chat_models_user_id'))
    )
    op.create_table('conversations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('provider_id', sa.String(length=64), nullable=True),
    sa.Column('model', sa.Text(), nullable=True),
    sa.Column('reasoning_effort', sa.String(length=16), nullable=True),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_activity_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('last_prompt_tokens', sa.Integer(), nullable=True),
    sa.Column('held_proposal', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('turn_started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_conversations_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_conversations'))
    )
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_conversations_user_id'), ['user_id'], unique=False)

    op.create_table('user_settings',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('temperature', sa.Float(), nullable=True),
    sa.Column('warning_unit', sa.String(length=8), nullable=True),
    sa.Column('warning_amount', sa.Numeric(precision=18, scale=6), nullable=True),
    sa.Column('warning_notified_month', sa.String(length=7), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_settings_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_user_settings'))
    )
    op.create_table('messages',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('content', sa.Text(), nullable=True),
    sa.Column('tool_calls', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('tool_call_id', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('compacted', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_messages_conversation_id_conversations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_messages')),
    sa.UniqueConstraint('conversation_id', 'position', name=op.f('uq_messages_conversation_id'))
    )
    op.create_table('usage_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('provider_id', sa.String(length=64), nullable=False),
    sa.Column('model', sa.Text(), nullable=False),
    sa.Column('prompt_tokens', sa.Integer(), nullable=False),
    sa.Column('completion_tokens', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Numeric(precision=18, scale=10), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_usage_events_conversation_id_conversations'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_usage_events_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_usage_events'))
    )
    with op.batch_alter_table('usage_events', schema=None) as batch_op:
        batch_op.create_index('ix_usage_events_user_id_created_at', ['user_id', 'created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('usage_events', schema=None) as batch_op:
        batch_op.drop_index('ix_usage_events_user_id_created_at')

    op.drop_table('usage_events')
    op.drop_table('messages')
    op.drop_table('user_settings')
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_conversations_user_id'))

    op.drop_table('conversations')
    op.drop_table('chat_models')
