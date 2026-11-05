"""Approvals on Postgres (openspec mcp-connectors task 7.3): two concurrent
approvals run the tool once, and a turn expires what is still waiting."""

import pytest

from tests import test_connector_actions as actions_tests
from tests import test_connector_turns as turns

pytestmark = pytest.mark.postgres

config_path = turns.config_path
fake_mcp = turns.fake_mcp
client = turns.client
on = turns.on
acting = actions_tests.acting


def test_two_concurrent_approvals_run_the_tool_once_on_postgres(
    client, alice, acting, fake_llm, fake_mcp, test_database_url, monkeypatch
):
    action = actions_tests.held_action(client, alice, acting["conversation"], fake_llm)
    actions_tests.run_twice_at_once(
        test_database_url, client, alice, acting["conversation"], action["id"], fake_mcp,
        monkeypatch,
    )


def test_approving_after_the_next_turn_started_is_expired_on_postgres(
    client, alice, acting, fake_llm, fake_mcp, test_database_url
):
    actions_tests.test_approving_after_the_next_turn_started_gives_action_expired(
        client, alice, acting, fake_llm, fake_mcp, test_database_url
    )
