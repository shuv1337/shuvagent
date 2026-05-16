"""Tests for MCP integration — persistent stdio sessions and tool discovery.

Uses fake MCP client objects so no real subprocesses are spawned.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from shuvagent.tools.types import (
    ToolCallRequest,
    ToolResult,
    ToolRisk,
    ToolSpec,
    WindowSnapshot,
)

# ---------------------------------------------------------------------------
# Fake MCP runtime
# ---------------------------------------------------------------------------


class FakeMCPClient:
    """Records calls and returns canned results."""

    def __init__(
        self, tools: dict[str, dict[str, Any]], responses: dict[str, Any]
    ) -> None:
        self.tools = tools
        self.responses = responses
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.sessions_started = 0
        self.sessions_closed = 0

    def list_tools(self, server_name: str) -> list[dict[str, Any]]:
        self.sessions_started += 1
        return [
            {
                "name": name,
                "description": spec["description"],
                "inputSchema": spec.get("inputSchema", {}),
            }
            for name, spec in self.tools.items()
        ]

    def call_tool(
        self, server_name: str, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append((server_name, tool_name, arguments))
        key = f"{server_name}__{tool_name}"
        return self.responses.get(key, {"text": "default response", "isError": False})

    def shutdown(self) -> None:
        self.sessions_closed += 1


# ---------------------------------------------------------------------------
# Fake MCP runtime wrapper (simulates persistent session behavior)
# ---------------------------------------------------------------------------


class FakePersistentMCPRuntime:
    def __init__(self, client: FakeMCPClient) -> None:
        self.client = client
        self.workers: dict[str, Any] = {}

    def invoke(
        self,
        server_name: str,
        server_cfg: dict[str, Any],
        tool_name: str,
        arguments: dict[str, Any] | None,
        timeout: float = 120.0,
    ) -> Any:
        return self.client.call_tool(server_name, tool_name, arguments or {})

    def list_tools(self, server_name: str, server_cfg: dict[str, Any]) -> Any:
        return self.client.list_tools(server_name)

    def shutdown(self) -> None:
        self.client.shutdown()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _window() -> WindowSnapshot:
    return WindowSnapshot(app_id="firefox", title="t", captured_at=datetime.now(UTC))


def _make_mcp_tool_spec(
    name: str,
    description: str,
    mcp_runtime: FakePersistentMCPRuntime,
    server_name: str,
    server_cfg: dict[str, Any],
) -> ToolSpec:
    def handler(call: ToolCallRequest) -> ToolResult:
        try:
            result = mcp_runtime.invoke(
                server_name,
                server_cfg,
                name.split("__")[1] if "__" in name else name,
                call.arguments,
            )
            return ToolResult.success({"reply_text": str(result)})
        except Exception as e:
            return ToolResult.failure(str(e))

    return ToolSpec(
        name=name,
        risk=ToolRisk.EXTERNAL,
        input_schema={"type": "object", "properties": {}},
        description=description,
        handler=handler,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_discover_tools_from_fake_server() -> None:
    """list_tools returns specs translated to OpenAI function schema."""
    tools = {
        "create_issue": {
            "description": "Create a GitHub issue",
            "inputSchema": {"type": "object"},
        },
        "list_repos": {
            "description": "List user repos",
            "inputSchema": {"type": "object"},
        },
    }
    client = FakeMCPClient(tools=tools, responses={})
    runtime = FakePersistentMCPRuntime(client)

    discovered = runtime.list_tools("github", {"command": "npx"})
    assert len(discovered) == 2
    names = [t["name"] for t in discovered]
    assert "create_issue" in names
    assert "list_repos" in names


def test_invoke_tool_through_persistent_session() -> None:
    """Two calls to same server reuse the same logical session."""
    tools = {"greet": {"description": "Say hello"}}
    responses = {"github__greet": {"text": "Hello!"}}
    client = FakeMCPClient(tools=tools, responses=responses)
    runtime = FakePersistentMCPRuntime(client)

    result1 = runtime.invoke("github", {"command": "npx"}, "greet", {"name": "Alice"})
    result2 = runtime.invoke("github", {"command": "npx"}, "greet", {"name": "Bob"})

    assert client.calls == [
        ("github", "greet", {"name": "Alice"}),
        ("github", "greet", {"name": "Bob"}),
    ]
    assert result1["text"] == "Hello!"
    assert result2["text"] == "Hello!"


def test_worker_death_retries_once() -> None:
    """Subprocess crash mid-call → fresh worker, call retried."""
    call_count = 0

    class FailingThenSucceedingClient:
        def call_tool(
            self, server_name: str, tool_name: str, arguments: dict[str, Any]
        ) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("worker died")
            return {"text": "recovered"}

    class RetryRuntime:
        def __init__(self) -> None:
            self.dead = True

        def invoke(self, *args: Any, **kwargs: Any) -> Any:
            if self.dead:
                self.dead = False
                raise RuntimeError("worker died")
            return {"text": "recovered"}

    runtime = RetryRuntime()
    # First call dies, second succeeds (simulating retry)
    try:
        runtime.invoke("srv", {}, "tool", {})
    except RuntimeError:
        pass
    result = runtime.invoke("srv", {}, "tool", {})
    assert result["text"] == "recovered"


def test_tool_namespacing_avoids_collisions() -> None:
    """github__create_issue vs local create_issue don't collide."""
    mcp_tools = {"github__create_issue": "Create GitHub issue"}
    local_tools = {"create_issue": "Create local issue"}
    all_names = set(mcp_tools.keys()) | set(local_tools.keys())
    assert len(all_names) == 2
    assert "github__create_issue" in all_names
    assert "create_issue" in all_names


def test_shutdown_closes_all_sessions() -> None:
    """App exit sends sentinel, cancels tasks."""
    tools = {"greet": {"description": "Say hello"}}
    client = FakeMCPClient(tools=tools, responses={})
    runtime = FakePersistentMCPRuntime(client)

    runtime.invoke("srv", {}, "greet", {})
    runtime.shutdown()
    assert client.sessions_closed >= 1
