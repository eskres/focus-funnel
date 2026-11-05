"""The similar-thought check (thought-appending tasks 3.1 and 3.3).

Postgres: the check runs the search's SQL. The fake provider embeds with
concept_embedder, so texts that share a concept word are close.
"""

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.chat.config import get_chat_config
from app.chat.prompt import forced_tool
from app.chat.similar import REPEATED_TASK, Query, check_parts, find_similar
from app.chat.tools import ALREADY_PROPOSED, ProposalPart
from app.models import Conversation, Message, Proposal, SearchIndex, Thought
from app.thoughts.baseline import cutoffs
from app.thoughts.search import search_by_vector, search_thoughts
from app.thoughts.store import store_thought
from tests.chat_helpers import (
    MODEL_LIST,
    FakeLLM,
    chat,
    completion,
    ready_user,
    run_db,
    seed_conversation,
    text_chunks,
    tool_call,
    tool_call_chunks,
    user_id_for,
)
from tests.sse_helpers import parse_events
from tests.thought_helpers import (
    DEFAULT_CONCEPTS,
    EMBED_MODEL,
    concept_embedder,
    models_with_embedding,
    run_as,
)

pytestmark = pytest.mark.postgres

CONCEPTS = [
    *DEFAULT_CONCEPTS,
    {"podcast", "maps", "map", "cartography", "atlas", "episode"},
    {"bike", "lock", "d-lock", "cycling", "padlock"},
    {"cello", "music", "lessons"},
]


@pytest.fixture
def fake(settings_env) -> FakeLLM:
    settings_env.setenv("EMBEDDING_MODEL", EMBED_MODEL)
    fake = FakeLLM(models=models_with_embedding(MODEL_LIST)).install()
    fake.embedder = concept_embedder(CONCEPTS)
    return fake


@pytest.fixture
def alice_id(client, alice, fake):
    ready_user(client, alice)
    return user_id_for(client, alice)


def store(url, user_id, fake, title, summary, tags=(), category=None, days_ago=0) -> str:
    async def work(session, user, settings, http_client):
        outcome = await store_thought(
            session,
            user,
            title=title,
            summary=summary,
            tags=list(tags),
            category=category,
            settings=settings,
            http_client=http_client,
        )
        return outcome.thought.id

    thought_id = run_as(url, user_id, fake, work)
    if days_ago:
        set_created(url, thought_id, datetime.now(UTC) - timedelta(days=days_ago))
    return str(thought_id)


def set_created(url, thought_id, when: datetime) -> None:
    async def work(session):
        await session.execute(
            update(Thought).where(Thought.id == uuid.UUID(str(thought_id))).values(created_at=when)
        )
        await session.commit()

    run_db(url, work)


def seed(url, user_id, fake) -> dict[str, str]:
    """A year-old podcast idea, a bike lock task, a grocery task, and a dentist note."""
    return {
        "podcast": store(
            url,
            user_id,
            fake,
            "Podcast about maps",
            "An episode series on old maps and how atlas makers worked.",
            tags=["podcast"],
            category="idea",
            days_ago=365,
        ),
        "lock": store(
            url, user_id, fake, "Buy new bike lock", "A strong D-lock for the bike.",
            tags=["bike"], category="task",
        ),
        "milk": store(
            url, user_id, fake, "Buy oat milk", "Oat milk from the shop.",
            tags=["groceries"], category="task", days_ago=30,
        ),
        "dentist": store(
            url, user_id, fake, "Dentist", "Book a check-up before October.",
            tags=["health"], category="note",
        ),
    }


def new_part(title, summary, tags=(), category="idea", add_to=None, new=False) -> ProposalPart:
    return ProposalPart(
        title=title, summary=summary, tags=list(tags), category=category, add_to=add_to, new=new
    )


def run_check(url, user_id, fake, parts, *, config=None, again=False):
    async def work(session, user, settings, http_client):
        return await check_parts(
            session,
            user,
            parts,
            None,
            config=config or get_chat_config(),
            settings=settings,
            again=again,
            http_client=http_client,
        )

    return run_as(url, user_id, fake, work)


def candidate_titles(part_check) -> list[str]:
    return [candidate.thought.title for candidate in part_check.candidates]


# --- 3.1: layer 1 ---


