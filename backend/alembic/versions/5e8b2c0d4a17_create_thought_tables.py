"""create thought tables

Revision ID: 5e8b2c0d4a17
Revises: a97e96671d5c
Create Date: 2026-09-24 18:00:00.000000

Creates thoughts, search_indexes, and thought_embeddings, and on Postgres the
pgvector extension (0.7 or later, for halfvec) and the GIN indexes for tags
and full-text search. SQLite
gets the same tables with plain JSON and text columns, for tests of the rest
of the app. No thought existed before, so no data is migrated. The downgrade
drops the tables but keeps the extension, which other databases on the
server may use.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import HALFVEC
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5e8b2c0d4a17'
down_revision: Union[str, Sequence[str], None] = 'a97e96671d5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TAGS = postgresql.ARRAY(sa.Text()).with_variant(sa.JSON(), 'sqlite')
TSVECTOR = postgresql.TSVECTOR().with_variant(sa.Text(), 'sqlite')
VECTOR = HALFVEC().with_variant(sa.JSON(), 'sqlite')


def upgrade() -> None:
    """Upgrade schema."""
    is_postgres = op.get_bind().dialect.name == 'postgresql'
    if is_postgres:
        op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    op.create_table('thoughts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('raw_text', sa.Text(), nullable=True),
    sa.Column('category', sa.Text(), nullable=True),
    sa.Column('tags', TAGS, nullable=False),
    sa.Column('search_tsv', TSVECTOR, nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_thoughts_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_thoughts'))
    )
    op.create_index('ix_thoughts_user_id_created_at', 'thoughts', ['user_id', 'created_at'], unique=False)
    if is_postgres:
        op.create_index('ix_thoughts_tags', 'thoughts', ['tags'], unique=False, postgresql_using='gin')
        op.create_index('ix_thoughts_search_tsv', 'thoughts', ['search_tsv'], unique=False, postgresql_using='gin')

    op.create_table('search_indexes',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('embedding_provider', sa.String(length=64), nullable=False),
    sa.Column('embedding_model', sa.Text(), nullable=False),
    sa.Column('dimension', sa.Integer(), nullable=False),
    sa.Column('requested_dimensions', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_search_indexes_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_search_indexes')),
    sa.UniqueConstraint('user_id', 'version', name='uq_search_indexes_user_id_version')
    )
    for status in ('active', 'building'):
        where = sa.text(f"status = '{status}'")
        op.create_index(
            f'uq_search_indexes_one_{status}', 'search_indexes', ['user_id'], unique=True,
            postgresql_where=where, sqlite_where=where,
        )

    op.create_table('thought_embeddings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('index_id', sa.Uuid(), nullable=False),
    sa.Column('thought_id', sa.Uuid(), nullable=False),
    sa.Column('chunk', sa.Integer(), nullable=False),
    sa.Column('start_char', sa.Integer(), nullable=True),
    sa.Column('end_char', sa.Integer(), nullable=True),
    sa.Column('embedding', VECTOR, nullable=False),
    sa.ForeignKeyConstraint(['index_id'], ['search_indexes.id'], name=op.f('fk_thought_embeddings_index_id_search_indexes'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['thought_id'], ['thoughts.id'], name=op.f('fk_thought_embeddings_thought_id_thoughts'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_thought_embeddings')),
    sa.UniqueConstraint('index_id', 'thought_id', 'chunk', name='uq_thought_embeddings_index_thought_chunk')
    )
    if is_postgres:
        # Vectors stay in the row, so an exact search reads no TOAST table.
        op.execute('ALTER TABLE thought_embeddings ALTER COLUMN embedding SET STORAGE MAIN')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('thought_embeddings')
    op.drop_index('uq_search_indexes_one_building', table_name='search_indexes')
    op.drop_index('uq_search_indexes_one_active', table_name='search_indexes')
    op.drop_table('search_indexes')
    if op.get_bind().dialect.name == 'postgresql':
        op.drop_index('ix_thoughts_search_tsv', table_name='thoughts')
        op.drop_index('ix_thoughts_tags', table_name='thoughts')
    op.drop_index('ix_thoughts_user_id_created_at', table_name='thoughts')
    op.drop_table('thoughts')
