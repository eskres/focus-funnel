from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.errors import ApiError, ErrorCode, register_error_handlers
from app.main import app


def make_test_app() -> FastAPI:
    test_app = FastAPI()
    register_error_handlers(test_app)

    class Body(BaseModel):
        name: str

    @test_app.post("/echo")
    async def echo(body: Body):
        return body

    @test_app.get("/api-error")
    async def api_error():
        raise ApiError(400, ErrorCode.PROVIDER_KEY_INVALID, "The provider rejected this API key.")

    @test_app.get("/boom")
    async def boom():
        raise RuntimeError("secret internal detail")

    return test_app


def assert_error_shape(response, status_code: int, code: str) -> dict:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    return body["error"]


def test_validation_failure_uses_error_format():
    client = TestClient(make_test_app())
    response = client.post("/echo", json={})
    error = assert_error_shape(response, 422, ErrorCode.VALIDATION_ERROR)
    assert "name" in error["message"]


def test_unknown_route_uses_error_format(settings_env):
    with TestClient(app) as client:
        response = client.get("/does-not-exist")
    assert_error_shape(response, 404, ErrorCode.NOT_FOUND)


def test_api_error_uses_error_format():
    client = TestClient(make_test_app())
    response = client.get("/api-error")
    error = assert_error_shape(response, 400, ErrorCode.PROVIDER_KEY_INVALID)
    assert error["message"] == "The provider rejected this API key."


def test_unexpected_error_hides_details():
    client = TestClient(make_test_app(), raise_server_exceptions=False)
    response = client.get("/boom")
    error = assert_error_shape(response, 500, ErrorCode.INTERNAL_ERROR)
    assert "secret" not in error["message"]