def test_three_new_parts_make_one_embedding_call(test_database_url, fake, alice_id):
    seed(test_database_url, alice_id, fake)
    fake.embed_requests.clear()

    check = run_check(
        test_database_url,
        alice_id,
        fake,
        [
            new_part("Cartography podcast", "A podcast on maps.", ["podcast"]),
            new_part("Oat milk", "Buy oat milk again.", ["groceries"], category="task"),
            new_part("Cello lessons", "Find a cello teacher.", ["music"]),
        ],
    )

    [request] = fake.embed_requests
    # Each query is embedded as a head entry is, with no query instruction.
    assert request["input"] == [
        "Cartography podcast\n#podcast\nA podcast on maps.",
        "Oat milk\n#groceries\nBuy oat milk again.",
        "Cello lessons\n#music\nFind a cello teacher.",
    ]
    assert candidate_titles(check.parts[0]) == ["Podcast about maps"]
    assert candidate_titles(check.parts[1]) == ["Buy oat milk"]
    assert candidate_titles(check.parts[2]) == []


def test_results_match_the_existing_search_for_the_same_query(test_database_url, fake, alice_id):
    seed(test_database_url, alice_id, fake)
    query = "maps podcast bike"
    config = get_chat_config().search

    async def work(session, user, settings, http_client):
        searched = await search_thoughts(
            session, user, query, settings=settings, http_client=http_client
        )
        index = (
            await session.execute(select(SearchIndex).where(SearchIndex.user_id == user.id))
        ).scalar_one()
        # The search embeds the query with the model's query instruction.
        vector = fake.embedder(config.query_instruction_for(EMBED_MODEL) + query)
        by_vector = await search_by_vector(
            session,
            user,
            query,
            index=index,
            vector=vector,
            min_similarity=config.min_similarity_for(EMBED_MODEL),
            limit=config.limit,
            config=config,
        )
        return searched, by_vector

    searched, by_vector = run_as(test_database_url, alice_id, fake, work)

    assert len(searched.hits) >= 2
    assert [(hit.thought.id, hit.similarity, hit.keyword_rank) for hit in by_vector.hits] == [
        (hit.thought.id, hit.similarity, hit.keyword_rank) for hit in searched.hits
    ]
    assert by_vector.total == searched.total


def test_age_does_not_change_the_order(test_database_url, fake, alice_id):
    url = test_database_url
    close = store(url, alice_id, fake, "Podcast about maps", "An atlas episode on old maps.", ["podcast"])
    store(url, alice_id, fake, "Map shop", "A shop that sells maps.", ["shopping"])
    part = [new_part("Maps podcast", "A podcast episode on maps and atlas makers.", ["podcast"])]

    before = candidate_titles(run_check(url, alice_id, fake, part).parts[0])
    set_created(url, close, datetime.now(UTC) - timedelta(days=3 * 365))
    after = candidate_titles(run_check(url, alice_id, fake, part).parts[0])

    assert before[0] == "Podcast about maps"
    assert after == before


def test_with_no_key_the_words_half_still_returns_a_candidate(
    client, bob, test_database_url, fake
):
    # Bob saved no key: his thoughts have no entries and no index.
    bob_id = user_id_for(client, bob)
    store(test_database_url, bob_id, fake, "Buy oat milk", "From the shop.", ["groceries"], "task")
    store(test_database_url, bob_id, fake, "Dentist", "Book a check-up.", ["health"], "note")
    fake.embed_requests.clear()

    check = run_check(
        test_database_url, bob_id, fake, [new_part("Oat milk", "Get some.", category="task")]
    )

    assert candidate_titles(check.parts[0]) == ["Buy oat milk"]
    assert check.parts[0].strong is None
    assert fake.embed_requests == []


def test_with_the_key_removed_the_words_half_still_runs(
    client, alice, test_database_url, fake, alice_id
):
    seed(test_database_url, alice_id, fake)
    assert client.delete("/api/providers/nebius/key", headers=alice).status_code == 204

    check = run_check(
        test_database_url,
        alice_id,
        fake,
        [new_part("Bike lock", "Which colour.", category="task")],
    )

    assert candidate_titles(check.parts[0]) == ["Buy new bike lock"]
    assert check.parts[0].candidates[0].similarity is None


