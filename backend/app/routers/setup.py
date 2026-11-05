"""The first-run setup wizard's API. Every route needs a login and the setup token."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/setup", tags=["setup"])
