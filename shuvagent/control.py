from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from shuvagent.coordination import Decision, can_start_agent_session

StartDecision = Callable[[], Decision | Awaitable[Decision]]
SessionHook = Callable[[str], Awaitable[None]]


@dataclass
class ControlState:
    status: str = "idle"
    session_id: str | None = None


class ControlServer:
    def __init__(
        self,
        socket_path: Path,
        *,
        start_decision: StartDecision | None = None,
        on_start: SessionHook | None = None,
        on_stop: SessionHook | None = None,
    ) -> None:
        self.socket_path = socket_path
        self.state = ControlState()
        self._start_decision = start_decision or can_start_agent_session
        self._on_start = on_start
        self._on_stop = on_stop
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()
        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=self.socket_path,
        )

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        if self.socket_path.exists():
            self.socket_path.unlink()

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def handle_command(self, command: str) -> str:
        verb = command.strip().split()[0] if command.strip() else ""
        if verb == "status":
            if self.state.session_id:
                return f"OK {self.state.status} session={self.state.session_id}"
            return f"OK {self.state.status}"
        if verb == "start":
            return await self._start_session()
        if verb == "stop":
            if self.state.status == "idle":
                return "OK idle"
            stopped_id = self.state.session_id or ""
            self.state = ControlState()
            if self._on_stop is not None:
                await self._on_stop(stopped_id)
            return "OK stopped"
        return f"ERROR unknown command: {verb or '<empty>'}"

    async def _start_session(self) -> str:
        if self.state.status != "idle":
            return f"OK {self.state.status} session={self.state.session_id}"
        decision = self._start_decision()
        if asyncio.iscoroutine(decision):
            decision = await decision
        if not decision.allowed:
            return f"ERROR start denied: {decision.reason}"
        session_id = uuid4().hex
        self.state = ControlState(status="active", session_id=session_id)
        if self._on_start is not None:
            await self._on_start(session_id)
        return f"OK started session={session_id}"

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        data = await reader.readline()
        response = await self.handle_command(data.decode().strip())
        writer.write(f"{response}\n".encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()


async def send_control_command(socket_path: Path, command: str) -> str:
    reader, writer = await asyncio.open_unix_connection(path=socket_path)
    writer.write(f"{command.strip()}\n".encode())
    await writer.drain()
    response = await reader.readline()
    writer.close()
    await writer.wait_closed()
    return response.decode().strip()
