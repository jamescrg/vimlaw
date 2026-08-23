"""Filters behind the agent trail and status strip."""

from apps.case.templatetags.ai_extras import (
    agent_tool_icon,
    duration_short,
    kchars,
    ktokens,
)


def test_ktokens():
    assert ktokens(0) == "0"
    assert ktokens(None) == "0"
    assert ktokens("") == "0"
    assert ktokens(999) == "999"
    assert ktokens(1000) == "1.0k"
    assert ktokens(48_231) == "48.2k"
    assert ktokens(1_200_000) == "1.2M"
    assert kchars(210_000) == "210.0k"


def test_duration_short():
    assert duration_short(0) == "0s"
    assert duration_short(None) == "0s"
    assert duration_short(9) == "9s"
    assert duration_short(59) == "59s"
    assert duration_short(60) == "1m 0s"
    assert duration_short(72) == "1m 12s"
    assert duration_short(3600) == "1h 0m"
    assert duration_short(3725) == "1h 2m"
    assert duration_short(9.6) == "9s"


def test_agent_tool_icon():
    assert agent_tool_icon("read_document") == "icon-file-text"
    assert agent_tool_icon("search_materials") == "icon-file-search"
    assert agent_tool_icon("nope") == "icon-wrench"
    assert agent_tool_icon(None) == "icon-wrench"
