"""Tests for ``tool_router`` — query-relevant tool filtering."""

from __future__ import annotations

from typing import Any

from shuvagent.tool_router import ToolSelectionStrategy, select_tools

# ---------------------------------------------------------------------------
# Fixture tools
# ---------------------------------------------------------------------------


def _make_tools() -> dict[str, Any]:
    """Return a fake tool registry for testing."""
    return {
        "getWeather": {"description": "Get current weather and forecast."},
        "webSearch": {"description": "Search the web for current information."},
        "screenshot": {"description": "Capture screen and OCR text."},
        "localFiles": {"description": "Read and list local files."},
        "stop": {"description": "Stop the assistant from speaking."},
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_all_strategy_returns_everything() -> None:
    """Default 'all' strategy returns every tool."""
    tools = _make_tools()
    selected = select_tools(
        "what's the weather", tools, strategy=ToolSelectionStrategy.ALL
    )
    assert set(selected) == set(tools.keys())


def test_keyword_strategy_filters_by_overlap() -> None:
    """Query 'weather' returns getWeather, not screenshot."""
    tools = _make_tools()
    selected = select_tools(
        "what's the weather", tools, strategy=ToolSelectionStrategy.KEYWORD
    )
    assert "getWeather" in selected
    assert "stop" in selected  # always included


def test_llm_strategy_returns_capped_list() -> None:
    """LLM strategy returns ≤5 tools even if model wants more."""
    tools = _make_tools()

    def fake_llm_router(query, tools_list, **kwargs):
        # Simulates a chatty router that returns everything
        return list(tools_list.keys())

    selected = select_tools(
        "search the web and check weather",
        tools,
        strategy=ToolSelectionStrategy.LLM,
        llm_router=fake_llm_router,
    )
    assert len(selected) <= 5
    assert "stop" in selected  # always included


def test_always_included_tools_preserved() -> None:
    """Tools in ALWAYS_INCLUDED are present regardless of strategy."""
    tools = _make_tools()
    selected = select_tools(
        "irrelevant query", tools, strategy=ToolSelectionStrategy.KEYWORD
    )
    assert "stop" in selected


def test_llm_failure_falls_back_to_keyword() -> None:
    """LLM timeout/error → keyword strategy."""
    tools = _make_tools()

    def broken_llm(*args, **kwargs):
        raise RuntimeError("LLM unreachable")

    selected = select_tools(
        "what's the weather",
        tools,
        strategy=ToolSelectionStrategy.LLM,
        llm_router=broken_llm,
    )
    # Should not be empty and should include weather-relevant tools
    assert "getWeather" in selected


def test_unknown_strategy_falls_back_to_all() -> None:
    """Bad config value → all tools (safe default)."""
    tools = _make_tools()
    selected = select_tools("anything", tools, strategy="bad_strategy")  # type: ignore[arg-type]
    assert set(selected) == set(tools.keys())


def test_keyword_no_matches_returns_all() -> None:
    """When keyword strategy finds nothing, return all tools rather than empty."""
    tools = _make_tools()
    selected = select_tools(
        "zzzzzzzzzzz", tools, strategy=ToolSelectionStrategy.KEYWORD
    )
    assert len(selected) == len(tools)
