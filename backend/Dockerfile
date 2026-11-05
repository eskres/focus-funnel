FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /bin/uv

WORKDIR /srv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/srv/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# Set again here so the image works from a checkout that lost file modes.
RUN chmod +x /srv/docker-entrypoint.sh

EXPOSE 8000
# The entrypoint runs `alembic upgrade head` before exec'ing this command.
ENTRYPOINT ["/srv/docker-entrypoint.sh"]
# Keep this one process: no --workers, and one replica. Running chat turns
# live in this process's memory (app/chat/running.py), and at startup the
# backend frees every claimed conversation, taking it as left by a stopped
# process (release_stale_turns). A second process would break both.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
