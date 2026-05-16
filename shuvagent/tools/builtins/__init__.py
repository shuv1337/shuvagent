"""Built-in tools shipped with shuvagent.

The default live set remains read-only until an interactive confirmation UI
exists. PLAN-02 write tools are exposed as specs for explicit opt-in wiring and
tests; every non-read call still routes through the permission gate.

Each builtin module exports a ``spec()`` factory that builds a
:class:`ToolSpec`. The factory takes any I/O collaborators (selection
helper, hyprctl runner, ShuVoice runner) so tests can inject fakes
without monkeypatching shell-outs.
"""

from __future__ import annotations

from shuvagent.tools.builtins.copy_to_clipboard import (
    spec as copy_to_clipboard_spec,
)
from shuvagent.tools.builtins.fetch_web_page import (
    spec as fetch_web_page_spec,
)
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
from shuvagent.tools.builtins.local_files import (
    spec as local_files_spec,
)
from shuvagent.tools.builtins.paste_text import (
    spec as paste_text_spec,
)
from shuvagent.tools.builtins.replace_selected_text import (
    spec as replace_selected_text_spec,
)
from shuvagent.tools.builtins.screenshot import (
    spec as screenshot_spec,
)
from shuvagent.tools.builtins.weather import (
    spec as weather_spec,
)
from shuvagent.tools.builtins.web_search import (
    spec as web_search_spec,
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


def default_context_tools() -> list[ToolSpec]:
    """Return desktop context tools (web, files, screen, weather).

    These are kept separate from the minimal read-only set so users can
    opt into heavier tools via config.
    """
    return [
        web_search_spec(),
        fetch_web_page_spec(),
        screenshot_spec(),
        local_files_spec(),
        weather_spec(),
    ]


def default_write_tools() -> list[ToolSpec]:
    """Return PLAN-02 local write tools for explicit opt-in wiring."""
    return [
        paste_text_spec(),
        replace_selected_text_spec(),
        copy_to_clipboard_spec(),
    ]


__all__ = [
    "copy_to_clipboard_spec",
    "default_context_tools",
    "default_read_only_tools",
    "default_write_tools",
    "fetch_web_page_spec",
    "get_active_window_spec",
    "get_clipboard_text_spec",
    "get_selected_text_spec",
    "get_shuvoice_status_spec",
    "local_files_spec",
    "paste_text_spec",
    "replace_selected_text_spec",
    "screenshot_spec",
    "weather_spec",
    "web_search_spec",
]
