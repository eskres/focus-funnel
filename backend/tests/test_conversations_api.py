import uuid

from sqlalchemy import func, select

from app.chat.conversations import new_conversation, title_from
from app.errors import ErrorCode
from app.models import ChatModel, Conversation, Message, UsageEvent, User
from tests.chat_helpers import (
    BIG,
    NANO,
    entry,
    error_code,
    run_db,
    save_key,
    save_models,
    seed_conversation,
)

# --- 5.1 list, read, and change ---


def test_the_main_list_is_newest_activity_first(client, alice, test_database_url):
    old = seed_conversation(test_database_url, client, alice, title="old", minutes_ago=30)
    new = seed_conversation(test_database_url, client, alice, title="new", minutes_ago=1)
    mid = seed_conversation(test_database_url, client, alice, title="mid", minutes_ago=10)

    body = client.get("/api/conversations", headers=alice).json()

    assert [c["id"] for c in body["conversations"]] == [new, mid, old]
    assert body["archived"] == []


def test_an_empty_list(client, alice):
    assert client.get("/api/conversations", headers=alice).json() == {
        "conversations": [],
        "archived": [],
    }


def test_reading_a_conversation_returns_every_message_in_order(client, alice, test_database_url):
    conversation_id = seed_conversation(
        test_database_url, client, alice, messages=("one", "two", "three")
    )

    async def compact_first(session):
        message = (
            await session.execute(select(Message).where(Message.position == 0))
        ).scalar_one()
        message.compacted = True
        await session.commit()

    run_db(test_database_url, compact_first)

    body = client.get(f"/api/conversations/{conversation_id}", headers=alice).json()
    assert [m["content"] for m in body["messages"]] == ["one", "two", "three"]
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"]
    assert body["messages"][0]["compacted"] is True


def test_archive_and_restore_move_the_conversation_and_keep_its_messages(
    client, alice, test_database_url
):
    conversation_id = seed_conversation(test_database_url, client, alice)

    response = client.patch(
        f"/api/conversations/{conversation_id}", headers=alice, json={"archived": True}
    )
    assert response.status_code == 200
    lists = client.get("/api/conversations", headers=alice).json()
    assert lists["conversations"] == []
    assert [c["id"] for c in lists["archived"]] == [conversation_id]
    assert lists["archived"][0]["archived"] is True

    client.patch(f"/api/conversations/{conversation_id}", headers=alice, json={"archived": False})
    lists = client.get("/api/conversations", headers=alice).json()
    assert [c["id"] for c in lists["conversations"]] == [conversation_id]
    detail = client.get(f"/api/conversations/{conversation_id}", headers=alice).json()
    assert [m["content"] for m in detail["messages"]] == ["hello", "Hi!"]


def test_a_title_change_persists(client, alice, test_database_url):
    conversation_id = seed_conversation(test_database_url, client, alice)

    client.patch(f"/api/conversations/{conversation_id}", headers=alice, json={"title": " Rent  plan "})

    assert client.get(f"/api/conversations/{conversation_id}", headers=alice).json()["title"] == "Rent plan"


def test_an_empty_title_is_refused(client, alice, test_database_url):
    conversation_id = seed_conversation(test_database_url, client, alice)
    response = client.patch(f"/api/conversations/{conversation_id}", headers=alice, json={"title": "  "})
    assert response.status_code == 422


def test_a_model_change_persists(client, alice, fake_llm, test_database_url):
    save_key(client, alice)
    save_models(client, alice, entry(NANO, default=True), entry(BIG, effort="high"))
    conversation_id = seed_conversation(
        test_database_url, client, alice, provider_id="nebius", model=NANO
    )

    response = client.patch(
        f"/api/conversations/{conversation_id}",
        headers=alice,
        json={"provider_id": "nebius", "model": BIG},
    )

    assert response.status_code == 200, response.text
    stored = client.get(f"/api/conversations/{conversation_id}", headers=alice).json()
    assert (stored["model"], stored["reasoning_effort"]) == (BIG, "high")


def test_another_users_conversation_is_not_found(client, alice, bob, test_database_url):
    conversation_id = seed_conversation(test_database_url, client, alice)

    assert client.get(f"/api/conversations/{conversation_id}", headers=bob).status_code == 404
    response = client.patch(f"/api/conversations/{conversation_id}", headers=bob, json={"title": "x"})
    assert response.status_code == 404
    assert error_code(response) == ErrorCode.NOT_FOUND
    assert client.get("/api/conversations", headers=bob).json()["conversations"] == []


