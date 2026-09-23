from openai import AsyncOpenAI

from app.provider_config import ModelListCapabilities, ProviderCapabilities
from app.provider_models import fetch_model_list
from tests.conftest import FakeProvider, status

FULL_CAPS = ProviderCapabilities(
    model_list=ModelListCapabilities(prices=True, context_length=True, features=True),
    stream_usage="final_chunk",
)
BARE_CAPS = ProviderCapabilities(
    model_list=ModelListCapabilities(prices=False, context_length=False, features=False),
    stream_usage="final_chunk",
)


async def fetch(models: list[dict], capabilities: ProviderCapabilities):
    fake = FakeProvider(status(200, {"object": "list", "data": models}))
    client = AsyncOpenAI(
        api_key="x", base_url="https://test.example/v1/", http_client=fake.http_client()
    )
    try:
        return await fetch_model_list(client, capabilities)
    finally:
        await client.close()


async def test_nebius_style_supported_features_field():
    models = await fetch(
        [{"id": "m1", "context_length": 8192, "pricing": {"prompt": "0.1", "completion": "0.2"}, "supported_features": ["tools"]}],
        FULL_CAPS,
    )
    assert models[0].features.tool_calling == "supported"


async def test_openrouter_style_supported_parameters_field():
    """OpenRouter reports feature/parameter names under a different field name."""
    models = await fetch(
        [
            {
                "id": "m1",
                "context_length": 131072,
                "pricing": {"prompt": "0.0000002", "completion": "0.0000006"},
                "supported_parameters": ["temperature", "tools", "tool_choice"],
            }
        ],
        FULL_CAPS,
    )
    assert models[0].context_length == 131072
    assert models[0].prices.prompt == "0.0000002"
    assert models[0].features.tool_calling == "supported"


async def test_supported_parameters_without_tools_gives_unconfirmed():
    models = await fetch(
        [{"id": "m1", "supported_parameters": ["temperature", "top_p"]}],
        FULL_CAPS,
    )
    assert models[0].features.tool_calling == "unconfirmed"


async def test_bare_capabilities_report_nothing_even_if_present():
    models = await fetch(
        [{"id": "m1", "context_length": 8192, "pricing": {"prompt": "0.1", "completion": "0.2"}, "supported_features": ["tools"]}],
        BARE_CAPS,
    )
    assert models[0].context_length is None
    assert models[0].prices is None
    assert models[0].features.tool_calling == "unknown"