def test_a_model_with_no_rule_gets_working_cut_offs(test_database_url, fake, alice_id):
    seed(test_database_url, alice_id, fake)
    shipped = get_chat_config()
    config = replace(
        shipped, search=replace(shipped.search, similarity_rules=(), query_instructions=())
    )

    async def limits(session, user, settings, http_client):
        index = (
            await session.execute(select(SearchIndex).where(SearchIndex.user_id == user.id))
        ).scalar_one()
        return cutoffs(index, config)

    found = run_as(test_database_url, alice_id, fake, limits)
    check = run_check(
        test_database_url,
        alice_id,
        fake,
        [new_part("Maps podcast", "Episodes on maps.", ["podcast"]), new_part("Cello", "Lessons.")],
        config=config,
    )

    # No rule names the model: the default search cut-off sets them.
    assert (found.candidate, found.strong) == pytest.approx((0.25, 0.35))
    assert candidate_titles(check.parts[0]) == ["Podcast about maps"]
    assert check.parts[0].strong.thought.title == "Podcast about maps"
    assert candidate_titles(check.parts[1]) == []


def test_the_thoughts_other_parts_add_to_are_no_candidates(test_database_url, fake, alice_id):
    ids = seed(test_database_url, alice_id, fake)

    async def work(session, user, settings, http_client):
        return await find_similar(
            session,
            user,
            [Query("Maps podcast", ["podcast"], "Episodes on maps.")],
            config=get_chat_config(),
            settings=settings,
            exclude={uuid.UUID(ids["podcast"])},
            http_client=http_client,
        )

    found, _ = run_as(test_database_url, alice_id, fake, work)

    assert found == [[]]


# --- 3.3: layers 2 and 3 in the turn ---


def events_of(response, name: str) -> list[dict]:
    return [data for event, data in parse_events(response.text) if event == name]


def tool_summaries(response) -> list[str]:
    return [event["summary"] for event in events_of(response, "tool") if event["phase"] == "end"]


def tool_results(request: dict) -> list[str]:
    return [m["content"] for m in request["messages"] if m["role"] == "tool"]


def propose_round(*thoughts, call_id="call_1") -> list:
    return tool_call_chunks(
        "propose_thought", json.dumps({"thoughts": list(thoughts)}), call_id=call_id
    )


def podcast_args(**fields) -> dict:
    return {
        "title": "Cartography podcast",
        "summary": "A podcast on cartography: how old maps and atlas makers worked.",
        "tags": ["podcast"],
        "category": "idea",
        **fields,
    }


def stored_rows(url, conversation_id):
    async def work(session):
        conversation_uuid = uuid.UUID(conversation_id)
        messages = list(
            (
                await session.execute(
                    select(Message)
                    .where(Message.conversation_id == conversation_uuid)
                    .order_by(Message.position)
                )
            ).scalars()
        )
        proposals = list(
            (
                await session.execute(
                    select(Proposal).where(Proposal.conversation_id == conversation_uuid)
                )
            ).scalars()
        )
        return messages, proposals

    return run_db(url, work)


@pytest.fixture
def seeded(client, alice, test_database_url, fake, alice_id):
    ids = seed(test_database_url, alice_id, fake)
    conversation_id = seed_conversation(
        test_database_url, client, alice, messages=("I want to make a podcast", "On what?")
    )
    fake.embed_requests.clear()
    return ids, conversation_id


def test_candidates_cause_no_proposal_and_the_second_call_adds_to_one(
    client, alice, test_database_url, fake, seeded
):
    ids, conversation_id = seeded
    fake.queue(
        propose_round(podcast_args()),
        propose_round(podcast_args(add_to="T1"), call_id="call_2"),
        text_chunks("Ready to check."),
    )

    response = chat(client, alice, "on cartography and old maps", conversation_id)

    assert response.status_code == 200, response.text
    assert tool_summaries(response) == ["Checked for similar thoughts", "Proposed a thought to file"]
    [proposal] = events_of(response, "proposal")
    assert proposal["parts"][0]["add_to"] == ids["podcast"]
    # The candidate round's result lists the candidate by ref, and no id.
    [listing] = tool_results(fake.chat_requests[1])
    assert listing.startswith("Nothing was proposed yet")
    assert "Similar to “Cartography podcast”:\nT1 · Podcast about maps · filed " in listing
    assert ids["podcast"] not in listing and REPEATED_TASK not in listing
    # The next round must propose again; the round after it is free.
    assert fake.chat_requests[1]["tool_choice"] == forced_tool("propose_thought")
    assert "tool_choice" not in fake.chat_requests[2]
    # One embedding call: the second call adds to T1, so it is not checked.
    assert len(fake.embed_requests) == 1
    messages, proposals = stored_rows(test_database_url, conversation_id)
    [candidate_message] = [m for m in messages if m.role == "tool" and "similar" in (m.details or {})]
    assert [item["id"] for item in candidate_message.details["similar"]] == [ids["podcast"]]
    assert len(proposals) == 1


