"""MCP connector settings (openspec mcp-connectors task 2.1)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings


def use_demo(env) -> None:
    env.setenv("AUTH_MODE", "demo")
    for name in ("OIDC_ISSUER", "OIDC_CLIENT_ID"):
        env.delenv(name)


def test_both_switches_default_to_off(settings_env):
    settings = Settings()
    assert settings.mcp_enabled is False
    assert settings.mcp_user_connectors is False
    assert settings.mcp_connectors_path is None


def test_the_switches_can_be_turned_on(settings_env, tmp_path):
    settings_env.setenv("MCP_ENABLED", "true")
    settings_env.setenv("MCP_USER_CONNECTORS", "true")
    settings_env.setenv("MCP_CONNECTORS_PATH", str(tmp_path / "connectors.yaml"))
    settings = Settings()
    assert settings.mcp_enabled is True
    assert settings.mcp_user_connectors is True
    assert settings.mcp_connectors_path == tmp_path / "connectors.yaml"


def test_empty_values_count_as_unset(settings_env):
    for name in ("MCP_ENABLED", "MCP_USER_CONNECTORS"):
        settings_env.setenv(name, "")
    settings_env.setenv("MCP_CONNECTORS_PATH", "  ")
    settings = Settings()
    assert settings.mcp_enabled is False
    assert settings.mcp_user_connectors is False
    assert settings.mcp_connectors_path is None


def test_demo_mode_refuses_an_explicit_mcp_enabled(settings_env):
    use_demo(settings_env)
    settings_env.setenv("MCP_ENABLED", "true")
    with pytest.raises(ValidationError, match="MCP_ENABLED"):
        Settings()


def test_demo_mode_turns_connectors_off(settings_env):
    use_demo(settings_env)
    assert Settings().mcp_enabled is False


def test_demo_mode_accepts_connectors_turned_off(settings_env):
    use_demo(settings_env)
    settings_env.setenv("MCP_ENABLED", "false")
    settings_env.setenv("MCP_USER_CONNECTORS", "true")
    settings = Settings()
    assert settings.mcp_enabled is False


def test_the_path_is_a_path(settings_env):
    settings_env.setenv("MCP_CONNECTORS_PATH", " /etc/focus-funnel/connectors.yaml ")
    assert Settings().mcp_connectors_path == Path("/etc/focus-funnel/connectors.yaml")
