"""Changing and deleting a thought (thought-editing tasks 1.2 to 1.5)."""

import time
import uuid
from datetime import datetime

import httpx2
import pytest

from app.models import Proposal
from app.thoughts.search import search_thoughts
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
    run_as,
)

pytestmark = pytest.mark.postgres

# A raw text long enough for several pieces, with none of the summary's words.
LONG_RAW = "\n\n".join(
    f"Paragraph {n}. The flat near Alfama was cheaper than the hotel. " * 6 for n in range(4)
)
SAVED = {
    "title": "Oat milk",
    "summary": "Buy oat milk on the way home.",
    "tags": ["groceries"],
    "category": "task",
}


@pytest.fixture
def fake(settings_env) -> FakeLLM:
    settings_env.setenv("EMBEDDING_MODEL", EMBED_MODEL)
    return FakeLLM(models=models_with_embedding(MODEL_LIST)).install()


def confirm(client, headers, conversation_id, proposal_id, index=0, **fields):
    response = client.post(
        f"/api/conversations/{conversation_id}/proposals/{proposal_id}/confirm",
        headers=headers,
        json={"parts": [index], **SAVED, **fields},
    )
    assert response.status_code == 200, response.text
    return response.json()["thought_id"]


def saved_thought(client, headers, url, raw_text="I need oat milk.", **fields) -> dict:
    """A conversation with a one-part proposal saved as a thought."""
    conversation_id = seed_conversation(url, client, headers, title="Groceries")
    proposal_id = seed_proposal(url, conversation_id, [part(title="Oat milk")], raw_text=raw_text)
    thought_id = confirm(client, headers, conversation_id, proposal_id, **fields)
    return {"conversation_id": conversation_id, "proposal_id": proposal_id, "thought_id": thought_id}


@pytest.fixture
def alices(client, alice, fake, test_database_url) -> dict:
    ready_user(client, alice)
    saved = saved_thought(client, alice, test_database_url)
    fake.embed_requests.clear()
    return saved


@pytest.fixture
def bobs(client, bob, fake, test_database_url) -> dict:
    ready_user(client, bob)
    saved = saved_thought(client, bob, test_database_url, title="Bob's note")
    fake.embed_requests.clear()
    return saved


def get(client, headers, thought_id):
    return client.get(f"/api/thoughts/{thought_id}", headers=headers)


def patch(client, headers, thought_id, body):
    return client.patch(f"/api/thoughts/{thought_id}", headers=headers, json=body)


def delete(client, headers, thought_id):
    return client.delete(f"/api/thoughts/{thought_id}", headers=headers)


def thought(client, headers, thought_id) -> dict:
    response = get(client, headers, thought_id)
    assert response.status_code == 200, response.text
    return response.json()


def search_titles(url, user_id, fake, query) -> list[str]:
    async def work(session, user, settings, http_client):
        result = await search_thoughts(session, user, query, settings=settings, http_client=http_client)
        return [hit.thought.title for hit in result.hits]

    return run_as(url, user_id, fake, work)


def proposal_parts(url, proposal_id) -> list[dict]:
    async def work(session):
        return (await session.get(Proposal, uuid.UUID(proposal_id))).parts

    return run_db(url, work)


# --- PATCH (task 1.2) ---


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("title", "  Dentist in May ", "Dentist in May"),
        ("summary", "Book the dentist.", "Book the dentist."),
        ("tags", ["Health", "#teeth", "health"], ["health", "teeth"]),
        ("category", " Idea", "idea"),
    ],
)
def test_each_field_changes_alone(client, alice, alices, field, value, expected):
    before = thought(client, alice, alices["thought_id"])

    response = patch(client, alice, alices["thought_id"], {field: value})

    assert response.status_code == 200, response.text
    after = response.json()
    assert after[field] == expected
    unchanged = {"title", "summary", "tags", "category", "raw_text", "created_at", "origin"} - {field}
    assert {key: after[key] for key in unchanged} == {key: before[key] for key in unchanged}


def test_a_missing_field_is_kept_and_a_null_category_clears_it(client, alice, alices):
    before = thought(client, alice, alices["thought_id"])

    after = patch(client, alice, alices["thought_id"], {"category": None}).json()

    assert after["category"] is None
    assert (after["title"], after["summary"], after["tags"]) == (
        before["title"],
        before["summary"],
        before["tags"],
    )
    assert patch(client, alice, alices["thought_id"], {"category": ""}).json()["category"] is None


def test_the_answer_has_the_get_shape_with_the_same_origin(client, alice, alices):
    origin = thought(client, alice, alices["thought_id"])["origin"]
    assert origin["conversation_id"] == alices["conversation_id"]

    response = patch(client, alice, alices["thought_id"], {"title": "Lisbon trip", "tags": ["travel"]})

    assert response.json() == thought(client, alice, alices["thought_id"])
    assert response.json()["origin"] == origin


