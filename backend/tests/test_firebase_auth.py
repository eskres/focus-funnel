"""Firebase ID token checks, with a local key standing in for Google's key set."""

import time

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import FIREBASE_JWKS_URL, bearer_token, get_authenticator, get_jwks_cache
from app.errors import ErrorCode, register_error_handlers

PROJECT = "focus-funnel"


@pytest.fixture
def firebase_env(settings_env):
    settings_env.setenv("AUTH_MODE", "firebase")
    settings_env.delenv("OIDC_ISSUER")
    settings_env.delenv("OIDC_CLIENT_ID")
    settings_env.setenv("FIREBASE_PROJECT_ID", PROJECT)
    return settings_env


@pytest.fixture
def client(firebase_env, jwks_cache):
    test_app = FastAPI()
    register_error_handlers(test_app)

    @test_app.get("/identity")
    async def identity(token: str = Depends(bearer_token), authenticator=Depends(get_authenticator)):
        found = await authenticator.authenticate(token)
        return {"issuer": found.issuer, "subject": found.subject, "verified": found.email_verified}

    test_app.dependency_overrides[get_jwks_cache] = lambda: jwks_cache
    return TestClient(test_app)


def firebase_token(make_token, project=PROJECT, **claims) -> str:
    return make_token(iss=f"https://securetoken.google.com/{project}", aud=project, **claims)


def call(client, token):
    return client.get("/identity", headers={"Authorization": f"Bearer {token}"})


def test_firebase_keys_come_from_google():
    assert FIREBASE_JWKS_URL == (
        "https://www.googleapis.com/service_accounts/v1/jwk/"
        "securetoken@system.gserviceaccount.com"
    )


def test_valid_token(client, make_token):
    response = call(
        client, firebase_token(make_token, sub="firebase-uid", email="a@b.org", email_verified=True)
    )
    assert response.status_code == 200
    assert response.json() == {
        "issuer": f"https://securetoken.google.com/{PROJECT}",
        "subject": "firebase-uid",
        "verified": True,
    }


def test_token_from_another_project(client, make_token):
    response = call(client, firebase_token(make_token, project="someone-elses-project"))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == ErrorCode.UNAUTHENTICATED


def test_token_with_our_issuer_but_another_audience(client, make_token):
    token = make_token(iss=f"https://securetoken.google.com/{PROJECT}", aud="other-project")
    assert call(client, token).status_code == 401


def test_expired_token(client, make_token):
    past = int(time.time()) - 3600
    response = call(client, firebase_token(make_token, iat=past - 60, exp=past))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == ErrorCode.UNAUTHENTICATED


def test_oidc_token_is_refused_in_firebase_mode(client, make_token):
    assert call(client, make_token()).status_code == 401
