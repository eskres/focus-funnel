"""Connectors per conversation and the meter (openspec mcp-connectors tasks 8.1 and 8.2).

The MCP client is replaced with `FakeConnect` from the connector turn tests:
nothing here connects to a server except Test, which stores the tool list.
"""

import pytest

from app.chat.prompt import CONNECTORS_PROMPT, estimate_tool_tokens
from app.errors import ErrorCode
from app.main import app
from app.mcp_client import McpTool, get_mcp_connect
from tests.chat_helpers import (
    MODEL_LIST,
    NANO,
    chat,
    entry,
    error_code,
    ready_user,
    run_db,
    seed_conversation,
    text_chunks,
)
from tests.connector_helpers import connectors_app, links, write_config
from tests.sse_helpers import parse_events
from tests.test_connector_turns import (
    SCHEMA,
    FakeConnect,
    chat_config,
    listed_connector,
    switch_on,
    tool_names,
)

SMALL = "vendor/small-model"


@pytest.fixture
def config_path(tmp_path):
    return write_config(tmp_path / "connectors.yaml", [])


@pytest.fixture
def fake_mcp():
    fake = FakeConnect()
    app.dependency_overrides[get_mcp_connect] = lambda: fake
    return fake


@pytest.fixture
def client(test_database_url, jwks_cache, settings_env, config_path, fake_llm, fake_mcp):
    with connectors_app(settings_env, jwks_cache, config_path) as client:
        app.dependency_overrides[get_mcp_connect] = lambda: fake_mcp
        yield client


def put(client, headers, conversation_id, *connector_ids):
    return client.put(
        f"/api/conversations/{conversation_id}/connectors",
        headers=headers,
        json={"connector_ids": list(connector_ids)},
    )