def test_the_second_call_is_shown_unchecked_with_its_strong_match_named(
    client, alice, test_database_url, fake, seeded
):
    ids, conversation_id = seeded
    fake.queue(
        propose_round(podcast_args()),
        # The model keeps it new, without saying so: it is shown all the same.
        propose_round(podcast_args(), call_id="call_2"),
        text_chunks("Ready to check."),
    )

    response = chat(client, alice, "on cartography and old maps", conversation_id)

    assert tool_summaries(response) == ["Checked for similar thoughts", "Proposed a thought to file"]
    [proposal] = events_of(response, "proposal")
    [stored] = proposal["parts"]
    assert stored["add_to"] is None
    # The payload names the match as it is now (task 4.2).
    assert (stored["similar"]["thought_id"], stored["similar"]["title"]) == (
        ids["podcast"],
        "Podcast about maps",
    )
    # The second call ran layer 1 again for the strong match only.
    assert len(fake.embed_requests) == 2


def test_a_strong_match_on_a_part_marked_new_sets_similar(
    client, alice, test_database_url, fake, seeded
):
    ids, conversation_id = seeded
    fake.queue(propose_round(podcast_args(new=True)), text_chunks("Ready."))

    response = chat(client, alice, "on cartography and old maps", conversation_id)

    assert tool_summaries(response) == ["Proposed a thought to file"]
    [proposal] = events_of(response, "proposal")
    assert proposal["parts"][0]["similar"]["thought_id"] == ids["podcast"]
    assert len(fake.embed_requests) == 1


def test_a_task_part_gets_the_repeated_task_line_and_no_similar(
    client, alice, test_database_url, fake, seeded
):
    ids, conversation_id = seeded
    milk = {"title": "Buy oat milk", "summary": "Oat milk.", "tags": ["groceries"], "category": "task"}
    fake.queue(
        propose_round(milk),
        propose_round({**milk, "new": True}, call_id="call_2"),
        text_chunks("Ready."),
    )

    response = chat(client, alice, "/push buy oat milk", conversation_id)

    assert tool_summaries(response) == ["Checked for similar thoughts", "Proposed a thought to file"]
    [listing] = tool_results(fake.chat_requests[1])
    assert "T1 · Buy oat milk · filed " in listing
    assert listing.rstrip().endswith(REPEATED_TASK)
    [proposal] = events_of(response, "proposal")
    [stored] = proposal["parts"]
    assert stored["add_to"] is None and stored["similar"] is None
    # A task is never checked for the hint: the second call embeds nothing.
    assert len(fake.embed_requests) == 1


def test_no_candidate_writes_the_proposal_at_once(client, alice, test_database_url, fake, seeded):
    _, conversation_id = seeded
    fake.queue(
        propose_round({"title": "Cello lessons", "summary": "Find a cello teacher.", "tags": [], "category": "idea"}),
        text_chunks("Ready."),
    )

    response = chat(client, alice, "I want to learn the cello", conversation_id)

    assert tool_summaries(response) == ["Proposed a thought to file"]
    [proposal] = events_of(response, "proposal")
    assert proposal["parts"][0]["similar"] is None


def four_rounds(settings_env, tmp_path) -> None:
    """Four tool rounds: the shipped chat.yaml has them since thought-status
    (design decision 11), so this only checks that it still does."""
    assert get_chat_config().tool_rounds == 4


def test_a_candidate_round_does_not_trip_the_one_proposal_rule_and_a_third_call_does(
    client, alice, test_database_url, fake, seeded, settings_env, tmp_path
):
    four_rounds(settings_env, tmp_path)
    _, conversation_id = seeded
    fake.queue(
        propose_round(podcast_args()),
        propose_round(podcast_args(add_to="T1"), call_id="call_2"),
        propose_round(podcast_args(new=True), call_id="call_3"),
        text_chunks("Ready."),
    )

    response = chat(client, alice, "on cartography and old maps", conversation_id)

    assert tool_summaries(response) == [
        "Checked for similar thoughts",
        "Proposed a thought to file",
        "Already proposed in this answer",
    ]
    assert len(events_of(response, "proposal")) == 1
    assert tool_results(fake.chat_requests[3])[-1] == ALREADY_PROPOSED
    assert events_of(response, "error") == []
    _, proposals = stored_rows(test_database_url, conversation_id)
    assert len(proposals) == 1


