"""Confirming an addition, the payload and additions list, and undo
(thought-appending tasks 4.1 to 4.3)."""

import uuid
from datetime import UTC, datetime

import httpx2
import pytest
from sqlalchemy import select

from app.models import Thought, ThoughtAddition
from tests.chat_helpers import (
    MODEL_LIST,
    FakeLLM,
    error_code,
    part,
    ready_user,
    run_db,
    seed_conversation,
    seed_proposal,
    user_id_for,
)
from tests.conftest import fail_with
from tests.thought_helpers import (
    EMBED_MODEL,
    counted_queries,
    entries,
    found_by_words,
    head_texts,
    models_with_embedding,
)

pytestmark = pytest.mark.postgres

FILED = {
    "title": "Buy new bike lock",
    "summary": "Buy a new lock for the bike.",
    "tags": ["shopping"],
    "category": "task",
}
ADDED = {
    "title": "A title the model wrote",
    "summary": "Buy a black D-lock for 40 to 80 euros.",
    "tags": ["shopping", "security"],
    "category": "idea",
}
TALK = (
    "/push buy new bike lock",
    "Filed.",
    "For the lock, red or black?",
    "Black hides dirt.",
    "Prices run from 40 to 80 euros.",
    "Noted.",
)
GONE = "The thought this adds to no longer exists. File it as a new thought instead."
TODAY = datetime.now(UTC).date().isoformat()


@pytest.fixture
def fake(settings_env) -> FakeLLM:
    settings_env.setenv("EMBEDDING_MODEL", EMBED_MODEL)
    return FakeLLM(models=models_with_embedding(MODEL_LIST)).install()


def confirm(client, headers, conversation_id, proposal_id, index=0, **fields):
    return client.post(
        f"/api/conversations/{conversation_id}/proposals/{proposal_id}/confirm",
        headers=headers,
        json={"parts": [index], **fields},
    )


def add(client, headers, conversation_id, proposal_id, index=0, **fields):
    return confirm(
        client, headers, conversation_id, proposal_id, index, mode="add", **{**ADDED, **fields}
    )


