import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from openai import AsyncOpenAI
from sqlalchemy import select, update

import app.chat.turn as turn_module
from app.chat.prompt import system_prompt, build_context
from app.chat.tools import NO_MATCH, SearchToolResult
from app.errors import ErrorCode
from app.models import Conversation, Message
from tests.chat_helpers import (
    BIG,
    NANO,
    FakeLLM,
    MidStreamFailure,
    api_error,
    chat,
    entry,
    error_code,
    finish_chunk,
    ready_user,
    reasoning_chunk,
    run_db,
    save_models,
    text_chunks,
    tool_call_chunks,
    usage_chunk,
)
from tests.sse_helpers import parse_events


def names(response) -> list[str]:
    return [name for name, _ in parse_events(response.text)]


def events_of(response, name: str) -> list[dict]:
    return [data for event, data in parse_events(response.text) if event == name]


def text_of(response) -> str:
    return "".join(data["text"] for data in events_of(response, "delta"))


def conversation_id_of(response) -> str:
    return events_of(response, "conversation")[0]["id"]


def stored(client, headers, conversation_id) -> dict:
    return client.get(f"/api/conversations/{conversation_id}", headers=headers).json()


PROPOSAL = {"title": "Oat milk", "summary": "Buy oat milk tomorrow.", "tags": ["shopping"]}
# The flat call above, as the stored part it becomes.
PART = {**PROPOSAL, "category": None, "thought_id": None}


def proposed_parts(response) -> list[list[dict]]:
    return [event["parts"] for event in events_of(response, "proposal")]


# --- 6.2 the context ---


def message(position, role, content=None, **fields) -> Message:
    return Message(position=position, role=role, content=content, compacted=False, **fields)


def test_the_context_is_the_prompt_then_the_messages():
    context = build_context([message(0, "user", "hi"), message(1, "assistant", "Hello")])
    assert context == [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hello"},
    ]


def test_compacted_messages_are_left_out_and_the_summary_comes_first():
    old = message(0, "user", "old")
    old.compacted = True
    context = build_context(
        [old, message(1, "summary", "We talked about rent."), message(2, "user", "new")]
    )
    assert [m["content"] for m in context[1:]] == [
        "Summary of the earlier conversation:\nWe talked about rent.",
        "new",
    ]
    assert context[1]["role"] == "system"


def test_tool_messages_are_included_in_order():
    calls = [{"id": "c1", "type": "function", "function": {"name": "search_thoughts", "arguments": "{}"}}]
    context = build_context(
        [
            message(0, "user", "what about milk?"),
            message(1, "assistant", None, tool_calls=calls),
            message(2, "tool", "not available", tool_call_id="c1"),
            message(3, "assistant", "Search is not available yet."),
        ]
    )
    assert [m["role"] for m in context] == ["system", "user", "assistant", "tool", "assistant"]
    assert context[2]["tool_calls"] == calls
    assert context[3]["tool_call_id"] == "c1"


def test_a_stored_command_reaches_the_model_without_the_command():
    context = build_context([message(0, "user", "/push buy oat milk")])
    assert context[1]["content"] == "buy oat milk"


def test_an_empty_failed_answer_is_left_out():
    context = build_context([message(0, "user", "hi"), message(1, "assistant", None, status="failed")])
    assert [m["role"] for m in context] == ["system", "user"]


# --- 6.3 the fake delivers each stream shape as a provider does ---


async def read_stream(fake: FakeLLM):
    client = AsyncOpenAI(api_key="x", base_url="https://p.test/v1/", http_client=fake.http_client())
    stream = await client.chat.completions.create(model=NANO, messages=[], stream=True)
    return [chunk async for chunk in stream]


async def test_the_fake_streams_text_deltas_and_a_final_usage_chunk():
    chunks = await read_stream(FakeLLM([text_chunks("Hel", "lo") + [usage_chunk(45, 7)]]))
    texts = [c.choices[0].delta.content for c in chunks if c.choices and c.choices[0].delta.content]
    assert texts == ["Hel", "lo"]
    assert chunks[-1].choices == [] and chunks[-1].usage.prompt_tokens == 45


async def test_the_fake_streams_a_tool_call_in_pieces():
    chunks = await read_stream(FakeLLM([tool_call_chunks("search_thoughts", '{"query": "milk"}')]))
    pieces = [c.choices[0].delta.tool_calls[0] for c in chunks]
    assert pieces[0].function.name == "search_thoughts"
    assert "".join(p.function.arguments or "" for p in pieces) == '{"query": "milk"}'