def test_updated_at_grows_on_a_change_and_stays_on_an_empty_body(client, alice, alices):
    before = thought(client, alice, alices["thought_id"])
    time.sleep(0.01)

    same = patch(client, alice, alices["thought_id"], {})
    assert same.status_code == 200
    assert same.json() == before

    same_values = patch(client, alice, alices["thought_id"], {**SAVED})
    assert same_values.json() == before

    changed = patch(client, alice, alices["thought_id"], {"summary": "Book the dentist."}).json()
    assert datetime.fromisoformat(changed["updated_at"]) > datetime.fromisoformat(before["updated_at"])
    assert changed["created_at"] == before["created_at"]


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"title": "   "}, "title"),
        ({"title": "x" * 201}, "title"),
        ({"tags": "groceries"}, "tags"),
        ({"tags": ["x" * 51]}, "tags"),
        ({"category": "holiday"}, "category"),
        ({"raw_text": "Something else."}, "raw_text"),
        ({"title": "Fine", "raw_text": "Something else."}, "raw_text"),
    ],
)
def test_a_refused_field_is_named_and_the_thought_is_unchanged(client, alice, alices, fake, body, field):
    before = thought(client, alice, alices["thought_id"])

    response = patch(client, alice, alices["thought_id"], body)

    assert response.status_code == 422, response.text
    assert error_code(response) == "validation_error"
    assert response.json()["error"]["message"].startswith(f"{field}: ")
    assert thought(client, alice, alices["thought_id"]) == before
    assert fake.embed_requests == []


def test_a_removed_category_the_thought_has_is_kept(client, alice, alices):
    assert client.post("/api/settings/categories", headers=alice, json={"name": "trip"}).status_code == 201
    assert patch(client, alice, alices["thought_id"], {"category": "trip"}).json()["category"] == "trip"
    assert client.delete("/api/settings/categories/trip", headers=alice).status_code == 204

    title_only = patch(client, alice, alices["thought_id"], {"title": "Lisbon trip"})
    assert title_only.status_code == 200, title_only.text
    assert title_only.json()["category"] == "trip"

    # Sending it back unchanged is no error either; another removed name is.
    assert patch(client, alice, alices["thought_id"], {"category": "Trip"}).json()["category"] == "trip"
    refused = patch(client, alice, alices["thought_id"], {"category": "holiday"})
    assert refused.status_code == 422
    assert thought(client, alice, alices["thought_id"])["category"] == "trip"


@pytest.mark.parametrize("body", [{"title": "Taken"}, {"category": "idea"}, {}])
def test_another_users_thought_and_a_missing_one_are_not_found(client, alice, bob, alices, bobs, body):
    before = thought(client, bob, bobs["thought_id"])

    for thought_id in (bobs["thought_id"], str(uuid.uuid4())):
        response = patch(client, alice, thought_id, body)
        assert response.status_code == 404, response.text
        assert error_code(response) == "not_found"

    assert thought(client, bob, bobs["thought_id"]) == before


def test_an_unreachable_provider_still_saves_the_edit(
    client, alice, alices, fake, test_database_url
):
    fake.embed_replies.append(fail_with(httpx2.ConnectError))

    response = patch(client, alice, alices["thought_id"], {"summary": "Book the dentist."})

    assert response.status_code == 200, response.text
    assert response.json()["summary"] == "Book the dentist."
    assert len(fake.embed_requests) == 1
    user_id = user_id_for(client, alice)
    assert found_by_words(test_database_url, user_id, "dentist") == ["Oat milk"]
    assert entries(test_database_url, alices["thought_id"]) == {}


# --- embedding calls (task 1.3) ---


@pytest.fixture
def long_one(client, alice, fake, test_database_url) -> dict:
    """A saved thought with several pieces, every thought with its entries."""
    ready_user(client, alice)
    saved = saved_thought(client, alice, test_database_url, raw_text=LONG_RAW)
    [(index, chunks)] = entries(test_database_url, saved["thought_id"]).items()
    assert len(chunks) > 1
    fake.embed_requests.clear()
    return {**saved, "index": index, "chunks": chunks}


@pytest.mark.parametrize(
    ("body", "head"),
    [
        ({"title": "Lisbon trip"}, "Lisbon trip\n#groceries\nBuy oat milk on the way home."),
        ({"summary": "Book the dentist."}, "Oat milk\n#groceries\nBook the dentist."),
    ],
)
def test_a_title_or_summary_edit_embeds_every_piece_in_one_call(
    client, alice, long_one, fake, test_database_url, body, head
):
    assert patch(client, alice, long_one["thought_id"], body).status_code == 200

    assert len(fake.embed_requests) == 1
    texts = fake.embed_requests[0]["input"]
    assert len(texts) == len(long_one["chunks"])
    assert texts[0] == head
    assert entries(test_database_url, long_one["thought_id"]) == {long_one["index"]: long_one["chunks"]}


