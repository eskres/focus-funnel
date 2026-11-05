"""MCP connector configuration: `connectors.yaml`, loaded once at startup.

The file holds the operator's connectors, which every user sees, and the
catalog of known servers offered when users may add their own (openspec
mcp-connectors design decision 5). It is read only when MCP_ENABLED is on.
Each value is checked by name, so a bad file stops the server at startup with
a message naming the connector and the field. MCP_CONNECTORS_PATH points
tests or an operator at another file.
"""

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import yaml

from app.chat.prompt import PROPOSE_TOOL, SEARCH_TOOL
from app.config import get_settings

# Design decision 3: a connector's tools are offered as `<name>__<tool>`.
CONNECTOR_NAME = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
RESERVED_NAMES = frozenset({SEARCH_TOOL, PROPOSE_TOOL})
AUTH_KINDS = ("none", "bearer", "header")
# An HTTP header name is an RFC 7230 token.
HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
# The auth_header column's size.
MAX_HEADER_LENGTH = 255
# Headers the MCP transport sets itself; an auth header may not replace them.
TRANSPORT_HEADERS = frozenset(
    {"host", "content-type", "content-length", "accept", "mcp-session-id", "mcp-protocol-version"}
)


class ConnectorConfigError(ValueError):
    """The connector configuration file is missing, malformed, or invalid."""


@dataclass(frozen=True)
class ConnectorAuth:
    kind: str  # one of AUTH_KINDS
    # The header that carries the value, for kind "header".
    header: str | None = None
    # The environment variable holding the value (operator connectors only).
    env: str | None = None


NO_AUTH = ConnectorAuth(kind="none")


@dataclass(frozen=True)
class OperatorConnector:
    name: str
    url: str
    auth: ConnectorAuth
    # The server tools this connector offers; None offers every tool.
    tools: tuple[str, ...] | None
    # Tools the operator marks as reads, trusted over the server's hint.
    read_only: tuple[str, ...]


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    title: str
    description: str
    url: str
    auth: ConnectorAuth
    guide: str


@dataclass(frozen=True)
class ConnectorConfig:
    connectors: tuple[OperatorConnector, ...]
    catalog: tuple[CatalogEntry, ...]

    def get(self, name: str) -> OperatorConnector | None:
        return next((c for c in self.connectors if c.name == name), None)


def name_problem(name: object) -> str | None:
    """Why a connector name is refused, or None when it is fine."""
    if not isinstance(name, str) or not CONNECTOR_NAME.fullmatch(name):
        return (
            "must start with a lowercase letter and hold only lowercase letters, "
            "digits, and underscores, at most 24 characters"
        )
    if "__" in name:
        return "must not contain two underscores in a row"
    if name.endswith("_"):
        # `a_` + `x` and `a` + `_x` would both be `a___x`.
        return "must not end with an underscore"
    if name in RESERVED_NAMES:
        return f"'{name}' is reserved for a built-in tool"
    return None


def header_problem(header: object) -> str | None:
    """Why an auth header name is refused, or None when it is fine."""
    if not isinstance(header, str) or not HEADER_NAME.fullmatch(header):
        return "must be an HTTP header name"
    if len(header) > MAX_HEADER_LENGTH:
        return f"must be at most {MAX_HEADER_LENGTH} characters"
    if header.lower() in TRANSPORT_HEADERS:
        return f"'{header}' is set by the connection itself"
    return None


def get_config_path() -> Path:
    path = get_settings().mcp_connectors_path
    return path if path is not None else Path(__file__).parent / "connectors.yaml"


def _check_fields(raw: dict, allowed: tuple[str, ...], where: str) -> None:
    for key in raw:
        if key not in allowed:
            raise ConnectorConfigError(f"{where} has an unknown field '{key}'")


