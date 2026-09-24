"""The context meter, the soft and hard limits, and /compact."""

from sqlalchemy import select

from app.chat.prompt import SYSTEM_PROMPT
from app.models import UsageEvent
from tests.chat_helpers import (
    BIG,
    MODEL_LIST,
    NANO,
    NO_TOOLS,
    MidStreamFailure,
    api_error,
    chat,
    entry,
    error_code,
    ready_user,
    run_db,
    seed_conversation,
    text_chunks,
    usage_chunk,
)
from tests.sse_helpers import parse_events

SMALL = "vendor/small-model"
TEN = tuple(f"message {n}" for n in range(10))


def events_of(response, name: str) -> list[dict]:
    return [data for event, data in parse_events(response.text) if event == name]


def names(response) -> list[str]:
    return [name for name, _ in parse_events(response.text)]


def conversation_id_of(response) -> str:
    return events_of(response, "conversation")[0]["id"]


def stored(client, headers, conversation_id) -> dict:
    response = client.get(f"/api/conversations/{conversation_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def usage_rows(url: str) -> list[UsageEvent]:
    async def work(session):
        return list(
            (await session.execute(select(UsageEvent).order_by(UsageEvent.created_at))).scalars()
        )

    return run_db(url, work)


def with_models(fake_llm, *extra: dict) -> None:
    fake_llm.models = {"object": "list", "data": [*MODEL_LIST["data"], *extra]}


def seeded(url, client, headers, messages=TEN, model=NANO, **fields) -> str:
    return seed_conversation(
        url, client, headers, messages=messages, provider_id="nebius", model=model, **fields
    )


def compact(client, headers, conversation_id, **extra):
    return chat(client, headers, "/compact", conversation_id, **extra)


def accept(client, headers, conversation_id, summary, through_position):
    return client.post(
        f"/api/conversations/{conversation_id}/compaction",
        headers=headers,
        json={"summary": summary, "through_position": through_position},
    )


# --- 8.1 the meter ---


def test_the_prompt_tokens_are_stored_and_sent_with_the_context_length(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Hi") + [usage_chunk(500, 20)])

    response = chat(client, alice, "hello")

    assert events_of(response, "usage") == [
        {"prompt_tokens": 500, "completion_tokens": 20, "context_length": 131072}
    ]
    assert names(response)[-1] == "done"
    body = stored(client, alice, conversation_id_of(response))
    assert body["last_prompt_tokens"] == 500
    assert body["context"] == {"tokens": 500, "estimated": False, "context_length": 131072}


def test_the_model_list_is_read_once_for_several_turns(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Hi") + [usage_chunk()], text_chunks("Hi") + [usage_chunk()])
    first = chat(client, alice, "hello")
    calls = fake_llm.model_list_calls

    chat(client, alice, "again", conversation_id_of(first))

    assert fake_llm.model_list_calls == calls


def test_switching_model_changes_the_context_length(client, alice, fake_llm):
    ready_user(client, alice, entry(NANO, default=True), entry(BIG))
    fake_llm.queue(text_chunks("Hi") + [usage_chunk()], text_chunks("Hi") + [usage_chunk()])
    first = chat(client, alice, "hello")

    second = chat(client, alice, "again", conversation_id_of(first), provider_id="nebius", model=BIG)

    assert events_of(first, "usage")[0]["context_length"] == 131072
    assert events_of(second, "usage")[0]["context_length"] == 262144


def test_a_missing_context_length_is_left_out(client, alice, fake_llm):
    fake_llm.models = {
        "object": "list",
        "data": [{"id": NANO, "supported_features": ["tools"]}],
    }
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Hi") + [usage_chunk(300, 5)])

    response = chat(client, alice, "hello")

    assert events_of(response, "usage") == [{"prompt_tokens": 300, "completion_tokens": 5}]
    body = stored(client, alice, conversation_id_of(response))
    assert body["context"] == {"tokens": 300, "estimated": False, "context_length": None}


# --- 8.2 the soft limit ---


def test_compact_is_suggested_once_when_the_share_is_passed(client, alice, fake_llm):
    ready_user(client, alice)
    # 70% of 131072 is 91750.
    fake_llm.queue(
        text_chunks("One") + [usage_chunk(50_000)],
        text_chunks("Two") + [usage_chunk(95_000)],
        text_chunks("Three") + [usage_chunk(96_000)],
    )
    first = chat(client, alice, "one")
    conversation_id = conversation_id_of(first)
    second = chat(client, alice, "two", conversation_id)
    third = chat(client, alice, "three", conversation_id)

    assert events_of(first, "notice") == []
    assert events_of(second, "notice") == [
        {"kind": "compact_suggested", "prompt_tokens": 95_000, "context_length": 131072}
    ]
    assert names(second)[-1] == "done"
    assert events_of(third, "notice") == []


def test_compact_is_suggested_again_after_the_count_falls_and_rises(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seeded(test_database_url, client, alice, last_prompt_tokens=40_000)
    fake_llm.queue(text_chunks("Up") + [usage_chunk(95_000)])

    response = chat(client, alice, "more", conversation_id)

    assert [n["kind"] for n in events_of(response, "notice")] == ["compact_suggested"]


# --- 8.3 the hard limit ---


def test_a_message_that_cannot_fit_is_refused_before_any_call(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    # 125,000 + the message + the 8,192 reply limit is over 131,072.
    conversation_id = seeded(test_database_url, client, alice, last_prompt_tokens=125_000)

    response = chat(client, alice, "one more thing", conversation_id)

    assert response.status_code == 409
    assert error_code(response) == "context_full"
    assert "/compact" in response.json()["error"]["message"]
    assert response.headers["X-Conversation-Id"] == conversation_id
    assert fake_llm.chat_requests == []
    body = stored(client, alice, conversation_id)
    assert body["messages"][-1]["role"] == "user"
    assert body["messages"][-1]["content"] == "one more thing"
    assert len(body["messages"]) == 11


def test_the_refused_conversation_is_free_for_the_next_message(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seeded(test_database_url, client, alice, last_prompt_tokens=125_000)
    chat(client, alice, "one more thing", conversation_id)
    fake_llm.queue(text_chunks("Summary") + [usage_chunk()])

    assert compact(client, alice, conversation_id).status_code == 200


def test_a_provider_context_error_maps_to_context_full(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(
        api_error(400, "This model's maximum context length is 131072 tokens. Please reduce it.")
    )

    response = chat(client, alice, "hello")

    assert response.status_code == 409
    assert error_code(response) == "context_full"


# --- 8.4 the /compact draft ---


def test_compact_streams_a_draft_and_changes_nothing(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    conversation_id = seeded(test_database_url, client, alice)
    before = stored(client, alice, conversation_id)
    fake_llm.queue(text_chunks("We talked ", "about rent.") + [usage_chunk(400, 60)])

    response = compact(client, alice, conversation_id)

    assert response.status_code == 200, response.text
    assert names(response) == ["compact_draft", "done"]
    assert events_of(response, "compact_draft") == [
        {
            "summary": "We talked about rent.",
            "through_position": 3,
            "provider_id": "nebius",
            "model": NANO,
        }
    ]
    request = fake_llm.chat_requests[0]
    assert "tools" not in request and "tool_choice" not in request
    assert request["model"] == NANO
    transcript = request["messages"][1]["content"]
    assert "User: message 0" in transcript and "Assistant: message 3" in transcript
    assert "message 4" not in transcript
    assert stored(client, alice, conversation_id) == before
    [row] = usage_rows(test_database_url)
    assert (row.kind, row.model, row.prompt_tokens) == ("compact", NANO, 400)


def test_compact_with_only_recent_messages_has_nothing_to_do(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seeded(test_database_url, client, alice, messages=TEN[:6])

    response = compact(client, alice, conversation_id)

    assert response.status_code == 422
    assert "nothing to compact" in response.json()["error"]["message"]
    assert fake_llm.chat_requests == []


def test_compact_needs_a_conversation(client, alice, fake_llm):
    ready_user(client, alice)
    response = chat(client, alice, "/compact")
    assert response.status_code == 422
    assert fake_llm.chat_requests == []


def test_the_kept_messages_never_start_with_a_tool_result():
    from app.chat.compaction import plan_compaction
    from app.models import Message

    def m(position, role, **fields):
        return Message(position=position, role=role, content="x", compacted=False, **fields)

    messages = [
        m(0, "user"),
        m(1, "assistant", tool_calls=[{"id": "c", "function": {"name": "search_thoughts"}}]),
        m(2, "tool", tool_call_id="c"),
        m(3, "assistant"),
    ]
    plan = plan_compaction(messages, keep_recent=2)
    assert [message.position for message in plan.replaced] == [0, 1, 2]


# --- 8.5 accepting the summary ---


def test_an_accepted_summary_replaces_the_older_messages_for_the_model(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seeded(test_database_url, client, alice, last_prompt_tokens=90_000)

    response = accept(client, alice, conversation_id, "We agreed the rent is 900.", 3)

    assert response.status_code == 200, response.text
    body = response.json()
    assert [m["compacted"] for m in body["messages"]] == [True] * 4 + [False] * 7
    assert body["messages"][-1]["role"] == "summary"
    assert body["messages"][-1]["content"] == "We agreed the rent is 900."
    assert body["context"]["estimated"] is True
    assert body["context"]["tokens"] < 90_000

    fake_llm.queue(text_chunks("Ok") + [usage_chunk()])
    chat(client, alice, "next", conversation_id)
    sent = fake_llm.chat_requests[0]["messages"]
    assert sent[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert sent[1]["content"].endswith("We agreed the rent is 900.")
    assert [m["content"] for m in sent[2:]] == [*TEN[4:], "next"]


def test_the_transcript_still_returns_every_message(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    conversation_id = seeded(test_database_url, client, alice)
    accept(client, alice, conversation_id, "Summary.", 3)

    body = stored(client, alice, conversation_id)

    assert [m["content"] for m in body["messages"]] == [*TEN, "Summary."]


def test_a_second_compaction_includes_the_first_summary(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seeded(test_database_url, client, alice)
    accept(client, alice, conversation_id, "First summary.", 3)
    fake_llm.queue(
        text_chunks("Ok") + [usage_chunk()],
        text_chunks("Second summary.") + [usage_chunk()],
    )
    chat(client, alice, "more", conversation_id)

    draft = events_of(compact(client, alice, conversation_id), "compact_draft")[0]

    assert "First summary." in fake_llm.chat_requests[1]["messages"][1]["content"]
    body = accept(client, alice, conversation_id, draft["summary"], draft["through_position"]).json()
    summaries = [m for m in body["messages"] if m["role"] == "summary"]
    assert [(m["content"], m["compacted"]) for m in summaries] == [
        ("First summary.", True),
        ("Second summary.", False),
    ]
    live = [m["content"] for m in body["messages"] if not m["compacted"] and m["role"] != "summary"]
    assert len(live) == 6


def test_an_empty_or_stale_summary_is_refused(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    conversation_id = seeded(test_database_url, client, alice)
    accept(client, alice, conversation_id, "Summary.", 3)

    assert accept(client, alice, conversation_id, "  ", 5).status_code == 422
    assert accept(client, alice, conversation_id, "Again.", 2).status_code == 422
    assert len(stored(client, alice, conversation_id)["messages"]) == 11


def test_another_users_conversation_cannot_be_compacted(
    client, alice, bob, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seeded(test_database_url, client, alice)

    assert accept(client, bob, conversation_id, "Mine now.", 3).status_code == 404
    assert compact(client, bob, conversation_id).status_code == 404


# --- 8.6 a failed summary ---


def test_a_summary_call_refused_before_it_starts_changes_nothing(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seeded(test_database_url, client, alice)
    before = stored(client, alice, conversation_id)
    fake_llm.queue(api_error(500, "overloaded"))

    response = compact(client, alice, conversation_id)

    assert response.status_code == 502
    assert error_code(response) == "provider_unreachable"
    assert stored(client, alice, conversation_id) == before


def test_a_summary_call_failing_mid_stream_changes_nothing(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seeded(test_database_url, client, alice)
    before = stored(client, alice, conversation_id)
    fake_llm.queue(text_chunks("We talked") + [MidStreamFailure], text_chunks("Hi"))

    response = compact(client, alice, conversation_id)

    assert names(response) == ["error"]
    assert events_of(response, "error")[0]["error"]["code"] == "provider_unreachable"
    assert stored(client, alice, conversation_id) == before
    # The conversation is free again.
    assert chat(client, alice, "hello", conversation_id).status_code == 200


# --- 8.7 a larger model for /compact ---


def test_a_conversation_too_long_for_its_model_offers_larger_loadout_models(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice, entry(NO_TOOLS, default=True), entry(NANO), entry(BIG))
    conversation_id = seeded(test_database_url, client, alice, model=NO_TOOLS)

    response = compact(client, alice, conversation_id)

    assert response.status_code == 200
    assert names(response) == ["compact_models", "done"]
    choice = events_of(response, "compact_models")[0]
    assert choice["context_length"] == 8192
    assert choice["models"] == [
        {"provider_id": "nebius", "model": NANO, "context_length": 131072},
        {"provider_id": "nebius", "model": BIG, "context_length": 262144},
    ]
    assert fake_llm.chat_requests == []


def test_the_chosen_model_writes_the_summary_and_is_recorded(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice, entry(NO_TOOLS, default=True), entry(BIG, effort="low"))
    conversation_id = seeded(test_database_url, client, alice, model=NO_TOOLS)
    fake_llm.queue(text_chunks("Summary by the big model.") + [usage_chunk(700, 50)])

    response = compact(
        client, alice, conversation_id, compact_model={"provider_id": "nebius", "model": BIG}
    )

    draft = events_of(response, "compact_draft")[0]
    assert (draft["model"], draft["summary"]) == (BIG, "Summary by the big model.")
    assert fake_llm.chat_requests[0]["model"] == BIG
    assert fake_llm.chat_requests[0]["reasoning_effort"] == "low"
    [row] = usage_rows(test_database_url)
    assert (row.kind, row.model) == ("compact", BIG)
    # The conversation keeps its own model.
    assert stored(client, alice, conversation_id)["model"] == NO_TOOLS


def test_a_chosen_model_must_be_in_the_loadout(client, alice, fake_llm, test_database_url):
    ready_user(client, alice, entry(NO_TOOLS, default=True))
    conversation_id = seeded(test_database_url, client, alice, model=NO_TOOLS)

    response = compact(
        client, alice, conversation_id, compact_model={"provider_id": "nebius", "model": BIG}
    )

    assert response.status_code == 422
    assert fake_llm.chat_requests == []


# --- 8.8 the meter on a model switch ---


def test_a_switch_changes_the_limit_and_marks_the_figure_as_an_estimate(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice, entry(NANO, default=True), entry(BIG))
    conversation_id = seeded(test_database_url, client, alice, last_prompt_tokens=2_000)
    assert stored(client, alice, conversation_id)["context"] == {
        "tokens": 2_000,
        "estimated": False,
        "context_length": 131072,
    }

    body = client.patch(
        f"/api/conversations/{conversation_id}",
        headers=alice,
        json={"provider_id": "nebius", "model": BIG},
    ).json()

    assert body["context"]["context_length"] == 262144
    assert body["context"]["estimated"] is True
    fake_llm.queue(text_chunks("Hi") + [usage_chunk(2_100)])
    chat(client, alice, "next", conversation_id)
    assert stored(client, alice, conversation_id)["context"]["estimated"] is False


def test_a_switch_to_a_smaller_context_refuses_the_next_message(
    client, alice, fake_llm, test_database_url
):
    with_models(
        fake_llm, {"id": SMALL, "context_length": 20_000, "supported_features": ["tools"]}
    )
    ready_user(client, alice, entry(NANO, default=True), entry(SMALL))
    # About 14,000 tokens of text: fits Nano, not the small model with room for a reply.
    long = ("word " * 10_000,) * 2
    conversation_id = seeded(test_database_url, client, alice, messages=long)

    body = client.patch(
        f"/api/conversations/{conversation_id}",
        headers=alice,
        json={"provider_id": "nebius", "model": SMALL},
    ).json()
    response = chat(client, alice, "next", conversation_id)

    assert body["context"]["context_length"] == 20_000
    assert body["context"]["tokens"] + 8192 > 20_000
    assert response.status_code == 409
    assert error_code(response) == "context_full"
    assert fake_llm.chat_requests == []

    fake_llm.queue(text_chunks("Back on Nano") + [usage_chunk()])
    back = chat(client, alice, "next", conversation_id, provider_id="nebius", model=NANO)
    assert back.status_code == 200
