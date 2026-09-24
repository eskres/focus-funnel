"""The rebuild job (thought-storage task 7.1)."""

import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from app import reembed
from app.config import get_settings
from app.models import SearchIndex, Thought, ThoughtEmbedding, User
from app.thoughts.indexing import count_missing
from app.thoughts.search import search_thoughts
from app.thoughts.store import delete_thought, store_thought
from tests.chat_helpers import FakeLLM, MODEL_LIST, run_db, save_key, user_id_for
from tests.thought_helpers import EMBED_MODEL, models_with_embedding, run_as

pytestmark = pytest.mark.postgres

NEW_MODEL = "vendor/embed-model-2"


@pytest.fixture
def fake(settings_env) -> FakeLLM:
    settings_env.setenv("EMBEDDING_MODEL", EMBED_MODEL)
    return FakeLLM(models=models_with_embedding(MODEL_LIST)).install()


def use_model(settings_env, model: str) -> None:
    settings_env.setenv("EMBEDDING_MODEL", model)
    get_settings.cache_clear()


def store(url, user_id, fake, n: int, title="Oat milk"):
    async def work(session, user, settings, http_client):
        ids = []
        for number in range(n):
            outcome = await store_thought(
                session,
                user,
                title=f"{title} {number}",
                summary="Buy oat milk on the way home.",
                raw_text=("A long note about milk. " * 60) if number == 0 else None,
                settings=settings,
                http_client=http_client,
            )
            ids.append(outcome.thought.id)
        return ids

    return run_as(url, user_id, fake, work)


def indexes(url, user_id) -> list[SearchIndex]:
    async def work(session):
        query = select(SearchIndex).where(SearchIndex.user_id == uuid.UUID(str(user_id)))
        return list((await session.execute(query.order_by(SearchIndex.version))).scalars())

    return run_db(url, work)


def entry_count(url, index_id) -> int:
    async def work(session):
        query = select(func.count()).select_from(ThoughtEmbedding).where(
            ThoughtEmbedding.index_id == index_id
        )
        return (await session.execute(query)).scalar_one()

    return run_db(url, work)


def missing(url, user_id, index) -> int:
    return run_db(url, lambda session: count_missing(session, uuid.UUID(str(user_id)), index))


def run_job(fake, *argv) -> int:
    return asyncio.run(reembed.main(list(argv), http_client=fake.http_client()))


def test_rebuild_one_user_with_a_new_model(fake, client, alice, settings_env, test_database_url, capsys):
    save_key(client, alice)
    alice_id = user_id_for(client, alice)
    store(test_database_url, alice_id, fake, 12)
    [old] = indexes(test_database_url, alice_id)
    old_entries = entry_count(test_database_url, old.id)
    use_model(settings_env, NEW_MODEL)
    fake.embed_requests.clear()

    assert run_job(fake, "--user", alice_id) == 0

    old_after, new = indexes(test_database_url, alice_id)
    assert (old_after.status, new.status) == ("retired", "active")
    assert old_after.retired_at is not None
    assert (new.version, new.embedding_model) == (2, NEW_MODEL)
    assert missing(test_database_url, alice_id, new) == 0
    assert entry_count(test_database_url, new.id) == old_entries
    assert entry_count(test_database_url, old.id) == 0
    assert {body["model"] for body in fake.embed_requests} == {NEW_MODEL}
    assert f"{alice_id}  rebuilt  nebius {NEW_MODEL}" in capsys.readouterr().out


def test_search_uses_the_active_index_during_a_build(fake, client, alice, settings_env, test_database_url):
    save_key(client, alice)
    alice_id = user_id_for(client, alice)
    store(test_database_url, alice_id, fake, 3)
    use_model(settings_env, NEW_MODEL)

    async def start_then_search(session, user, settings, http_client):
        await reembed.start_rebuild(session, user, settings, http_client=http_client)
        fake.embed_requests.clear()
        return await search_thoughts(session, user, "milk", settings=settings, http_client=http_client)

    result = run_as(test_database_url, alice_id, fake, start_then_search)

    assert [body["model"] for body in fake.embed_requests] == [EMBED_MODEL]
    assert result.hits and result.words_only is None
    statuses = [index.status for index in indexes(test_database_url, alice_id)]
    assert statuses == ["active", "building"]


