"""The connectors.yaml loader (openspec mcp-connectors task 2.2)."""

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.connector_config import (
    ConnectorConfigError,
    get_connector_config,
    header_problem,
    load_connector_config,
    name_problem,
)
from app.main import app

SHIPPED = Path(__file__).parent.parent / "app" / "connectors.yaml"

CALENDAR = {
    "name": "calendar",
    "url": "http://gcal-mcp:8000/mcp",
    "auth": {"kind": "bearer", "env": "GCAL_MCP_TOKEN"},
    "tools": ["list-events", "create-event"],
    "read_only": ["list-events"],
}
NOTES = {
    "name": "notes_2",
    "url": "https://notes.example.org/mcp",
    "auth": {"kind": "header", "header": "X-Api-Key", "env": "NOTES_KEY"},
}
WIKI = {"name": "wiki", "url": "http://192.168.1.20:9000/mcp"}
CATALOG_ENTRY = {
    "name": "calendar",
    "title": "Google Calendar",
    "description": "Read and add events.",
    "url": "http://gcal-mcp:8000/mcp",
    "auth": {"kind": "none"},
    "guide": "https://example.org/docs/connectors.md#google-calendar",
}
VALID = {"connectors": [CALENDAR, NOTES, WIKI], "catalog": [CATALOG_ENTRY]}


@pytest.fixture(autouse=True)
def auth_env(monkeypatch):
    monkeypatch.setenv("GCAL_MCP_TOKEN", "calendar-token-1234")
    monkeypatch.setenv("NOTES_KEY", "notes-key-5678")
    return monkeypatch


def write(tmp_path, data) -> Path:
    path = tmp_path / "connectors.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def with_connector(**change) -> dict:
    return {**VALID, "connectors": [{**CALENDAR, **change}, NOTES, WIKI]}


def with_catalog(**change) -> dict:
    return {**VALID, "catalog": [{**CATALOG_ENTRY, **change}]}


def test_a_valid_file_loads(tmp_path):
    config = load_connector_config(write(tmp_path, VALID))

    calendar, notes, wiki = config.connectors
    assert calendar.name == "calendar"
    assert calendar.url == "http://gcal-mcp:8000/mcp"
    assert (calendar.auth.kind, calendar.auth.env, calendar.auth.header) == (
        "bearer",
        "GCAL_MCP_TOKEN",
        None,
    )
    assert calendar.tools == ("list-events", "create-event")
    assert calendar.read_only == ("list-events",)
    assert (notes.auth.kind, notes.auth.header, notes.auth.env) == ("header", "X-Api-Key", "NOTES_KEY")
    assert notes.tools is None and notes.read_only == ()
    assert wiki.auth.kind == "none" and wiki.tools is None
    assert config.get("wiki") is wiki and config.get("missing") is None

    (entry,) = config.catalog
    assert (entry.name, entry.title, entry.url) == ("calendar", "Google Calendar", CATALOG_ENTRY["url"])
    assert entry.auth.kind == "none" and entry.auth.env is None
    assert entry.guide.endswith("#google-calendar")


def test_auth_values_are_not_kept_in_the_config(tmp_path):
    config = load_connector_config(write(tmp_path, VALID))
    assert "calendar-token-1234" not in repr(config)


def test_the_shipped_file_holds_the_google_calendar_catalog_entry():
    config = load_connector_config(SHIPPED)
    assert config.connectors == ()
    (entry,) = config.catalog
    assert entry.name == "calendar"
    assert entry.title == "Google Calendar"
    assert entry.url.startswith("http") and entry.guide.startswith("https://")


@pytest.mark.parametrize("data", [{}, {"connectors": None, "catalog": None}])
def test_an_empty_file_has_no_connectors(tmp_path, data):
    config = load_connector_config(write(tmp_path, data))
    assert (config.connectors, config.catalog) == ((), ())


