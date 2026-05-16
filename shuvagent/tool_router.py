"""Tool router — filter relevant tools per query.

Strategies:
  - all:       return every tool (no filtering)
  - keyword:   score tools by keyword overlap with the query
  - llm:       ask the chat model to choose relevant tools
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any


class ToolSelectionStrategy(Enum):
    ALL = "all"
    KEYWORD = "keyword"
    LLM = "llm"


# Tools that must always be available regardless of selection strategy.
_ALWAYS_INCLUDED: set[str] = {"stop"}

# Hard caps
_MIN_SELECTED = 3
_MAX_SELECTED = 8
_LLM_MAX_SELECTED = 5


def select_tools(
    query: str,
    all_tools: dict[str, Any],
    strategy: ToolSelectionStrategy = ToolSelectionStrategy.ALL,
    **kwargs: Any,
) -> list[str]:
    """Return a list of tool names relevant to *query*."""
    if not isinstance(strategy, ToolSelectionStrategy):
        return list(all_tools)
    if strategy is ToolSelectionStrategy.ALL:
        return list(all_tools)
    if strategy is ToolSelectionStrategy.LLM:
        llm_router = kwargs.get("llm_router")
        if callable(llm_router):
            try:
                selected = [
                    name
                    for name in llm_router(query, all_tools, **kwargs)
                    if name in all_tools
                ]
                return _with_always_included(selected, all_tools)[:_LLM_MAX_SELECTED]
            except Exception:
                pass
        return _select_keyword(query, all_tools)
    return _select_keyword(query, all_tools)


def _select_keyword(query: str, all_tools: dict[str, Any]) -> list[str]:
    query_tokens = _tokens(query)
    scored: list[tuple[int, str]] = []
    for name, spec in all_tools.items():
        if name in _ALWAYS_INCLUDED:
            continue
        haystack = f"{name} {_description(spec)}"
        score = len(query_tokens & _tokens(haystack))
        if score > 0:
            scored.append((score, name))
    if not scored:
        return list(all_tools)
    selected = [
        name for _, name in sorted(scored, key=lambda item: (-item[0], item[1]))
    ]
    return _with_always_included(selected, all_tools)


def _with_always_included(selected: list[str], all_tools: dict[str, Any]) -> list[str]:
    merged = [name for name in selected if name in all_tools]
    for name in _ALWAYS_INCLUDED:
        if name in all_tools and name not in merged:
            merged.append(name)
    return merged[:_MAX_SELECTED]


def _description(spec: Any) -> str:
    if isinstance(spec, dict):
        return str(spec.get("description", ""))
    return str(getattr(spec, "description", ""))


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", text.lower())
        if token not in {"the", "and", "for", "with", "what", "this"}
    }