# --- 5.2 delete ---


def test_delete_removes_the_conversation_and_its_messages_but_keeps_usage(
    client, alice, test_database_url
):
    conversation_id = seed_conversation(test_database_url, client, alice)
    user_id = uuid.UUID(client.get("/api/me", headers=alice).json()["id"])

    async def add_usage(session):
        session.add(
            UsageEvent(
                user_id=user_id,
                conversation_id=uuid.UUID(conversation_id),
                kind="chat",
                provider_id="nebius",
                model=NANO,
                prompt_tokens=1,
                completion_tokens=1,
            )
        )
        await session.commit()

    run_db(test_database_url, add_usage)

    response = client.delete(f"/api/conversations/{conversation_id}", headers=alice)

    assert response.status_code == 204
    assert client.get(f"/api/conversations/{conversation_id}", headers=alice).status_code == 404

    async def counts(session):
        return [
            (await session.execute(select(func.count()).select_from(model))).scalar_one()
            for model in (Conversation, Message, UsageEvent)
        ]

    assert run_db(test_database_url, counts) == [0, 0, 1]


def test_deleting_another_users_conversation_is_not_found(client, alice, bob, test_database_url):
    conversation_id = seed_conversation(test_database_url, client, alice)

    response = client.delete(f"/api/conversations/{conversation_id}", headers=bob)

    assert response.status_code == 404
    assert error_code(response) == ErrorCode.NOT_FOUND
    assert client.get(f"/api/conversations/{conversation_id}", headers=alice).status_code == 200


# --- 5.3 a new conversation's title and model ---


def test_the_title_starts_with_the_first_message():
    assert title_from("buy oat milk tomorrow") == "buy oat milk tomorrow"
    long = "buy oat milk tomorrow and also remember to call the landlord about the heating"
    title = title_from(long)
    assert long.startswith(title.removesuffix("…"))
    assert title.endswith("…") and len(title) <= 61
    assert title_from("two\nlines") == "two lines"


def test_a_new_conversation_takes_the_default_model_and_effort():
    user = User(id=uuid.uuid4(), issuer="test-issuer", subject="auth0|x")
    default = ChatModel(provider_id="nebius", model=NANO, reasoning_effort="low")

    conversation = new_conversation(user, "hello", default)

    assert (conversation.provider_id, conversation.model, conversation.reasoning_effort) == (
        "nebius",
        NANO,
        "low",
    )


def test_a_new_conversation_without_a_default_has_no_model():
    user = User(id=uuid.uuid4(), issuer="test-issuer", subject="auth0|x")
    conversation = new_conversation(user, "hello", None)
    assert conversation.model is None and conversation.provider_id is None


def test_a_later_default_change_leaves_an_existing_conversation(client, alice, fake_llm, test_database_url):
    save_key(client, alice)
    save_models(client, alice, entry(NANO, default=True), entry(BIG))
    conversation_id = seed_conversation(
        test_database_url, client, alice, provider_id="nebius", model=NANO
    )

    save_models(client, alice, entry(NANO), entry(BIG, default=True))

    assert client.get(f"/api/conversations/{conversation_id}", headers=alice).json()["model"] == NANO


# --- 5.4 switching model ---


def switch(client, headers, conversation_id, **body):
    return client.patch(f"/api/conversations/{conversation_id}", headers=headers, json=body)


def test_a_switch_takes_the_new_models_loadout_effort(client, alice, fake_llm, test_database_url):
    save_key(client, alice)
    save_models(client, alice, entry(NANO, effort="high", default=True), entry(BIG))
    conversation_id = seed_conversation(
        test_database_url, client, alice, provider_id="nebius", model=NANO, reasoning_effort="high"
    )

    body = switch(client, alice, conversation_id, provider_id="nebius", model=BIG).json()

    assert (body["model"], body["reasoning_effort"]) == (BIG, None)


def test_a_switch_drops_an_effort_the_table_refuses(client, alice, fake_llm, test_database_url):
    gpt_oss = "openai/gpt-oss-20b"
    fake_llm.models = {"object": "list", "data": [{"id": NANO}, {"id": gpt_oss}]}
    save_key(client, alice)
    save_models(client, alice, entry(NANO, default=True), entry(gpt_oss))
    conversation_id = seed_conversation(
        test_database_url, client, alice, provider_id="nebius", model=NANO
    )

    response = switch(
        client, alice, conversation_id, provider_id="nebius", model=gpt_oss, reasoning_effort="minimal"
    )
    assert response.status_code == 422

    body = switch(
        client, alice, conversation_id, provider_id="nebius", model=gpt_oss, reasoning_effort="low"
    ).json()
    assert body["reasoning_effort"] == "low"


