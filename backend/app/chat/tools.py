"""What the two tools do. Each sits behind one function, so the changes that
add thought storage and search replace it without touching the tool loop."""

from dataclasses import dataclass
from typing import Any

from app.models import User

NOT_AVAILABLE_SEARCH = (
    "Searching filed thoughts is not available yet. Tell the user that searching "
    "their filed thoughts is not available yet."
)
PROPOSAL_SHOWN = (
    "The proposal is now shown to the user as a card they can edit and confirm. "
    "Nothing is saved until they confirm. Do not repeat it; reply in one short sentence."
)


class ToolArgumentError(ValueError):
    """The model called a tool with arguments that do not fit it."""


@dataclass(frozen=True)
class Proposal:
    title: str
    summary: str
    tags: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {"title": self.title, "summary": self.summary, "tags": self.tags}


def parse_proposal(arguments: dict[str, Any]) -> Proposal:
    title = arguments.get("title")
    summary = arguments.get("summary")
    tags = arguments.get("tags", [])
    if not isinstance(title, str) or not title.strip():
        raise ToolArgumentError("title must be a non-empty string")
    if not isinstance(summary, str) or not summary.strip():
        raise ToolArgumentError("summary must be a non-empty string")
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ToolArgumentError("tags must be a list of strings")
    return Proposal(
        title=title.strip(),
        summary=summary.strip(),
        tags=[tag.strip() for tag in tags if tag.strip()],
    )


async def search_thoughts(user: User, query: str) -> str:
    """The search tool's result for the model. Replaced by thought-storage."""
    return NOT_AVAILABLE_SEARCH


@dataclass(frozen=True)
class SaveOutcome:
    saved: bool
    message: str


async def save_thought(user: User, proposal: Proposal) -> SaveOutcome:
    """Hand a confirmed proposal to thought storage. Replaced by push-and-pull-gates."""
    return SaveOutcome(
        saved=False, message="Saving thoughts is not available yet. Copy the text to keep it."
    )
