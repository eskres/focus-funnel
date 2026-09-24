"""Choosing the embedding model and calling it with the user's own key."""

from dataclasses import dataclass

from app.config import Settings
from app.models import User
from app.provider_config import ProvidersConfig


class EmbeddingConfigError(ValueError):
    """The embedding settings name a provider that cannot be used."""


def check_embedding_provider(settings: Settings, providers: ProvidersConfig) -> None:
    """Refuse at startup an EMBEDDING_PROVIDER that is not a preset."""
    if providers.get(settings.embedding_provider) is None:
        known = ", ".join(sorted(providers.providers))
        raise EmbeddingConfigError(
            f"EMBEDDING_PROVIDER '{settings.embedding_provider}' is not a provider preset: "
            f"use one of {known}"
        )


@dataclass(frozen=True)
class EmbeddingChoice:
    provider_id: str
    model: str
    dimensions: int | None


def resolve_embedding_model(user: User, settings: Settings) -> EmbeddingChoice:
    """The embedding model for a new search index of this user.

    Called only when an index is created. Every other operation reads the
    model from the user's index. A per-user choice is added here and nowhere
    else.
    """
    return EmbeddingChoice(
        provider_id=settings.embedding_provider,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )
