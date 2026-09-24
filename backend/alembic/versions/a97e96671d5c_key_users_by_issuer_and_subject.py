"""key users by issuer and subject

Revision ID: a97e96671d5c
Revises: 7c2e4f9a1d35
Create Date: 2026-09-24 13:35:50.154396

Renames users.auth0_sub to subject, adds issuer (existing rows become
'auth0-legacy'), expires_at, and demo_notice_accepted_at, and keys users by
(issuer, subject). The downgrade deletes every user that is not
'auth0-legacy', with their data, then restores auth0_sub.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a97e96671d5c'
down_revision: Union[str, Sequence[str], None] = '7c2e4f9a1d35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_ISSUER = "auth0-legacy"

# Tables that hold a users.id, at this revision. Migrations run with SQLite's
# foreign keys off, so the downgrade deletes these rows itself instead of
# relying on ON DELETE CASCADE.
_USER_OWNED_TABLES = ("provider_keys", "chat_models", "user_settings", "usage_events")


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_constraint('uq_users_auth0_sub', type_='unique')
        batch_op.alter_column(
            'auth0_sub',
            new_column_name='subject',
            existing_type=sa.String(length=255),
            existing_nullable=False,
        )
        batch_op.add_column(
            sa.Column(
                'issuer',
                sa.String(length=255),
                nullable=False,
                server_default=LEGACY_ISSUER,
            )
        )
        batch_op.add_column(sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column('demo_notice_accepted_at', sa.DateTime(timezone=True), nullable=True)
        )

    # The default only fills existing rows; new rows always name their issuer.
    with op.batch_alter_table('users') as batch_op:
        batch_op.alter_column(
            'issuer',
            existing_type=sa.String(length=255),
            existing_nullable=False,
            server_default=None,
        )
        batch_op.create_unique_constraint(op.f('uq_users_issuer'), ['issuer', 'subject'])


def downgrade() -> None:
    """Downgrade schema."""
    others = sa.text("SELECT id FROM users WHERE issuer <> :legacy")
    params = {"legacy": LEGACY_ISSUER}
    op.execute(
        sa.text(
            "DELETE FROM messages WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE user_id IN (SELECT id FROM users WHERE issuer <> :legacy))"
        ).bindparams(**params)
    )
    for table in (*_USER_OWNED_TABLES, "conversations"):
        op.execute(
            sa.text(f"DELETE FROM {table} WHERE user_id IN ({others.text})").bindparams(**params)
        )
    op.execute(sa.text("DELETE FROM users WHERE issuer <> :legacy").bindparams(**params))

    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_constraint(op.f('uq_users_issuer'), type_='unique')
        batch_op.drop_column('demo_notice_accepted_at')
        batch_op.drop_column('expires_at')
        batch_op.drop_column('issuer')
        batch_op.alter_column(
            'subject',
            new_column_name='auth0_sub',
            existing_type=sa.String(length=255),
            existing_nullable=False,
        )
    # A constraint on a renamed column needs its own batch on SQLite.
    with op.batch_alter_table('users') as batch_op:
        batch_op.create_unique_constraint(op.f('uq_users_auth0_sub'), ['auth0_sub'])