def _http_url(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConnectorConfigError(f"{where} is required")
    try:
        parsed = urlparse(value.strip())
        parsed.port  # noqa: B018 - raises ValueError on a bad port
    except ValueError as exc:
        raise ConnectorConfigError(f"{where} does not parse as a URL: {exc}") from exc
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ConnectorConfigError(f"{where} must be an http or https URL")
    return value.strip()


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConnectorConfigError(f"{where} must be a non-empty string")
    return value.strip()


def _names(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ConnectorConfigError(f"{where} must be a non-empty list of tool names")
    names = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ConnectorConfigError(f"{where} must hold only tool names")
        if item.strip() in names:
            raise ConnectorConfigError(f"{where} names '{item.strip()}' twice")
        names.append(item.strip())
    return tuple(names)


def _parse_auth(raw: object, where: str, operator: bool) -> ConnectorAuth:
    if raw is None:
        return NO_AUTH
    if not isinstance(raw, dict):
        raise ConnectorConfigError(f"{where} 'auth' must be a mapping with a 'kind'")
    _check_fields(raw, ("kind", "header", "env") if operator else ("kind", "header"), f"{where} 'auth'")
    kind = raw.get("kind")
    if kind not in AUTH_KINDS:
        raise ConnectorConfigError(
            f"{where} 'auth.kind' must be one of {', '.join(AUTH_KINDS)}, not {kind!r}"
        )
    if kind == "none":
        if set(raw) - {"kind"}:
            raise ConnectorConfigError(f"{where} 'auth' of kind none takes no other fields")
        return NO_AUTH
    header = None
    if kind == "header":
        problem = header_problem(raw.get("header"))
        if problem:
            raise ConnectorConfigError(f"{where} 'auth.header' {problem}")
        header = raw["header"]
    elif "header" in raw:
        raise ConnectorConfigError(f"{where} 'auth.header' is only for auth kind header")
    env = None
    if operator:
        env = raw.get("env")
        if not isinstance(env, str) or not env.strip():
            raise ConnectorConfigError(
                f"{where} 'auth.env' must name the environment variable holding the value"
            )
        env = env.strip()
        if not os.environ.get(env, "").strip():
            raise ConnectorConfigError(
                f"{where} 'auth.env': the environment variable {env} is not set"
            )
    return ConnectorAuth(kind=kind, header=header, env=env)


def _name(raw: dict, label: str, position: str) -> str:
    name = raw.get("name")
    if name is None:
        raise ConnectorConfigError(f"{label} {position} 'name' is required")
    problem = name_problem(name)
    if problem:
        raise ConnectorConfigError(f"{label} {name!r} 'name' {problem}")
    return name


def _parse_operator(raw: object, index: int) -> OperatorConnector:
    if not isinstance(raw, dict):
        raise ConnectorConfigError(f"Connector connectors[{index}] must be a mapping")
    name = _name(raw, "Connector", f"connectors[{index}]")
    where = f"Connector '{name}'"
    _check_fields(raw, ("name", "url", "auth", "tools", "read_only"), where)
    url = _http_url(raw.get("url"), f"{where} 'url'")
    auth = _parse_auth(raw.get("auth"), where, operator=True)
    tools = _names(raw["tools"], f"{where} 'tools'") if "tools" in raw else None
    read_only = _names(raw["read_only"], f"{where} 'read_only'") if "read_only" in raw else ()
    if tools is not None:
        missing = [tool for tool in read_only if tool not in tools]
        if missing:
            raise ConnectorConfigError(
                f"{where} 'read_only' names '{missing[0]}', which is not in 'tools'"
            )
    return OperatorConnector(name=name, url=url, auth=auth, tools=tools, read_only=read_only)


def _parse_catalog(raw: object, index: int) -> CatalogEntry:
    if not isinstance(raw, dict):
        raise ConnectorConfigError(f"Catalog entry catalog[{index}] must be a mapping")
    name = _name(raw, "Catalog entry", f"catalog[{index}]")
    where = f"Catalog entry '{name}'"
    _check_fields(raw, ("name", "title", "description", "url", "auth", "guide"), where)
    url = _http_url(raw.get("url"), f"{where} 'url'")
    parsed = urlparse(url)
    if parsed.username is not None or parsed.password is not None:
        raise ConnectorConfigError(f"{where} 'url' must not hold a user name or password")
    return CatalogEntry(
        name=name,
        title=_text(raw.get("title"), f"{where} 'title'"),
        description=_text(raw.get("description"), f"{where} 'description'"),
        url=url,
        auth=_parse_auth(raw.get("auth"), where, operator=False),
        guide=_http_url(raw.get("guide"), f"{where} 'guide'"),
    )


def _list(raw: dict, key: str) -> list:
    value = raw.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConnectorConfigError(f"'{key}' must be a list")
    return value


def _unique(names: list[str], what: str) -> None:
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise ConnectorConfigError(f"{what} '{name}' 'name' is used twice")
        seen.add(name)


def load_connector_config(path: str | Path | None = None) -> ConnectorConfig:
    target_path = Path(path) if path is not None else get_config_path()
    if not target_path.exists():
        raise ConnectorConfigError(f"Connector configuration file not found: {target_path}")
    try:
        with open(target_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ConnectorConfigError(f"Failed to parse connector configuration YAML: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConnectorConfigError("Connector configuration must be a mapping")
    _check_fields(raw, ("connectors", "catalog"), "Connector configuration")

    connectors = [_parse_operator(item, i) for i, item in enumerate(_list(raw, "connectors"))]
    _unique([c.name for c in connectors], "Connector")
    catalog = [_parse_catalog(item, i) for i, item in enumerate(_list(raw, "catalog"))]
    _unique([entry.name for entry in catalog], "Catalog entry")
    return ConnectorConfig(connectors=tuple(connectors), catalog=tuple(catalog))


@lru_cache
def get_connector_config() -> ConnectorConfig:
    return load_connector_config()