def test_a_tags_only_edit_embeds_only_the_head_piece(client, alice, long_one, fake, test_database_url):
    assert patch(client, alice, long_one["thought_id"], {"tags": ["errands"]}).status_code == 200

    assert len(fake.embed_requests) == 1
    assert head_texts(fake) == ["Oat milk\n#errands\nBuy oat milk on the way home."]
    assert entries(test_database_url, long_one["thought_id"]) == {long_one["index"]: long_one["chunks"]}


@pytest.mark.parametrize("body", [{"category": "idea"}, {}, {"title": "Oat milk", "tags": ["Groceries"]}])
def test_a_category_only_edit_or_no_change_makes_no_call(client, alice, long_one, fake, body):
    assert patch(client, alice, long_one["thought_id"], body).status_code == 200
    assert fake.embed_requests == []


def test_after_a_summary_edit_the_old_summary_no_longer_finds_it(
    client, alice, long_one, fake, test_database_url
):
    user_id = user_id_for(client, alice)
    assert found_by_words(test_database_url, user_id, "way home") == ["Oat milk"]
    assert "Oat milk" in search_titles(test_database_url, user_id, fake, "way home")
    fake.embed_requests.clear()

    patch(client, alice, long_one["thought_id"], {"summary": "Book the dentist."})

    assert found_by_words(test_database_url, user_id, "way home") == []
    assert found_by_words(test_database_url, user_id, "dentist") == ["Oat milk"]
    # The new pieces are the only ones embedded, so search by meaning has no old summary.
    assert not any("home" in text for text in head_texts(fake))
    assert search_titles(test_database_url, user_id, fake, "dentist") == ["Oat milk"]


# --- DELETE (task 1.4) ---


def test_delete_removes_the_thought_and_keeps_its_proposal(
    client, alice, alices, fake, test_database_url
):
    user_id = user_id_for(client, alice)
    assert search_titles(test_database_url, user_id, fake, "oat milk") == ["Oat milk"]
    parts_before = proposal_parts(test_database_url, alices["proposal_id"])

    response = delete(client, alice, alices["thought_id"])

    assert response.status_code == 204
    assert response.content == b""
    gone = get(client, alice, alices["thought_id"])
    assert gone.status_code == 404 and error_code(gone) == "not_found"
    assert search_titles(test_database_url, user_id, fake, "oat milk") == []
    assert found_by_words(test_database_url, user_id, "oat milk") == []
    assert entries(test_database_url, alices["thought_id"]) == {}
    assert proposal_parts(test_database_url, alices["proposal_id"]) == parts_before
    assert parts_before[0]["thought_id"] == alices["thought_id"]
    conversation = client.get(f"/api/conversations/{alices['conversation_id']}", headers=alice)
    assert conversation.status_code == 200
    assert [p["id"] for p in conversation.json()["proposals"]] == [alices["proposal_id"]]


def test_delete_of_another_users_thought_or_a_missing_one_is_not_found(client, alice, bob, alices, bobs):
    before = thought(client, bob, bobs["thought_id"])

    for thought_id in (bobs["thought_id"], str(uuid.uuid4())):
        response = delete(client, alice, thought_id)
        assert response.status_code == 404, response.text
        assert error_code(response) == "not_found"

    assert thought(client, bob, bobs["thought_id"]) == before
    gone_twice = delete(client, alice, alices["thought_id"]), delete(client, alice, alices["thought_id"])
    assert [r.status_code for r in gone_twice] == [204, 404]


# --- saved_title and deleted on proposal parts (task 1.5) ---


def stored_parts(client, headers, conversation_id) -> list[list[dict]]:
    response = client.get(f"/api/conversations/{conversation_id}", headers=headers)
    assert response.status_code == 200, response.text
    return [proposal["parts"] for proposal in response.json()["proposals"]]


@pytest.fixture
def two_parts(client, alice, fake, test_database_url) -> dict:
    """A held proposal with two parts, the first saved."""
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice, title="Groceries")
    proposal_id = seed_proposal(
        test_database_url,
        conversation_id,
        [part(title="Trip ideas", tags=["travel"]), part(title="Dentist", tags=["health"])],
    )
    thought_id = confirm(client, alice, conversation_id, proposal_id, title="Trip ideas")
    return {"conversation_id": conversation_id, "proposal_id": proposal_id, "thought_id": thought_id}


