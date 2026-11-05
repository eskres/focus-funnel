"""One category check for confirm and edit (thought-editing task 1.1)."""

import uuid

import pytest

from app.errors import ApiError
from app.models import User
from app.thoughts.categories import check_category
from tests.chat_helpers import run_db, user_id_for


def checked(url, user_id, value, keep=None):
    """check_category's answer, or the ApiError it raises."""

    async def work(session):
        user = await session.get(User, uuid.UUID(user_id))
        try:
            return await check_category(session, user, value, keep=keep)
        except ApiError as error:
            return error

    return run_db(url, work)


@pytest.fixture
def alice_id(client, alice):
    user_id = user_id_for(client, alice)
    response = client.post("/api/settings/categories", headers=alice, json={"name": "recipe"})
    assert response.status_code == 201, response.text
    return user_id


def test_a_fixed_kind_is_accepted_cleaned(test_database_url, alice_id):
    assert checked(test_database_url, alice_id, "idea") == "idea"
    assert checked(test_database_url, alice_id, "  Idea ") == "idea"


def test_an_added_category_is_accepted(test_database_url, alice_id):
    assert checked(test_database_url, alice_id, "Recipe") == "recipe"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_empty_means_none(test_database_url, alice_id, value):
    assert checked(test_database_url, alice_id, value) is None


def test_keep_accepts_a_removed_category(client, alice, test_database_url, alice_id):
    assert client.delete("/api/settings/categories/recipe", headers=alice).status_code == 204

    refused = checked(test_database_url, alice_id, "recipe")
    assert isinstance(refused, ApiError)
    assert checked(test_database_url, alice_id, "Recipe", keep="recipe") == "recipe"


@pytest.mark.parametrize("keep", [None, "trip"])
def test_another_name_is_refused_naming_the_category(test_database_url, alice_id, keep):
    refused = checked(test_database_url, alice_id, "Holiday", keep=keep)

    assert isinstance(refused, ApiError)
    assert refused.status_code == 422
    assert refused.code == "validation_error"
    assert refused.message == "category: 'holiday' is not one of your categories"


def test_another_users_category_is_refused(client, bob, test_database_url, alice_id):
    bob_id = user_id_for(client, bob)
    refused = checked(test_database_url, bob_id, "recipe")
    assert isinstance(refused, ApiError) and refused.message.startswith("category:")