@pytest.mark.parametrize(
    "name",
    ["Calendar", "1cal", "cal-endar", "cal endar", "a" * 25, "", 7, "cal__endar", "cal_"],
)
def test_a_bad_name_fails_naming_the_connector_and_field(tmp_path, name):
    with pytest.raises(ConnectorConfigError, match=r"Connector .* 'name'") as error:
        load_connector_config(write(tmp_path, with_connector(name=name)))
    assert repr(name) in str(error.value)


def test_a_missing_name_fails_naming_its_position(tmp_path):
    connector = {**CALENDAR}
    connector.pop("name")
    with pytest.raises(ConnectorConfigError, match=r"connectors\[0\] 'name' is required"):
        load_connector_config(write(tmp_path, {"connectors": [connector]}))


def test_a_duplicate_name_fails_naming_it(tmp_path):
    data = {"connectors": [CALENDAR, {**WIKI, "name": "calendar"}]}
    with pytest.raises(ConnectorConfigError, match="Connector 'calendar' 'name' is used twice"):
        load_connector_config(write(tmp_path, data))


@pytest.mark.parametrize("name", ["search_thoughts", "propose_thought"])
def test_a_reserved_name_fails_naming_it(tmp_path, name):
    with pytest.raises(ConnectorConfigError, match=f"Connector '{name}' 'name' '{name}' is reserved"):
        load_connector_config(write(tmp_path, with_connector(name=name)))


@pytest.mark.parametrize(
    "url, problem",
    [
        ("http://[::1/mcp", "does not parse"),
        ("http://gcal-mcp:port/mcp", "does not parse"),
        ("not a url", "must be an http or https URL"),
        ("ftp://gcal-mcp/mcp", "must be an http or https URL"),
        ("http:///mcp", "must be an http or https URL"),
        ("", "is required"),
        (None, "is required"),
    ],
)
def test_a_url_that_does_not_parse_fails_naming_the_connector_and_field(tmp_path, url, problem):
    with pytest.raises(ConnectorConfigError, match=f"Connector 'calendar' 'url' {problem}"):
        load_connector_config(write(tmp_path, with_connector(url=url)))


def test_an_operator_url_on_a_private_address_is_accepted(tmp_path):
    config = load_connector_config(write(tmp_path, VALID))
    assert config.get("wiki").url == "http://192.168.1.20:9000/mcp"


@pytest.mark.parametrize("kind", ["oauth", "Bearer", None, 3])
def test_an_unknown_auth_kind_fails_naming_the_connector_and_field(tmp_path, kind):
    with pytest.raises(ConnectorConfigError, match="Connector 'calendar' 'auth.kind'"):
        load_connector_config(write(tmp_path, with_connector(auth={"kind": kind, "env": "GCAL_MCP_TOKEN"})))


def test_a_missing_auth_environment_variable_fails_naming_the_connector_and_field(
    tmp_path, auth_env
):
    auth_env.delenv("GCAL_MCP_TOKEN")
    with pytest.raises(
        ConnectorConfigError, match="Connector 'calendar' 'auth.env'.*GCAL_MCP_TOKEN is not set"
    ):
        load_connector_config(write(tmp_path, VALID))


def test_an_empty_auth_environment_variable_counts_as_missing(tmp_path, auth_env):
    auth_env.setenv("NOTES_KEY", "  ")
    with pytest.raises(ConnectorConfigError, match="Connector 'notes_2' 'auth.env'.*NOTES_KEY"):
        load_connector_config(write(tmp_path, VALID))


def test_auth_without_an_environment_variable_fails(tmp_path):
    with pytest.raises(ConnectorConfigError, match="Connector 'calendar' 'auth.env' must name"):
        load_connector_config(write(tmp_path, with_connector(auth={"kind": "bearer"})))


@pytest.mark.parametrize(
    "header, problem",
    [
        (None, "must be an HTTP header name"),
        ("X Api Key", "must be an HTTP header name"),
        ("X-Key:", "must be an HTTP header name"),
        ("Mcp-Session-Id", "is set by the connection itself"),
        ("content-type", "is set by the connection itself"),
        ("Host", "is set by the connection itself"),
        ("X" * 256, "must be at most 255 characters"),
    ],
)
def test_a_bad_auth_header_fails_naming_the_connector_and_field(tmp_path, header, problem):
    auth = {"kind": "header", "header": header, "env": "GCAL_MCP_TOKEN"}
    with pytest.raises(ConnectorConfigError, match=f"Connector 'calendar' 'auth.header' .*{problem}"):
        load_connector_config(write(tmp_path, with_connector(auth=auth)))


