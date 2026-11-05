"""The doctor command (self-hosting-setup tasks 6.1 and 6.2).

Every run injects an httpx transport for the login provider and an httpx2
transport for the providers and connectors, so no test leaves the machine.
"""

import asyncio
import base64
import json
import os
import socket
import threading
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import httpx2
import pytest
import sqlalchemy as sa
from sqlalchemy.pool import NullPool

from app import doctor
from app.config import Settings
from app.db import create_engine
from app.setup.state import hash_token
from tests.chat_helpers import PROVIDERS_FIXTURE
from tests.conftest import TEST_ISSUER
from tests.test_provider_key_migration import run_alembic
from tests.test_thought_migration import with_database

CLIENT_SECRET = "oidc-client-secret-never-printed-0123456789"
SESSION_SECRET = "session-secret-never-printed-" + "s" * 40
SETUP_TOKEN = "setup-token-never-printed-0123456789"

setup_state = sa.table(
    "setup_state",
    sa.column("id", sa.Integer()),
    sa.column("token_hash", sa.String()),
    sa.column("completed_at", sa.DateTime(timezone=True)),
)


# transports


def discovery(
    issuer: str = TEST_ISSUER, seen: list | None = None
) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
        return httpx.Response(
            200, json={"issuer": issuer, "jwks_uri": f"{issuer}/jwks"}
        )

    return httpx.MockTransport(handle)


def login_raising(
    error=httpx.ConnectError, seen: list | None = None
) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
        raise error("connection refused", request=request)

    return httpx.MockTransport(handle)


def providers_answer(
    code: int = 200,
    body=None,
    unreachable: tuple[str, ...] = (),
    seen: list | None = None,
) -> httpx2.MockTransport:
    """Answers every GET with code and body, except hosts in unreachable."""

    def handle(request: httpx2.Request) -> httpx2.Response:
        if seen is not None:
            seen.append(str(request.url))
        if request.url.host in unreachable:
            raise httpx2.ConnectError("connection refused", request=request)
        return httpx2.Response(code, json=body if body is not None else {"data": []})

    return httpx2.MockTransport(handle)


class NeverAnswers(httpx2.AsyncBaseTransport):
    async def handle_async_request(self, request):
        await asyncio.sleep(60)


class NeverAnswersHttpx(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request):
        await asyncio.sleep(60)


# running the doctor


def run_doctor(capsys, *args, login=None, http=None, **kwargs):
    code = asyncio.run(
        doctor.main(
            list(args),
            login_transport=login if login is not None else discovery(),
            http_transport=http if http is not None else providers_answer(),
            **kwargs,
        )
    )
    return code, capsys.readouterr().out


def lines(out: str) -> dict[str, list[str]]:
    """Each check id's lines, as (state, message) text."""
    found: dict[str, list[str]] = {}
    for line in out.splitlines():
        state, id, message = line.split(None, 2)
        found.setdefault(id, []).append(f"{state} {message}")
    return found


def state_of(out: str, id: str) -> str:
    return lines(out)[id][0].split()[0]


# databases


def migrated_sqlite(tmp_path, revision: str = "head") -> str:
    url = f"sqlite+aiosqlite:///{tmp_path / 'doctor.sqlite3'}"
    res = run_alembic(url, "upgrade", revision)
    assert res.returncode == 0, res.stdout + res.stderr
    return url


def execute(url: str, *statements):
    async def main():
        engine = create_engine(url, poolclass=NullPool)
        try:
            async with engine.begin() as connection:
                for statement in statements:
                    await connection.execute(statement)
        finally:
            await engine.dispose()

    asyncio.run(main())


@pytest.fixture
def env(settings_env):
    settings_env.setenv("PROVIDERS_CONFIG_PATH", str(PROVIDERS_FIXTURE))
    settings_env.setenv("OIDC_CLIENT_SECRET", CLIENT_SECRET)
    settings_env.setenv("SESSION_SECRET", SESSION_SECRET)
    settings_env.setenv("AUTH_ALLOWED_EMAILS", "ops@example.org")
    return settings_env


@pytest.fixture
def database(env, tmp_path):
    url = migrated_sqlite(tmp_path)
    env.setenv("DATABASE_URL", url)
    return url


# 6.1: settings, files, instance items, migrations, setup


