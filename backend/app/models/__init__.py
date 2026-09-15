"""Import every model here so Base.metadata is complete for Alembic."""

from app.db import Base
from app.models.user import User

__all__ = ["Base", "User"]