def test_a_read_only_tool_not_in_tools_fails_naming_the_connector_and_field(tmp_path):
    with pytest.raises(
        ConnectorConfigError,
        match="Connector 'calendar' 'read_only' names 'get-event', which is not in 'tools'",
    ):
        load_connector_config(write(tmp_path, with_connector(read_only=["list-events", "get-event"])))


def test_read_only_without_tools_is_accepted(tmp_path):
    data = {"connectors": [{**WIKI, "read_only": ["search"]}]}
    assert load_connector_config(write(tmp_path, data)).get("wiki").read_only == ("search",)


@pytest.mark.parametrize(
    "change, field",
    [
        ({"tools": []}, "'tools'"),
        ({"tools": "list-events"}, "'tools'"),
        ({"tools": ["list-events", "list-events"]}, "'tools'"),
        ({"read_only": [""]}, "'read_only'"),
        ({"readonly": ["list-events"]}, "unknown field 'readonly'"),
    ],
)
def test_other_bad_fields_fail_naming_the_connector_and_field(tmp_path, change, field):
    with pytest.raises(ConnectorConfigError, match=f"Connector 'calendar'.*{field}"):
        load_connector_config(write(tmp_path, with_connector(**change)))


@pytest.mark.parametrize(
    "change, field",
    [
        ({"name": "Google Calendar"}, "'name'"),
        ({"name": "propose_thought"}, "'name'"),
        ({"url": "calendar"}, "'url'"),
        ({"url": "http://me:secret@gcal-mcp:8000/mcp"}, "'url' must not hold a user name"),
        ({"guide": "docs/connectors.md"}, "'guide'"),
        ({"title": " "}, "'title'"),
        ({"description": None}, "'description'"),
        ({"auth": {"kind": "token"}}, "'auth.kind'"),
        ({"auth": {"kind": "bearer", "env": "GCAL_MCP_TOKEN"}}, "unknown field 'env'"),
    ],
)
def test_a_bad_catalog_entry_fails_naming_it_and_the_field(tmp_path, change, field):
    with pytest.raises(ConnectorConfigError, match=f"Catalog entry .*{field}"):
        load_connector_config(write(tmp_path, with_catalog(**change)))


def test_a_duplicate_catalog_name_fails(tmp_path):
    data = {"catalog": [CATALOG_ENTRY, CATALOG_ENTRY]}
    with pytest.raises(ConnectorConfigError, match="Catalog entry 'calendar' 'name' is used twice"):
        load_connector_config(write(tmp_path, data))


@pytest.mark.parametrize(
    "data, problem",
    [
        ([CALENDAR], "must be a mapping"),
        ({"connectors": CALENDAR}, "'connectors' must be a list"),
        ({"servers": []}, "unknown field 'servers'"),
    ],
)
def test_a_bad_file_shape_fails(tmp_path, data, problem):
    with pytest.raises(ConnectorConfigError, match=problem):
        load_connector_config(write(tmp_path, data))


def test_a_missing_file_fails(tmp_path):
    with pytest.raises(ConnectorConfigError, match="not found"):
        load_connector_config(tmp_path / "missing.yaml")


def test_the_name_and_header_checks_are_reusable():
    assert name_problem("calendar") is None
    assert name_problem("my_calendar") is None
    assert name_problem("search_thoughts")
    # A trailing underscore would make `cal_` + `x` and `cal` + `_x` the same
    # tool name (decision 3).
    assert name_problem("cal_") == "must not end with an underscore"
    assert header_problem("X" * 255) is None
    assert header_problem("X" * 256) == "must be at most 255 characters"
    assert header_problem("X-Api-Key") is None
    assert header_problem("Authorization") is None
    assert header_problem("Mcp-Protocol-Version")


