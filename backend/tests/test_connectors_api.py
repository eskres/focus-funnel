"""The connector settings API (openspec mcp-connectors tasks 5.1 and 5.2)."""

import logging

import pytest

from tests.chat_helpers import error_code, seed_conversation
from tests.connector_helpers import (
    add,
    by_name,
    connector_rows,
    connectors_app,
    link,
    links,
    listing,
    write_config,
)

TOKEN = "gcal-bearer-0123456789abcdef"
OPERATOR = {
    "name": "team",
    "url": "http://team-mcp:8000/mcp",
    "read_only": ["list_events"],
}


@pytest.fixture
def config_path(tmp_path):
    return write_config(tmp_path / "connectors.yaml", [OPERATOR])


@pytest.fixture
def client(test_database_url, jwks_cache, settings_env, config_path):
    with connectors_app(settings_env, jwks_cache, config_path) as client:
        yield client


# --- 5.1 listing and the warning ----------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/connectors"),
        ("POST", "/api/connectors/warning"),
        ("POST", "/api/connectors"),
        ("PATCH", "/api/connectors/00000000-0000-0000-0000-000000000001"),
        ("DELETE", "/api/connectors/00000000-0000-0000-0000-000000000001"),
        ("POST", "/api/connectors/00000000-0000-0000-0000-000000000001/test"),
        (
            "PATCH",
            "/api/connectors/00000000-0000-0000-0000-000000000001/tools/list_events",
        ),
    ],
)
def test_every_route_is_404_while_connectors_are_off(
    test_database_url, jwks_cache, settings_env, config_path, alice, method, path
):
    with connectors_app(settings_env, jwks_cache, config_path, enabled=False) as client:
        response = client.request(method, path, headers=alice, json={})
    assert response.status_code == 404
    assert error_code(response) == "not_found"


def test_listing_shows_operator_and_user_connectors_catalog_and_warning(client, alice):
    assert add(client, alice, auth_kind="bearer", auth_value=TOKEN).status_code == 201

    body = listing(client, alice)

    assert [(c["name"], c["source"]) for c in body["connectors"]] == [
        ("team", "operator"),
        ("calendar", "user"),
    ]
    team = by_name(body, "team")
    assert team["url"] is None  # an operator URL stays in the configuration
    assert team["tools"] == []
    calendar = by_name(body, "calendar")
    assert calendar["url"] == "http://127.0.0.1:9/mcp"
    assert calendar["auth_kind"] == "bearer"
    assert calendar["auth_set"] is True
    assert calendar["auth_last4"] == "cdef"
    assert TOKEN not in str(body)
    assert body["user_connectors_allowed"] is True
    assert [entry["title"] for entry in body["catalog"]] == ["Google Calendar"]
    assert body["catalog"][0]["guide"].endswith("#google-calendar")
    assert body["warning_accepted"] is False
    assert body["max_tools"] == 20


def test_the_warning_is_stored_once(client, alice, bob):
    assert client.post("/api/connectors/warning", headers=alice).status_code == 204
    assert listing(client, alice)["warning_accepted"] is True
    assert client.post("/api/connectors/warning", headers=alice).status_code == 204
    assert listing(client, alice)["warning_accepted"] is True
    assert listing(client, bob)["warning_accepted"] is False


def test_without_user_connectors_only_operator_ones_and_no_catalog(
    test_database_url, jwks_cache, settings_env, config_path, alice
):
    with connectors_app(settings_env, jwks_cache, config_path) as client:
        assert add(client, alice).status_code == 201
    with connectors_app(settings_env, jwks_cache, config_path, users=False) as client:
        body = listing(client, alice)
    assert [c["name"] for c in body["connectors"]] == ["team"]
    assert body["user_connectors_allowed"] is False
    assert body["catalog"] == []


def test_operator_rows_are_made_once_per_user(client, alice, bob, test_database_url):
    listing(client, alice)
    listing(client, alice)
    listing(client, bob)
    rows = connector_rows(test_database_url)
    assert sorted((r.name, r.source, r.operator_key) for r in rows) == [
        ("team", "operator", "team"),
        ("team", "operator", "team"),
    ]
    assert len({r.user_id for r in rows}) == 2


def test_a_removed_operator_connector_disappears_with_its_links(
    client, alice, test_database_url, config_path
):
    team = by_name(listing(client, alice), "team")
    conversation = seed_conversation(test_database_url, client, alice)
    link(test_database_url, conversation, team["id"])
    assert links(test_database_url) == [(conversation, team["id"])]

    write_config(config_path, [])
    body = listing(client, alice)

    assert body["connectors"] == []
    assert connector_rows(test_database_url) == []
    assert links(test_database_url) == []
    # The conversation itself is kept.
    assert (
        client.get(f"/api/conversations/{conversation}", headers=alice).status_code
        == 200
    )


