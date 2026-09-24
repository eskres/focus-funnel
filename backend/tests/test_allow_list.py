import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import Identity, check_allowed, get_current_user, get_jwks_cache
from app.errors import ApiError, ErrorCode, register_error_handlers
from app.models import User
from tests.conftest import count_users


@pytest.fixture
def client_with_list(test_database_url, jwks_cache, settings_env):
    def build(allowed: str | None) -> TestClient:
        if allowed is None:
            settings_env.delenv("AUTH_ALLOWED_EMAILS", raising=False)
        else:
            settings_env.setenv("AUTH_ALLOWED_EMAILS", allowed)
        test_app = FastAPI()
        register_error_handlers(test_app)

        @test_app.get("/whoami")
        async def whoami(user: User = Depends(get_current_user)):
            return {"subject": user.subject}

        test_app.dependency_overrides[get_jwks_cache] = lambda: jwks_cache
        return TestClient(test_app)

    return build


def call(client, token):
    return client.get("/whoami", headers={"Authorization": f"Bearer {token}"})


def assert_refused(response, url, subject):
    assert response.status_code == 403
    assert response.json()["error"]["code"] == ErrorCode.NOT_ALLOWED
    assert count_users(url, subject) == 0


def test_listed_address_gets_in(client_with_list, make_token, test_database_url):
    client = client_with_list("ana@example.org, bo@other.org")
    token = make_token(sub="ana", email="Ana@Example.org", email_verified=True)
    assert call(client, token).status_code == 200
    assert count_users(test_database_url, "ana") == 1


def test_listed_domain_gets_in(client_with_list, make_token):
    client = client_with_list("@example.org")
    token = make_token(sub="ana", email="ana@example.org", email_verified=True)
    assert call(client, token).status_code == 200


def test_domain_entry_does_not_match_a_subdomain_or_suffix(client_with_list, make_token, test_database_url):
    client = client_with_list("@example.org")
    for sub, email in [("s1", "ana@evil.example.org"), ("s2", "ana@notexample.org")]:
        token = make_token(sub=sub, email=email, email_verified=True)
        assert_refused(call(client, token), test_database_url, sub)


def test_unlisted_address_is_refused_without_a_user_row(client_with_list, make_token, test_database_url):
    client = client_with_list("ana@example.org")
    token = make_token(sub="eve", email="eve@example.org", email_verified=True)
    assert_refused(call(client, token), test_database_url, "eve")


@pytest.mark.parametrize("verified", [False, None, "true"])
def test_unverified_address_is_refused(client_with_list, make_token, test_database_url, verified):
    client = client_with_list("ana@example.org")
    token = make_token(sub="ana", email="ana@example.org", email_verified=verified)
    assert_refused(call(client, token), test_database_url, "ana")


def test_missing_email_claim_is_refused(client_with_list, make_token, test_database_url):
    client = client_with_list("ana@example.org")
    assert_refused(call(client, make_token(sub="ana")), test_database_url, "ana")


def test_no_list_lets_anyone_in(client_with_list, make_token, test_database_url):
    client = client_with_list(None)
    assert call(client, make_token(sub="anyone")).status_code == 200
    assert count_users(test_database_url, "anyone") == 1


def test_removing_an_address_refuses_the_next_call(client_with_list, make_token):
    token = make_token(sub="ana", email="ana@example.org", email_verified=True)
    assert call(client_with_list("ana@example.org"), token).status_code == 200

    # The operator changes the list and restarts the server.
    from app.config import get_settings

    get_settings.cache_clear()
    response = call(client_with_list("bo@example.org"), token)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == ErrorCode.NOT_ALLOWED


def test_check_allowed_directly():
    allowed = frozenset({"ana@example.org", "@team.io"})
    check_allowed(Identity("i", "s", "ana@example.org", True), allowed)
    check_allowed(Identity("i", "s", "x@team.io", True), allowed)
    check_allowed(Identity("i", "s", None, False), None)
    with pytest.raises(ApiError):
        check_allowed(Identity("i", "s", "x@team.io", False), allowed)
