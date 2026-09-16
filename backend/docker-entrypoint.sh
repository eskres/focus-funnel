#!/bin/sh
# Applies database migrations, then hands control to the server command.
#
# This runs as the image's ENTRYPOINT rather than from the FastAPI lifespan, so
# it happens once per container start and finishes before anything binds a
# port. `alembic upgrade head` is a no-op when the database is already at head.
# `set -e` stops the container on a failed migration, so the server never comes
# up against a half-built schema.
set -e

echo "Applying database migrations..."
alembic upgrade head

# exec, so the server replaces this shell as PID 1 and gets SIGTERM directly.
exec "$@"
