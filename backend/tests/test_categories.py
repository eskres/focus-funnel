"""Categories in settings (push-and-pull task 2.1)."""

import uuid

from sqlalchemy import select

from app.models import Thought
from tests.chat_helpers import error_code, run_db, user_id_for

FIXED = ["task", "idea", "decision", "note", "reference"]


def add(client, headers, name):
    return client.post("/api/settings/categories", headers=headers, json={"name": name})


def test_the_list_returns_fixed_and_added_separately(client, alice):
    assert client.get("/api/settings/categories", headers=alice).json() == {"fixed": FIXED, "added": []}

    response = add(client, alice, "recipe")

    assert response.status_code == 201, response.text
    assert response.json() == {"fixed": FIXED, "added": ["recipe"]}
    assert client.get("/api/settings/categories", headers=alice).json()["added"] == ["recipe"]


def test_a_name_is_trimmed_and_lowercased(client, alice):
    assert add(client, alice, " Recipe").json()["added"] == ["recipe"]


def test_a_fixed_kind_or_a_repeated_name_is_refused(client, alice):
    add(client, alice, "recipe")
    for name in ("Idea", "RECIPE "):
        response = add(client, alice, name)
        assert response.status_code == 409
        assert error_code(response) == "category_exists"
    assert client.get("/api/settings/categories", headers=alice).json()["added"] == ["recipe"]


def test_an_empty_or_too_long_name_is_refused_naming_the_field(client, alice):
    for name in ("  ", "x" * 31):
        response = add(client, alice, name)
        assert response.status_code == 422
        assert error_code(response) == "validation_error"
        assert response.json()["error"]["message"].startswith("name:")
    assert add(client, alice, "x" * 30).status_code == 201


def test_a_21st_category_is_refused(client, alice):
    for number in range(20):
        assert add(client, alice, f"kind {number}").status_code == 201
    response = add(client, alice, "one more")
    assert response.status_code == 422
    assert response.json()["error"]["message"].startswith("name:")
    assert len(client.get("/api/settings/categories", headers=alice).json()["added"]) == 20


def test_a_fixed_kind_cannot_be_removed(client, alice):
    response = client.delete("/api/settings/categories/idea", headers=alice)
    assert response.status_code == 422
    assert error_code(response) == "validation_error"


def test_removing_an_unknown_category_is_not_found(client, alice):
    response = client.delete("/api/settings/categories/recipe", headers=alice)
    assert response.status_code == 404
    assert error_code(response) == "not_found"


def test_removing_an_added_category_leaves_thoughts_with_it_unchanged(client, alice, test_database_url):
    add(client, alice, "recipe")
    user_id = uuid.UUID(user_id_for(client, alice))

    async def seed(session):
        thought = Thought(user_id=user_id, title="Pancakes", summary="Eggs, milk, flour.", tags=[], category="recipe")
        session.add(thought)
        await session.commit()
        return thought.id

    thought_id = run_db(test_database_url, seed)

    assert client.delete("/api/settings/categories/Recipe", headers=alice).status_code == 204

    assert client.get("/api/settings/categories", headers=alice).json()["added"] == []

    async def category(session):
        return (await session.execute(select(Thought.category).where(Thought.id == thought_id))).scalar_one()

    assert run_db(test_database_url, category) == "recipe"


def test_another_user_sees_none_of_them(client, alice, bob):
    add(client, alice, "recipe")
    assert client.get("/api/settings/categories", headers=bob).json() == {"fixed": FIXED, "added": []}
    assert client.delete("/api/settings/categories/recipe", headers=bob).status_code == 404
    assert add(client, bob, "recipe").status_code == 201
