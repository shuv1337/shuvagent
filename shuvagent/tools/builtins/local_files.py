"""``local_files`` — safe file operations within the home directory."""

from __future__ import annotations

from pathlib import Path

from shuvagent.tools.types import GatedToolCall, ToolResult, ToolRisk, ToolSpec

NAME = "local_files"
DESCRIPTION = (
    "Safely read or list files within your home directory. "
    "Write operations require confirmation."
)
INPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "operation": {
            "type": "string",
            "description": "Operation to perform: list, read",
        },
        "path": {
            "type": "string",
            "description": "File or directory path (relative to home directory)",
        },
        "glob": {
            "type": "string",
            "description": "Glob pattern for listing (default: *)",
        },
        "recursive": {
            "type": "boolean",
            "description": "Whether to search recursively (for list operation)",
        },
    },
    "required": ["operation", "path"],
    "additionalProperties": False,
}


def spec(
    *,
    home_dir: str | None = None,
    max_read_chars: int = 10_000,
    max_list_files: int = 50,
) -> ToolSpec:
    home = Path(home_dir).expanduser().resolve() if home_dir else Path.home().resolve()

    def handler(call: GatedToolCall) -> ToolResult:
        operation = call.arguments.get("operation")
        raw_path = call.arguments.get("path")
        if operation not in {"list", "read"}:
            return ToolResult.failure("unsupported_operation")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return ToolResult.failure("missing_path")
        try:
            path = _resolve_allowed_path(raw_path, home)
        except PermissionError as exc:
            return ToolResult.failure(str(exc))

        if operation == "list":
            return _list_files(
                path,
                glob=str(call.arguments.get("glob") or "*"),
                recursive=bool(call.arguments.get("recursive", False)),
                max_list_files=max_list_files,
            )
        return _read_file(path, max_read_chars=max_read_chars)

    return ToolSpec(
        name=NAME,
        risk=ToolRisk.READ,
        input_schema=INPUT_SCHEMA,
        description=DESCRIPTION,
        handler=handler,
    )


def _resolve_allowed_path(raw_path: str, home: Path) -> Path:
    expanded = (
        raw_path.replace("~", str(home), 1) if raw_path.startswith("~") else raw_path
    )
    path = Path(expanded)
    if not path.is_absolute():
        path = home / path
    resolved = path.resolve()
    try:
        resolved.relative_to(home)
    except ValueError as exc:
        raise PermissionError("path_not_allowed_outside_home") from exc
    return resolved


def _list_files(
    path: Path,
    *,
    glob: str,
    recursive: bool,
    max_list_files: int,
) -> ToolResult:
    if not path.exists():
        return ToolResult.failure("path_not_found")
    if not path.is_dir():
        return ToolResult.failure("path_not_directory")
    iterator = path.rglob(glob) if recursive else path.glob(glob)
    entries = sorted(iterator, key=lambda item: (not item.is_dir(), item.name.lower()))
    lines = []
    for entry in entries[:max_list_files]:
        kind = "DIR" if entry.is_dir() else "FILE"
        try:
            display = entry.relative_to(path)
        except ValueError:
            display = entry
        lines.append(f"{kind} {display}")
    if len(entries) > max_list_files:
        lines.append(f"[truncated to {max_list_files} entries]")
    return ToolResult.success({"reply_text": "\n".join(lines), "entries": lines})


def _read_file(path: Path, *, max_read_chars: int) -> ToolResult:
    if not path.exists():
        return ToolResult.failure("path_not_found")
    if not path.is_file():
        return ToolResult.failure("path_not_file")
    data = path.read_bytes()
    if b"\x00" in data:
        return ToolResult.failure("binary file, cannot read")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ToolResult.failure("binary file, cannot read")
    truncated = len(text) > max_read_chars
    text = text[:max_read_chars]
    if truncated:
        text += "\n[truncated]"
    return ToolResult.success({"reply_text": text, "truncated": truncated})
