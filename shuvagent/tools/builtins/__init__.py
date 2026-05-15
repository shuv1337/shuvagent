"""Built-in read-only tools shipped in PLAN-01 (M1.7).

Write tools land in PLAN-02. Everything here is :class:`ToolRisk.READ`
— no confirmation needed, but every call is still audited via the
registry.

Each builtin module exports a ``spec()`` factory that builds a
:class:`ToolSpec`. The factory takes any I/O collaborators (selection
helper, hyprctl runner, ShuVoice runner) so tests can inject fakes
without monkeypatching shell-outs.
"""

from __future__ import annotations

from shuvagent.tools.builtins.get_active_window import (
    spec as get_active_window_spec,
)
from shuvagent.tools.builtins.get_clipboard_text import (
    spec as get_clipboard_text_spec,
)
from shuvagent.tools.builtins.get_selected_text import (
    spec as get_selected_text_spec,
)
from shuvagent.tools.builtins.get_shuvoice_status import (
    spec as get_shuvoice_status_spec,
)
from shuvagent.tools.types import ToolSpec


def default_read_only_tools() -> list[ToolSpec]:
    """Return the default read-only tool set with default I/O wiring."""
    return [
        get_selected_text_spec(),
        get_clipboard_text_spec(),
        get_active_window_spec(),
        get_shuvoice_status_spec(),
    ]


__all__ = [
    "default_read_only_tools",
    "get_active_window_spec",
    "get_clipboard_text_spec",
    "get_selected_text_spec",
    "get_shuvoice_status_spec",
]
