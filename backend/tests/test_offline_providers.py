"""The offline providers file (self-hosting-setup task 7.3, design decision 15)."""

import re
from pathlib import Path

import yaml
from sqlalchemy import func, select

from app.config import Settings
from app.main import app
from app.models import ProviderKey
from app.provider_config import load_providers_config
from app.thoughts.embeddings import check_embedding_provider
from tests.test_setup_status import get_status, items_of, setup_env, start  # noqa: F401
from tests.test_setup_token import printed_token, run

REPO = Path(__file__).resolve().parents[2]
OFFLINE_PROVIDERS = REPO / "deploy" / "offline" / "providers.yaml"
OFFLINE_OVERLAY = REPO / "docker-compose.offline.yml"


def overlay_backend_environment() -> dict[str, str]:
    """The backend environment docker-compose.offline.yml sets, with no .env.

    `${NAME:-default}` reads as its default, as compose does when NAME is unset.
    """
    environment = yaml.safe_load(OFFLINE_OVERLAY.read_text())["services"]["backend"][
        "environment"
    ]
    return {
        name: re.sub(r"\$\{[A-Z_]+:-([^}]*)\}", r"\1", str(value))
        for name, value in environment.items()
    }


def test_the_loader_accepts_the_offline_file_with_one_keyless_preset():
    config = load_providers_config(OFFLINE_PROVIDERS)
    assert list(config.providers) == ["ollama"]
    ollama = config.providers["ollama"]
    assert ollama.key_required is False
    assert ollama.base_url == "http://ollama:11434/v1/"
    assert ollama.key_url == "https://ollama.com/library"
    assert "docs/offline.md" in ollama.notice
    assert ollama.capabilities.stream_usage == "final_chunk"
    model_list = ollama.capabilities.model_list
    assert (model_list.prices, model_list.context_length, model_list.features) == (
        False,
        False,
        False,
    )


def test_ollama_is_accepted_as_the_embedding_provider(settings_env):
    settings_env.setenv("EMBEDDING_PROVIDER", "ollama")
    settings_env.setenv("EMBEDDING_MODEL", "nomic-embed-text:v1.5")
    settings_env.setenv("EMBEDDING_DIMENSIONS", "native")
    settings = Settings()
    check_embedding_provider(settings, load_providers_config(OFFLINE_PROVIDERS))
    assert settings.embedding_dimensions is None


def test_the_offline_overlay_offers_only_ollama_and_search_needs_no_key(
    setup_env,  # noqa: F811 - the fixture imported above
    test_database_url,
    jwks_cache,
    capsys,
    alice,
):
    environment = overlay_backend_environment()
    assert environment["PROVIDERS_CONFIG_PATH"] == "/srv/offline/providers.yaml"
    assert environment["EMBEDDING_PROVIDER"] == "ollama"
    for name, value in environment.items():
        setup_env.setenv(name, value)
    # The overlay mounts the file at that path inside the container.
    setup_env.setenv("PROVIDERS_CONFIG_PATH", str(OFFLINE_PROVIDERS))
    try:
        with start(jwks_cache) as client:
            token = printed_token(capsys.readouterr().err)
            providers = client.get("/api/providers", headers=alice)
            items = items_of(get_status(client, alice, token))
    finally:
        app.dependency_overrides.clear()

    assert providers.status_code == 200, providers.text
    listed = providers.json()["providers"]
    assert [provider["id"] for provider in listed] == ["ollama"]
    assert listed[0]["key_required"] is False
    assert listed[0]["key_saved"] is False

    assert items["search_key"]["state"] == "ok"
    assert "needs no key" in items["search_key"]["message"]
    assert run(test_database_url, select(func.count()).select_from(ProviderKey)) == [
        (0,)
    ]
