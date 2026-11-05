"""Test lists a connector's tools, and the tool switches (openspec mcp-connectors
tasks 5.3 and 5.4), against the local MCP test server."""

from datetime import datetime

import mcp_types as types
import pytest

from tests.chat_helpers import error_code
from tests.connector_helpers import add, by_name, connectors_app, listing, write_config
from tests.mcp_helpers import free_port

TOKEN = "gcal-bearer-0123456789abcdef"
TEAM_TOKEN = "team-token-abcdef0123456789"
ALL_TOOLS = ["list_events", "create_event", "mixed", "structured", "fails", "slow"]


@pytest.fixture(autouse=True)
def clean_server(mcp_server):
    mcp_server.reset()
    yield
    mcp_server.reset()


@pytest.fixture
def config_path(tmp_path, mcp_server, settings_env):
    settings_env.setenv("TEAM_TOKEN", TEAM_TOKEN)
    return write_config(
        tmp_path / "connectors.yaml",
        [
            {
                "name": "team",
                "url": mcp_server.url,
                "auth": {"kind": "bearer", "env": "TEAM_TOKEN"},
                "tools": ["list_events", "create_event", "mixed"],
                "read_only": ["mixed"],
            }
        ],
    )


@pytest.fixture
def client(test_database_url, jwks_cache, settings_env, config_path):
    with connectors_app(settings_env, jwks_cache, config_path) as client:
        yield client