def test_a_restart_without_the_operator_connector_prunes_every_users_row(
    test_database_url, jwks_cache, settings_env, config_path, alice, bob
):
    with connectors_app(settings_env, jwks_cache, config_path) as client:
        team = by_name(listing(client, alice), "team")
        listing(client, bob)
        conversation = seed_conversation(test_database_url, client, alice)
        link(test_database_url, conversation, team["id"])

    write_config(config_path, [])
    with connectors_app(settings_env, jwks_cache, config_path):
        pass

    assert connector_rows(test_database_url) == []
    assert links(test_database_url) == []


def test_an_operator_name_the_user_already_uses_is_skipped_for_them(
    client, alice, config_path, caplog
):
    assert add(client, alice, name="later").status_code == 201
    write_config(
        config_path, [OPERATOR, {"name": "later", "url": "http://later:8000/mcp"}]
    )
    with caplog.at_level(logging.WARNING):
        body = listing(client, alice)
    assert [(c["name"], c["source"]) for c in body["connectors"]] == [
        ("team", "operator"),
        ("later", "user"),
    ]
    assert "Operator connector 'later' is not offered" in caplog.text


# --- 5.2 add, change, remove ---------------------------------------------------


def test_add_stores_the_token_encrypted(client, alice, test_database_url):
    response = add(client, alice, auth_kind="bearer", auth_value=TOKEN)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "calendar"
    assert body["source"] == "user"
    assert body["auth_last4"] == "cdef"
    assert body["tools"] == []
    assert TOKEN not in response.text

    [row] = [r for r in connector_rows(test_database_url) if r.source == "user"]
    assert row.auth_ciphertext is not None
    assert TOKEN.encode() not in row.auth_ciphertext
    assert row.auth_last4 == "cdef"


def test_add_with_a_header(client, alice):
    response = add(
        client, alice, auth_kind="header", auth_header="X-Api-Key", auth_value=TOKEN
    )
    assert response.status_code == 201, response.text
    assert response.json()["auth_header"] == "X-Api-Key"
    assert response.json()["auth_last4"] == "cdef"


@pytest.mark.parametrize(
    ("fields", "named"),
    [
        ({"name": "Calendar"}, "name:"),
        ({"name": "2cal"}, "name:"),
        ({"name": "cal__dav"}, "name:"),
        ({"name": "a" * 25}, "name:"),
        ({"name": "search_thoughts"}, "name:"),
        ({"name": "propose_thought"}, "name:"),
        ({"name": "team"}, "name:"),  # the operator's
        ({"url": "file:///etc/passwd"}, "url:"),
        ({"url": "ftp://example.com/mcp"}, "url:"),
        ({"url": "not a url"}, "url:"),
        ({"url": "https://user:secret@example.com/mcp"}, "url:"),
        ({"url": "https://token@example.com/mcp"}, "url:"),
        ({"auth_kind": "bearer"}, "auth_value:"),
        ({"auth_kind": "header", "auth_value": TOKEN}, "auth_header:"),
        (
            {"auth_kind": "header", "auth_header": "Bad Header", "auth_value": TOKEN},
            "auth_header:",
        ),
        (
            {
                "auth_kind": "header",
                "auth_header": "Mcp-Session-Id",
                "auth_value": TOKEN,
            },
            "auth_header:",
        ),
        ({"auth_kind": "none", "auth_value": TOKEN}, "auth_value:"),
        ({"auth_kind": "basic", "auth_value": TOKEN}, "auth_kind:"),
    ],
)
def test_bad_fields_give_validation_error(client, alice, fields, named):
    response = add(
        client,
        alice,
        **{"name": "calendar", "url": "https://example.com/mcp", **fields},
    )
    assert response.status_code == 422, response.text
    assert error_code(response) == "validation_error"
    assert response.json()["error"]["message"].startswith(named)
    assert TOKEN not in response.text


def test_a_duplicate_name_gives_validation_error(client, alice, bob):
    assert add(client, alice).status_code == 201
    response = add(client, alice)
    assert response.status_code == 422
    assert error_code(response) == "validation_error"
    assert (
        "already have a connector named 'calendar'"
        in response.json()["error"]["message"]
    )
    # Names are per user.
    assert add(client, bob).status_code == 201


def test_the_auth_value_never_appears_in_a_response_or_log(client, alice, caplog):
    secret = "header-value-9876543210zyxw"
    with caplog.at_level(logging.DEBUG):
        created = add(client, alice, auth_kind="bearer", auth_value=TOKEN)
        connector_id = created.json()["id"]
        changed = client.patch(
            f"/api/connectors/{connector_id}",
            headers=alice,
            json={"auth_kind": "header", "auth_header": "X-Key", "auth_value": secret},
        )
        listed = client.get("/api/connectors", headers=alice)
    for response in (created, changed, listed):
        assert response.status_code in (200, 201), response.text
        assert TOKEN not in response.text
        assert secret not in response.text
    assert changed.json()["auth_last4"] == "zyxw"
    assert TOKEN not in caplog.text
    assert secret not in caplog.text