def test_the_round_limit_still_ends_a_looping_model(client, alice, test_database_url, fake, seeded):
    _, conversation_id = seeded
    fake.queue(
        propose_round(podcast_args()),
        propose_round(podcast_args(new=True), call_id="call_2"),
        propose_round(podcast_args(new=True), call_id="call_3"),
        propose_round(podcast_args(new=True), call_id="call_4"),
    )

    response = chat(client, alice, "on cartography and old maps", conversation_id)

    # chat.yaml: tool_rounds 4 (thought-status design decision 11).
    assert len(fake.chat_requests) == get_chat_config().tool_rounds == 4
    [error] = events_of(response, "error")
    assert error["error"]["code"] == "tool_loop_limit"
    messages, proposals = stored_rows(test_database_url, conversation_id)
    assert len(proposals) == 1
    assert [m.error_code for m in messages if m.role == "assistant"][-1] == "tool_loop_limit"


def search_round(query: str, call_id: str) -> list:
    return tool_call_chunks("search_thoughts", json.dumps({"query": query}), call_id=call_id)


def test_a_proposal_in_the_last_round_is_shown_without_a_candidate_round(
    client, alice, test_database_url, fake, seeded
):
    """No round is left to propose again in, so the card is written at once,
    with its strong match named, before the round limit ends the turn."""
    ids, conversation_id = seeded
    fake.queue(
        search_round("maps", "call_1"),
        search_round("atlas", "call_2"),
        search_round("old maps", "call_3"),
        propose_round(podcast_args(), call_id="call_4"),
    )

    response = chat(client, alice, "on cartography and old maps", conversation_id)

    assert len(fake.chat_requests) == get_chat_config().tool_rounds == 4
    assert tool_summaries(response)[-1] == "Proposed a thought to file"
    [proposal] = events_of(response, "proposal")
    [stored] = proposal["parts"]
    assert stored["add_to"] is None
    assert stored["similar"]["thought_id"] == ids["podcast"]
    [error] = events_of(response, "error")
    assert error["error"]["code"] == "tool_loop_limit"
    _, proposals = stored_rows(test_database_url, conversation_id)
    assert len(proposals) == 1


def test_two_parts_that_match_one_thought_name_it_on_one_card_only(
    client, alice, test_database_url, fake, seeded
):
    """Two parts of one proposal never add to one thought, so the hint names
    a thought on one part only."""
    ids, conversation_id = seeded
    atlas = podcast_args(
        title="Atlas podcast",
        summary="A podcast on atlas makers and their maps.",
        new=True,
    )
    fake.queue(propose_round(podcast_args(new=True), atlas), text_chunks("Ready."))

    response = chat(client, alice, "on cartography and old maps, and atlas makers", conversation_id)

    [proposal] = events_of(response, "proposal")
    named = [p["similar"]["thought_id"] for p in proposal["parts"] if p["similar"] is not None]
    assert named == [ids["podcast"]]


def test_a_card_confirmed_while_the_turn_runs_does_not_renumber_its_candidates(
    client, alice, test_database_url, fake, seeded, monkeypatch
):
    """The user confirms an older card after the turn stored its tool call and
    before it numbers the candidates. The card counts after the candidate
    message, so the ref the model is shown for a candidate is the one every
    later load gives it, and the model's add_to names that thought."""
    from app.chat import turn as turn_module
    from app.chat.conversations import next_position
    from tests.chat_helpers import part, seed_proposal

    ids, conversation_id = seeded
    older = seed_proposal(
        test_database_url, conversation_id, [part(title="Dentist")], position=1, hold=False
    )
    real_refs_for = turn_module.refs_for
    confirmed = []

    async def confirm_first(session, conversation, *args, **kwargs):
        if not confirmed:
            # As confirm_proposal leaves it: the part names the thought, seen now.
            proposal = await session.get(Proposal, uuid.UUID(older))
            seen = await next_position(session, conversation)
            proposal.parts = [
                {**proposal.parts[0], "thought_id": ids["dentist"], "seen_position": seen}
            ]
            await session.commit()
            confirmed.append(seen)
        return await real_refs_for(session, conversation, *args, **kwargs)

    monkeypatch.setattr(turn_module, "refs_for", confirm_first)
    fake.queue(
        propose_round(podcast_args()),
        propose_round(podcast_args(add_to="T1"), call_id="call_2"),
        text_chunks("Ready."),
    )

    response = chat(client, alice, "on cartography and old maps", conversation_id)

    assert response.status_code == 200, response.text
    [listing] = tool_results(fake.chat_requests[1])
    assert "T1 · Podcast about maps · filed " in listing
    [proposal] = events_of(response, "proposal")
    assert proposal["parts"][0]["add_to"] == ids["podcast"]
    # Every later load numbers the candidate as the model was shown it.
    messages, _ = stored_rows(test_database_url, conversation_id)

    async def load(session):
        conversation = await session.get(Conversation, uuid.UUID(conversation_id))
        return await real_refs_for(session, conversation)

    refs = run_db(test_database_url, load)
    assert refs.ref_of(uuid.UUID(ids["podcast"])) == "T1"
    assert refs.ref_of(uuid.UUID(ids["dentist"])) is not None
    [candidate_message] = [m for m in messages if m.role == "tool" and "similar" in (m.details or {})]
    assert candidate_message.position == confirmed[0]


