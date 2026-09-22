"""Classifies whether a provider's reported model features confirm tool calling.

A provider's feature list is advisory: a model may support tool calling
without the provider listing it, so this only ever narrows what's reported,
never what a user is allowed to pick.
"""

from collections.abc import Sequence

TOOL_CALLING_ALIASES = frozenset({"tools"})


def classify_tool_calling(supported_features: Sequence[str] | None) -> str:
    """'supported', 'unconfirmed', or 'unknown', from a provider's reported features."""
    if not supported_features:
        return "unknown"
    normalized = {item.strip().lower() for item in supported_features if isinstance(item, str)}
    if normalized & TOOL_CALLING_ALIASES:
        return "supported"
    return "unconfirmed"


def classify_features(supported_features: Sequence[str] | None) -> dict[str, str]:
    """Every known feature for a model, classified from its reported features."""
    return {"tool_calling": classify_tool_calling(supported_features)}
