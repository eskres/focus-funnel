"""Import every model here so Base.metadata is complete for Alembic."""

from app.db import Base

__all__ = ["Base"]
