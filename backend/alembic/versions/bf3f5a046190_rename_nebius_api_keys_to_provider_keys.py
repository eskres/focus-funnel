"""rename nebius_api_keys to provider_keys

Revision ID: bf3f5a046190
Revises: d06a9fe12cba
Create Date: 2026-09-22 09:26:42.039719

Renames nebius_api_keys to provider_keys, adds provider_id (existing rows
default to 'nebius') and base_url (null except for the custom provider), and
lets the key columns be null for a keyless local provider. The unique
constraint moves from (user_id) to (user_id, provider_id).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bf3f5a046190'
down_revision: Union[str, Sequence[str], None] = 'd06a9fe12cba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.rename_table('nebius_api_keys', 'provider_keys')

    with op.batch_alter_table('provider_keys', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'provider_id', sa.String(length=64), nullable=False, server_default='nebius'
            )
        )
        batch_op.add_column(sa.Column('base_url', sa.String(length=2048), nullable=True))
        batch_op.alter_column('ciphertext', existing_type=sa.LargeBinary(), nullable=True)
        batch_op.alter_column('nonce', existing_type=sa.LargeBinary(), nullable=True)
        batch_op.alter_column('key_version', existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column('last4', existing_type=sa.String(length=4), nullable=True)
        batch_op.drop_constraint(op.f('uq_nebius_api_keys_user_id'), type_='unique')
        batch_op.create_unique_constraint(
            op.f('uq_provider_keys_user_id'), ['user_id', 'provider_id']
        )


def downgrade() -> None:
    """Downgrade schema."""
    # Keys saved for other providers, and any keyless row, don't fit the old
    # single-key-per-user Nebius shape, so they're dropped on rollback.
    op.execute("DELETE FROM provider_keys WHERE provider_id != 'nebius' OR ciphertext IS NULL")

    with op.batch_alter_table('provider_keys', schema=None) as batch_op:
        batch_op.drop_constraint(op.f('uq_provider_keys_user_id'), type_='unique')
        batch_op.create_unique_constraint(op.f('uq_nebius_api_keys_user_id'), ['user_id'])
        batch_op.alter_column('last4', existing_type=sa.String(length=4), nullable=False)
        batch_op.alter_column('key_version', existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column('nonce', existing_type=sa.LargeBinary(), nullable=False)
        batch_op.alter_column('ciphertext', existing_type=sa.LargeBinary(), nullable=False)
        batch_op.drop_column('base_url')
        batch_op.drop_column('provider_id')

    op.rename_table('provider_keys', 'nebius_api_keys')