def detail(client, headers, conversation_id) -> dict:
    response = client.get(f"/api/conversations/{conversation_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def calendar(client, headers, *tools, name="calendar") -> str:
    """A user connector whose Test stored the fake server's tools, with these switched on."""
    connector_id = listed_connector(client, headers, name=name)
    switch_on(client, headers, connector_id, *tools)
    return connector_id


def last_prompt_tokens(url: str, conversation_id: str) -> int | None:
    import uuid

    from app.models import Conversation

    async def work(session):
        return (await session.get(Conversation, uuid.UUID(conversation_id))).last_prompt_tokens

    return run_db(url, work)


# --- 8.1 PUT /api/conversations/{id}/connectors ---------------------------------


def test_a_new_conversation_has_no_connectors_and_only_the_built_in_tools(
    client, alice, fake_llm
):
    ready_user(client, alice)
    calendar(client, alice, "list_events")
    fake_llm.queue(text_chunks("Hi"))

    response = chat(client, alice, "hello")

    conversation_id = next(d for n, d in parse_events(response.text) if n == "conversation")["id"]
    assert detail(client, alice, conversation_id)["connectors"] == []
    assert tool_names(fake_llm.chat_requests[0]) == ["search_thoughts", "propose_thought"]


def test_turning_a_connector_on_and_off_is_stored_and_kept_through_archive_and_restore(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    connector_id = calendar(client, alice, "list_events")
    conversation_id = seed_conversation(test_database_url, client, alice)
    other_id = seed_conversation(test_database_url, client, alice, title="Another")

    response = put(client, alice, conversation_id, connector_id)

    assert response.status_code == 200, response.text
    on = [{"id": connector_id, "name": "calendar"}]
    assert response.json()["connectors"] == on
    assert detail(client, alice, conversation_id)["connectors"] == on
    assert detail(client, alice, other_id)["connectors"] == []

    for archived in (True, False):
        response = client.patch(
            f"/api/conversations/{conversation_id}", headers=alice, json={"archived": archived}
        )
        assert response.status_code == 200, response.text
        assert response.json()["archived"] is archived
        assert detail(client, alice, conversation_id)["connectors"] == on

    # The next turn offers its switched-on tools.
    fake_llm.queue(text_chunks("Hi"), text_chunks("Hi again"))
    chat(client, alice, "what is on?", conversation_id)
    assert tool_names(fake_llm.chat_requests[0]) == [
        "search_thoughts",
        "propose_thought",
        "calendar__list_events",
    ]

    response = put(client, alice, conversation_id)

    assert response.status_code == 200, response.text
    assert response.json()["connectors"] == []
    assert links(test_database_url) == []
    chat(client, alice, "and now?", conversation_id)
    assert tool_names(fake_llm.chat_requests[1]) == ["search_thoughts", "propose_thought"]


def test_putting_the_same_set_twice_stores_one_link(client, alice, test_database_url):
    ready_user(client, alice)
    connector_id = calendar(client, alice, "list_events")
    conversation_id = seed_conversation(test_database_url, client, alice)

    assert put(client, alice, conversation_id, connector_id, connector_id).status_code == 200
    assert put(client, alice, conversation_id, connector_id).status_code == 200

    assert links(test_database_url) == [(conversation_id, connector_id)]


def test_a_connector_with_no_switched_on_tools_cannot_be_turned_on(
    client, alice, test_database_url
):
    ready_user(client, alice)
    connector_id = calendar(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice)

    response = put(client, alice, conversation_id, connector_id)

    assert response.status_code == 422
    assert error_code(response) == ErrorCode.VALIDATION_ERROR
    assert "calendar has no tools switched on" in response.json()["error"]["message"]
    assert links(test_database_url) == []


def test_turning_on_a_connector_past_the_tool_limit_gives_too_many_tools(
    test_database_url, jwks_cache, settings_env, config_path, fake_llm, fake_mcp, alice, tmp_path
):
    settings_env.setenv("CHAT_CONFIG_PATH", str(chat_config(tmp_path, max_tools=2)))
    with connectors_app(settings_env, jwks_cache, config_path) as client:
        app.dependency_overrides[get_mcp_connect] = lambda: fake_mcp
        ready_user(client, alice)
        first = calendar(client, alice, "list_events")
        second = calendar(client, alice, "list_events", "find_free_time", name="work")
        conversation_id = seed_conversation(test_database_url, client, alice)
        assert put(client, alice, conversation_id, first).status_code == 200

        response = put(client, alice, conversation_id, first, second)

        assert response.status_code == 422
        assert error_code(response) == ErrorCode.TOO_MANY_TOOLS
        assert "at most 2 connector tools" in response.json()["error"]["message"]
        assert links(test_database_url) == [(conversation_id, first)]

        # Settings put the conversation past the limit: turning off still works.
        switch_on(client, alice, first, "find_free_time", "create_event")
        response = put(client, alice, conversation_id)
        assert response.status_code == 200, response.text
        assert links(test_database_url) == []


def test_another_users_conversation_or_connector_answers_404(
    client, alice, bob, test_database_url
):
    ready_user(client, alice)
    ready_user(client, bob)
    alices_connector = calendar(client, alice, "list_events")
    alices_conversation = seed_conversation(test_database_url, client, alice)
    bobs_connector = calendar(client, bob, "list_events")
    bobs_conversation = seed_conversation(test_database_url, client, bob)

    cases = [
        put(client, alice, bobs_conversation, alices_connector),
        put(client, alice, alices_conversation, bobs_connector),
        put(client, alice, alices_conversation, "00000000-0000-0000-0000-000000000000"),
        put(client, alice, "00000000-0000-0000-0000-000000000000", alices_connector),
    ]

    for response in cases:
        assert response.status_code == 404, response.text
        assert error_code(response) == ErrorCode.NOT_FOUND
    assert links(test_database_url) == []


def test_the_route_is_not_found_while_connectors_are_off(
    test_database_url, jwks_cache, settings_env, config_path, fake_llm, alice
):
    with connectors_app(settings_env, jwks_cache, config_path, enabled=False) as client:
        ready_user(client, alice)
        conversation_id = seed_conversation(test_database_url, client, alice)

        response = put(client, alice, conversation_id)

        assert response.status_code == 404
        assert error_code(response) == ErrorCode.NOT_FOUND
        assert detail(client, alice, conversation_id)["connectors"] == []


def test_a_change_clears_the_reported_prompt_count(client, alice, test_database_url):
    ready_user(client, alice)
    connector_id = calendar(client, alice, "list_events")
    conversation_id = seed_conversation(
        test_database_url,
        client,
        alice,
        provider_id="nebius",
        model=NANO,
        last_prompt_tokens=2_000,
    )
    assert detail(client, alice, conversation_id)["context"]["estimated"] is False

    # The same set again changes nothing.
    assert put(client, alice, conversation_id).status_code == 200
    assert last_prompt_tokens(test_database_url, conversation_id) == 2_000

    body = put(client, alice, conversation_id, connector_id).json()

    assert body["last_prompt_tokens"] is None
    assert body["context"]["estimated"] is True
    assert last_prompt_tokens(test_database_url, conversation_id) is None


# --- 8.2 tool definitions in the meter and in context_full ------------------------


def test_turning_a_connector_on_raises_the_estimate_by_its_definitions(
    client, alice, test_database_url
):
    ready_user(client, alice)
    connector_id = calendar(client, alice, "list_events", "find_free_time")
    conversation_id = seed_conversation(
        test_database_url, client, alice, provider_id="nebius", model=NANO
    )
    before = detail(client, alice, conversation_id)["context"]

    after = put(client, alice, conversation_id, connector_id).json()["context"]

    definitions = [
        {
            "type": "function",
            "function": {
                "name": f"calendar__{name}",
                "parameters": SCHEMA,
                "description": description,
            },
        }
        for name, description in (
            ("list_events", "Lists events."),
            ("find_free_time", "Finds free time."),
        )
    ]
    added = estimate_tool_tokens(definitions)
    assert before["estimated"] is True and after["estimated"] is True
    assert before["tool_tokens"] > 0
    assert abs(after["tool_tokens"] - before["tool_tokens"] - added) <= 1
    # The definitions, and the connectors paragraph in the system prompt.
    prompt = len(CONNECTORS_PROMPT) / 3.5
    assert abs(after["tokens"] - before["tokens"] - added - prompt) <= 3

    # Off again: back to the built-in tools.
    assert put(client, alice, conversation_id).json()["context"] == before


def test_context_full_counts_the_connector_definitions_and_advises_turning_them_off(
    client, alice, fake_llm, fake_mcp, test_database_url
):
    fake_llm.models = {
        "object": "list",
        "data": [
            *MODEL_LIST["data"],
            {"id": SMALL, "context_length": 20_000, "supported_features": ["tools"]},
        ],
    }
    ready_user(client, alice, entry(NANO, default=True), entry(SMALL))
    conversation_id = seed_conversation(
        test_database_url,
        client,
        alice,
        messages=("word " * 2_000, "Noted."),
        provider_id="nebius",
        model=SMALL,
    )
    tokens = detail(client, alice, conversation_id)["context"]["tokens"]
    # Room for the message and a reply, but not for one more large tool.
    room = 20_000 - 8_192 - tokens
    assert room > 1_000
    fake_mcp.tools = [
        McpTool("list_events", None, "x" * int((room + 300) * 3.5), SCHEMA, True)
    ]
    connector_id = calendar(client, alice, "list_events")
    assert put(client, alice, conversation_id, connector_id).status_code == 200
    fake_mcp.reset()

    response = chat(client, alice, "hi", conversation_id)

    assert response.status_code == 409
    assert error_code(response) == ErrorCode.CONTEXT_FULL
    assert response.json()["error"]["message"].endswith("or turn some connectors off.")
    assert fake_llm.chat_requests == []
    assert fake_mcp.connects == []

    # With the connector off, the same message fits.
    assert put(client, alice, conversation_id).status_code == 200
    fake_llm.queue(text_chunks("Hello"))
    response = chat(client, alice, "hi", conversation_id)
    assert [name for name, _ in parse_events(response.text)][-1] == "done"
    assert len(fake_llm.chat_requests) == 1


def test_context_full_without_connectors_does_not_mention_them(
    client, alice, fake_llm, test_database_url
):
    fake_llm.models = {
        "object": "list",
        "data": [
            *MODEL_LIST["data"],
            {"id": SMALL, "context_length": 10_000, "supported_features": ["tools"]},
        ],
    }
    ready_user(client, alice, entry(NANO, default=True), entry(SMALL))
    conversation_id = seed_conversation(
        test_database_url,
        client,
        alice,
        messages=("word " * 2_000, "Noted."),
        provider_id="nebius",
        model=SMALL,
    )

    response = chat(client, alice, "hi", conversation_id)

    assert error_code(response) == ErrorCode.CONTEXT_FULL
    assert "connectors" not in response.json()["error"]["message"]