# --- 3.3: layers 2 and 3 in the offer ---


def offer(client, headers, conversation_id):
    return client.post(f"/api/conversations/{conversation_id}/proposal", headers=headers)


def asked(*thoughts):
    return completion(None, tool_calls=[tool_call("propose_thought", {"thoughts": list(thoughts)})])


def system_notes(request: dict) -> list[str]:
    return [m["content"] for m in request["messages"] if m["role"] == "system"]


@pytest.fixture
def podcast_talk(client, alice, test_database_url, fake, alice_id):
    ids = seed(test_database_url, alice_id, fake)
    conversation_id = seed_conversation(
        test_database_url,
        client,
        alice,
        messages=("a podcast on cartography and old maps?", "Sounds good.", "with atlas makers", "Yes."),
    )
    fake.embed_requests.clear()
    return ids, conversation_id


def test_the_offer_asks_again_with_the_candidates(client, alice, fake, podcast_talk):
    ids, conversation_id = podcast_talk
    fake.queue(asked(podcast_args()), asked(podcast_args(add_to="T1")))

    offered = offer(client, alice, conversation_id).json()["proposal"]

    assert len(fake.chat_requests) == 2
    note = system_notes(fake.chat_requests[1])[-1]
    assert note.startswith("Nothing was proposed yet")
    assert "T1 · Podcast about maps · filed " in note
    assert offered["parts"][0]["add_to"] == ids["podcast"]
    assert offered["parts"][0]["title"] == "Podcast about maps"


def test_the_offer_makes_one_call_without_candidates(client, alice, fake, podcast_talk):
    _, conversation_id = podcast_talk
    fake.queue(asked({"title": "Cello", "summary": "Learn the cello.", "tags": [], "category": "idea"}))

    offered = offer(client, alice, conversation_id).json()["proposal"]

    assert len(fake.chat_requests) == 1
    assert offered["parts"][0]["title"] == "Cello"


def test_the_offer_names_a_strong_match_on_a_part_kept_new(
    client, alice, fake, test_database_url, podcast_talk
):
    ids, conversation_id = podcast_talk
    fake.queue(asked(podcast_args()), asked(podcast_args(new=True)))

    offered = offer(client, alice, conversation_id).json()["proposal"]

    assert len(fake.chat_requests) == 2
    assert offered["parts"][0]["title"] == "Cartography podcast"
    _, [proposal] = stored_rows(test_database_url, conversation_id)
    assert proposal.parts[0]["similar"] == {"thought_id": ids["podcast"]}


def test_a_decline_after_the_candidates_offers_nothing(
    client, alice, fake, test_database_url, podcast_talk
):
    _, conversation_id = podcast_talk
    fake.queue(asked(podcast_args()), completion("nothing"))

    assert offer(client, alice, conversation_id).json() == {"proposal": None}

    assert len(fake.chat_requests) == 2
    _, proposals = stored_rows(test_database_url, conversation_id)
    assert proposals == []


def test_a_first_decline_makes_no_check(client, alice, fake, test_database_url, podcast_talk):
    _, conversation_id = podcast_talk
    fake.queue(completion("nothing"))

    assert offer(client, alice, conversation_id).json() == {"proposal": None}

    assert len(fake.chat_requests) == 1 and fake.embed_requests == []