async def test_the_fake_can_break_mid_stream():
    import openai

    with pytest.raises(openai.APIConnectionError):
        await read_stream(FakeLLM([text_chunks("Half")[:2] + [MidStreamFailure]]))


# --- 6.4 the streamed call ---


def test_text_is_forwarded_in_order(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(
        [reasoning_chunk("thinking...")] + text_chunks("Hel", "lo", " there") + [usage_chunk()]
    )

    response = chat(client, alice, "hello")

    assert response.status_code == 200
    assert [d["text"] for d in events_of(response, "delta")] == ["Hel", "lo", " there"]
    assert "thinking" not in response.text


def test_the_request_asks_for_usage_and_sends_no_effort_when_none_is_set(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Hi"))

    chat(client, alice, "hello")

    request = fake_llm.chat_requests[0]
    assert request["stream"] is True
    assert request["stream_options"] == {"include_usage": True}
    assert request["model"] == NANO
    assert request["temperature"] == 0.3
    assert "reasoning_effort" not in request


def test_the_conversations_effort_is_sent(client, alice, fake_llm):
    ready_user(client, alice, entry(NANO, effort="low", default=True))
    fake_llm.queue(text_chunks("Hi"))

    chat(client, alice, "hello")

    assert fake_llm.chat_requests[0]["reasoning_effort"] == "low"


def test_split_tool_call_arguments_are_joined(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(
        tool_call_chunks("search_thoughts", '{"query": "oat milk"}') + [finish_chunk("tool_calls")],
        text_chunks("Nothing filed about that."),
    )

    response = chat(client, alice, "what did I say about oat milk?")

    tool_end = [e for e in events_of(response, "tool") if e["phase"] == "end"][0]
    assert tool_end["summary"] == "Searched your thoughts for “oat milk”"
    body = stored(client, alice, conversation_id_of(response))
    assistant = body["messages"][1]
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"query": "oat milk"}


# --- 6.5 the tool loop ---


def test_a_tool_result_reaches_the_next_call(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(
        tool_call_chunks("search_thoughts", '{"query": "milk"}', call_id="call_abc"),
        text_chunks("Nothing about milk, sorry."),
    )

    response = chat(client, alice, "what about milk?")

    second = fake_llm.chat_requests[1]["messages"]
    assert second[-2]["role"] == "assistant"
    assert second[-2]["tool_calls"][0]["id"] == "call_abc"
    assert second[-1]["role"] == "tool"
    assert second[-1]["tool_call_id"] == "call_abc"
    assert second[-1]["content"] == NO_MATCH
    assert names(response) == ["conversation", "tool", "tool", "delta", "done"]


def test_the_loop_stops_at_the_round_limit_and_keeps_the_text(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(
        text_chunks("Let me look. ")[:-1] + tool_call_chunks("search_thoughts", '{"query": "a"}'),
        tool_call_chunks("search_thoughts", '{"query": "b"}'),
        tool_call_chunks("search_thoughts", '{"query": "c"}'),
    )

    response = chat(client, alice, "find everything")

    assert len(fake_llm.chat_requests) == 3
    assert names(response)[-1] == "error"
    assert events_of(response, "error")[0]["error"]["code"] == ErrorCode.TOOL_LOOP_LIMIT
    assert "done" not in names(response)
    body = stored(client, alice, conversation_id_of(response))
    assert body["messages"][1]["content"] == "Let me look. "
    assert body["messages"][-2]["error_code"] == "tool_loop_limit"


def test_malformed_arguments_go_back_as_a_tool_error_for_a_retry(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(
        tool_call_chunks("propose_thought", '{"title": "Oat'),
        tool_call_chunks("propose_thought", json.dumps(PROPOSAL)),
        text_chunks("Here is a proposal."),
    )

    response = chat(client, alice, "buy oat milk tomorrow")

    retry = fake_llm.chat_requests[1]["messages"][-1]
    assert retry["role"] == "tool" and retry["content"].startswith("Error:")
    assert proposed_parts(response) == [[PART]]
    assert names(response)[-1] == "done"


# --- 6.6 the chat endpoint and its events ---


def test_a_new_conversation_starts_with_its_conversation_event(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Hi!"))

    response = chat(client, alice, "buy oat milk tomorrow")

    assert response.headers["content-type"].startswith("text/event-stream")
    assert names(response) == ["conversation", "delta", "done"]
    first = events_of(response, "conversation")[0]
    assert first["title"] == "buy oat milk tomorrow"
    uuid.UUID(first["id"])


def test_a_later_message_has_no_conversation_event_and_joins_the_conversation(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Hi!"), text_chunks("Sure."))
    conversation_id = conversation_id_of(chat(client, alice, "hello"))

    response = chat(client, alice, "and again", conversation_id)

    assert names(response) == ["delta", "done"]
    body = stored(client, alice, conversation_id)
    assert [(m["role"], m["content"]) for m in body["messages"]] == [
        ("user", "hello"),
        ("assistant", "Hi!"),
        ("user", "and again"),
        ("assistant", "Sure."),
    ]
    # The model saw the earlier turn.
    assert [m["content"] for m in fake_llm.chat_requests[1]["messages"][1:]] == [
        "hello",
        "Hi!",
        "and again",
    ]


def test_the_users_message_is_stored_before_the_model_is_called_and_kept_after_a_failure(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    seen = {}

    def respond(request):
        async def count(session):
            return (await session.execute(select(Message.content))).scalars().all()

        # The fake answers on the app's event loop, so read from another thread.
        with ThreadPoolExecutor(1) as pool:
            seen["stored"] = pool.submit(run_db, test_database_url, count).result()
        return api_error(500)

    fake_llm.queue(respond, respond, respond)

    response = chat(client, alice, "hello")

    assert seen["stored"] == ["hello"]
    assert response.status_code == 502
    assert error_code(response) == ErrorCode.PROVIDER_UNREACHABLE
    conversation_id = response.headers["x-conversation-id"]
    assert [m["content"] for m in stored(client, alice, conversation_id)["messages"]] == ["hello"]


def test_an_error_mid_stream_is_an_event_with_the_same_code(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Half an ans")[:-1] + [MidStreamFailure])

    response = chat(client, alice, "hello")

    assert response.status_code == 200
    assert names(response) == ["conversation", "delta", "error"]
    assert events_of(response, "error")[0]["error"]["code"] == ErrorCode.PROVIDER_UNREACHABLE
    body = stored(client, alice, conversation_id_of(response))
    assert body["messages"][-1]["content"] == "Half an ans"
    assert body["messages"][-1]["status"] == "failed"


def test_resending_an_unanswered_message_does_not_store_it_twice(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(api_error(500), api_error(500), api_error(500), text_chunks("Hi!"))
    conversation_id = chat(client, alice, "hello").headers["x-conversation-id"]

    response = chat(client, alice, "hello", conversation_id)

    assert names(response) == ["delta", "done"]
    body = stored(client, alice, conversation_id)
    assert [m["content"] for m in body["messages"]] == ["hello", "Hi!"]


def test_sending_in_an_archived_conversation_restores_it(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Hi!"), text_chunks("Back."))
    conversation_id = conversation_id_of(chat(client, alice, "hello"))
    client.patch(f"/api/conversations/{conversation_id}", headers=alice, json={"archived": True})

    chat(client, alice, "again", conversation_id)

    lists = client.get("/api/conversations", headers=alice).json()
    assert [c["id"] for c in lists["conversations"]] == [conversation_id]


def test_another_users_conversation_is_not_found(client, alice, bob, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Hi!"))
    conversation_id = conversation_id_of(chat(client, alice, "hello"))
    ready_user(client, bob)

    response = chat(client, bob, "hi", conversation_id)

    assert response.status_code == 404
    assert len(fake_llm.chat_requests) == 1


@pytest.mark.parametrize("message", ["/delete", "/compact"])
def test_commands_handled_elsewhere_do_not_reach_the_model(client, alice, fake_llm, message):
    ready_user(client, alice)
    response = chat(client, alice, message)
    assert response.status_code == 422
    assert fake_llm.chat_requests == []


# --- 6.7 forced tools ---


def test_push_forces_the_proposal_tool(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(
        tool_call_chunks("propose_thought", json.dumps(PROPOSAL)) + [finish_chunk("stop")],
        text_chunks("Proposed."),
    )

    response = chat(client, alice, "/push buy oat milk")

    first, second = fake_llm.chat_requests
    assert first["tool_choice"] == {"type": "function", "function": {"name": "propose_thought"}}
    assert first["messages"][-1] == {"role": "user", "content": "buy oat milk"}
    assert "tool_choice" not in second
    # A forced call ends with finish_reason stop, and its tool call still runs.
    assert proposed_parts(response) == [[PART]]


def test_pull_forces_the_search_tool(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(
        tool_call_chunks("search_thoughts", '{"query": "rent"}'), text_chunks("Not available yet.")
    )

    chat(client, alice, "/pull what did I say about rent?")

    request = fake_llm.chat_requests[0]
    assert request["tool_choice"] == {"type": "function", "function": {"name": "search_thoughts"}}
    assert request["messages"][-1]["content"] == "what did I say about rent?"


def test_explore_forces_no_tool(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Let's think."))

    chat(client, alice, "/explore how should I organise my notes")

    request = fake_llm.chat_requests[0]
    assert "tool_choice" not in request
    assert len(request["tools"]) == 2
    assert request["messages"][-1]["content"] == "how should I organise my notes"


# --- 6.8 the reply length limit ---


def test_a_reply_cut_by_the_length_limit_keeps_its_text(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(text_chunks("A long answer that", finish_reason="length"))

    response = chat(client, alice, "tell me everything")

    assert names(response) == ["conversation", "delta", "error"]
    error = events_of(response, "error")[0]["error"]
    assert error["code"] == ErrorCode.OUTPUT_LIMIT_REACHED
    last = stored(client, alice, conversation_id_of(response))["messages"][-1]
    assert (last["content"], last["status"]) == ("A long answer that", "cut")


def test_an_empty_reply_is_reported_as_out_of_room(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue([reasoning_chunk("hmm")] + text_chunks(finish_reason="length"))

    response = chat(client, alice, "hello")

    error = events_of(response, "error")[0]["error"]
    assert error["code"] == ErrorCode.OUTPUT_LIMIT_REACHED
    assert "thinking" in error["message"]
    assert "done" not in names(response)


def test_the_servers_limit_is_sent_on_every_call(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(tool_call_chunks("search_thoughts", '{"query": "x"}'), text_chunks("ok"))

    chat(client, alice, "find x")

    assert [r["max_tokens"] for r in fake_llm.chat_requests] == [8192, 8192]


# --- 6.9 model checks and no fallback (and 4.5) ---


def test_no_model_set_is_refused_before_any_network_call(client, alice, fake_llm):
    response = chat(client, alice, "hello")

    assert response.status_code == 409
    assert error_code(response) == ErrorCode.MODEL_NOT_SET
    assert fake_llm.chat_requests == []
    assert fake_llm.requests == []


def test_removing_the_default_returns_to_model_not_set(client, alice, fake_llm):
    ready_user(client, alice, entry(NANO, default=True), entry(BIG))
    save_models(client, alice, entry(BIG))

    response = chat(client, alice, "hello")

    assert error_code(response) == ErrorCode.MODEL_NOT_SET
    assert fake_llm.chat_requests == []


def test_a_withdrawn_model_is_unavailable_and_no_other_model_is_called(client, alice, fake_llm):
    ready_user(client, alice, entry(NANO, default=True), entry(BIG))
    fake_llm.queue(api_error(404, f"The model {NANO} does not exist"))

    response = chat(client, alice, "hello")

    assert response.status_code == 409
    assert error_code(response) == ErrorCode.MODEL_UNAVAILABLE
    assert NANO in response.json()["error"]["message"]
    assert [r["model"] for r in fake_llm.chat_requests] == [NANO]


def test_an_unreachable_provider(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(*[lambda request: (_ for _ in ()).throw(httpx2.ConnectError("down"))] * 3)

    response = chat(client, alice, "hello")

    assert error_code(response) == ErrorCode.PROVIDER_UNREACHABLE
    assert {r["model"] for r in fake_llm.chat_requests} == {NANO}


def test_a_rate_limit_after_retries(client, alice, fake_llm, monkeypatch):
    monkeypatch.setattr("openai._base_client.AsyncAPIClient._calculate_retry_timeout", lambda *a, **k: 0)
    ready_user(client, alice)
    fake_llm.queue(api_error(429), api_error(429), api_error(429))

    response = chat(client, alice, "hello")

    assert response.status_code == 429
    assert error_code(response) == ErrorCode.PROVIDER_RATE_LIMITED
    # The first call and two retries, all to the same model.
    assert [r["model"] for r in fake_llm.chat_requests] == [NANO, NANO, NANO]


def test_another_client_error_is_a_refused_request(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(api_error(400, "messages must not be empty"))

    response = chat(client, alice, "hello")

    assert error_code(response) == ErrorCode.PROVIDER_REQUEST_REFUSED
    assert "messages must not be empty" in response.json()["error"]["message"]


def test_a_model_that_rejects_tools_is_unsupported(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(api_error(400, "tools are not supported for this model"))

    response = chat(client, alice, "hello")

    assert error_code(response) == ErrorCode.MODEL_UNSUPPORTED
    assert "tool calling" in response.json()["error"]["message"]


# --- 6.10 one turn at a time ---


def set_claim(url, conversation_id, started):
    async def work(session):
        await session.execute(
            update(Conversation)
            .where(Conversation.id == uuid.UUID(conversation_id))
            .values(turn_started_at=started)
        )
        await session.commit()

    run_db(url, work)


def test_a_second_turn_while_one_runs_is_busy(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Hi!"))
    conversation_id = conversation_id_of(chat(client, alice, "hello"))
    set_claim(test_database_url, conversation_id, datetime.now(UTC))

    response = chat(client, alice, "again", conversation_id)

    assert response.status_code == 409
    assert error_code(response) == ErrorCode.CONVERSATION_BUSY
    assert len(fake_llm.chat_requests) == 1
    assert len(stored(client, alice, conversation_id)["messages"]) == 2


def test_a_claim_from_a_stopped_server_expires(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Hi!"), text_chunks("Back."))
    conversation_id = conversation_id_of(chat(client, alice, "hello"))
    set_claim(test_database_url, conversation_id, datetime.now(UTC) - timedelta(hours=1))

    assert chat(client, alice, "again", conversation_id).status_code == 200


def test_the_claim_is_released_after_a_failure_and_after_success(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(api_error(400, "bad"))
    conversation_id = chat(client, alice, "hello").headers["x-conversation-id"]
    fake_llm.queue(text_chunks("Half")[:-1] + [MidStreamFailure])
    assert names(chat(client, alice, "hello", conversation_id))[-1] == "error"
    fake_llm.queue(text_chunks("Hi!"))
    assert names(chat(client, alice, "hello", conversation_id)) == ["delta", "done"]
    fake_llm.queue(text_chunks("Again."))
    assert names(chat(client, alice, "more", conversation_id)) == ["delta", "done"]


# --- 6.11 conversations are independent ---


async def test_two_conversations_on_two_models_run_at_the_same_time(
    test_database_url, jwks_cache, settings_env, make_token
):
    import asyncio

    import httpx

    from app.auth import get_jwks_cache
    from app.main import app
    from app.providers import get_provider_http_client
    from tests.chat_helpers import PROVIDERS_FIXTURE

    settings_env.setenv("PROVIDERS_CONFIG_PATH", str(PROVIDERS_FIXTURE))
    headers = {"Authorization": f"Bearer {make_token(sub='user|alice')}"}
    fake = FakeLLM()
    app.dependency_overrides[get_jwks_cache] = lambda: jwks_cache
    app.dependency_overrides[get_provider_http_client] = fake.http_client
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as api:
            await api.put("/api/providers/nebius/key", headers=headers, json={"key": "nb-key-1111"})
            await api.put(
                "/api/settings/models",
                headers=headers,
                json={"models": [entry(NANO, default=True), entry(BIG)], "temperature": None},
            )
            fake.queue(text_chunks("A1"), text_chunks("B1"))
            first = parse_events((await api.post("/api/chat", headers=headers, json={"message": "about apples"})).text)
            second = parse_events(
                (
                    await api.post(
                        "/api/chat",
                        headers=headers,
                        json={"message": "about bikes", "provider_id": "nebius", "model": BIG},
                    )
                ).text
            )
            a_id, b_id = first[0][1]["id"], second[0][1]["id"]

            # Conversation A's answer waits until B's call has been made, so if
            # A blocked B this would time out.
            b_called = asyncio.Event()
            a_reply = text_chunks("A2")
            a_reply.insert(1, b_called)

            def b_reply(request):
                b_called.set()
                return httpx2.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=b"".join(
                        f"data: {json.dumps(c)}\n\n".encode() for c in text_chunks("B2")
                    )
                    + b"data: [DONE]\n\n",
                )

            fake.queue(a_reply, b_reply)
            a_response, b_response = await asyncio.gather(
                api.post("/api/chat", headers=headers, json={"message": "more apples", "conversation_id": a_id}),
                api.post("/api/chat", headers=headers, json={"message": "more bikes", "conversation_id": b_id}),
            )
    finally:
        app.dependency_overrides.clear()

    assert [name for name, _ in parse_events(a_response.text)] == ["delta", "done"]
    assert [name for name, _ in parse_events(b_response.text)] == ["delta", "done"]
    by_model = {}
    for request in fake.chat_requests[2:]:
        by_model[request["model"]] = [m["content"] for m in request["messages"][1:]]
    assert by_model[NANO] == ["about apples", "A1", "more apples"]
    assert by_model[BIG] == ["about bikes", "B1", "more bikes"]


# --- 6.12 a conversation keeps its model ---


def test_a_model_removed_from_the_loadout_keeps_answering(client, alice, fake_llm):
    ready_user(client, alice, entry(NANO, default=True), entry(BIG))
    fake_llm.queue(text_chunks("Hi!"))
    conversation_id = conversation_id_of(chat(client, alice, "hello", provider_id="nebius", model=BIG))
    save_models(client, alice, entry(NANO, default=True))

    fake_llm.queue(text_chunks("Still me."))
    response = chat(client, alice, "again", conversation_id)

    assert names(response) == ["delta", "done"]
    assert fake_llm.chat_requests[-1]["model"] == BIG


def test_after_a_withdrawn_model_a_switch_carries_on_with_the_history(client, alice, fake_llm):
    ready_user(client, alice, entry(NANO, default=True), entry(BIG))
    fake_llm.queue(text_chunks("Hi!"), api_error(404, f"model {NANO} not found"))
    conversation_id = conversation_id_of(chat(client, alice, "hello"))
    assert error_code(chat(client, alice, "again", conversation_id)) == ErrorCode.MODEL_UNAVAILABLE

    fake_llm.queue(text_chunks("Big here."))
    response = chat(client, alice, "again", conversation_id, provider_id="nebius", model=BIG)

    assert names(response) == ["delta", "done"]
    last = fake_llm.chat_requests[-1]
    assert last["model"] == BIG
    assert [m["content"] for m in last["messages"][1:]] == ["hello", "Hi!", "again"]
    assert stored(client, alice, conversation_id)["model"] == BIG


# --- 5.3 a conversation without a model takes the default at its next message ---


def test_a_conversation_with_no_model_takes_the_default_at_its_next_message(
    client, alice, fake_llm
):
    first = chat(client, alice, "hello")
    assert error_code(first) == ErrorCode.MODEL_NOT_SET
    conversation_id = first.headers["x-conversation-id"]
    assert stored(client, alice, conversation_id)["model"] is None

    ready_user(client, alice, entry(NANO, effort="low", default=True))
    fake_llm.queue(text_chunks("Hi!"))
    response = chat(client, alice, "hello", conversation_id)

    assert names(response) == ["delta", "done"]
    body = stored(client, alice, conversation_id)
    assert (body["model"], body["reasoning_effort"]) == (NANO, "low")
    assert [m["content"] for m in body["messages"]] == ["hello", "Hi!"]


def test_a_new_conversation_takes_its_title_from_the_first_message(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Noted."))
    conversation_id = conversation_id_of(chat(client, alice, "buy oat milk tomorrow"))
    assert stored(client, alice, conversation_id)["title"] == "buy oat milk tomorrow"


# --- 7.1 the proposal tool ---


def test_a_valid_proposal_is_emitted_and_held_and_nothing_is_saved(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    fake_llm.queue(
        tool_call_chunks("propose_thought", json.dumps(PROPOSAL)), text_chunks("Want to keep it?")
    )

    response = chat(client, alice, "I need to buy oat milk tomorrow")

    assert names(response) == ["conversation", "tool", "proposal", "tool", "delta", "done"]
    [event] = events_of(response, "proposal")
    assert event["parts"] == [PART]
    assert event["position"] == 2
    body = stored(client, alice, conversation_id_of(response))
    assert body["held_proposal_id"] == event["id"]
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "tool", "assistant"]
    assert body["messages"][2]["details"] == {"proposal_id": event["id"]}
    assert event["replaces"] is None
    assert body["proposals"] == [{k: v for k, v in event.items() if k != "replaces"}]


@pytest.mark.parametrize(
    "arguments",
    [
        {"title": "", "summary": "x", "tags": []},
        {"title": "x", "tags": []},
        {"title": "x", "summary": "y", "tags": "shopping"},
        {"thoughts": []},
        {"thoughts": [{"title": f"t{n}", "summary": "s", "tags": []} for n in range(9)]},
        {"thoughts": [{"title": "a", "summary": "s", "tags": []}, {"summary": "s", "tags": []}]},
        {"summary": "no title", "tags": []},
    ],
)
def test_invalid_proposal_arguments_are_refused(client, alice, fake_llm, arguments):
    ready_user(client, alice)
    fake_llm.queue(
        tool_call_chunks("propose_thought", json.dumps(arguments)), text_chunks("Sorry.")
    )

    response = chat(client, alice, "keep this")

    assert events_of(response, "proposal") == []
    assert fake_llm.chat_requests[1]["messages"][-1]["content"].startswith("Error:")
    body = stored(client, alice, conversation_id_of(response))
    assert body["held_proposal_id"] is None
    assert body["proposals"] == []


def test_a_list_of_three_gives_three_parts(client, alice, fake_llm):
    ready_user(client, alice)
    thoughts = [
        {"title": "Oat milk", "summary": "Buy oat milk.", "tags": ["groceries"], "category": "task"},
        {"title": "Dentist", "summary": "Book the dentist.", "tags": ["health"], "category": "Task"},
        {"title": "Map podcast", "summary": "A podcast about maps.", "tags": [], "category": "idea"},
    ]
    fake_llm.queue(
        tool_call_chunks("propose_thought", json.dumps({"thoughts": thoughts})), text_chunks("Three.")
    )

    response = chat(client, alice, "/push buy oat milk, book the dentist, and idea: a podcast about maps")

    [parts] = proposed_parts(response)
    assert [(p["title"], p["category"], p["thought_id"]) for p in parts] == [
        ("Oat milk", "task", None),
        ("Dentist", "task", None),
        ("Map podcast", "idea", None),
    ]


def test_an_unknown_category_becomes_none(client, alice, fake_llm):
    ready_user(client, alice)
    thought = {"title": "Eggs", "summary": "Buy eggs.", "tags": [], "category": "shopping"}
    fake_llm.queue(
        tool_call_chunks("propose_thought", json.dumps({"thoughts": [thought]})), text_chunks("Ok.")
    )

    response = chat(client, alice, "/push buy eggs")

    assert proposed_parts(response)[0][0]["category"] is None


def propose_schema(request: dict) -> dict:
    [tool] = [t for t in request["tools"] if t["function"]["name"] == "propose_thought"]
    return tool["function"]["parameters"]["properties"]["thoughts"]["items"]["properties"]


def test_the_tool_lists_the_users_own_categories_only(client, alice, bob, fake_llm):
    ready_user(client, alice)
    ready_user(client, bob)
    client.post("/api/settings/categories", headers=alice, json={"name": "Recipe"})
    fake_llm.queue(text_chunks("Hi."), text_chunks("Hi."))

    chat(client, alice, "hello")
    chat(client, bob, "hello")

    alice_request, bob_request = fake_llm.chat_requests
    fixed = ["task", "idea", "decision", "note", "reference"]
    assert propose_schema(alice_request)["category"]["enum"] == [*fixed, "recipe"]
    assert propose_schema(bob_request)["category"]["enum"] == fixed
    # No thoughts, so no known tags: the plain description.
    assert propose_schema(alice_request)["tags"]["description"] == "A few short tags."


# --- the search tool (thought-storage 6.2 has the tests with stored thoughts) ---


def test_the_search_result_reaches_the_model(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(tool_call_chunks("search_thoughts", '{"query": "rent"}'), text_chunks("ok"))

    chat(client, alice, "what did I say about rent?")

    assert fake_llm.chat_requests[1]["messages"][-1]["content"] == NO_MATCH
    assert fake_llm.embed_requests == []


def test_the_search_function_can_be_replaced(client, alice, fake_llm, monkeypatch):
    async def found(session, user, arguments, **options):
        return SearchToolResult(text=f"1 thought about {arguments.query}: pay rent on the 1st")

    monkeypatch.setattr(turn_module, "search_tool_result", found)
    ready_user(client, alice)
    fake_llm.queue(tool_call_chunks("search_thoughts", '{"query": "rent"}'), text_chunks("ok"))

    chat(client, alice, "what did I say about rent?")

    assert fake_llm.chat_requests[1]["messages"][-1]["content"] == (
        "1 thought about rent: pay rent on the 1st"
    )
