import pytest

from app.errors import ErrorCode
from tests.chat_helpers import (
    BIG,
    NANO,
    NO_TOOLS,
    api_error,
    completion,
    entry,
    error_code,
    save_key,
    save_models,
    tool_call,
)


# --- 4.1 loadout, default, and temperature ---


def test_first_visit_has_no_models_and_the_system_temperature(client, alice):
    response = client.get("/api/settings/models", headers=alice)
    assert response.status_code == 200
    body = response.json()
    assert body["models"] == []
    assert body["temperature"] is None
    assert body["temperature_default"] == 0.3
    assert body["max_models"] == 5
    assert body["model_hint"]


def test_a_valid_save_is_returned_and_kept(client, alice, fake_llm):
    save_key(client, alice)
    response = save_models(
        client, alice, entry(NANO, effort="low", default=True), entry(BIG), temperature=0.7
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert [m["model"] for m in saved["models"]] == [NANO, BIG]
    assert saved["models"][0]["is_default"] is True
    assert saved["models"][0]["reasoning_effort"] == "low"
    assert saved["temperature"] == 0.7

    stored = client.get("/api/settings/models", headers=alice).json()
    assert [(m["model"], m["is_default"]) for m in stored["models"]] == [(NANO, True), (BIG, False)]
    assert stored["temperature"] == 0.7


def test_a_save_writes_exactly_the_body(client, alice, fake_llm):
    save_key(client, alice)
    save_models(client, alice, entry(NANO, default=True), entry(BIG), temperature=0.7)

    save_models(client, alice, entry(BIG))

    stored = client.get("/api/settings/models", headers=alice).json()
    assert [(m["model"], m["is_default"]) for m in stored["models"]] == [(BIG, False)]
    assert stored["temperature"] is None


def test_a_sixth_model_is_refused(client, alice, fake_llm):
    save_key(client, alice)
    calls_before = fake_llm.model_list_calls
    six = [entry(f"vendor/m{i}") for i in range(6)]
    response = save_models(client, alice, *six)
    assert response.status_code == 422
    assert error_code(response) == ErrorCode.VALIDATION_ERROR
    assert "full" in response.json()["error"]["message"]
    assert fake_llm.model_list_calls == calls_before


def test_a_model_not_in_the_users_list_is_unknown(client, alice, fake_llm):
    save_key(client, alice)
    response = save_models(client, alice, entry("vendor/not-listed"))
    assert response.status_code == 400
    assert error_code(response) == ErrorCode.MODEL_UNKNOWN
    message = response.json()["error"]["message"]
    assert "vendor/not-listed" in message and "Nebius" in message


def test_a_model_without_reported_tool_calling_is_saved_unconfirmed(client, alice, fake_llm):
    save_key(client, alice)
    response = save_models(client, alice, entry(NO_TOOLS), entry(NANO))
    assert response.status_code == 200
    models = {m["model"]: m for m in response.json()["models"]}
    assert models[NO_TOOLS]["unconfirmed"] is True
    assert models[NO_TOOLS]["tool_calling"] == "unconfirmed"
    assert models[NANO]["unconfirmed"] is False


@pytest.mark.parametrize("temperature", [-0.1, 2.5])
def test_an_out_of_range_temperature_is_refused(client, alice, temperature):
    response = save_models(client, alice, temperature=temperature)
    assert response.status_code == 422
    assert error_code(response) == ErrorCode.VALIDATION_ERROR


@pytest.mark.parametrize(
    "entries",
    [
        [entry(NANO), entry(NANO)],
        [entry(NANO, default=True), entry(BIG, default=True)],
        [entry(NANO, effort="enormous")],
    ],
)
def test_other_bad_bodies_are_refused(client, alice, entries):
    response = save_models(client, alice, *entries)
    assert response.status_code == 422
    assert error_code(response) == ErrorCode.VALIDATION_ERROR


def test_a_refused_save_leaves_the_earlier_loadout(client, alice, fake_llm):
    save_key(client, alice)
    save_models(client, alice, entry(NANO, default=True), temperature=0.5)

    assert save_models(client, alice, entry("vendor/not-listed")).status_code == 400
    assert save_models(client, alice, *[entry(f"m{i}") for i in range(6)]).status_code == 422
    assert save_models(client, alice, entry(BIG), temperature=9).status_code == 422

    stored = client.get("/api/settings/models", headers=alice).json()
    assert [(m["model"], m["is_default"]) for m in stored["models"]] == [(NANO, True)]
    assert stored["temperature"] == 0.5


def test_one_users_settings_do_not_affect_another(client, alice, bob, fake_llm):
    save_key(client, alice)
    save_models(client, alice, entry(NANO, default=True), temperature=0.9)

    stored = client.get("/api/settings/models", headers=bob).json()
    assert stored["models"] == []
    assert stored["temperature"] is None


# --- 4.2 efforts per model ---


def test_the_effort_table_limits_the_offered_efforts(client, alice):
    def efforts(model):
        return client.get(
            "/api/settings/models/efforts", params={"model": model}, headers=alice
        ).json()["efforts"]

    assert "none" not in efforts("nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")
    assert "low" in efforts("nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")
    gpt_oss = efforts("openai/gpt-oss-120b")
    assert "none" not in gpt_oss and "minimal" not in gpt_oss and "high" in gpt_oss
    assert efforts("vendor/unlisted") == ["none", "minimal", "low", "medium", "high"]


def test_loadout_entries_carry_their_offered_efforts(client, alice, fake_llm):
    save_key(client, alice)
    save_models(client, alice, entry(NANO))
    stored = client.get("/api/settings/models", headers=alice).json()
    # The shipped table does not mention the fake models, so every effort is offered.
    assert stored["models"][0]["efforts"] == ["none", "minimal", "low", "medium", "high"]


def test_a_refused_effort_cannot_be_saved(client, alice, fake_llm):
    fake_llm.models = {"object": "list", "data": [{"id": "openai/gpt-oss-20b"}]}
    save_key(client, alice)
    response = save_models(client, alice, entry("openai/gpt-oss-20b", effort="minimal"))
    assert response.status_code == 422
    assert "minimal" in response.json()["error"]["message"]


# --- 4.3 Test ---


def run_test(client, headers, model=NANO, effort=None, provider_id="nebius"):
    return client.post(
        "/api/settings/models/test",
        headers=headers,
        json={"provider_id": provider_id, "model": model, "reasoning_effort": effort},
    )


def stored_state(client, headers):
    return client.get("/api/settings/models", headers=headers).json()


def test_a_working_model_reports_success(client, alice, fake_llm):
    save_key(client, alice)
    fake_llm.queue(completion("Ready."), completion(None, tool_calls=[tool_call("ping", {})]))

    response = run_test(client, alice, effort="low")

    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert response.json()["model"] == NANO
    first, probe = fake_llm.chat_requests
    assert first["reasoning_effort"] == "low"
    assert first["max_tokens"] == 8192
    assert probe["tools"][0]["function"]["name"] == "ping"


def test_no_effort_is_sent_when_none_is_chosen(client, alice, fake_llm):
    save_key(client, alice)
    fake_llm.queue(completion("Ready."), completion(None, tool_calls=[tool_call("ping", {})]))
    run_test(client, alice)
    assert all("reasoning_effort" not in r for r in fake_llm.chat_requests)


def test_an_empty_answer_fails_naming_the_effort(client, alice, fake_llm):
    save_key(client, alice)
    fake_llm.queue(completion(""))
    response = run_test(client, alice, effort="none")
    assert response.status_code == 400
    assert error_code(response) == ErrorCode.MODEL_UNSUPPORTED
    assert "empty answer" in response.json()["error"]["message"]
    assert "'none'" in response.json()["error"]["message"]


@pytest.mark.parametrize(
    "probe_reply",
    [completion("I won't call it."), api_error(400, "This model does not support tools")],
)
def test_a_model_that_rejects_or_ignores_tools_is_unsupported(client, alice, fake_llm, probe_reply):
    save_key(client, alice)
    fake_llm.queue(completion("Ready."), probe_reply)
    response = run_test(client, alice)
    assert response.status_code == 400
    assert error_code(response) == ErrorCode.MODEL_UNSUPPORTED
    assert "tool calling" in response.json()["error"]["message"]


def test_a_missing_model_is_unavailable(client, alice, fake_llm):
    save_key(client, alice)
    fake_llm.queue(api_error(404, f"Model {NANO} not found"))
    response = run_test(client, alice)
    assert response.status_code == 409
    assert error_code(response) == ErrorCode.MODEL_UNAVAILABLE


def test_a_refused_effort_is_reported_naming_it(client, alice, fake_llm):
    save_key(client, alice)
    fake_llm.queue(api_error(400, "reasoning_effort 'high' is not supported by this model"))
    response = run_test(client, alice, effort="high")
    assert response.status_code == 400
    assert error_code(response) == ErrorCode.MODEL_UNSUPPORTED
    assert "'high'" in response.json()["error"]["message"]


def test_a_missing_key_is_reported(client, alice, fake_llm):
    response = run_test(client, alice)
    assert response.status_code == 409
    assert error_code(response) == ErrorCode.PROVIDER_KEY_MISSING
    assert fake_llm.chat_requests == []


def test_no_stored_setting_changes_in_any_case(client, alice, fake_llm):
    save_key(client, alice)
    save_models(client, alice, entry(NANO, effort="low", default=True), temperature=0.4)
    before = stored_state(client, alice)

    fake_llm.queue(completion("Ready."), completion(None, tool_calls=[tool_call("ping", {})]))
    run_test(client, alice, model=BIG, effort="high")
    fake_llm.queue(completion(""))
    run_test(client, alice, model=BIG)
    fake_llm.queue(api_error(404))
    run_test(client, alice, model=BIG)

    assert stored_state(client, alice) == before


# --- 4.4 models come from the provider's list ---


def test_a_loadout_entry_stores_its_provider_and_model(client, alice, fake_llm):
    save_key(client, alice)
    save_key(client, alice, provider="local", key="")
    save_models(client, alice, entry(NANO), entry(NANO, provider_id="local"))

    stored = stored_state(client, alice)
    assert [(m["provider_id"], m["model"]) for m in stored["models"]] == [
        ("nebius", NANO),
        ("local", NANO),
    ]


def test_a_provider_with_no_saved_key_is_refused(client, alice, fake_llm):
    response = save_models(client, alice, entry(NANO))
    assert response.status_code == 409
    assert error_code(response) == ErrorCode.PROVIDER_KEY_MISSING
    assert stored_state(client, alice)["models"] == []


def test_prices_and_context_length_come_through_when_reported(client, alice, fake_llm):
    save_key(client, alice)
    save_key(client, alice, provider="local", key="")
    response = save_models(client, alice, entry(NANO), entry(NANO, provider_id="local"))
    reported, bare = response.json()["models"]
    assert reported["context_length"] == 131072
    assert reported["prices"] == {"prompt": "0.00000006", "completion": "0.00000024"}
    # The local provider's capabilities say its list reports neither.
    assert "context_length" not in bare
    assert "prices" not in bare