def test_a_switch_clears_the_stored_prompt_token_count(client, alice, fake_llm, test_database_url):
    save_key(client, alice)
    save_models(client, alice, entry(NANO, default=True), entry(BIG))
    conversation_id = seed_conversation(
        test_database_url,
        client,
        alice,
        provider_id="nebius",
        model=NANO,
        last_prompt_tokens=5000,
        messages=("one", "two"),
    )

    body = switch(client, alice, conversation_id, provider_id="nebius", model=BIG).json()

    assert body["last_prompt_tokens"] is None
    assert [m["content"] for m in body["messages"]] == ["one", "two"]


def test_an_effort_change_on_the_same_model_keeps_the_token_count(
    client, alice, fake_llm, test_database_url
):
    save_key(client, alice)
    save_models(client, alice, entry(NANO, default=True))
    conversation_id = seed_conversation(
        test_database_url, client, alice, provider_id="nebius", model=NANO, last_prompt_tokens=500
    )

    body = switch(client, alice, conversation_id, reasoning_effort="medium").json()

    assert body["reasoning_effort"] == "medium"
    assert body["last_prompt_tokens"] == 500


def test_a_model_outside_the_loadout_is_refused(client, alice, fake_llm, test_database_url):
    save_key(client, alice)
    save_models(client, alice, entry(NANO, default=True))
    conversation_id = seed_conversation(
        test_database_url, client, alice, provider_id="nebius", model=NANO
    )

    response = switch(client, alice, conversation_id, provider_id="nebius", model=BIG)

    assert response.status_code == 422
    assert client.get(f"/api/conversations/{conversation_id}", headers=alice).json()["model"] == NANO


# --- 7.2 confirming a proposal ---

HELD = {"title": "Oat milk", "summary": "Buy oat milk.", "tags": ["shopping"], "position": 1}


def confirm(client, headers, conversation_id, **proposal):
    body = {"title": "Oat milk", "summary": "Buy oat milk.", "tags": ["shopping"], **proposal}
    return client.post(
        f"/api/conversations/{conversation_id}/proposal/confirm", headers=headers, json=body
    )


def test_confirming_returns_the_edited_text_and_that_saving_is_not_available(
    client, alice, test_database_url
):
    conversation_id = seed_conversation(test_database_url, client, alice, held_proposal=HELD)

    response = confirm(client, alice, conversation_id, summary="  Buy oat milk tomorrow.  ", tags=["milk", " "])

    assert response.status_code == 200
    body = response.json()
    assert body["saved"] is False
    assert "not available yet" in body["message"]
    assert body["proposal"] == {"title": "Oat milk", "summary": "Buy oat milk tomorrow.", "tags": ["milk"]}
    # Not saved, so it stays held.
    assert client.get(f"/api/conversations/{conversation_id}", headers=alice).json()["held_proposal"] == HELD


def test_the_save_seam_can_be_replaced_to_report_success(client, alice, test_database_url, monkeypatch):
    from app.chat import tools

    handed = []

    async def save(user, proposal):
        handed.append(proposal)
        return tools.SaveOutcome(saved=True, message="Saved.")

    monkeypatch.setattr(tools, "save_thought", save)
    conversation_id = seed_conversation(test_database_url, client, alice, held_proposal=HELD)

    response = confirm(client, alice, conversation_id, summary="Trimmed.")

    assert response.json()["saved"] is True
    assert handed[0].summary == "Trimmed."
    assert client.get(f"/api/conversations/{conversation_id}", headers=alice).json()["held_proposal"] is None


def test_confirming_in_another_users_conversation_is_not_found(client, alice, bob, test_database_url):
    conversation_id = seed_conversation(test_database_url, client, alice, held_proposal=HELD)
    assert confirm(client, bob, conversation_id).status_code == 404


def test_a_proposal_needs_a_title_and_summary(client, alice, test_database_url):
    conversation_id = seed_conversation(test_database_url, client, alice)
    assert confirm(client, alice, conversation_id, title="  ").status_code == 422
