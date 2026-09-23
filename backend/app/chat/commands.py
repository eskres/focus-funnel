"""Slash commands at the start of a chat message."""

import re
from dataclasses import dataclass

from app.errors import ApiError, ErrorCode

# Commands that need text after them, and commands that take none.
COMMANDS_WITH_TEXT = ("push", "pull", "explore")
COMMANDS_WITHOUT_TEXT = ("compact", "delete")
COMMANDS = COMMANDS_WITH_TEXT + COMMANDS_WITHOUT_TEXT


@dataclass(frozen=True)
class ParsedMessage:
    command: str | None
    content: str


def parse_message(message: str) -> ParsedMessage:
    """Split a leading slash command from the message.

    A command is matched after optional whitespace, in any letter case, and
    only when followed by whitespace or the end of the message.
    """
    if not message.strip():
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, "Message must not be empty.")
    names = "|".join(re.escape(name) for name in COMMANDS)
    match = re.match(rf"\s*/({names})(?:\s+(.*))?$", message, re.IGNORECASE | re.DOTALL)
    if match is None:
        return ParsedMessage(command=None, content=message.strip())
    command = match.group(1).lower()
    content = (match.group(2) or "").strip()
    if command in COMMANDS_WITH_TEXT and not content:
        raise ApiError(
            422,
            ErrorCode.VALIDATION_ERROR,
            f"/{command} needs a message after it, like '/{command} your text'.",
        )
    if command in COMMANDS_WITHOUT_TEXT and content:
        raise ApiError(
            422, ErrorCode.VALIDATION_ERROR, f"/{command} takes no message after it."
        )
    return ParsedMessage(command=command, content=content)