def test_changes_during_a_build_reach_the_new_index(fake, client, alice, settings_env, test_database_url):
    save_key(client, alice)
    alice_id = user_id_for(client, alice)
    first, second, _ = store(test_database_url, alice_id, fake, 3)
    use_model(settings_env, NEW_MODEL)

    async def rebuild_with_changes(session, user, settings, http_client):
        building = await reembed.start_rebuild(session, user, settings, http_client=http_client)
        added = await store_thought(
            session, user, title="Dentist", summary="Book the dentist.",
            settings=settings, http_client=http_client,
        )
        await delete_thought(session, user, second)
        await reembed.finish_rebuild(session, user, building, settings, http_client=http_client)
        return added.thought.id, building

    added, building = run_as(test_database_url, alice_id, fake, rebuild_with_changes)

    async def thoughts_in_index(session):
        query = select(ThoughtEmbedding.thought_id).where(
            ThoughtEmbedding.index_id == building.id, ThoughtEmbedding.chunk == 0
        )
        return set((await session.execute(query)).scalars())

    in_new = run_db(test_database_url, thoughts_in_index)
    assert added in in_new and first in in_new and second not in in_new
    assert [index.status for index in indexes(test_database_url, alice_id)] == ["retired", "active"]


def test_a_user_without_a_key_keeps_the_old_index(fake, client, alice, bob, settings_env, test_database_url, capsys):
    save_key(client, alice)
    save_key(client, bob, key="nb-bob-key-2222")
    alice_id, bob_id = user_id_for(client, alice), user_id_for(client, bob)
    store(test_database_url, alice_id, fake, 2)
    store(test_database_url, bob_id, fake, 2)
    assert client.delete("/api/providers/nebius/key", headers=bob).status_code == 204
    use_model(settings_env, NEW_MODEL)

    assert run_job(fake, "--all") == 1

    assert [index.status for index in indexes(test_database_url, alice_id)] == ["retired", "active"]
    [bob_index] = indexes(test_database_url, bob_id)
    assert (bob_index.status, bob_index.embedding_model) == ("active", EMBED_MODEL)
    output = capsys.readouterr()
    assert f"{bob_id}  failed  provider_key_missing" in output.out
    assert "1 user(s) failed" in output.err


def test_demo_users_and_users_without_thoughts_are_skipped(fake, client, alice, test_database_url, capsys):
    save_key(client, alice)
    alice_id = user_id_for(client, alice)

    async def add_demo_user(session):
        user = User(issuer="demo", subject=uuid.uuid4().hex)
        session.add(user)
        await session.flush()
        session.add(Thought(user_id=user.id, title="t", summary="s", tags=[]))
        await session.commit()
        return user.id

    demo_id = run_db(test_database_url, add_demo_user)

    assert run_job(fake, "--all") == 0

    out = capsys.readouterr().out
    assert f"{demo_id}  skipped  demo user" in out
    assert f"{alice_id}  skipped  no thoughts" in out
    assert indexes(test_database_url, demo_id) == []


def test_a_leftover_building_index_needs_restart(fake, client, alice, settings_env, test_database_url, capsys):
    save_key(client, alice)
    alice_id = user_id_for(client, alice)
    store(test_database_url, alice_id, fake, 2)
    use_model(settings_env, NEW_MODEL)

    async def start_only(session, user, settings, http_client):
        return (await reembed.start_rebuild(session, user, settings, http_client=http_client)).id

    leftover = run_as(test_database_url, alice_id, fake, start_only)

    assert run_job(fake, "--user", alice_id) == 1
    assert "rerun with --restart" in capsys.readouterr().out
    assert [index.status for index in indexes(test_database_url, alice_id)] == ["active", "building"]

    assert run_job(fake, "--user", alice_id, "--restart") == 0
    statuses = [(index.id == leftover, index.status) for index in indexes(test_database_url, alice_id)]
    assert statuses == [(False, "retired"), (False, "active")]


def test_unknown_user(fake, test_database_url, capsys):
    assert run_job(fake, "--user", str(uuid.uuid4())) == 2
    assert "No user with id" in capsys.readouterr().err