def test_valid_settings_on_sqlite_print_ok_lines_and_exit_0(database, capsys):
    code, out = run_doctor(capsys)
    assert code == 0, out
    found = lines(out)
    for id in (
        "settings",
        "providers_file",
        "chat_file",
        "database",
        "encryption_key",
        "allow_list",
        "migrations",
        "login_provider",
        "provider:nebius",
        "provider:local",
    ):
        assert found[id][0].startswith("ok "), (id, out)
    assert found["database"][0].endswith("The database answers.")
    assert "failed" not in out


def test_login_is_info(database, capsys):
    _code, out = run_doctor(capsys)
    login = lines(out)["login"][0]
    assert login.startswith(
        "info OpenID Connect: issuer https://login.focus-funnel.test"
    )


def test_auth_mode_unset_fails_names_it_and_skips_what_needs_settings(
    database, env, capsys
):
    env.delenv("AUTH_MODE")
    code, out = run_doctor(capsys)
    assert code == 1
    failed = lines(out)["settings"]
    assert len(failed) == 1
    assert failed[0].startswith("failed AUTH_MODE")
    for mode in ("oidc", "firebase", "demo"):
        assert mode in failed[0]
    for id in (
        "encryption_key",
        "login",
        "allow_list",
        "custom_provider",
        "connectors",
        "setup",
        "login_provider",
        "providers",
    ):
        assert state_of(out, id) == "skipped", (id, out)
    # The database is still checked, with DATABASE_URL read directly.
    assert lines(out)["database"][0].startswith("ok ")
    assert state_of(out, "migrations") == "ok"


def test_auth_mode_error_names_the_variable_in_json(database, env, capsys):
    env.delenv("AUTH_MODE")
    _code, out = run_doctor(capsys, "--json")
    settings = [
        entry for entry in json.loads(out)["items"] if entry["id"] == "settings"
    ]
    assert settings[0]["state"] == "failed"
    assert settings[0]["settings"] == ["AUTH_MODE"]


def test_a_short_key_encryption_key_is_named_but_never_shown(database, env, capsys):
    short = base64.b64encode(os.urandom(31)).decode()
    env.setenv("KEY_ENCRYPTION_KEY", short)
    code, out = run_doctor(capsys)
    assert code == 1
    failed = lines(out)["settings"][0]
    assert failed.startswith("failed KEY_ENCRYPTION_KEY")
    assert "32 bytes" in failed
    assert short not in out
    code, out = run_doctor(capsys, "--json")
    assert code == 1
    assert short not in out
    entries = json.loads(out)["items"]
    assert {"id": "settings", "state": "failed"}.items() <= entries[0].items()
    assert entries[0]["settings"] == ["KEY_ENCRYPTION_KEY"]