def thought(client, headers, thought_id) -> dict:
    response = client.get(f"/api/thoughts/{thought_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def conversation(client, headers, conversation_id) -> dict:
    response = client.get(f"/api/conversations/{conversation_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def addition_part(lock: dict, title="Lock colours and prices") -> dict:
    """A stored addition part, as write_proposal() resolves a ref."""
    return part(title=title, summary=ADDED["summary"], tags=ADDED["tags"]) | {
        "add_to": lock["id"],
        "based_on": lock["updated_at"],
    }


def seed_addition(url, conversation_id, lock: dict, position=5, from_position=2, to_position=4, extra=()):
    return seed_proposal(
        url,
        conversation_id,
        [addition_part(lock), *extra],
        position=position,
        raw_text="For the lock, red or black?\n\nPrices run from 40 to 80 euros.",
        from_position=from_position,
        to_position=to_position,
    )


def additions_rows(url, thought_id) -> list[ThoughtAddition]:
    async def work(session):
        rows = await session.execute(
            select(ThoughtAddition)
            .where(ThoughtAddition.thought_id == uuid.UUID(thought_id))
            .order_by(ThoughtAddition.added_at)
        )
        return list(rows.scalars())

    return run_db(url, work)


def thought_row(url, thought_id) -> Thought:
    async def work(session):
        return await session.get(Thought, uuid.UUID(thought_id))

    return run_db(url, work)


def held_id(client, headers, conversation_id):
    return conversation(client, headers, conversation_id)["held_proposal_id"]


@pytest.fixture
def lock(client, alice, fake, test_database_url) -> dict:
    """`Buy new bike lock`, filed with /push in a conversation that then
    talks about the lock's colour and price."""
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice, title="Bike", messages=TALK)
    origin = seed_proposal(
        test_database_url,
        conversation_id,
        [part(title=FILED["title"])],
        position=1,
        raw_text="buy new bike lock",
        from_position=0,
        to_position=0,
    )
    response = confirm(client, alice, conversation_id, origin, **FILED)
    assert response.status_code == 200, response.text
    thought_id = response.json()["thought_id"]
    fake.embed_requests.clear()
    return {
        "conversation_id": conversation_id,
        "origin_proposal": origin,
        **thought(client, alice, thought_id),
    }


@pytest.fixture
def proposed(client, alice, lock, test_database_url) -> dict:
    """The held addition to `Buy new bike lock` from the talk after it."""
    return {
        "conversation_id": lock["conversation_id"],
        "proposal_id": seed_addition(test_database_url, lock["conversation_id"], lock),
    }


# --- 4.1: confirming an addition ---


def test_an_addition_changes_the_content_and_keeps_the_title_and_origin(
    client, alice, lock, proposed, fake, test_database_url
):
    response = add(client, alice, **proposed)

    assert response.status_code == 200, response.text
    assert response.json()["thought_id"] == lock["id"]
    after = thought(client, alice, lock["id"])
    assert after["title"] == FILED["title"]
    assert (after["summary"], after["tags"], after["category"]) == (
        ADDED["summary"],
        ADDED["tags"],
        ADDED["category"],
    )
    assert after["raw_text"] == (
        f"buy new bike lock\n\n--- added {TODAY} ---\n\n"
        "For the lock, red or black?\n\nPrices run from 40 to 80 euros."
    )
    assert after["origin"]["proposal_id"] == lock["origin_proposal"]
    assert thought_row(test_database_url, lock["id"]).proposal_id == uuid.UUID(lock["origin_proposal"])
    # The content changed, so every piece is embedded again, in one call.
    assert len(fake.embed_requests) == 1
    assert any(ADDED["summary"] in text for text in head_texts(fake))

    [row] = additions_rows(test_database_url, lock["id"])
    assert row.before == {
        "title": FILED["title"],
        "summary": FILED["summary"],
        "tags": FILED["tags"],
        "category": FILED["category"],
        "raw_text": "buy new bike lock",
    }
    assert (row.proposal_id, row.from_position, row.to_position) == (
        uuid.UUID(proposed["proposal_id"]),
        2,
        4,
    )
    assert row.after_updated_at == datetime.fromisoformat(after["updated_at"])
    assert row.undone_at is None
    # The part is saved, so the proposal is no longer held.
    assert held_id(client, alice, lock["conversation_id"]) is None


def test_a_deleted_target_gives_404_with_the_file_as_new_message(
    client, alice, lock, proposed, test_database_url
):
    assert client.delete(f"/api/thoughts/{lock['id']}", headers=alice).status_code == 204

    response = add(client, alice, **proposed)

    assert response.status_code == 404
    assert response.json()["error"] == {"code": "not_found", "message": GONE}
    assert held_id(client, alice, lock["conversation_id"]) == proposed["proposal_id"]
    [[saved]] = [p["parts"] for p in conversation(client, alice, lock["conversation_id"])["proposals"][1:]]
    assert saved["thought_id"] is None


def test_another_users_thought_gives_the_same_404(client, alice, bob, lock, fake, test_database_url):
    ready_user(client, bob)
    conversation_id = seed_conversation(test_database_url, client, bob, messages=TALK)
    proposal_id = seed_addition(test_database_url, conversation_id, lock)

    response = add(client, bob, conversation_id, proposal_id)

    assert response.status_code == 404
    assert response.json()["error"]["message"] == GONE
    assert thought(client, alice, lock["id"])["summary"] == FILED["summary"]


def test_a_changed_target_gives_409_with_its_current_fields_and_nothing_changes(
    client, alice, lock, proposed, test_database_url
):
    edit = client.patch(
        f"/api/thoughts/{lock['id']}", headers=alice, json={"summary": "A lock with an alarm."}
    )
    assert edit.status_code == 200, edit.text
    edited = edit.json()

    response = add(client, alice, **proposed)

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "thought_changed"
    assert error["message"]
    assert error["thought"] == {
        "id": lock["id"],
        "title": FILED["title"],
        "summary": "A lock with an alarm.",
        "tags": FILED["tags"],
        "category": FILED["category"],
        "updated_at": error["thought"]["updated_at"],
    }
    assert datetime.fromisoformat(error["thought"]["updated_at"]) == datetime.fromisoformat(
        edited["updated_at"]
    )
    # The user's edit is kept, and nothing else changed.
    assert thought(client, alice, lock["id"]) == edited
    assert additions_rows(test_database_url, lock["id"]) == []
    assert held_id(client, alice, lock["conversation_id"]) == proposed["proposal_id"]

    # The card takes the current version and confirms again.
    again = add(client, alice, **proposed, based_on=error["thought"]["updated_at"])
    assert again.status_code == 200, again.text
    assert thought(client, alice, lock["id"])["summary"] == ADDED["summary"]


def test_a_repeated_confirm_answers_the_same_thought_without_a_second_addition(
    client, alice, lock, proposed, fake, test_database_url
):
    first = add(client, alice, **proposed)
    once = thought(client, alice, lock["id"])
    fake.embed_requests.clear()

    second = add(client, alice, **proposed, summary="Something else entirely.")

    assert (first.status_code, second.status_code) == (200, 200)
    assert second.json()["thought_id"] == first.json()["thought_id"] == lock["id"]
    assert len(additions_rows(test_database_url, lock["id"])) == 1
    assert thought(client, alice, lock["id"]) == once
    assert fake.embed_requests == []


def test_the_held_proposal_clears_when_every_part_is_saved(client, alice, lock, test_database_url):
    proposal_id = seed_addition(
        test_database_url,
        lock["conversation_id"],
        lock,
        extra=[part(title="Bike pump", summary="Buy a bike pump.")],
    )
    conversation_id = lock["conversation_id"]

    assert add(client, alice, conversation_id, proposal_id, 0).status_code == 200
    assert held_id(client, alice, conversation_id) == proposal_id

    saved = confirm(
        client, alice, conversation_id, proposal_id, 1, title="Bike pump", summary="Buy a bike pump."
    )
    assert saved.status_code == 200, saved.text
    assert held_id(client, alice, conversation_id) is None


def test_with_the_provider_unreachable_the_addition_commits_and_words_find_it(
    client, alice, lock, proposed, fake, test_database_url
):
    fake.embed_replies.append(fail_with(httpx2.ConnectError))

    response = add(client, alice, **proposed)

    assert response.status_code == 200, response.text
    assert len(fake.embed_requests) == 1
    assert thought(client, alice, lock["id"])["summary"] == ADDED["summary"]
    assert len(additions_rows(test_database_url, lock["id"])) == 1
    user_id = user_id_for(client, alice)
    # "D-lock" is only in the new summary.
    assert found_by_words(test_database_url, user_id, "D-lock") == [FILED["title"]]
    assert entries(test_database_url, lock["id"]) == {}


def test_an_addition_is_one_part_only_and_needs_a_seen_target(
    client, alice, lock, proposed, test_database_url
):
    two = seed_addition(
        test_database_url, lock["conversation_id"], lock, position=6, extra=[part(title="Pump")]
    )
    merged = client.post(
        f"/api/conversations/{lock['conversation_id']}/proposals/{two}/confirm",
        headers=alice,
        json={"parts": [0, 1], "mode": "add", **ADDED},
    )
    assert merged.status_code == 422
    assert "an addition covers one part" in merged.json()["error"]["message"]

    # A thought this conversation never saw cannot be named by a crafted body.
    elsewhere = seed_conversation(test_database_url, client, alice, title="Elsewhere", messages=TALK)
    plain = seed_proposal(test_database_url, elsewhere, [part(title="Lock")], position=5, to_position=4)
    response = add(client, alice, elsewhere, plain, add_to=lock["id"], based_on=lock["updated_at"])
    assert response.status_code == 422
    assert error_code(response) == "validation_error"
    assert additions_rows(test_database_url, lock["id"]) == []


def test_the_similar_hint_confirms_as_an_addition_with_the_version_it_shows(
    client, alice, lock, test_database_url
):
    """Layer 3: a new part names its strong match; the card sends add_to and based_on."""
    proposal_id = seed_proposal(
        test_database_url,
        lock["conversation_id"],
        [part(title="Black D-lock") | {"similar": {"thought_id": lock["id"]}}],
        position=5,
        from_position=2,
        to_position=4,
    )
    [_, hinted] = conversation(client, alice, lock["conversation_id"])["proposals"]
    similar = hinted["parts"][0]["similar"]

    response = add(
        client,
        alice,
        lock["conversation_id"],
        proposal_id,
        add_to=similar["thought_id"],
        based_on=similar["updated_at"],
    )

    assert response.status_code == 200, response.text
    assert response.json()["thought_id"] == lock["id"]
    assert thought(client, alice, lock["id"])["summary"] == ADDED["summary"]


def test_two_parts_of_one_proposal_never_add_to_one_thought(client, alice, lock, test_database_url):
    """Two cards whose hints both named the lock: the second, even confirmed
    against the current version, is refused and nothing is added twice."""
    hinted = part(title="Black D-lock") | {"similar": {"thought_id": lock["id"]}}
    proposal_id = seed_proposal(
        test_database_url,
        lock["conversation_id"],
        [hinted, hinted | {"title": "Lock prices"}],
        position=5,
        from_position=2,
        to_position=4,
    )
    first = add(
        client, alice, lock["conversation_id"], proposal_id, 0,
        add_to=lock["id"], based_on=lock["updated_at"],
    )
    assert first.status_code == 200, first.text
    now = thought(client, alice, lock["id"])

    second = add(
        client, alice, lock["conversation_id"], proposal_id, 1,
        add_to=lock["id"], based_on=now["updated_at"],
    )

    assert second.status_code == 409, second.text
    assert error_code(second) == "proposal_part_saved"
    assert len(additions_rows(test_database_url, lock["id"])) == 1
    assert thought(client, alice, lock["id"])["updated_at"] == now["updated_at"]


def test_two_additions_from_one_conversation_add_each_message_once(
    client, alice, lock, proposed, test_database_url
):
    assert add(client, alice, **proposed).status_code == 200
    current = thought(client, alice, lock["id"])
    # A later proposal over the same talk and one more message.
    later = seed_addition(
        test_database_url, lock["conversation_id"], current, position=6, from_position=2, to_position=6
    )

    async def one_more(session):
        from app.models import Message

        session.add(
            Message(
                conversation_id=uuid.UUID(lock["conversation_id"]),
                position=6,
                role="user",
                content="Get two keys.",
            )
        )
        await session.commit()

    run_db(test_database_url, one_more)
    assert add(client, alice, lock["conversation_id"], later).status_code == 200

    raw = thought(client, alice, lock["id"])["raw_text"]
    assert raw.count("For the lock, red or black?") == 1
    assert raw.endswith(f"--- added {TODAY} ---\n\nGet two keys.")


# --- 4.2: target, similar, and the additions list ---


def proposal_parts(client, headers, conversation_id) -> list[list[dict]]:
    return [p["parts"] for p in conversation(client, headers, conversation_id)["proposals"]]


def test_target_holds_the_current_fields_or_deleted(client, alice, lock, proposed):
    [_, [target_part]] = proposal_parts(client, alice, lock["conversation_id"])
    assert target_part["add_to"] == lock["id"]
    assert target_part["target"] == {
        "title": FILED["title"],
        "summary": FILED["summary"],
        "tags": FILED["tags"],
        "category": FILED["category"],
        "created_at": target_part["target"]["created_at"],
        "updated_at": target_part["target"]["updated_at"],
    }
    assert datetime.fromisoformat(target_part["target"]["updated_at"]) == datetime.fromisoformat(
        lock["updated_at"]
    )
    assert (target_part["added"], target_part["undone"], target_part["similar"]) == (False, False, None)

    client.patch(f"/api/thoughts/{lock['id']}", headers=alice, json={"title": "Bike lock"})
    [_, [target_part]] = proposal_parts(client, alice, lock["conversation_id"])
    assert target_part["target"]["title"] == "Bike lock"

    # The offered held proposal carries the same payload.
    offered = client.post(f"/api/conversations/{lock['conversation_id']}/proposal", headers=alice)
    assert offered.json()["proposal"]["parts"] == [target_part]

    client.delete(f"/api/thoughts/{lock['id']}", headers=alice)
    [[filed], [target_part]] = proposal_parts(client, alice, lock["conversation_id"])
    assert target_part["target"] == {"deleted": True}
    assert filed["target"] is None and filed["deleted"] is True


def test_similar_names_the_match_as_it_is_now_or_nothing(client, alice, lock, test_database_url):
    seed_proposal(
        test_database_url,
        lock["conversation_id"],
        [part(title="Black D-lock") | {"similar": {"thought_id": lock["id"]}}],
        position=5,
    )

    [_, [hinted]] = proposal_parts(client, alice, lock["conversation_id"])
    assert hinted["target"] is None
    assert hinted["similar"]["thought_id"] == lock["id"]
    assert hinted["similar"]["title"] == FILED["title"]
    assert datetime.fromisoformat(hinted["similar"]["created_at"]) == datetime.fromisoformat(
        lock["created_at"]
    )
    assert hinted["similar"]["summary"] == FILED["summary"]

    client.delete(f"/api/thoughts/{lock['id']}", headers=alice)
    [_, [hinted]] = proposal_parts(client, alice, lock["conversation_id"])
    assert hinted["similar"] is None


def test_a_saved_addition_says_added_on_reload(client, alice, lock, proposed):
    add(client, alice, **proposed)

    [_, [saved]] = proposal_parts(client, alice, lock["conversation_id"])

    assert (saved["thought_id"], saved["added"], saved["undone"]) == (lock["id"], True, False)
    assert saved["saved_title"] == FILED["title"]
    assert saved["target"]["summary"] == ADDED["summary"]
    assert "seen_position" not in saved


def rename(client, headers, conversation_id, title):
    response = client.patch(f"/api/conversations/{conversation_id}", headers=headers, json={"title": title})
    assert response.status_code == 200, response.text


def test_additions_list_newest_first_with_the_conversations_current_title(
    client, alice, lock, proposed, test_database_url
):
    assert add(client, alice, **proposed).status_code == 200
    # A second addition from another conversation, which saw the lock in a search.
    current = thought(client, alice, lock["id"])
    other = seed_conversation(test_database_url, client, alice, title="Cycling", messages=TALK)
    later = seed_addition(test_database_url, other, current)
    assert add(client, alice, other, later, summary="A black D-lock with two keys.").status_code == 200
    rename(client, alice, lock["conversation_id"], "Bike shopping")

    body = thought(client, alice, lock["id"])

    first, second = body["additions"]
    assert (first["conversation_id"], first["conversation_title"], first["proposal_id"]) == (
        other,
        "Cycling",
        later,
    )
    assert (second["conversation_id"], second["conversation_title"], second["proposal_id"]) == (
        lock["conversation_id"],
        "Bike shopping",
        proposed["proposal_id"],
    )
    assert first["added_at"] > second["added_at"]
    assert [a["undone"] for a in body["additions"]] == [False, False]
    # The origin is still where the thought was first filed.
    assert body["origin"]["proposal_id"] == lock["origin_proposal"]

    # Deleting a conversation removes its additions from the list.
    assert client.delete(f"/api/conversations/{other}", headers=alice).status_code == 204
    after = thought(client, alice, lock["id"])
    assert [a["proposal_id"] for a in after["additions"]] == [proposed["proposal_id"]]
    assert after["summary"] == "A black D-lock with two keys."


def test_a_thought_with_no_additions_lists_none(client, alice, lock):
    assert thought(client, alice, lock["id"])["additions"] == []


def test_neither_endpoint_grows_its_queries_with_parts_or_additions(
    client, alice, lock, test_database_url
):
    def addition_in(title):
        current = thought(client, alice, lock["id"])
        conversation_id = seed_conversation(test_database_url, client, alice, title=title, messages=TALK)
        parts = [
            addition_part(current),
            part(title="Pump") | {"similar": {"thought_id": lock["id"]}},
            part(title="Bell"),
        ]
        proposal_id = seed_proposal(
            test_database_url, conversation_id, parts, position=5, from_position=2, to_position=4
        )
        assert add(client, alice, conversation_id, proposal_id).status_code == 200
        return conversation_id

    one = addition_in("One")
    with counted_queries() as conversation_one:
        conversation(client, alice, one)
    with counted_queries() as thought_one:
        thought(client, alice, lock["id"])

    many = addition_in("Many")
    for position in (6, 7):
        current = thought(client, alice, lock["id"])
        proposal_id = seed_proposal(
            test_database_url,
            many,
            [addition_part(current), part(title="Light") | {"similar": {"thought_id": lock["id"]}}],
            position=position,
            from_position=2,
            to_position=4,
        )
        assert add(client, alice, many, proposal_id).status_code == 200
    with counted_queries() as conversation_many:
        parts = proposal_parts(client, alice, many)
    with counted_queries() as thought_many:
        body = thought(client, alice, lock["id"])

    assert sum(len(p) for p in parts) == 7
    assert len(body["additions"]) == 4
    assert len(conversation_many) == len(conversation_one)
    assert len(thought_many) == len(thought_one)
    assert sum("FROM thoughts" in s for s in conversation_many) == 1
    assert sum("FROM thought_additions" in s for s in conversation_many) == 1
    assert sum("FROM thought_additions" in s for s in thought_many) == 1


# --- 4.3: undo ---


def undo(client, headers, thought_id, addition_id):
    return client.post(f"/api/thoughts/{thought_id}/additions/{addition_id}/undo", headers=headers)


@pytest.fixture
def added(client, alice, lock, proposed, fake) -> dict:
    assert add(client, alice, **proposed).status_code == 200
    body = thought(client, alice, lock["id"])
    fake.embed_requests.clear()
    return body


def test_undo_restores_the_fields_and_raw_text_and_embeds_again(
    client, alice, lock, proposed, added, fake, test_database_url
):
    [addition] = added["additions"]

    response = undo(client, alice, lock["id"], addition["id"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["title"], body["summary"], body["tags"], body["category"], body["raw_text"]) == (
        FILED["title"],
        FILED["summary"],
        FILED["tags"],
        FILED["category"],
        "buy new bike lock",
    )
    assert [a["undone"] for a in body["additions"]] == [True]
    assert body == thought(client, alice, lock["id"])
    # Embedded again, with the restored summary, in one call.
    assert len(fake.embed_requests) == 1
    assert any(FILED["summary"] in text for text in head_texts(fake))
    user_id = user_id_for(client, alice)
    assert found_by_words(test_database_url, user_id, "D-lock") == []
    assert found_by_words(test_database_url, user_id, "new lock") == [FILED["title"]]
    [row] = additions_rows(test_database_url, lock["id"])
    assert row.undone_at is not None
    # The card says the addition was undone; the part stays saved.
    [_, [saved]] = proposal_parts(client, alice, lock["conversation_id"])
    assert (saved["thought_id"], saved["added"], saved["undone"]) == (lock["id"], True, True)


def test_undo_is_refused_when_the_thought_changed_after_the_addition(
    client, alice, lock, added, fake
):
    edit = client.patch(f"/api/thoughts/{lock['id']}", headers=alice, json={"title": "Bike lock"})
    assert edit.status_code == 200
    before = thought(client, alice, lock["id"])
    fake.embed_requests.clear()

    response = undo(client, alice, lock["id"], added["additions"][0]["id"])

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "thought_changed"
    assert "changed after this addition" in error["message"]
    assert error["thought"]["title"] == "Bike lock"
    assert thought(client, alice, lock["id"]) == before
    assert fake.embed_requests == []


def test_undo_is_refused_while_a_newer_addition_is_not_undone(
    client, alice, lock, added, test_database_url
):
    other = seed_conversation(test_database_url, client, alice, title="Cycling", messages=TALK)
    later = seed_addition(test_database_url, other, added)
    assert add(client, alice, other, later, summary="Two keys.").status_code == 200
    newest, older = thought(client, alice, lock["id"])["additions"]
    assert older["id"] == added["additions"][0]["id"]

    refused = undo(client, alice, lock["id"], older["id"])

    assert refused.status_code == 409
    assert error_code(refused) == "thought_changed"
    assert thought(client, alice, lock["id"])["summary"] == "Two keys."
    # The newest goes first; the older one is still refused, as the thought
    # changed after it (one undo step, design non-goals).
    assert undo(client, alice, lock["id"], newest["id"]).status_code == 200
    assert thought(client, alice, lock["id"])["summary"] == ADDED["summary"]
    assert undo(client, alice, lock["id"], newest["id"]).status_code == 409


def test_another_users_thought_gives_404(client, alice, bob, lock, added, fake):
    ready_user(client, bob)
    addition_id = added["additions"][0]["id"]

    response = undo(client, bob, lock["id"], addition_id)

    assert response.status_code == 404
    assert error_code(response) == "not_found"
    assert undo(client, alice, lock["id"], str(uuid.uuid4())).status_code == 404
    assert thought(client, alice, lock["id"])["summary"] == ADDED["summary"]


def test_an_addition_of_another_thought_gives_404(client, alice, lock, added, test_database_url):
    conversation_id = seed_conversation(test_database_url, client, alice, title="Pump", messages=TALK)
    proposal_id = seed_proposal(test_database_url, conversation_id, [part(title="Pump")])
    other = confirm(client, alice, conversation_id, proposal_id, title="Pump", summary="Buy a pump.")
    assert other.status_code == 200

    response = undo(client, alice, other.json()["thought_id"], added["additions"][0]["id"])

    assert response.status_code == 404


def test_the_proposal_is_not_offered_again_after_an_undo(client, alice, lock, added, fake):
    assert undo(client, alice, lock["id"], added["additions"][0]["id"]).status_code == 200

    response = client.post(f"/api/conversations/{lock['conversation_id']}/proposal", headers=alice)

    assert response.status_code == 200, response.text
    assert response.json() == {"proposal": None}
    assert fake.chat_requests == []


def test_an_undo_survives_an_unreachable_provider(client, alice, lock, added, fake, test_database_url):
    fake.embed_replies.append(fail_with(httpx2.ConnectError))

    response = undo(client, alice, lock["id"], added["additions"][0]["id"])

    assert response.status_code == 200, response.text
    assert response.json()["summary"] == FILED["summary"]
    assert found_by_words(test_database_url, user_id_for(client, alice), "new lock") == [FILED["title"]]


# --- with thought-dates: an addition keeps its thought's date (design decision 22) ---


def dated_lock(client, headers, lock: dict) -> dict:
    response = client.patch(
        f"/api/thoughts/{lock['id']}",
        headers=headers,
        json={"when": {"start": "2026-10-02T19:00", "end": "2026-10-02T21:00", "time_zone": "Europe/Berlin"}},
    )
    assert response.status_code == 200, response.text
    return {**lock, **response.json()}


CHOICES = [
    {"start": "2026-10-09", "end": None, "time_zone": "Europe/Berlin"},
    {"start": "2026-10-16", "end": None, "time_zone": "Europe/Berlin"},
]


def test_an_addition_keeps_the_date_and_the_detail_shows_it_with_the_additions(
    client, alice, lock, test_database_url
):
    lock = dated_lock(client, alice, lock)
    # A part that still carries date choices, as a row from before the restack
    # might: the addition needs no pick, and a date in the body is ignored.
    proposal_id = seed_proposal(
        test_database_url,
        lock["conversation_id"],
        [addition_part(lock) | {"when": None, "when_choices": CHOICES}],
        position=5,
        raw_text="Prices run from 40 to 80 euros.",
        from_position=2,
        to_position=4,
    )

    response = add(
        client, alice, lock["conversation_id"], proposal_id, when={"start": "2027-01-01", "time_zone": "UTC"}
    )

    assert response.status_code == 200, response.text
    after = thought(client, alice, lock["id"])
    assert after["summary"] == ADDED["summary"]
    assert after["when"] == lock["when"]
    [addition] = after["additions"]
    assert (addition["proposal_id"], addition["undone"]) == (proposal_id, False)

    restored = undo(client, alice, lock["id"], addition["id"])

    assert restored.status_code == 200, restored.text
    assert restored.json()["summary"] == FILED["summary"]
    assert restored.json()["when"] == lock["when"]
    assert restored.json()["additions"][0]["undone"] is True


def test_the_similar_hint_adds_a_part_with_date_choices_without_a_pick(
    client, alice, lock, test_database_url
):
    lock = dated_lock(client, alice, lock)
    new_part = part(title="Lock prices", summary=ADDED["summary"]) | {
        "when": None,
        "when_choices": CHOICES,
        "similar": {"thought_id": lock["id"]},
    }
    proposal_id = seed_proposal(
        test_database_url, lock["conversation_id"], [new_part], position=5, from_position=2, to_position=4
    )
    # Filed as new, the card must pick a date first (thought-dates).
    refused = confirm(client, alice, lock["conversation_id"], proposal_id, **ADDED)
    assert refused.status_code == 422
    assert refused.json()["error"]["message"].startswith("when:")

    response = add(
        client, alice, lock["conversation_id"], proposal_id, add_to=lock["id"], based_on=lock["updated_at"]
    )

    assert response.status_code == 200, response.text
    assert response.json()["thought_id"] == lock["id"]
    after = thought(client, alice, lock["id"])
    assert after["when"] == lock["when"]
    assert len(after["additions"]) == 1
