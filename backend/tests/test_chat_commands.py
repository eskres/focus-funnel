import pytest

from app.chat.commands import parse_message
from app.errors import ApiError, ErrorCode


@pytest.mark.parametrize(
    "message, command, content",
    [
        ("/push buy milk", "push", "buy milk"),
        ("/Pull x", "pull", "x"),
        ("   /explore x", "explore", "x"),
        ("/PUSH\nmulti\nline", "push", "multi\nline"),
        ("/push   spaced  ", "push", "spaced"),
        ("/compact", "compact", ""),
        ("  /DELETE  ", "delete", ""),
    ],
)
def test_commands_parse_case_insensitively_with_leading_whitespace(message, command, content):
    parsed = parse_message(message)
    assert parsed.command == command
    assert parsed.content == content


@pytest.mark.parametrize(
    "message",
    [
        "/pushing x",
        "remind me to /push later",
        "/archive x",
        "/router x",
        "just a thought",
    ],
)
def test_other_text_is_an_ordinary_message(message):
    parsed = parse_message(message)
    assert parsed.command is None
    assert parsed.content == message.strip()


@pytest.mark.parametrize(
    "message",
    ["/push", "/push   ", "  /PULL\n", "/explore", "", " \n ", "/compact x", "/delete now"],
)
def test_missing_or_extra_text_is_a_validation_error(message):
    with pytest.raises(ApiError) as exc_info:
        parse_message(message)
    assert exc_info.value.status_code == 422
    assert exc_info.value.code == ErrorCode.VALIDATION_ERROR