def test_a_saved_part_shows_the_current_title_and_an_unsaved_part_neither(client, alice, two_parts):
    [[saved, unsaved]] = stored_parts(client, alice, two_parts["conversation_id"])
    assert (saved["thought_id"], saved["saved_title"], saved["deleted"]) == (
        two_parts["thought_id"],
        "Trip ideas",
        False,
    )
    assert (unsaved["thought_id"], unsaved["saved_title"], unsaved["deleted"]) == (None, None, False)

    patch(client, alice, two_parts["thought_id"], {"title": "Lisbon trip"})

    [[saved, unsaved]] = stored_parts(client, alice, two_parts["conversation_id"])
    assert (saved["title"], saved["saved_title"], saved["deleted"]) == ("Trip ideas", "Lisbon trip", False)
    assert (unsaved["saved_title"], unsaved["deleted"]) == (None, False)


def test_a_deleted_thought_shows_deleted_with_no_title(client, alice, two_parts):
    assert delete(client, alice, two_parts["thought_id"]).status_code == 204

    [[saved, unsaved]] = stored_parts(client, alice, two_parts["conversation_id"])
    assert (saved["thought_id"], saved["saved_title"], saved["deleted"]) == (
        two_parts["thought_id"],
        None,
        True,
    )
    assert (unsaved["saved_title"], unsaved["deleted"]) == (None, False)


def test_the_offered_held_proposal_has_the_same_fields(client, alice, two_parts, fake):
    patch(client, alice, two_parts["thought_id"], {"title": "Lisbon trip"})

    response = client.post(f"/api/conversations/{two_parts['conversation_id']}/proposal", headers=alice)

    assert response.status_code == 200, response.text
    offered = response.json()["proposal"]
    assert offered["id"] == two_parts["proposal_id"]
    assert [(p["saved_title"], p["deleted"]) for p in offered["parts"]] == [("Lisbon trip", False), (None, False)]
    assert offered["parts"] == stored_parts(client, alice, two_parts["conversation_id"])[0]
    assert fake.chat_requests == []

    delete(client, alice, two_parts["thought_id"])
    offered = client.post(f"/api/conversations/{two_parts['conversation_id']}/proposal", headers=alice).json()
    assert [(p["saved_title"], p["deleted"]) for p in offered["proposal"]["parts"]] == [(None, True), (None, False)]


def test_a_proposal_whose_only_thought_was_deleted_is_not_offered_again(client, alice, alices, fake):
    assert delete(client, alice, alices["thought_id"]).status_code == 204

    response = client.post(f"/api/conversations/{alices['conversation_id']}/proposal", headers=alice)

    assert response.status_code == 200, response.text
    assert response.json() == {"proposal": None}
    # No model was asked for a new proposal: the deleted part still counts as filed.
    assert fake.chat_requests == []
    [[stored]] = stored_parts(client, alice, alices["conversation_id"])
    assert (stored["thought_id"], stored["deleted"]) == (alices["thought_id"], True)


def test_the_messages_query_count_does_not_grow_with_saved_parts(client, alice, fake, test_database_url):
    ready_user(client, alice)
    one = saved_thought(client, alice, test_database_url)["conversation_id"]
    many = seed_conversation(test_database_url, client, alice, title="Many")
    proposal_id = seed_proposal(
        test_database_url, many, [part(title=f"Part {n}") for n in range(4)], hold=False
    )
    for index in range(4):
        confirm(client, alice, many, proposal_id, index=index, title=f"Part {index}")
    for n in range(3):
        extra = seed_proposal(test_database_url, many, [part(title=f"Extra {n}")], position=1, hold=False)
        confirm(client, alice, many, extra, title=f"Extra {n}")
    deleted_id = stored_parts(client, alice, many)[0][0]["thought_id"]
    assert delete(client, alice, deleted_id).status_code == 204

    # Warm up: the first read may ask the provider for the model's details.
    stored_parts(client, alice, one)
    stored_parts(client, alice, many)
    with counted_queries() as for_one:
        stored_parts(client, alice, one)
    with counted_queries() as for_many:
        parts = stored_parts(client, alice, many)

    assert sum(len(p) for p in parts) == 7
    assert sum(p["deleted"] for ps in parts for p in ps) == 1
    assert parts[0][0]["thought_id"] == deleted_id
    assert len(for_many) == len(for_one)
    # One lookup for the parts' thoughts. The meter's tool definitions
    # (mcp-connectors) read the known tags once more, whatever the parts.
    assert sum("FROM thoughts" in s and "unnest" not in s for s in for_many) == 1
    assert sum("FROM thoughts" in s and "unnest" in s for s in for_many) == 1
