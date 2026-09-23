from app.provider_features import TOOL_CALLING_ALIASES, classify_features, classify_tool_calling


def test_tool_calling_alias_is_tools():
    assert "tools" in TOOL_CALLING_ALIASES


def test_reports_tools_gives_supported():
    assert classify_tool_calling(["tools"]) == "supported"
    assert classify_tool_calling(["other", "tools"]) == "supported"


def test_case_and_whitespace_insensitive():
    assert classify_tool_calling(["  TOOLS  "]) == "supported"


def test_reports_features_without_tools_gives_unconfirmed():
    assert classify_tool_calling(["reasoning"]) == "unconfirmed"
    assert classify_tool_calling(["structured_outputs"]) == "unconfirmed"


def test_reports_nothing_gives_unknown():
    assert classify_tool_calling(None) == "unknown"
    assert classify_tool_calling([]) == "unknown"


def test_classify_features_dictionary():
    assert classify_features(["tools"]) == {"tool_calling": "supported"}
    assert classify_features(["reasoning"]) == {"tool_calling": "unconfirmed"}
    assert classify_features([]) == {"tool_calling": "unknown"}
    assert classify_features(None) == {"tool_calling": "unknown"}
