"""remove added event categories

Revision ID: 2bea7235fdf6
Revises: 8a4d6f2b9c13
Create Date: 2026-11-05 00:27:11.613719

event is now a fixed kind, so this deletes the user_categories rows named
event that users added themselves. The names are stored cleaned, so an exact
match finds them all. Thoughts keep their category. The downgrade does nothing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2bea7235fdf6'
down_revision: Union[str, Sequence[str], None] = '8a4d6f2b9c13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

user_categories = sa.table('user_categories', sa.column('name', sa.Text()))


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(user_categories.delete().where(user_categories.c.name == 'event'))


def downgrade() -> None:
    """Downgrade schema."""
    # The deleted rows cannot be told apart from users who never added event,
    # so nothing is restored. Users who want it back add it again.
    pass
