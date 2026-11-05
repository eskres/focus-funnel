"""scripts/init-env.sh: the bootstrap secrets in .env (design decision 10).

Standard library and pytest only, with no `app` import and no conftest
fixture, so the file also runs under BusyBox in Alpine with `--noconftest`:

    docker run --rm -v "$PWD":/src -w /src/backend alpine:3.20 sh -c \\
      'apk add --no-cache openssl python3 py3-pytest && INIT_ENV_RUNNER="busybox sh" \\
       python3 -m pytest --noconftest -p no:cacheprovider tests/test_init_env_script.py'

INIT_ENV_RUNNER names the shell that runs the script (default `sh`).
"""

import base64
import os
import re
import shlex
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "init-env.sh"
EXAMPLE = REPO / ".env.example"
RUNNER = shlex.split(os.environ.get("INIT_ENV_RUNNER", "sh"))

SECRETS = ("KEY_ENCRYPTION_KEY", "SESSION_SECRET", "POCKET_ID_ENCRYPTION_KEY")
EXAMPLE_DATABASE_URL = (
    "postgresql+asyncpg://focus_funnel:focus_funnel@postgres:5432/focus_funnel"
)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A checkout with the script and .env.example, and no .env."""
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "scripts" / "init-env.sh")
    shutil.copy(EXAMPLE, root / ".env.example")
    return root


def run(
    root: Path, *args: str, path: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if path is not None:
        env["PATH"] = path
    return subprocess.run(
        [*RUNNER, str(root / "scripts" / "init-env.sh"), *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        # Its own process group, so a fake openssl can signal the script
        # with `kill -TERM 0` without reaching pytest.
        start_new_session=True,
        check=False,
    )


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            name, _, value = line.partition("=")
            values[name] = value
    return values


def write_env(path: Path, changes: dict[str, str]) -> None:
    """Write .env.example with the given values replaced."""
    lines = []
    for line in EXAMPLE.read_text().splitlines():
        name = line.partition("=")[0]
        if not line.startswith("#") and name in changes:
            line = f"{name}={changes[name]}"
        lines.append(line)
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o644)


def output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def assert_no_secret_in_output(
    result: subprocess.CompletedProcess[str], env: dict[str, str]
) -> None:
    text = output(result)
    for name in (*SECRETS, "POSTGRES_PASSWORD"):
        value = env.get(name, "")
        if value and value != "focus_funnel":
            assert value not in text, name


def leftovers(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir() if p.name.startswith(".env.tmp"))


def test_first_run_creates_env_with_new_secrets(checkout: Path) -> None:
    result = run(checkout)
    assert result.returncode == 0, output(result)

    env_path = checkout / ".env"
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
    env = read_env(env_path)

    key = env["KEY_ENCRYPTION_KEY"]
    assert len(base64.b64decode(key, validate=True)) == 32
    assert re.fullmatch(r"[0-9a-f]{64}", env["SESSION_SECRET"])
    assert len(base64.b64decode(env["POCKET_ID_ENCRYPTION_KEY"], validate=True)) == 32
    assert env["POCKET_ID_ENCRYPTION_KEY"] != key

    password = env["POSTGRES_PASSWORD"]
    assert password and password != "focus_funnel"
    assert re.fullmatch(r"[0-9a-f]{32}", password)
    assert env["DATABASE_URL"] == (
        f"postgresql+asyncpg://focus_funnel:{password}@postgres:5432/focus_funnel"
    )

    # Every other line is the example's.
    example = read_env(EXAMPLE)
    changed = {name for name in example if env.get(name) != example[name]}
    assert changed == {*SECRETS, "POSTGRES_PASSWORD", "DATABASE_URL"}

    text = output(result)
    for name in (*SECRETS, "POSTGRES_PASSWORD", "DATABASE_URL"):
        assert name in text
    assert "Keep a copy of KEY_ENCRYPTION_KEY" in text
    assert "connector tokens" not in text
    assert_no_secret_in_output(result, env)
    assert leftovers(checkout) == []


def test_existing_postgres_data_keeps_the_example_password(checkout: Path) -> None:
    data = checkout / ".data" / "postgres"
    (data / "18" / "docker").mkdir(parents=True)
    (data / "18" / "docker" / "PG_VERSION").write_text("18\n")

    result = run(checkout, "--auth-mode", "oidc")
    assert result.returncode == 0, output(result)

    env = read_env(checkout / ".env")
    assert env["POSTGRES_PASSWORD"] == "focus_funnel"
    assert env["DATABASE_URL"] == EXAMPLE_DATABASE_URL
    assert len(base64.b64decode(env["KEY_ENCRYPTION_KEY"], validate=True)) == 32
    text = output(result)
    assert "Warning: .data/postgres already holds a database" in text
    assert "ALTER USER" in text
    assert_no_secret_in_output(result, env)


def test_empty_postgres_data_directory_gets_a_new_password(checkout: Path) -> None:
    (checkout / ".data" / "postgres").mkdir(parents=True)

    result = run(checkout)
    assert result.returncode == 0, output(result)

    env = read_env(checkout / ".env")
    assert env["POSTGRES_PASSWORD"] != "focus_funnel"
    assert "already holds a database" not in output(result)


def test_auth_mode_oidc_names_the_settings_it_still_needs(checkout: Path) -> None:
    result = run(checkout, "--auth-mode", "oidc")
    assert result.returncode == 0, output(result)

    env = read_env(checkout / ".env")
    assert env["AUTH_MODE"] == "oidc"
    text = output(result)
    assert "AUTH_MODE" in text
    for name in ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET"):
        assert name in text
    assert "FIREBASE_PROJECT_ID" not in text
    assert "pocket-id" in text
    assert "/setup" in text
    assert_no_secret_in_output(result, env)


def test_auth_mode_firebase_names_its_settings(checkout: Path) -> None:
    result = run(checkout, "--auth-mode=firebase")
    assert result.returncode == 0, output(result)

    assert read_env(checkout / ".env")["AUTH_MODE"] == "firebase"
    text = output(result)
    for name in ("FIREBASE_PROJECT_ID", "FIREBASE_API_KEY", "FIREBASE_AUTH_DOMAIN"):
        assert name in text
    assert "OIDC_ISSUER" not in text


def test_a_set_auth_mode_is_left_as_it_is(checkout: Path) -> None:
    write_env(checkout / ".env", {"AUTH_MODE": "oidc"})

    result = run(checkout, "--auth-mode", "firebase")
    assert result.returncode == 0, output(result)

    assert read_env(checkout / ".env")["AUTH_MODE"] == "oidc"
    assert "AUTH_MODE is already oidc" in output(result)


def test_a_second_run_changes_no_value(checkout: Path) -> None:
    assert run(checkout, "--auth-mode", "oidc").returncode == 0
    before = (checkout / ".env").read_bytes()

    result = run(checkout, "--auth-mode", "oidc")
    assert result.returncode == 0, output(result)

    assert (checkout / ".env").read_bytes() == before
    assert "Nothing to set" in output(result)
    assert stat.S_IMODE((checkout / ".env").stat().st_mode) == 0o600
    assert leftovers(checkout) == []


def test_only_an_empty_session_secret_is_filled(checkout: Path) -> None:
    key = base64.b64encode(os.urandom(32)).decode()
    pocket = base64.b64encode(os.urandom(32)).decode()
    url = "postgresql+asyncpg://focus_funnel:s3cret-pw@postgres:5432/focus_funnel"
    write_env(
        checkout / ".env",
        {
            "AUTH_MODE": "oidc",
            "KEY_ENCRYPTION_KEY": key,
            "POCKET_ID_ENCRYPTION_KEY": pocket,
            "SESSION_SECRET": "",
            "POSTGRES_PASSWORD": "s3cret-pw",
            "DATABASE_URL": url,
        },
    )
    before = read_env(checkout / ".env")

    result = run(checkout)
    assert result.returncode == 0, output(result)

    after = read_env(checkout / ".env")
    assert re.fullmatch(r"[0-9a-f]{64}", after["SESSION_SECRET"])
    assert {n for n in before if before[n] != after.get(n)} == {"SESSION_SECRET"}
    assert set(after) == set(before)
    assert after["KEY_ENCRYPTION_KEY"] == key
    assert after["POSTGRES_PASSWORD"] == "s3cret-pw"
    assert after["DATABASE_URL"] == url
    assert stat.S_IMODE((checkout / ".env").stat().st_mode) == 0o600
    text = output(result)
    assert "SESSION_SECRET" in text
    assert "POSTGRES_PASSWORD" not in text.split("Keep a copy")[0]
    assert_no_secret_in_output(result, after)


def test_an_empty_postgres_password_in_env_stays_empty(checkout: Path) -> None:
    write_env(checkout / ".env", {"POSTGRES_PASSWORD": ""})

    result = run(checkout)
    assert result.returncode == 0, output(result)

    env = read_env(checkout / ".env")
    assert env["POSTGRES_PASSWORD"] == ""
    assert env["DATABASE_URL"] == EXAMPLE_DATABASE_URL
    for name in SECRETS:
        assert env[name]


def test_connector_token_note_only_with_mcp_enabled(checkout: Path) -> None:
    write_env(checkout / ".env", {})
    plain = run(checkout)
    assert plain.returncode == 0, output(plain)
    assert "connector tokens" not in output(plain)

    with (checkout / ".env").open("a") as env:
        env.write("MCP_ENABLED=true\n")
    enabled = run(checkout)
    assert enabled.returncode == 0, output(enabled)
    text = output(enabled)
    assert "connector tokens go in .env" in text
    assert "connectors.yaml" in text
    assert "does not generate them" in text


@pytest.mark.parametrize(
    "args", [["--auth-mode", "ldap"], ["--auth-mode"], ["--bogus"]]
)
def test_invalid_arguments_exit_non_zero_and_write_nothing(
    checkout: Path, args: list[str]
) -> None:
    result = run(checkout, *args)
    assert result.returncode != 0
    assert not (checkout / ".env").exists()
    assert leftovers(checkout) == []


def test_a_stopped_run_leaves_no_temporary_file(checkout: Path, tmp_path: Path) -> None:
    """A fake openssl records the directory, then sends the script TERM."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    seen = tmp_path / "seen"
    fake = bin_dir / "openssl"
    fake.write_text(
        f'#!/bin/sh\nls -A "{checkout}" > "{seen}"\nkill -TERM 0\nsleep 5\n'
    )
    fake.chmod(0o755)

    result = run(
        checkout,
        "--auth-mode",
        "oidc",
        path=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    )

    assert result.returncode != 0
    # The temporary file existed when the script was stopped...
    assert any(name.startswith(".env.tmp.") for name in seen.read_text().split())
    # ...and is gone, with no .env written.
    assert leftovers(checkout) == []
    assert not (checkout / ".env").exists()


def test_a_stopped_run_on_an_existing_env_leaves_it_unchanged(
    checkout: Path, tmp_path: Path
) -> None:
    write_env(checkout / ".env", {"AUTH_MODE": "oidc"})
    before = (checkout / ".env").read_bytes()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "openssl"
    fake.write_text("#!/bin/sh\nkill -TERM 0\nsleep 5\n")
    fake.chmod(0o755)

    result = run(checkout, path=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    assert result.returncode != 0
    assert leftovers(checkout) == []
    assert (checkout / ".env").read_bytes() == before