def test_the_path_comes_from_the_settings(settings_env, tmp_path):
    settings_env.setenv("MCP_CONNECTORS_PATH", str(write(tmp_path, VALID)))
    assert [c.name for c in get_connector_config().connectors] == ["calendar", "notes_2", "wiki"]


def test_the_shipped_file_is_the_default(settings_env):
    assert get_connector_config() == load_connector_config(SHIPPED)


def test_app_refuses_to_start_on_an_invalid_file_when_enabled(settings_env, tmp_path):
    settings_env.setenv("MCP_ENABLED", "true")
    settings_env.setenv("MCP_CONNECTORS_PATH", str(write(tmp_path, with_connector(name="Bad"))))
    with pytest.raises(ConnectorConfigError, match="'Bad' 'name'"):
        with TestClient(app):
            pass


def test_app_starts_with_a_valid_file_when_enabled(settings_env, tmp_path, test_database_url):
    # Startup also prunes unconfigured operator rows, so it needs the tables.
    settings_env.setenv("MCP_ENABLED", "true")
    settings_env.setenv("MCP_CONNECTORS_PATH", str(write(tmp_path, VALID)))
    with TestClient(app):
        pass


def test_app_does_not_read_the_file_when_disabled(settings_env, tmp_path, test_database_url):
    # Startup sweeps stale turn claims (background-turns), so it needs the tables.
    settings_env.setenv("MCP_CONNECTORS_PATH", str(write(tmp_path, with_connector(name="Bad"))))
    with TestClient(app):
        pass
    assert get_connector_config.cache_info().currsize == 0


REPO = Path(__file__).parent.parent.parent
OVERLAY = REPO / "docker-compose.mcp.yml"
OVERLAY_CONNECTORS = REPO / "mcp" / "google-calendar" / "connectors.yaml"
CALENDAR_READS = {
    "list-calendars",
    "list-events",
    "search-events",
    "get-event",
    "list-colors",
    "get-freebusy",
    "get-current-time",
}


def test_the_compose_overlay_connector_file_offers_the_calendar_without_sign_in():
    # Task 10.1: docker-compose.mcp.yml hands the backend this file.
    config = load_connector_config(OVERLAY_CONNECTORS)
    assert config.catalog == ()
    [calendar] = config.connectors
    assert calendar.name == "calendar"
    assert calendar.url == "http://gcal-mcp:8000/mcp"
    assert calendar.auth.kind == "none"
    # manage-accounts would start a Google sign-in from inside a chat.
    assert calendar.tools is not None and "manage-accounts" not in calendar.tools
    assert len(calendar.tools) == 12
    assert set(calendar.read_only) == CALENDAR_READS


def test_the_compose_overlay_keeps_the_server_off_the_host_and_points_the_backend_at_it():
    overlay = yaml.safe_load(OVERLAY.read_text())
    server = overlay["services"]["gcal-mcp"]
    assert "ports" not in server
    assert (REPO / server["build"] / "Dockerfile").exists()
    backend = overlay["services"]["backend"]
    assert backend["environment"]["MCP_ENABLED"] == "true"
    target = backend["environment"]["MCP_CONNECTORS_PATH"]
    source, mounted, _ = backend["volumes"][0].split(":")
    assert mounted == target
    assert (REPO / source).resolve() == OVERLAY_CONNECTORS.resolve()


def test_the_catalog_guide_points_at_a_section_of_the_connector_docs():
    # Task 10.2: the shipped catalog links to docs/connectors.md#google-calendar.
    (entry,) = load_connector_config(SHIPPED).catalog
    page, anchor = entry.guide.rsplit("#", 1)
    assert page.endswith("/docs/connectors.md")
    headings = [
        line.lstrip("#").strip().lower().replace(" ", "-")
        for line in (REPO / "docs" / "connectors.md").read_text().splitlines()
        if line.startswith("#")
    ]
    assert anchor in headings