@pytest.fixture
def calendar(client, alice, mcp_server) -> str:
    response = add(
        client, alice, url=mcp_server.url, auth_kind="bearer", auth_value=TOKEN
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def run_test(client, headers, connector_id):
    return client.post(f"/api/connectors/{connector_id}/test", headers=headers)


def listed_by_test(client, headers, connector_id) -> dict:
    response = run_test(client, headers, connector_id)
    assert response.status_code == 200, response.text
    return response.json()


def moment(value: str) -> datetime:
    """A stored time, compared without its zone (SQLite drops it)."""
    return datetime.fromisoformat(value).replace(tzinfo=None)


def tools(body: dict) -> dict[str, dict]:
    return {tool["name"]: tool for tool in body["tools"]}


def switch(client, headers, connector_id, tool, **fields):
    return client.patch(
        f"/api/connectors/{connector_id}/tools/{tool}", headers=headers, json=fields
    )


def badges(body: dict) -> dict[str, tuple[bool, bool, bool]]:
    """name -> (enabled, acts, always_allow)"""
    return {
        t["name"]: (t["enabled"], t["acts"], t["always_allow"]) for t in body["tools"]
    }


# --- 5.3 Test --------------------------------------------------------------------


def test_test_stores_tools_switched_off_with_badges_from_the_hint(
    client, alice, calendar, mcp_server
):
    body = listed_by_test(client, alice, calendar)

    assert [tool["name"] for tool in body["tools"]] == ALL_TOOLS
    assert body["tools_listed_at"] is not None
    listed = tools(body)
    assert listed["list_events"] == {
        "name": "list_events",
        "title": "List events",
        "description": "Lists calendar events.",
        "read_only_hint": True,
        "available": True,
        "enabled": False,
        "acts": False,
        "always_allow": False,
        "reads_allowed": True,
    }
    # No hint: acts, and it may not become reads.
    assert (
        listed["create_event"]["acts"],
        listed["create_event"]["reads_allowed"],
    ) == (True, False)
    assert all(not tool["enabled"] for tool in body["tools"])
    assert all(tool["available"] for tool in body["tools"])
    # The token went to the server, and the list is kept for later.
    assert {"authorization": f"Bearer {TOKEN}"}.items() <= mcp_server.seen_headers[
        -1
    ].items()
    assert by_name(listing(client, alice), "calendar")["tools"] == body["tools"]


def test_an_operator_connector_keeps_its_tools_and_its_read_only_list(
    client, alice, mcp_server
):
    team = by_name(listing(client, alice), "team")
    body = listed_by_test(client, alice, team["id"])

    # Only the tools the operator lists; mixed is reads by the operator's word.
    assert badges(body) == {
        "list_events": (False, False, False),
        "create_event": (False, True, False),
        "mixed": (False, False, False),
    }
    assert tools(body)["mixed"]["reads_allowed"] is True
    assert tools(body)["mixed"]["read_only_hint"] is None
    # Its auth comes from the environment, at call time.
    assert mcp_server.seen_headers[-1]["authorization"] == f"Bearer {TEAM_TOKEN}"
    assert body["auth_set"] is True
    assert body["auth_last4"] is None


def test_names_too_long_or_with_other_characters_are_unavailable(
    client, alice, calendar, mcp_server
):
    mcp_server.extra_tools.extend(
        [
            types.Tool(
                name="get.time", description="Dotted.", input_schema={"type": "object"}
            ),
            types.Tool(
                name="t" * 55, description="Long.", input_schema={"type": "object"}
            ),
            # calendar__ + 54 characters is exactly 64.
            types.Tool(
                name="u" * 54, description="Fits.", input_schema={"type": "object"}
            ),
        ]
    )
    listed = tools(listed_by_test(client, alice, calendar))

    assert listed["get.time"]["available"] is False
    assert listed["t" * 55]["available"] is False
    assert listed["u" * 54]["available"] is True
    assert listed["list_events"]["available"] is True


def test_a_rename_works_availability_out_again(client, alice, calendar, mcp_server):
    mcp_server.extra_tools.append(
        types.Tool(name="u" * 54, description="Fits.", input_schema={"type": "object"})
    )
    listed_by_test(client, alice, calendar)
    assert switch(client, alice, calendar, "u" * 54, enabled=True).status_code == 200

    body = client.patch(
        f"/api/connectors/{calendar}", headers=alice, json={"name": "work_calendar"}
    ).json()

    assert tools(body)["u" * 54]["available"] is False
    assert tools(body)["u" * 54]["enabled"] is False


def test_a_new_test_keeps_switches_of_tools_still_offered_and_drops_the_rest(
    client, alice, calendar, mcp_server
):
    listed_by_test(client, alice, calendar)
    assert (
        switch(client, alice, calendar, "list_events", enabled=True).status_code == 200
    )
    assert (
        switch(
            client, alice, calendar, "create_event", enabled=True, always_allow=True
        ).status_code
        == 200
    )
    assert switch(client, alice, calendar, "mixed", enabled=True).status_code == 200

    mcp_server.hidden.add("create_event")
    mcp_server.extra_tools.append(
        types.Tool(
            name="delete_event",
            description="Deletes an event.",
            input_schema={"type": "object"},
            annotations=types.ToolAnnotations(read_only_hint=False),
        )
    )
    body = listed_by_test(client, alice, calendar)

    assert [tool["name"] for tool in body["tools"]] == [
        "list_events",
        "mixed",
        "structured",
        "fails",
        "slow",
        "delete_event",
    ]
    states = badges(body)
    assert states["list_events"] == (True, False, False)
    assert states["mixed"] == (True, True, False)
    assert states["delete_event"] == (False, True, False)

    # A tool that comes back starts over, switched off.
    mcp_server.hidden.clear()
    assert badges(listed_by_test(client, alice, calendar))["create_event"] == (
        False,
        True,
        False,
    )


@pytest.mark.parametrize(
    ("path", "code", "reason"),
    [
        ("/401", "connector_auth_failed", "The server refused the auth."),
        (
            "/html",
            "connector_protocol_error",
            "The server did not answer as an MCP server.",
        ),
        (None, "connector_unreachable", "The server could not be reached."),
    ],
)
def test_a_failed_test_keeps_the_stored_list_and_gives_the_code(
    client, alice, calendar, mcp_server, path, code, reason
):
    before = listed_by_test(client, alice, calendar)
    assert (
        switch(client, alice, calendar, "list_events", enabled=True).status_code == 200
    )
    url = mcp_server.base + path if path else f"http://127.0.0.1:{free_port()}/mcp"
    assert (
        client.patch(
            f"/api/connectors/{calendar}", headers=alice, json={"url": url}
        ).status_code
        == 200
    )

    response = run_test(client, alice, calendar)

    assert response.status_code == 502
    assert error_code(response) == code
    assert response.json()["error"]["message"] == reason
    after = by_name(listing(client, alice), "calendar")
    assert [t["name"] for t in after["tools"]] == [t["name"] for t in before["tools"]]
    assert moment(after["tools_listed_at"]) == moment(before["tools_listed_at"])
    assert badges(after)["list_events"] == (True, False, False)


def test_a_refused_token_gives_auth_failed_and_stores_nothing(
    client, alice, calendar, mcp_server
):
    mcp_server.revoked.add(f"Bearer {TOKEN}")
    response = run_test(client, alice, calendar)
    assert response.status_code == 502
    assert error_code(response) == "connector_auth_failed"
    after = by_name(listing(client, alice), "calendar")
    assert (after["tools"], after["tools_listed_at"]) == ([], None)


def test_test_is_404_for_a_missing_connector(client, alice):
    response = run_test(client, alice, "00000000-0000-0000-0000-000000000001")
    assert response.status_code == 404
    assert error_code(response) == "not_found"


# --- 5.4 tool switches -------------------------------------------------------


def test_switching_on_an_unavailable_tool_is_refused(
    client, alice, calendar, mcp_server
):
    mcp_server.extra_tools.append(
        types.Tool(
            name="get.time", description="Dotted.", input_schema={"type": "object"}
        )
    )
    listed_by_test(client, alice, calendar)
    response = switch(client, alice, calendar, "get.time", enabled=True)
    assert response.status_code == 422
    assert error_code(response) == "validation_error"
    assert response.json()["error"]["message"].startswith("enabled:")


def test_moving_acts_to_reads_is_refused(client, alice, calendar):
    listed_by_test(client, alice, calendar)
    response = switch(client, alice, calendar, "create_event", acts=False)
    assert response.status_code == 422
    assert error_code(response) == "validation_error"
    assert response.json()["error"]["message"].startswith("acts:")
    assert badges(by_name(listing(client, alice), "calendar"))["create_event"] == (
        False,
        True,
        False,
    )


def test_always_allow_on_a_reads_tool_is_refused(client, alice, calendar):
    listed_by_test(client, alice, calendar)
    response = switch(client, alice, calendar, "list_events", always_allow=True)
    assert response.status_code == 422
    assert error_code(response) == "validation_error"
    assert response.json()["error"]["message"].startswith("always_allow:")


def test_moving_reads_to_acts_works_and_back_clears_always_allow(
    client, alice, calendar
):
    listed_by_test(client, alice, calendar)

    moved = switch(client, alice, calendar, "list_events", acts=True, enabled=True)
    assert moved.status_code == 200, moved.text
    assert badges(moved.json())["list_events"] == (True, True, False)

    allowed = switch(client, alice, calendar, "list_events", always_allow=True)
    assert badges(allowed.json())["list_events"] == (True, True, True)

    back = switch(client, alice, calendar, "list_events", acts=False)
    assert back.status_code == 200, back.text
    assert badges(back.json())["list_events"] == (True, False, False)
    assert badges(by_name(listing(client, alice), "calendar"))["list_events"] == (
        True,
        False,
        False,
    )


def test_operator_tools_have_switches_too(client, alice):
    team = by_name(listing(client, alice), "team")
    listed_by_test(client, alice, team["id"])
    response = switch(
        client, alice, team["id"], "create_event", enabled=True, always_allow=True
    )
    assert response.status_code == 200, response.text
    assert badges(response.json())["create_event"] == (True, True, True)
    # The operator's list makes mixed reads, and it may stay so.
    assert switch(client, alice, team["id"], "mixed", acts=False).status_code == 200
    # A tool the operator does not offer is not there to switch.
    assert switch(client, alice, team["id"], "slow", enabled=True).status_code == 404


def test_an_unknown_tool_is_404(client, alice, calendar):
    listed_by_test(client, alice, calendar)
    response = switch(client, alice, calendar, "nope", enabled=True)
    assert response.status_code == 404
    assert error_code(response) == "not_found"