def test_adding_with_the_switch_off_is_403(
    test_database_url, jwks_cache, settings_env, config_path, alice
):
    with connectors_app(settings_env, jwks_cache, config_path, users=False) as client:
        response = add(client, alice)
        bad = add(client, alice, name="Bad Name")
    for answer in (response, bad):
        assert answer.status_code == 403
        assert error_code(answer) == "user_connectors_disabled"


def test_changing_or_removing_an_operator_row_is_403(client, alice):
    team = by_name(listing(client, alice), "team")
    for response in (
        client.patch(
            f"/api/connectors/{team['id']}", headers=alice, json={"name": "mine"}
        ),
        client.delete(f"/api/connectors/{team['id']}", headers=alice),
    ):
        assert response.status_code == 403
        assert error_code(response) == "operator_connector"
    assert by_name(listing(client, alice), "team")["id"] == team["id"]


def test_change_name_url_and_auth(client, alice, test_database_url):
    connector_id = add(client, alice, auth_kind="bearer", auth_value=TOKEN).json()["id"]

    response = client.patch(
        f"/api/connectors/{connector_id}",
        headers=alice,
        json={"name": "work_calendar", "url": "http://127.0.0.1:9/v2/mcp"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["name"], body["url"], body["auth_last4"]) == (
        "work_calendar",
        "http://127.0.0.1:9/v2/mcp",
        "cdef",  # the stored token is kept on the same server
    )

    # Another server gets the token only when it is entered again.
    moved = client.patch(
        f"/api/connectors/{connector_id}",
        headers=alice,
        json={"url": "https://cal.example.com/mcp", "auth_value": "new-token-9876"},
    )
    assert moved.status_code == 200, moved.text
    assert (moved.json()["url"], moved.json()["auth_last4"]) == (
        "https://cal.example.com/mcp",
        "9876",
    )

    cleared = client.patch(
        f"/api/connectors/{connector_id}", headers=alice, json={"auth_kind": "none"}
    ).json()
    assert (cleared["auth_kind"], cleared["auth_set"], cleared["auth_last4"]) == (
        "none",
        False,
        None,
    )
    [row] = [r for r in connector_rows(test_database_url) if r.source == "user"]
    assert row.auth_ciphertext is None


@pytest.mark.parametrize(
    ("fields", "named"),
    [
        ({"name": "team"}, "name:"),
        ({"name": "other"}, "name:"),
        ({"name": None}, "name:"),
        ({"url": "file:///etc/passwd"}, "url:"),
        ({"url": "https://me:pw@example.com"}, "url:"),
        ({"auth_kind": "header", "auth_header": "X-Key"}, "auth_value:"),
        ({"name": "cal_"}, "name:"),
        ({"auth_kind": "header", "auth_header": "X" * 300, "auth_value": "v"}, "auth_header:"),
        # The stored token is not sent to another server unless entered again.
        ({"url": "https://other.example.com/mcp"}, "auth_value:"),
        ({"url": "http://127.0.0.1:10/mcp"}, "auth_value:"),
    ],
)
def test_bad_changes_give_validation_error(client, alice, fields, named):
    add(client, alice, name="other")
    connector_id = add(client, alice, auth_kind="bearer", auth_value=TOKEN).json()["id"]
    response = client.patch(
        f"/api/connectors/{connector_id}", headers=alice, json=fields
    )
    assert response.status_code == 422, response.text
    assert error_code(response) == "validation_error"
    assert response.json()["error"]["message"].startswith(named)


def test_delete_removes_the_connector_from_conversations(
    client, alice, test_database_url
):
    connector_id = add(client, alice, auth_kind="bearer", auth_value=TOKEN).json()["id"]
    first = seed_conversation(test_database_url, client, alice, title="One")
    second = seed_conversation(test_database_url, client, alice, title="Two")
    link(test_database_url, first, connector_id)
    link(test_database_url, second, connector_id)

    response = client.delete(f"/api/connectors/{connector_id}", headers=alice)

    assert response.status_code == 204
    assert links(test_database_url) == []
    assert [c["name"] for c in listing(client, alice)["connectors"]] == ["team"]
    assert [r.source for r in connector_rows(test_database_url)] == ["operator"]
    for conversation in (first, second):
        assert (
            client.get(f"/api/conversations/{conversation}", headers=alice).status_code
            == 200
        )


def test_another_users_connector_is_404(client, alice, bob):
    connector_id = add(client, alice).json()["id"]
    team = by_name(listing(client, alice), "team")
    for connector in (connector_id, team["id"]):
        for response in (
            client.patch(
                f"/api/connectors/{connector}", headers=bob, json={"name": "mine"}
            ),
            client.delete(f"/api/connectors/{connector}", headers=bob),
            client.post(f"/api/connectors/{connector}/test", headers=bob),
            client.patch(
                f"/api/connectors/{connector}/tools/list_events",
                headers=bob,
                json={"enabled": True},
            ),
        ):
            assert response.status_code == 404, response.text
            assert error_code(response) == "not_found"