@pytest.fixture
def silent_server():
    """A local TCP socket that accepts connections and never replies."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    held: list[socket.socket] = []
    stop = threading.Event()

    def accept():
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                held.append(server.accept()[0])
            except OSError:
                continue

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    yield server.getsockname()[1]
    stop.set()
    thread.join()
    for connection in held:
        connection.close()
    server.close()


def test_a_database_that_never_replies_fails_within_6_seconds(
    env, silent_server, capsys
):
    env.setenv(
        "DATABASE_URL", f"postgresql+asyncpg://ff:pw@127.0.0.1:{silent_server}/ff"
    )
    started = time.monotonic()
    code, out = run_doctor(capsys)
    elapsed = time.monotonic() - started
    assert elapsed < 6, elapsed
    assert code == 1
    database = lines(out)["database"][0]
    assert database.startswith("failed ")
    assert "did not answer within 5 seconds" in database
    assert state_of(out, "migrations") == "skipped"


def closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_a_closed_port_could_not_connect(env, capsys):
    env.setenv(
        "DATABASE_URL", f"postgresql+asyncpg://ff:pw@127.0.0.1:{closed_port()}/ff"
    )
    code, out = run_doctor(capsys)
    assert code == 1
    database = lines(out)["database"][0]
    assert database.startswith("failed ")
    assert "Could not connect to the database" in database


def test_the_database_line_masks_the_password(env, capsys):
    port = closed_port()
    env.setenv(
        "DATABASE_URL",
        f"postgresql+asyncpg://ff:hunter2-userinfo@127.0.0.1:{port}/ff?password=hunter3-query",
    )
    for args in ((), ("--json",)):
        _code, out = run_doctor(capsys, *args)
        assert "hunter2-userinfo" not in out
        assert "hunter3-query" not in out
        assert "password=" not in out
    _code, out = run_doctor(capsys)
    assert (
        f"postgresql+asyncpg://ff:***@127.0.0.1:{port}/ff:" in lines(out)["database"][0]
    )


def test_a_database_one_migration_behind_is_a_warning(env, tmp_path, capsys):
    script, head = doctor.script_head()
    previous = script.get_revision(head).down_revision
    env.setenv("DATABASE_URL", migrated_sqlite(tmp_path, previous))
    code, out = run_doctor(capsys)
    migrations = lines(out)["migrations"][0]
    assert migrations.startswith("warning ")
    assert "1 migration behind" in migrations
    assert "the backend applies them when it starts" in migrations
    assert code == 0, out


@pytest.mark.postgres
def test_postgres_not_migrated_yet_warns_and_exits_0(env, capsys):
    url, drop = with_database("ff08_doctor_fresh")
    try:
        env.setenv("DATABASE_URL", url)
        env.setenv("SETUP_WIZARD", "true")
        code, out = run_doctor(capsys)
        found = lines(out)
        for id in ("database", "migrations", "setup"):
            assert found[id][0].startswith("warning "), (id, out)
            assert "not migrated yet" in found[id][0], (id, out)
        assert "pgvector" in found["database"][0]
        assert "failed" not in out
        assert code == 0
    finally:
        drop()


def test_setup_open_finished_off_not_used_and_record_missing(database, env, capsys):
    env.setenv("SETUP_WIZARD", "true")
    _code, out = run_doctor(capsys)
    assert lines(out)["setup"][0].startswith("info Setup is open.")
    assert "Restart the backend to print a new setup token" in out

    execute(database, setup_state.update().values(completed_at=datetime.now(UTC)))
    _code, out = run_doctor(capsys)
    assert lines(out)["setup"][0] == "ok Setup is finished."

    env.setenv("SETUP_WIZARD", "false")
    _code, out = run_doctor(capsys)
    assert lines(out)["setup"][0] == "info Setup is off (SETUP_WIZARD=false)."

    env.setenv("AUTH_MODE", "demo")
    for name in ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET"):
        env.delenv(name)
    _code, out = run_doctor(capsys)
    assert lines(out)["setup"][0] == "info Setup is not used in demo mode."

    env.setenv("AUTH_MODE", "oidc")
    env.setenv("OIDC_ISSUER", TEST_ISSUER)
    env.setenv("OIDC_CLIENT_ID", "focus-funnel-test-client")
    env.setenv("SETUP_WIZARD", "true")
    execute(database, setup_state.delete())
    _code, out = run_doctor(capsys)
    setup = lines(out)["setup"][0]
    assert setup.startswith("warning ")
    assert "setup record is missing, so setup is closed" in setup


class McpSettings(Settings):
    # A stand-in for the MCP settings that mcp-connectors adds to Settings,
    # until this branch is restacked onto it.
    mcp_enabled: bool = False
    mcp_user_connectors: bool = False


def test_a_connector_with_an_unset_auth_env_fails_the_config_files(
    database, env, capsys
):
    env.setenv("MCP_ENABLED", "true")
    env.delenv("GITHUB_MCP_TOKEN", raising=False)

    def load_connectors():
        # mcp-connectors' loader refuses an unset auth.env with a
        # ConnectorConfigError (a ValueError) naming the connector and variable.
        raise ValueError(
            "Connector 'github' 'auth.env': the environment variable GITHUB_MCP_TOKEN is not set"
        )

    code, out = run_doctor(
        capsys, load_settings=McpSettings, load_connectors=load_connectors
    )
    assert code == 1
    line = lines(out)["connectors_file"][0]
    assert line.startswith("failed ")
    assert "github" in line
    assert "GITHUB_MCP_TOKEN" in line
    assert state_of(out, "connectors") == "skipped"


def test_no_output_holds_a_secret(database, env, capsys):
    key = base64.b64encode(os.urandom(32)).decode()
    env.setenv("KEY_ENCRYPTION_KEY", key)
    env.setenv("SETUP_WIZARD", "true")
    token_hash = hash_token(SETUP_TOKEN)
    execute(database, setup_state.update().values(token_hash=token_hash))
    for args in ((), ("--json",)):
        _code, out = run_doctor(capsys, *args)
        for secret in (
            key,
            base64.b64decode(key).hex(),
            SESSION_SECRET,
            CLIENT_SECRET,
            SETUP_TOKEN,
            token_hash,
        ):
            assert secret not in out
    assert "KEY_ENCRYPTION_KEY" in out  # named, never shown


def test_the_frontend_line_points_at_its_logs(database, capsys):
    _code, out = run_doctor(capsys)
    assert lines(out)["frontend"] == [
        (
            "info The frontend checks its own settings when it starts: "
            "see docker compose logs frontend."
        )
    ]


# 6.2: the login provider, providers, and connectors


def test_a_discovery_document_with_another_issuer_fails(database, capsys):
    code, out = run_doctor(capsys, login=discovery("https://elsewhere.example.org"))
    assert code == 1
    line = lines(out)["login_provider"][0]
    assert line.startswith("failed ")
    assert "https://elsewhere.example.org" in line
    assert "OIDC_ISSUER" in line


@pytest.mark.parametrize(
    ("configured", "named"),
    [(f"{TEST_ISSUER}/", TEST_ISSUER), (TEST_ISSUER, f"{TEST_ISSUER}/")],
)
def test_an_issuer_differing_only_by_a_trailing_slash_fails(
    database, env, capsys, configured, named
):
    # The backend checks a token's iss against OIDC_ISSUER exactly, so a
    # trailing slash on one side only fails every login.
    env.setenv("OIDC_ISSUER", configured)
    code, out = run_doctor(capsys, login=discovery(named))
    assert code == 1
    line = lines(out)["login_provider"][0]
    assert line.startswith("failed ")
    assert "OIDC_ISSUER" in line


def test_a_discovery_fetch_that_cannot_connect_names_the_url(database, capsys):
    seen: list[str] = []
    code, out = run_doctor(capsys, login=login_raising(seen=seen))
    assert code == 1
    line = lines(out)["login_provider"][0]
    assert line.startswith("failed ")
    assert "ConnectError" in line
    assert f"{TEST_ISSUER}/.well-known/openid-configuration" in line
    assert seen == [f"{TEST_ISSUER}/.well-known/openid-configuration"]


def test_the_discovery_url_is_the_internal_one_when_set(database, env, capsys):
    env.setenv("OIDC_INTERNAL_URL", "http://pocket-id:1411")
    seen: list[str] = []
    _code, out = run_doctor(capsys, login=login_raising(seen=seen))
    line = lines(out)["login_provider"][0]
    assert "http://pocket-id:1411/.well-known/openid-configuration" in line
    assert seen == ["http://pocket-id:1411/.well-known/openid-configuration"]
    # And with the right issuer through the internal address, it is ok.
    _code, out = run_doctor(capsys, login=discovery(TEST_ISSUER))
    assert lines(out)["login_provider"][0].startswith(
        "ok The issuer answers at http://pocket-id:1411/"
    )


def test_firebase_fetches_googles_signing_keys(database, env, capsys):
    env.setenv("AUTH_MODE", "firebase")
    env.setenv("FIREBASE_PROJECT_ID", "focus-funnel-test-project")
    env.delenv("OIDC_ISSUER")
    env.delenv("OIDC_CLIENT_ID")
    seen: list[str] = []

    def keys(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"keys": [{"kid": "k"}]})

    _code, out = run_doctor(capsys, login=httpx.MockTransport(keys))
    assert lines(out)["login_provider"][0].startswith("ok Google's signing keys load")
    assert seen == [doctor.FIREBASE_JWKS_URL]
    _code, out = run_doctor(capsys, login=login_raising())
    assert lines(out)["login_provider"][0].startswith("failed Could not fetch Google's")


def test_demo_skips_the_login_provider(database, env, capsys):
    env.setenv("AUTH_MODE", "demo")
    for name in ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET"):
        env.delenv(name)
    _code, out = run_doctor(capsys, login=login_raising())
    assert state_of(out, "login_provider") == "skipped"


def test_an_unreachable_embedding_preset_fails_and_another_warns(database, capsys):
    # nebius is the embedding provider (EMBEDDING_PROVIDER defaults to it).
    code, out = run_doctor(
        capsys,
        http=providers_answer(unreachable=("api.tokenfactory.nebius.com", "localhost")),
    )
    assert code == 1
    found = lines(out)
    assert found["provider:nebius"][0].startswith("failed ")
    assert "search cannot work" in found["provider:nebius"][0]
    assert found["provider:local"][0].startswith("warning ")


def test_an_unreachable_preset_that_is_not_the_embedding_provider_only_warns(
    database, capsys
):
    code, out = run_doctor(capsys, http=providers_answer(unreachable=("localhost",)))
    assert code == 0, out
    assert state_of(out, "provider:local") == "warning"
    assert state_of(out, "provider:nebius") == "ok"


def test_a_401_counts_as_reachable(database, capsys):
    seen: list[str] = []
    code, out = run_doctor(
        capsys, http=providers_answer(401, {"error": "no key"}, seen=seen)
    )
    assert code == 0, out
    assert lines(out)["provider:nebius"][0].startswith("ok ")
    assert "HTTP 401" in lines(out)["provider:nebius"][0]
    assert "https://api.tokenfactory.nebius.com/v1/models" in seen


def test_a_keyless_preset_reports_its_models_and_the_embedding_model(
    database, env, capsys
):
    body = {"data": [{"id": "qwen3:1.7b"}, {"id": "nomic-embed-text:v1.5"}]}
    env.setenv("EMBEDDING_MODEL", "nomic-embed-text:v1.5")
    _code, out = run_doctor(capsys, http=providers_answer(200, body))
    line = lines(out)["provider:local"][0]
    assert "lists 2 models" in line
    assert "EMBEDDING_MODEL nomic-embed-text:v1.5 is among them" in line

    env.setenv("EMBEDDING_MODEL", "missing-embedder")
    _code, out = run_doctor(capsys, http=providers_answer(200, {"data": None}))
    line = lines(out)["provider:local"][0]
    assert "lists 0 models" in line
    assert "EMBEDDING_MODEL missing-embedder is not among them" in line


def test_a_keyless_embedding_preset_without_the_model_warns(database, env, capsys):
    env.setenv("EMBEDDING_PROVIDER", "local")
    env.setenv("EMBEDDING_MODEL", "nomic-embed-text:v1.5")
    _code, out = run_doctor(
        capsys, http=providers_answer(200, {"data": [{"id": "qwen3:1.7b"}]})
    )
    line = lines(out)["provider:local"][0]
    assert line.startswith("warning ")
    assert "is not among them" in line


def connector(name: str, url: str):
    return SimpleNamespace(name=name, url=url)


def test_an_unreachable_operator_connector_warns(database, env, capsys):
    env.setenv("MCP_ENABLED", "true")
    config = SimpleNamespace(
        connectors=(
            connector("wiki", "http://wiki-mcp:8080/mcp"),
            connector("tracker", "http://tracker-mcp:8080/mcp"),
        )
    )
    code, out = run_doctor(
        capsys,
        http=providers_answer(unreachable=("wiki-mcp",)),
        load_settings=McpSettings,
        load_connectors=lambda: config,
    )
    assert code == 0, out
    found = lines(out)
    assert found["connector:wiki"][0].startswith(
        "warning Connector wiki did not answer"
    )
    assert found["connector:tracker"][0].startswith("ok Connector tracker answers")
    assert found["connectors_file"][0].startswith("ok ")
    assert (
        found["connectors"][0] == "info Connectors are on: 2 operator connectors. "
        "Users may not add their own."
    )


def test_a_connector_url_shows_only_scheme_host_and_port(database, env, capsys):
    env.setenv("MCP_ENABLED", "true")
    url = "https://conn-user:conn-pass@mcp.example.org:8443/mcp/v1?token=conn-secret"
    config = SimpleNamespace(connectors=(connector("docs", url),))
    for http in (
        providers_answer(),
        providers_answer(unreachable=("mcp.example.org",)),
    ):
        for args in ((), ("--json",)):
            _code, out = run_doctor(
                capsys,
                *args,
                http=http,
                load_settings=McpSettings,
                load_connectors=lambda: config,
            )
            assert "https://mcp.example.org:8443" in out
            for part in ("conn-user", "conn-pass", "conn-secret", "token=", "/mcp/v1"):
                assert part not in out, (part, out)


def test_a_provider_that_never_answers_is_cut_off_at_5_seconds(database, capsys):
    started = time.monotonic()
    item = asyncio.run(
        doctor.check_provider(
            doctor.load_providers_config().get("nebius"), Settings(), NeverAnswers()
        )
    )
    elapsed = time.monotonic() - started
    assert 4.5 < elapsed < 6, elapsed
    assert item.state == "failed"
    assert "did not answer within 5 seconds" in item.message


@pytest.mark.parametrize(
    "check",
    [
        lambda transport: doctor.check_login_provider(
            Settings(), NeverAnswersHttpx(), 0.3
        ),
        lambda transport: doctor.check_connector(
            connector("slow", "http://slow-mcp:8080/mcp"), transport, 0.3
        ),
    ],
)
def test_the_login_provider_and_connectors_are_cut_off_too(database, check):
    started = time.monotonic()
    item = asyncio.run(check(NeverAnswers()))
    assert time.monotonic() - started < 1
    assert "within 0.3 seconds" in item.message
    assert item.state in ("failed", "warning")
