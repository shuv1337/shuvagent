import asyncio
from pathlib import Path

from shuvagent.control import ControlServer, send_control_command
from shuvagent.coordination import Decision


def test_control_socket_start_status_stop_round_trip(tmp_path: Path) -> None:
    async def run() -> None:
        server = ControlServer(
            tmp_path / "control.sock",
            start_decision=lambda: Decision.allow("test"),
        )
        await server.start()
        try:
            start = await send_control_command(server.socket_path, "start")
            status = await send_control_command(server.socket_path, "status")
            stop = await send_control_command(server.socket_path, "stop")
        finally:
            await server.stop()

        assert start.startswith("OK started session=")
        assert "OK active session=" in status
        assert stop == "OK stopped"

    asyncio.run(run())


def test_control_socket_denies_start_when_coordination_denies(tmp_path: Path) -> None:
    async def run() -> None:
        server = ControlServer(
            tmp_path / "control.sock",
            start_decision=lambda: Decision.deny("shuvoice-recording"),
        )
        await server.start()
        try:
            response = await send_control_command(server.socket_path, "start")
        finally:
            await server.stop()

        assert response == "ERROR start denied: shuvoice-recording"

    asyncio.run(run())
