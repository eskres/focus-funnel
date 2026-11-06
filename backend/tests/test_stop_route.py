"""POST /api/chat/{conversation_id}/stop (stop-and-spend-cap task 3.4,
design decision 1): it answers at once, for the owner only, and the stream's
terminal event says how the answer ended."""

import asyncio
import uuid

from tests.chat_helpers import Hold, text_chunks, turns_settled, usage_chunk
from tests.sse_helpers import parse_events
from tests.stop_helpers import STOPPED, adding, stopped_messages, the_turn
from tests.test_background_turns import claim_of, messages_of, stream_path, watch_chat


def stop_path(conversation_id: str) -> str:
    return f"/api/chat/{conversation_id}/stop"


async def held(api, message: str = "hello", conversation_id: str | None = None):
    """A turn whose stream waits after "Half "; returns (watcher, turn, id, hold)."""
    hold = Hold()
    api.fake.queue(text_chunks("Half ")[:-1] + [hold] + text_chunks("an answer.") + [usage_chunk()])
    watcher = await watch_chat(api, message, conversation_id)
    await asyncio.wait_for(hold.reached.wait(), 5)
    turn = the_turn()
    return watcher, turn, str(turn.conversation_id), hold


async def test_the_owners_stop_answers_at_once_and_the_next_message_is_answered(
    async_api, block_commit
):
    api = async_api
    await api.ready()
    blocked = block_commit(adding(role="assistant", status="stopped"))
    watcher, turn, conversation_id, _ = await held(api)

    response = await asyncio.wait_for(
        api.http.post(stop_path(conversation_id), headers=api.headers), 2
    )

    assert response.status_code == 204
    assert response.content == b""
    # Answered while the turn is still storing its stopped answer.
    await blocked.reached()
    assert not turn.ended
    blocked.release.set()
    left = await asyncio.wait_for(watcher, 5)
    assert left.events[-1] == STOPPED
    # The terminal event goes out once the claim is free: a message sent
    # right after it is answered, not refused as busy.
    api.fake.queue(text_chunks("Sure.") + [usage_chunk()])
    again = await api.chat("go on", conversation_id)
    assert again.status_code == 200, again.text
    assert parse_events(again.text)[-1] == ("done", {})
    messages = await messages_of(api, conversation_id)
    assert [(m.role, m.status, m.content) for m in messages] == [
        ("user", "complete", "hello"),
        ("assistant", "stopped", "Half "),
        ("user", "complete", "go on"),
        ("assistant", "complete", "Sure."),
    ]


async def test_two_stops_together_cancel_the_task_once(async_api, cancel_spy):
    api = async_api
    await api.ready()
    watcher, turn, conversation_id, _ = await held(api)

    first, second = await asyncio.gather(
        api.http.post(stop_path(conversation_id), headers=api.headers),
        api.http.post(stop_path(conversation_id), headers=api.headers),
    )
    left = await asyncio.wait_for(watcher, 5)
    await turns_settled()

    assert first.status_code == second.status_code == 204
    assert cancel_spy(turn) == 1
    assert left.events[-1] == STOPPED
    assert len(await stopped_messages(api, conversation_id)) == 1


async def test_a_stop_from_a_client_that_follows_the_turn_ends_both_streams(async_api):
    api = async_api
    await api.ready()
    watcher, turn, conversation_id, _ = await held(api)
    following = asyncio.ensure_future(
        api.http.get(stream_path(conversation_id), headers=api.headers)
    )
    await asyncio.sleep(0.05)

    response = await api.http.post(stop_path(conversation_id), headers=api.headers)
    left = await asyncio.wait_for(watcher, 5)
    followed = await asyncio.wait_for(following, 5)

    assert response.status_code == 204
    assert left.events[-1] == STOPPED
    assert parse_events(followed.text)[-1] == STOPPED
    assert [name for name, _ in parse_events(followed.text)] == ["conversation", "delta", "error"]


async def test_a_stop_with_nothing_running_answers_204_and_changes_nothing(async_api):
    api = async_api
    await api.ready()
    api.fake.queue(text_chunks("Hi!") + [usage_chunk()])
    conversation_id = parse_events((await api.chat("hello")).text)[0][1]["id"]
    before = [(m.position, m.role, m.status, m.content) for m in await messages_of(api, conversation_id)]

    response = await api.http.post(stop_path(conversation_id), headers=api.headers)

    assert response.status_code == 204
    after = [(m.position, m.role, m.status, m.content) for m in await messages_of(api, conversation_id)]
    assert after == before == [(0, "user", "complete", "hello"), (1, "assistant", "complete", "Hi!")]
    assert await claim_of(api, conversation_id) is None


async def test_another_users_stop_and_an_unknown_id_are_both_not_found(async_api, make_token):
    api = async_api
    await api.ready()
    watcher, turn, conversation_id, hold = await held(api)
    bob = {"Authorization": f"Bearer {make_token(sub='user|bob')}"}

    foreign = await api.http.post(stop_path(conversation_id), headers=bob)
    unknown = await api.http.post(stop_path(str(uuid.uuid4())), headers=api.headers)
    assert not turn.control.stop_requested
    hold.release.set()
    left = await asyncio.wait_for(watcher, 5)

    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json() == {
        "error": {"code": "not_found", "message": "Not found."}
    }
    assert left.events[-1] == ("done", {})
    messages = await messages_of(api, conversation_id)
    assert (messages[-1].status, messages[-1].content) == ("complete", "Half an answer.")
